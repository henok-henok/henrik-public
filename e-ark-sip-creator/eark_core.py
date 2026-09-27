"""Core utilities for E-ARK SIP package creation.

File collection, metadata gathering, filename normalization, and hashing.
"""

import hashlib
import logging
import mimetypes
import os
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lxml import etree

logger = logging.getLogger(__name__)

CATEGORY_PATHS: dict[str, str] = {
    "representation": "representations/rep_1/data",
    "representationmetadata": "representations/rep_1/metadata",
    "schema": "schemas",
    "descriptivemetadata": "metadata/descriptive",
    "othermetadata": "metadata/other",
    "preservationmetadata": "metadata/preservation",
    "documentation": "documentation",
}


# Characters replaced with "_" after normalization:
# - forbidden in Windows file names, including both path separators;
# - "#" and "%", which break the xlink:href URL in METS.
# NFKD produces several of these from harmless-looking characters. For
# example, a fullwidth colon becomes ":" and the two-dot leader becomes "..".
# So the check must run on the normalized text, not on the input.
_UNSAFE_CHARS = frozenset('<>:"/\\|?*#%')

# Device names Windows reserves regardless of extension, so "CON.txt"
# cannot be created as an ordinary file.
_RESERVED_NAMES = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"COM{i}" for i in range(1, 10)]
    + [f"LPT{i}" for i in range(1, 10)]
)


def normalize_filename(name: str) -> str:
    """Normalize a file or folder name to safe ASCII.

    Uses NFKD unicode normalization to decompose accented characters,
    then drops the combining marks, so "ärende" becomes "arende". Non-ASCII
    remainders, spaces, control characters and anything in _UNSAFE_CHARS
    become underscores. The result is always a single, ordinary path
    segment: it never contains a separator, is never "." or "..", never
    ends in a dot, and is never a reserved Windows device name.

    Args:
        name: Original file or folder name (one segment, not a path).

    Returns:
        ASCII-safe name, at least one character long.
    """
    decomposed = unicodedata.normalize("NFKD", name)
    result = []
    for char in decomposed:
        code = ord(char)
        if char == " " or char in _UNSAFE_CHARS or code < 32 or code == 127:
            result.append("_")
        elif code < 128:
            result.append(char)
        elif not unicodedata.combining(char):
            # Non-ASCII, non-combining character → underscore
            result.append("_")
        # Combining marks (accents) are silently dropped since
        # their base character was already kept

    # Windows drops trailing dots. "." and ".." are never valid names: they
    # are path segments for the folder itself and its parent.
    ascii_str = "".join(result).rstrip(".")
    if not ascii_str:
        ascii_str = "_"
    if ascii_str.split(".")[0].upper() in _RESERVED_NAMES:
        ascii_str = f"_{ascii_str}"
    return ascii_str


def deduplicate_filename(name: str, existing: set[str]) -> str:
    """Append _1, _2, etc. before the extension if name collides.

    Collisions are case-insensitive. Windows treats Report.txt and
    report.txt as the same file, so letting both through would make one
    overwrite the other in the package.

    Args:
        name: Filename to check.
        existing: Already-used filenames, stored casefolded
            (``name.casefold()``). Casefolding once when a name is added
            keeps this check constant-time for large collections.

    Returns:
        A unique filename whose casefolded form is not in existing.
    """
    if name.casefold() not in existing:
        return name

    stem = Path(name).stem
    suffix = Path(name).suffix
    counter = 1
    while True:
        candidate = f"{stem}_{counter}{suffix}"
        if candidate.casefold() not in existing:
            return candidate
        counter += 1


# Root elements of descriptive metadata this tool recognises, mapped to the
# METS MDTYPE vocabulary. Anything else is OTHER with the root's own name.
_DESCRIPTIVE_ROOTS = {
    "ead": "EAD",
    "mods": "MODS",
    "modscollection": "MODS",
    "dc": "DC",
}
_DC_NAMESPACE_PREFIXES = (
    "http://purl.org/dc/",
    "http://www.openarchives.org/OAI/2.0/oai_dc/",
)


