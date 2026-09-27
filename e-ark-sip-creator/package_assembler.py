"""E-ARK SIP package assembly.

Creates the folder structure, copies files with normalized names,
writes METS.xml, and optionally zips the result.
"""

import contextlib
import hashlib
import itertools
import logging
import os
import shutil
import stat
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable

from lxml import etree

from mets_builder import set_package_name

logger = logging.getLogger(__name__)

FOLDER_STRUCTURE: dict[str, str] = {
    "documentation": "documentation",
    "descriptivemetadata": "metadata/descriptive",
    "othermetadata": "metadata/other",
    "preservationmetadata": "metadata/preservation",
    "representation": "representations/rep_1/data",
    "representationmetadata": "representations/rep_1/metadata",
    "schema": "schemas",
}


def create_package(
    output_dir: Path,
    mets_tree: etree._ElementTree,
    file_categories: dict[str, dict],
    zip_output: bool = False,
    progress_callback: Callable[[int, int], None] | None = None,
) -> Path:
    """Create an E-ARK SIP package on disk.

    Args:
        output_dir: Directory where the package folder is created.
        mets_tree: lxml ElementTree of the METS document, from build_mets.
            Updated in place: its OBJID and root structMap div LABEL
            become the package name once that name is claimed.
        file_categories: Dict mapping category names to file
            metadata dicts (same structure as passed to build_mets).
        zip_output: If True, zip the package folder and remove
            the unzipped version.
        progress_callback: Optional callback(current, total) for
            progress reporting.

    Returns:
        Path to the created package folder (or zip file).

    Raises:
        FileNotFoundError: A source file is missing, or is no longer a
            file, since it was collected. The METS already lists it, so
            the package would be incomplete while looking finished.
        FileExistsError: Two selected items map to the same package path.
        ValueError: A destination would fall outside the package, or a
            source file changed since it was hashed (size, or content
            found while copying), or mets_tree has no structMap root div
            to carry the package name (it was not built by build_mets).
        OSError: The output folder cannot be created, for example because
            a parent path is blocked by a file, or in zip mode the zip name
            cannot be claimed (permissions, disk full). The operating
            system's own message is kept.

    The package is named IP_<timestamp>, with _1, _2, ... appended when
    that name is taken, so two runs in the same second give two packages,
    also when they run in parallel. That name, suffix included, is written
    into the METS as OBJID and as the root div LABEL. On any failure after
    the package folder is created, including Ctrl+C, this run's own folder
    and partial zip are removed before the error is re-raised.
    """
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    package_path, zip_path = _claim_package_paths(
        output_dir, f"IP_{timestamp}", zip_output
    )

    try:
        # The claimed name, suffix included, is the package identifier
        # CSIP wants in the METS. The zip is named after the folder, so
        # the folder name is right in both modes.
        set_package_name(mets_tree, package_path.name)
        _fill_package(
            package_path, mets_tree, file_categories, progress_callback
        )
        if zip_output:
            _zip_package(package_path, zip_path)
    except BaseException:
        # Leave nothing half-written behind, also on Ctrl+C. Both paths were
        # claimed by this run (the folder by mkdir, the zip by an exclusive
        # placeholder), so removing them cannot touch another run's output.
        _remove_tree(package_path, ignore_errors=True)
        if zip_output:
            # Must not mask the original error, e.g. if a scanner locks it
            with contextlib.suppress(OSError):
                zip_path.unlink(missing_ok=True)
        raise

    if zip_output:
        logger.info("Package zipped: %s", zip_path)
        return zip_path
    logger.info("Package created: %s", package_path)
    return package_path


