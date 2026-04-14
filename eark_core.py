"""Core utilities for E-ARK SIP package creation.

File collection, metadata gathering, filename normalization, and hashing.
"""

import hashlib
import logging
import mimetypes
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path

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


def normalize_filename(name: str) -> str:
    """Normalize a filename to ASCII-safe characters.

    Uses NFKD unicode normalization to decompose accented characters,
    then encodes to ASCII (dropping combining marks). Non-ASCII
    remainders and spaces become underscores.

    Args:
        name: Original filename (name only, not full path).

    Returns:
        ASCII-safe filename string.
    """
    decomposed = unicodedata.normalize("NFKD", name)
    # Replace non-ASCII characters with underscore, keep ASCII as-is
    result = []
    for char in decomposed:
        if ord(char) < 128:
            if char == " ":
                result.append("_")
            else:
                result.append(char)
        elif not unicodedata.combining(char):
            # Non-ASCII, non-combining character → underscore
            result.append("_")
        # Combining marks (accents) are silently dropped since
        # their base character was already kept
    ascii_str = "".join(result)
    if not ascii_str:
        ascii_str = "_"
    return ascii_str


def deduplicate_filename(name: str, existing: set[str]) -> str:
    """Append _1, _2, etc. before the extension if name collides.

    Args:
        name: Filename to check.
        existing: Set of already-used filenames.

    Returns:
        A unique filename not in the existing set.
    """
    if name not in existing:
        return name

    stem = Path(name).stem
    suffix = Path(name).suffix
    counter = 1
    while True:
        candidate = f"{stem}_{counter}{suffix}"
        if candidate not in existing:
            return candidate
        counter += 1


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
        originalfilename, fgsfilename, relativefilepath, uuid.
    """
    stat = path.stat()
    file_size = str(stat.st_size)
    # On Windows/NTFS, st_ctime is birth time (file creation)
    created_date = datetime.fromtimestamp(
        stat.st_ctime, tz=timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    hash_value = compute_sha256(path)
    mime_type = detect_mimetype(path)
    original_filename = path.name
    fgs_filename = normalize_filename(original_filename)
    file_uuid = f"uuid-{uuid.uuid4()}"

    # Compute relative path from base_dir to the file's parent
    try:
        relative_dir = path.parent.relative_to(base_dir)
        relative_file_path = (
            f"/{relative_dir}/" if str(relative_dir) != "." else "/"
        )
    except ValueError:
        relative_file_path = "/"

    # Build the filelink using category path
    category_path = CATEGORY_PATHS.get(category, "")
    # Convert backslashes and normalize
    rel_part = relative_file_path.replace("\\", "/")
    file_link = f"{category_path}{rel_part}{fgs_filename}"

    return {
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
        "relativefilepath": rel_part,
        "uuid": file_uuid,
    }


def collect_files(
    paths: list[Path],
    category: str,
    subdirectories: bool = False,
    warnings: list[str] | None = None,
) -> dict:
    """Collect files from a list of file/directory paths.

    Accepts a mix of individual files and directories. For directories,
    walks contents (optionally including subdirectories). Skips missing
    paths with a warning. Deduplicates normalized filenames.

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
    used_names: set[str] = set()

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
                file_dict, used_names, source_path,
                category, source_path.parent,
            )
        elif source_path.is_dir():
            if subdirectories:
                for file_path in sorted(source_path.rglob("*")):
                    if file_path.is_file():
                        _add_file(
                            file_dict, used_names, file_path,
                            category, source_path,
                        )
            else:
                for file_path in sorted(source_path.iterdir()):
                    if file_path.is_file():
                        _add_file(
                            file_dict, used_names, file_path,
                            category, source_path,
                        )

    return file_dict


def _add_file(
    file_dict: dict,
    used_names: set[str],
    file_path: Path,
    category: str,
    base_dir: Path,
) -> None:
    """Add a single file to the collection dict with deduplication."""
    metadata = get_file_metadata(file_path, category, base_dir)
    # Deduplicate the normalized filename
    unique_name = deduplicate_filename(metadata["fgsfilename"], used_names)
    if unique_name != metadata["fgsfilename"]:
        logger.info(
            "Renamed duplicate '%s' to '%s'",
            metadata["fgsfilename"], unique_name,
        )
        metadata["fgsfilename"] = unique_name
        # Rebuild filelink with the deduplicated name
        category_path = CATEGORY_PATHS.get(category, "")
        metadata["filelink"] = (
            f"{category_path}{metadata['relativefilepath']}{unique_name}"
        )
    used_names.add(unique_name)
    file_dict[str(file_path)] = metadata