def detect_descriptive_mdtype(path: Path) -> tuple[str, str | None]:
    """MDTYPE and OTHERMDTYPE for a descriptive metadata file.

    Only the root element's name is read. An ead root gives EAD, mods or
    modsCollection gives MODS, and Dublin Core (a dc root, or a root in a
    Dublin Core namespace) gives DC. Any other XML gives OTHER with the
    root element's local name as OTHERMDTYPE. A file that is not XML gives
    OTHER with the packaged file's extension (the normalized, ASCII one),
    without the dot, or "unknown" when the file has none.

    Args:
        path: The descriptive metadata file.

    Returns:
        (MDTYPE, OTHERMDTYPE). OTHERMDTYPE is None unless MDTYPE is OTHER.
    """
    root_name, namespace = _root_element(path)
    if root_name is None:
        # The packaged file's extension, not the original's: normalization
        # makes it ASCII, so it is always a valid attribute value, and it
        # matches the name the METS points at
        extension = Path(normalize_filename(path.name)).suffix.lstrip(".").lower()
        return "OTHER", extension or "unknown"
    mdtype = _DESCRIPTIVE_ROOTS.get(root_name.lower())
    if mdtype is None and namespace.startswith(_DC_NAMESPACE_PREFIXES):
        mdtype = "DC"
    if mdtype is None:
        return "OTHER", root_name
    return mdtype, None


def _root_element(path: Path) -> tuple[str | None, str]:
    """The root element's local name and namespace, or (None, "") if not XML.

    Stops after the root's start tag, so the file's size does not matter.
    A root with an undeclared namespace prefix, such as <dc:dc> without an
    xmlns, is a recoverable error for libxml2, which hands back the raw
    "dc:dc" tag; the part after the prefix is the local name then. A tag
    that leaves no local name at all (<x:/>) counts as not XML.

    The bytes are fed to a pull parser rather than handing lxml the open
    file: iterparse takes the file's name as the document's base URL and
    fails on a name it cannot encode, such as one with a lone surrogate,
    which NTFS allows. The parser never needs to know the name.
    """
    parser = etree.XMLPullParser(events=("start",))
    try:
        with open(path, "rb") as handle:
            while chunk := handle.read(65536):
                try:
                    parser.feed(chunk)
                except etree.XMLSyntaxError:
                    # feed raises for an error anywhere in the chunk, also
                    # long after the root. The root's start event is then
                    # already queued, and only the root matters here.
                    for _, element in parser.read_events():
                        return _split_tag(element.tag)
                    raise
                for _, element in parser.read_events():
                    return _split_tag(element.tag)
        parser.close()  # raises for an empty or truncated document
    except etree.XMLSyntaxError:
        return None, ""
    return None, ""