def _claim_package_paths(
    output_dir: Path, base_name: str, zip_output: bool
) -> tuple[Path, Path]:
    """Create the package folder under a name that is not taken.

    Two runs in the same second, from the GUI, from a script looping over
    jobs, or from two processes at once, get the same timestamp. The
    second one gets "_1" appended, the third "_2", and so on. Creating is
    the claim itself: two runs cannot both create the same folder, so the
    loser moves on to the next name instead of failing. In zip mode the
    zip name is claimed the same way, with an empty placeholder created
    exclusively, which _zip_package later overwrites. Without that claim
    a parallel run could finish its zip between this run's check and its
    own zip step, and this run's cleanup would then remove that zip.
    A name is taken by a folder or a zip alike, in either mode: the name
    is the package identifier in the METS, so a folder package and a zip
    package must never share it. In folder mode the zip is checked after
    the folder is held, which is race-free because a zip-mode run always
    claims the folder before the zip. Nothing is ever merged into or
    overwritten.

    Returns:
        The created package folder and the zip path next to it.

    Raises:
        OSError: The output folder cannot be created, for example because
            a parent path is blocked by a file, or the zip name cannot be
            claimed (permissions, disk full).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    for counter in itertools.count():
        name = base_name if counter == 0 else f"{base_name}_{counter}"
        package_path = output_dir / name
        zip_path = package_path.with_suffix(".zip")
        try:
            package_path.mkdir()
        except FileExistsError:
            continue  # taken by an earlier run, or by a parallel one just now
        if not zip_output:
            if zip_path.exists():
                package_path.rmdir()  # a zip package has this name: next name
                continue
            return package_path, zip_path
        try:
            open(zip_path, "x").close()
            return package_path, zip_path
        except FileExistsError:
            package_path.rmdir()  # the zip name is taken: next name
        except OSError:
            package_path.rmdir()  # leave no empty folder behind
            if zip_path.exists():
                # Something other than a file holds the zip name (Windows
                # answers "permission denied" for a directory): taken, as
                # in folder mode, so both modes agree on what taken means
                continue
            raise  # cannot claim the zip (permissions, disk full)
    raise AssertionError("unreachable")  # itertools.count never ends


def _fill_package(
    package_path: Path,
    mets_tree: etree._ElementTree,
    file_categories: dict[str, dict],
    progress_callback: Callable[[int, int], None] | None,
) -> None:
    """Create the folder structure, copy the files and write METS.xml."""
    package_root = package_path.resolve()

    # Create all subdirectories
    for folder_rel in FOLDER_STRUCTURE.values():
        (package_path / folder_rel).mkdir(parents=True, exist_ok=True)

    # Count total files for progress
    total_files = sum(len(files) for files in file_categories.values())
    copied = 0

    # Copy files
    for category, files in file_categories.items():
        dest_rel = FOLDER_STRUCTURE.get(category)
        if not dest_rel:
            logger.warning("Unknown category '%s', skipping", category)
            continue

        dest_folder = package_path / dest_rel
        for file_info in files.values():
            src = Path(file_info["path"])
            # The METS already lists this file with its checksum. Skipping
            # it would leave a package that looks complete but is not, so a
            # source that vanished or changed since it was hashed is an
            # error. Missing paths were already reported at collect time.
            if not src.is_file():
                raise FileNotFoundError(
                    "Source file is missing, or no longer a file, since it "
                    f"was collected: {src}"
                )
            expected_size = file_info.get("filesize")
            if expected_size is not None and src.stat().st_size != int(expected_size):
                raise ValueError(
                    f"Source file changed size after it was hashed: {src}"
                )

            # Build destination path preserving subdirectory structure
            rel_path = file_info.get("relativefilepath", "/")
            sub_dir = rel_path.strip("/") if rel_path else ""
            full_dest_dir = dest_folder / sub_dir if sub_dir else dest_folder
            dest_filename = file_info.get("fgsfilename", src.name)
            dest_path = full_dest_dir / dest_filename

            # Defence in depth: normalize_filename already makes every name a
            # single safe segment, but never write outside the package.
            # Checked before any folder is created.
            if not dest_path.resolve().is_relative_to(package_root):
                raise ValueError(
                    f"Refusing to write outside the package: {dest_path}"
                )
            # Deduplication gives every file a unique destination, so an
            # existing path means a clash, such as a file and a folder with the
            # same name. Stop rather than overwrite or misplace the file.
            if dest_path.exists():
                raise FileExistsError(
                    f"Two selected items map to the same package path: "
                    f"{dest_path.relative_to(package_path)}"
                )
            try:
                full_dest_dir.mkdir(parents=True, exist_ok=True)
            except (FileExistsError, NotADirectoryError):
                # A file was already copied where this folder must go
                raise FileExistsError(
                    f"Two selected items map to the same package path: "
                    f"{full_dest_dir.relative_to(package_path)} is needed "
                    "as both a file and a folder"
                ) from None

            logger.info("Copying %s -> %s", src, dest_path)
            _copy_and_verify(src, dest_path, file_info.get("hashvalue"))

            copied += 1
            if progress_callback:
                progress_callback(copied, total_files)

    # Write METS.xml through a Python file handle rather than by name:
    # lxml encodes a file name as strict UTF-8, so an output path with a
    # lone surrogate (NTFS allows one) would fail here, while every other
    # step handles such a path. The handle keeps the name out of lxml.
    mets_path = package_path / "METS.xml"
    with open(mets_path, "wb") as handle:
        mets_tree.write(
            handle,
            xml_declaration=True,
            encoding="utf-8",
            pretty_print=True,
        )
    logger.info("METS.xml written to %s", mets_path)


def _copy_and_verify(src: Path, dest: Path, expected_hash: str | None) -> None:
    """Copy src to dest in chunks, hashing on the way, then copy its timestamps.

    The METS already records the file's SHA-256. Hashing the bytes as they
    are copied costs no extra read and catches a file that changed since
    it was hashed, even at the same size, or while it was being copied.

    Raises:
        ValueError: The copied bytes do not match the recorded checksum.
    """
    digest = hashlib.sha256()
    with open(src, "rb") as source, open(dest, "wb") as target:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            target.write(chunk)
    # Keep the timestamps, not the attributes: copystat would also copy a
    # read-only bit, and Windows cannot delete a read-only file, which
    # would break the zip step and the cleanup of a failed run.
    source_stat = src.stat()
    os.utime(dest, ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns))
    if expected_hash and digest.hexdigest() != expected_hash:
        raise ValueError(f"Source file changed after it was hashed: {src}")


def _remove_tree(path: Path, ignore_errors: bool = False) -> None:
    """rmtree that clears the read-only bit and retries.

    Windows refuses to delete a read-only file. Copies are made writable,
    but this is the second layer for anything else in this run's folder.
    """
    def clear_and_retry(func, failed, _exc):
        os.chmod(failed, stat.S_IWRITE)
        func(failed)

    handler = (
        {"onexc": clear_and_retry} if sys.version_info >= (3, 12)
        else {"onerror": clear_and_retry}
    )
    try:
        shutil.rmtree(path, **handler)
    except OSError:
        if not ignore_errors:
            raise


def _zip_package(package_path: Path, zip_path: Path) -> None:
    """Zip the package folder into this run's placeholder, then remove the folder.

    Folders are written as entries too, so the zip has the same layout as
    the folder output, empty standard folders included.

    The copies keep their source's modification time, and the zip format
    can only store dates from 1980 to 2107. Files older than that are
    common in deliveries (extracts without timestamps are dated 1970),
    so the entry date is clamped to that range instead of failing the
    run. The METS CREATED value is unaffected.

    strict_timestamps=False alone is not enough: before it clamps,
    zipfile converts the mtime with time.localtime, which on Windows
    rejects anything before 1970 or after about year 3000 with "[Errno
    22] Invalid argument". So each entry's mtime is first pulled into a
    range localtime accepts. That is done on the copy in the package
    folder, which is removed right after zipping, never on the source.
    """
    logger.info("Creating zip archive: %s", zip_path)
    with zipfile.ZipFile(
        zip_path, "w", zipfile.ZIP_DEFLATED, strict_timestamps=False
    ) as zf:
        for entry in sorted(package_path.rglob("*")):
            _clamp_mtime_for_zip(entry)
            zf.write(entry, entry.relative_to(package_path.parent))
    _remove_tree(package_path)


# What time.localtime accepts on every platform, with a day of margin at
# the low end for any time zone. Both ends are outside the zip range, so
# the zip's own clamp (1980-01-01, 2107-12-31) still decides the date.
_LOCALTIME_SAFE_MIN = 86_400  # 1970-01-02T00:00:00Z
_LOCALTIME_SAFE_MAX = 32_503_593_600  # 2999-12-31T00:00:00Z


def _clamp_mtime_for_zip(entry: Path) -> None:
    """Pull a copied entry's mtime into the range time.localtime accepts."""
    mtime = entry.stat().st_mtime
    safe = min(max(mtime, _LOCALTIME_SAFE_MIN), _LOCALTIME_SAFE_MAX)
    if safe != mtime:
        os.utime(entry, (safe, safe))
