"""E-ARK SIP package assembly.

Creates the folder structure, copies files with normalized names,
writes METS.xml, and optionally zips the result.
"""

import logging
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable

from lxml import etree

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
        mets_tree: lxml ElementTree of the METS document.
        file_categories: Dict mapping category names to file
            metadata dicts (same structure as passed to build_mets).
        zip_output: If True, zip the package folder and remove
            the unzipped version.
        progress_callback: Optional callback(current, total) for
            progress reporting.

    Returns:
        Path to the created package folder (or zip file).
    """
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    package_name = f"IP_{timestamp}"
    package_path = output_dir / package_name
    package_path.mkdir(parents=True, exist_ok=True)

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
            if not src.exists():
                logger.warning("Source file not found, skipping: %s", src)
                copied += 1
                if progress_callback:
                    progress_callback(copied, total_files)
                continue

            # Build destination path preserving subdirectory structure
            rel_path = file_info.get("relativefilepath", "/")
            if rel_path and rel_path != "/":
                # Strip leading/trailing slashes and create subdirs
                sub_dir = rel_path.strip("/")
                full_dest_dir = dest_folder / sub_dir
                full_dest_dir.mkdir(parents=True, exist_ok=True)
            else:
                full_dest_dir = dest_folder

            dest_filename = file_info.get("fgsfilename", src.name)
            dest_path = full_dest_dir / dest_filename

            logger.info("Copying %s -> %s", src, dest_path)
            shutil.copy2(str(src), str(dest_path))

            copied += 1
            if progress_callback:
                progress_callback(copied, total_files)

    # Write METS.xml
    mets_path = package_path / "METS.xml"
    mets_tree.write(
        str(mets_path),
        xml_declaration=True,
        encoding="utf-8",
        pretty_print=True,
    )
    logger.info("METS.xml written to %s", mets_path)

    # Optionally zip
    if zip_output:
        zip_path = package_path.with_suffix(".zip")
        logger.info("Creating zip archive: %s", zip_path)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in sorted(package_path.rglob("*")):
                if file_path.is_file():
                    arcname = file_path.relative_to(package_path.parent)
                    zf.write(file_path, arcname)
        shutil.rmtree(package_path)
        logger.info("Package zipped: %s", zip_path)
        return zip_path

    logger.info("Package created: %s", package_path)
    return package_path