def _split_tag(tag: str) -> tuple[str | None, str]:
    """(local name, namespace) of an lxml tag; (None, "") if no local name.

    "{ns}local" is a namespaced tag. "prefix:local" is what libxml2 hands
    back for an undeclared prefix; the part after the colon is the name.
    """
    if tag.startswith("{"):
        namespace, local_name = tag[1:].split("}", 1)
    else:
        namespace, local_name = "", tag.rsplit(":", 1)[-1]
    return (local_name, namespace) if local_name else (None, "")


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _utc_iso(seconds: float) -> str:
    """A Unix timestamp as the ISO 8601 UTC text METS uses, e.g. 2025-01-15T10:00:00Z.

    Adds to the epoch instead of calling datetime.fromtimestamp, because
    on Windows that raises "[Errno 22] Invalid argument" for any time
    before 1970. NTFS creation times can be that old: a zero FILETIME
    (1601) left by some copy or restore tools, or a date set on purpose
    to a document's original date. Every date datetime can hold works.

    Raises:
        OverflowError: The date is after year 9999.
    """
    return (_EPOCH + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_sha256(path: Path) -> str:
    """Compute SHA-256 hash of a file using chunked reads.

    Args:
        path: Path to the file.

    Returns:
        Hex digest string.
    """
    file_hash = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            file_hash.update(chunk)
    return file_hash.hexdigest()


def detect_mimetype(path: Path) -> str:
    """Detect MIME type for a file.

    Forces .xsd files to application/xml. Falls back to
    application/octet-stream if detection fails.

    Args:
        path: Path to the file.

    Returns:
        MIME type string.
    """
    if path.suffix.lower() == ".xsd":
        return "application/xml"
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


def get_file_metadata(
    path: Path, category: str, base_dir: Path
) -> dict:
    """Gather all metadata for a single file.

    Args:
        path: Absolute path to the file.
        category: E-ARK category key (e.g. 'representation').
        base_dir: Base directory used to compute relative paths.

    Returns:
        Dict with keys: path, fileName, directory, category,
        filesize, hashvalue, createdate, mimetype, filelink,
        originalfilename, fgsfilename, relativefilepath, uuid. For
        descriptive metadata also mdtype and othermdtype, see
        detect_descriptive_mdtype.

    Raises:
        ValueError: The file's creation time is after year 9999, which
            no date format can hold; the message names the file.
        OSError: The file cannot be read.
    """
    stat = path.stat()
    file_size = str(stat.st_size)
    # Creation time. st_birthtime is the documented field since Python
    # 3.12; st_ctime, which older versions used for it on Windows, is the
    # fallback and will become the metadata-change time one day.
    try:
        created_date = _utc_iso(getattr(stat, "st_birthtime", stat.st_ctime))
    except OverflowError:
        # NTFS allows dates up to year 30828; datetime, and xsd:dateTime
        # in practice, stop at 9999. Such a value is corrupt metadata, so
        # stop and name the file rather than write a made-up date.
        raise ValueError(
            "Creation time cannot be written as a date (year 1 to 9999); "
            f"the file's timestamp is corrupt: {path}"
        ) from None
    hash_value = compute_sha256(path)
    mime_type = detect_mimetype(path)
    original_filename = path.name
    fgs_filename = normalize_filename(original_filename)
    file_uuid = f"uuid-{uuid.uuid4()}"

    # Compute relative path from base_dir to the file's parent. Folder names
    # get the same ASCII normalization as file names, so the package layout
    # and every xlink:href stay ASCII-safe.
    try:
        relative_dir = path.parent.relative_to(base_dir)
        parts = [normalize_filename(part) for part in relative_dir.parts]
        relative_file_path = f"/{'/'.join(parts)}/" if parts else "/"
    except ValueError:
        relative_file_path = "/"

    # Build the filelink using category path
    category_path = CATEGORY_PATHS.get(category, "")
    # relative_file_path is built from path parts joined with "/", so it is
    # already in URL form on every platform
    file_link = f"{category_path}{relative_file_path}{fgs_filename}"

    metadata = {
        "path": str(path),
        "fileName": original_filename,
        "directory": str(base_dir),
        "category": category,
        "filesize": file_size,
        "hashvalue": hash_value,
        "createdate": created_date,
        "mimetype": mime_type,
        "filelink": file_link,
        "originalfilename": original_filename,
        "fgsfilename": fgs_filename,
        "relativefilepath": relative_file_path,
        "uuid": file_uuid,
    }
    if category == "descriptivemetadata":
        mdtype, othermdtype = detect_descriptive_mdtype(path)
        metadata["mdtype"] = mdtype
        metadata["othermdtype"] = othermdtype
    return metadata


def collect_files(
    paths: list[Path],
    category: str,
    subdirectories: bool = False,
    warnings: list[str] | None = None,
) -> dict:
    """Collect files from a list of file/directory paths.

    Accepts a mix of individual files and directories. For directories,
    walks contents (optionally including subdirectories). Skips missing
    paths with a warning, warns about a directory that adds no files and
    about a subdirectory that cannot be read, and raises for a listed
    directory that cannot be read. Deduplicates normalized filenames
    within each package folder.

    Args:
        paths: List of file or directory paths to collect from.
        category: E-ARK category key for all collected files.
        subdirectories: Whether to recurse into subdirectories
            (only applies to directory paths).
        warnings: Optional list to accumulate human-readable warning
            messages (e.g. about skipped missing paths). When provided,
            callers can surface these to the user.

    Returns:
        Dict keyed by original file path string, values are
        metadata dicts from get_file_metadata.
    """
    file_dict: dict = {}
    # Names taken per package folder (casefolded folder -> casefolded
    # names), so only files that would land in the same folder collide
    used_names: dict[str, set[str]] = {}
    used_dirs: dict[str, str] = {}  # casefolded folder prefix -> spelling
    seen_files: set[str] = set()  # normalized paths, see _add_file

    for source_path in paths:
        source_path = Path(source_path)
        if not source_path.exists():
            msg = f"Path does not exist, skipped: {source_path}"
            logger.warning(msg)
            if warnings is not None:
                warnings.append(f"[{category}] {msg}")
            continue

        if source_path.is_file():
            _add_file(
                file_dict, used_names, used_dirs, seen_files, source_path,
                category, source_path.parent,
            )
        elif source_path.is_dir():
            # A listed folder that cannot be read is an error in both modes.
            # iterdir raises on its own; rglob would skip it silently.
            os.scandir(source_path).close()
            found_file = False
            if subdirectories:
                for file_path in sorted(source_path.rglob("*")):
                    if file_path.is_file():
                        found_file = True
                        _add_file(
                            file_dict, used_names, used_dirs, seen_files,
                            file_path, category, source_path,
                        )
                    elif file_path.is_dir():
                        _warn_if_unreadable(file_path, category, warnings)
            else:
                for file_path in sorted(source_path.iterdir()):
                    if file_path.is_file():
                        found_file = True
                        _add_file(
                            file_dict, used_names, used_dirs, seen_files,
                            file_path, category, source_path,
                        )
            if not found_file:
                # Treated like a missing path. In a script chain this usually
                # means an upstream step produced nothing, and a package
                # that looks complete would hide that.
                msg = f"Folder has no files, nothing added: {source_path}"
                logger.warning(msg)
                if warnings is not None:
                    warnings.append(f"[{category}] {msg}")

    return file_dict


def _warn_if_unreadable(
    folder: Path, category: str, warnings: list[str] | None
) -> None:
    """Report a subfolder rglob could not read.

    rglob skips a folder it cannot open without a word, so its files would
    be missing from a package that looks complete. Like a missing path,
    this is a warning: the run goes on and the caller sees it.
    """
    try:
        os.scandir(folder).close()
    except OSError as e:
        msg = f"Folder cannot be read, skipped: {folder} ({e.strerror})"
        logger.warning(msg)
        if warnings is not None:
            warnings.append(f"[{category}] {msg}")


def _canonical_dir(rel_path: str, used_dirs: dict[str, str]) -> str:
    """Spell each folder segment of rel_path the way it was first seen.

    Folders that differ only in case are one folder on Windows. Reusing the
    first spelling keeps every xlink:href in step with the folder that is
    actually created, and with the path stored in a zip, which is read from
    disk. This works segment by segment, so a clash in a middle folder is
    caught at any depth. For example, Data/ followed later by DATA/Sub/
    gives Data/Sub/.

    Args:
        rel_path: Relative folder path such as "/" or "/Data/Sub/".
        used_dirs: Maps each casefolded folder prefix (for example
            "/data/sub") to its chosen spelling. Updated in place.

    Returns:
        The canonical relative folder path, with leading and trailing "/".
    """
    if rel_path == "/":
        return rel_path
    canonical = ""
    for part in rel_path.strip("/").split("/"):
        candidate = f"{canonical}/{part}"
        canonical = used_dirs.setdefault(candidate.casefold(), candidate)
    return f"{canonical}/"


def _add_file(
    file_dict: dict,
    used_names: dict[str, set[str]],
    used_dirs: dict[str, str],
    seen_files: set[str],
    file_path: Path,
    category: str,
    base_dir: Path,
) -> None:
    """Add a single file to the collection dict with deduplication.

    A file reached twice, through overlapping listed paths such as a
    folder and one of its subfolders, counts once: the first collection
    stands, so it keeps its name and its place in the package. Paths are
    compared in normalized form, so "Data/sub" and "data/../data/sub"
    are the same file.
    """
    normalized = os.path.normcase(os.path.normpath(file_path))
    if normalized in seen_files:
        return
    seen_files.add(normalized)
    metadata = get_file_metadata(file_path, category, base_dir)

    canonical_rel = _canonical_dir(metadata["relativefilepath"], used_dirs)

    # Deduplicate the normalized filename within its package folder. Files
    # in different folders never overwrite each other, so 2020/report.pdf
    # and 2021/report.pdf both keep their names.
    folder_names = used_names.setdefault(canonical_rel.casefold(), set())
    unique_name = deduplicate_filename(metadata["fgsfilename"], folder_names)
    if unique_name != metadata["fgsfilename"]:
        logger.info(
            "Renamed duplicate '%s' to '%s'",
            metadata["fgsfilename"], unique_name,
        )
        metadata["fgsfilename"] = unique_name
    metadata["relativefilepath"] = canonical_rel

    # Rebuild filelink from the final folder and name
    category_path = CATEGORY_PATHS.get(category, "")
    metadata["filelink"] = f"{category_path}{canonical_rel}{unique_name}"

    folder_names.add(unique_name.casefold())
    file_dict[str(file_path)] = metadata
