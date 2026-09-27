"""GUI-free job model and pipeline for E-ARK SIP packages.

A Job holds everything the GUI form holds. validate_job, build_header and
run_job are the logic that used to live in the GUI class, moved here so
that the GUI and the command line call the same code and cannot disagree
about what a valid package is. load_job reads a Job from a JSON job file
that mirrors the form (see job.example.json).

This module never imports tkinter or customtkinter, so it runs on a
machine with no display.
"""

import json
import logging
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Callable

from eark_core import collect_files
from mets_builder import Agent, AltRecordID, MetsHeader, build_mets
from package_assembler import create_package

logger = logging.getLogger(__name__)

# The GUI's dropdown values, in the GUI's order. The GUI's dropdowns are
# read-only, so only a job built outside the GUI can hold anything else,
# and validate_job checks against these lists.
TYPE_VALUES = [
    "Datasets",
    "Geospatial Data",
    "Databases",
    "Websites",
    "Collection",
    "Mixed",
    "Other",
]
CONTENTINFORMATIONTYPE_VALUES = [
    "citserms_v2_1",
    "ERMS",
    "SIARD1",
    "SIARD2",
    "GeoData",
    "citssiard_v1_0",
    "MIXED",
    "OTHER",
]
RECORDSTATUS_VALUES = ["NEW", "SUPPLEMENT", "REPLACEMENT", "TEST", "VERSION"]
ID_TYPE_VALUES = ["ORG", "DUNS", "VAT", "HSA", "Local", "URI"]

# Status texts reported through run_job's status_callback. They are the
# texts the GUI shows in its status line during a run.
STATUS_COLLECTING = "Collecting files..."
STATUS_BUILDING = "Building METS XML..."
STATUS_ASSEMBLING = "Assembling package..."


class JobValidationError(ValueError):
    """Raised by run_job when validate_job finds problems.

    The message lists every problem, one per line. A ValueError, so code
    that catches ValueError keeps working, but distinct from the errors
    the pipeline itself raises.
    """


def _paths(values) -> list[Path]:
    """Accept str or Path entries, as a Job built in code may use either.

    A single path where a list is expected is reported, not iterated: a
    str would be split into characters, and "." among them would pull the
    whole working folder into the package.
    """
    if isinstance(values, (str, os.PathLike)):
        raise TypeError(f"expected a list of paths, not a single path: {values!r}")
    return [Path(value) for value in values]


# ── Job model ──
# Attribute names are the job file's keys, so a Job reads like the file.


@dataclass
class JobHeader:
    """The METS Header section of the form."""

    label: str = ""
    type: str = "Datasets"
    other_type: str = ""
    contentinformationtype: str = "citserms_v2_1"
    other_contentinformationtype: str = ""
    recordstatus: str = "NEW"


@dataclass
class OrganizationAgent:
    """ARCHIVIST or CREATOR: an organisation with an identification code."""

    name: str = ""
    id_type: str = "ORG"
    id_value: str = ""


@dataclass
class SystemAgent:
    """SYSTEM: the software that produced the material."""

    name: str = ""
    version: str = ""


@dataclass
class JobAgents:
    """The Agents section of the form."""

    archivist: OrganizationAgent = field(default_factory=OrganizationAgent)
    creator: OrganizationAgent = field(default_factory=OrganizationAgent)
    system: SystemAgent = field(default_factory=SystemAgent)


@dataclass
class JobAltRecordIds:
    """The Alt Record IDs section. Attribute names are the METS TYPE values."""

    SUBMISSIONAGREEMENT: str = ""
    PREVIOUSSUBMISSIONAGREEMENT: str = ""
    REFERENCECODE: str = ""
    PREVIOUSREFERENCECODE: str = ""


@dataclass
class RepresentationFiles:
    """The Representations selector, the only one with a subdirectory option."""

    paths: list[Path] = field(default_factory=list)
    subdirectories: bool = False

    def __post_init__(self) -> None:
        self.paths = _paths(self.paths)


@dataclass
class JobFiles:
    """The File Selection section, one entry per selector.

    Each path is a file or a folder, as added with Add File or Add Folder.
    The attribute names are the category keys eark_core uses. Paths may be
    given as str or Path.
    """

    schema: list[Path] = field(default_factory=list)
    representation: RepresentationFiles = field(
        default_factory=RepresentationFiles
    )
    representationmetadata: list[Path] = field(default_factory=list)
    descriptivemetadata: list[Path] = field(default_factory=list)
    preservationmetadata: list[Path] = field(default_factory=list)
    documentation: list[Path] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.schema = _paths(self.schema)
        self.representationmetadata = _paths(self.representationmetadata)
        self.descriptivemetadata = _paths(self.descriptivemetadata)
        self.preservationmetadata = _paths(self.preservationmetadata)
        self.documentation = _paths(self.documentation)


@dataclass
class JobOutput:
    """The Output section of the form. The folder may be a str or a Path."""

    folder: Path | None = None
    zip: bool = False

    def __post_init__(self) -> None:
        # An empty or blank string means "not set", as in a job file, rather
        # than the current directory that Path("") would silently point at
        if self.folder is not None:
            text = str(self.folder).strip()
            self.folder = Path(text) if text else None


@dataclass
class Job:
    """Everything the GUI form holds, as plain data."""

    header: JobHeader = field(default_factory=JobHeader)
    agents: JobAgents = field(default_factory=JobAgents)
    alt_record_ids: JobAltRecordIds = field(default_factory=JobAltRecordIds)
    files: JobFiles = field(default_factory=JobFiles)
    output: JobOutput = field(default_factory=JobOutput)


# ── Validation ──


def validate_job(job: Job) -> list[str]:
    """Check a job the way the GUI checks its form before Generate.

    Returns:
        Error messages, one per problem: the GUI's rules in the GUI's
        order, then the dropdown-value rule the GUI needs no check for,
        then text values holding characters XML does not allow. An empty
        list means the job is valid.
    """
    errors: list[str] = []
    header = job.header

    if header.type == "Other" and not header.other_type.strip():
        errors.append("TYPE is 'Other' but no custom type specified.")

    if (
        header.contentinformationtype == "OTHER"
        and not header.other_contentinformationtype.strip()
    ):
        errors.append(
            "CONTENTINFORMATIONTYPE is 'OTHER' but no custom value specified."
        )

    if not job.alt_record_ids.SUBMISSIONAGREEMENT.strip():
        errors.append("SUBMISSIONAGREEMENT is required.")

    folder = job.output.folder
    if folder is None:
        errors.append("No output folder selected.")
    elif not folder.is_dir():
        errors.append("Output folder does not exist.")

    # Values the GUI's read-only dropdowns cannot produce, but a job file can
    for key, value, allowed in (
        ("header.type", header.type, TYPE_VALUES),
        (
            "header.contentinformationtype",
            header.contentinformationtype,
            CONTENTINFORMATIONTYPE_VALUES,
        ),
        ("header.recordstatus", header.recordstatus, RECORDSTATUS_VALUES),
        ("agents.archivist.id_type", job.agents.archivist.id_type, ID_TYPE_VALUES),
        ("agents.creator.id_type", job.agents.creator.id_type, ID_TYPE_VALUES),
    ):
        if value not in allowed:
            errors.append(
                f"{key} must be one of {', '.join(allowed)}, not '{value}'."
            )

    # Text that ends up in the METS must be XML-compatible. lxml would
    # otherwise fail deep in the pipeline without naming the field.
    for key, value in _text_values(job):
        bad = _xml_incompatible_character(value)
        if bad is not None:
            errors.append(
                f"{key} contains a character XML does not allow "
                f"(U+{ord(bad):04X})."
            )

    return errors


def _text_values(job: Job) -> list[tuple[str, str]]:
    """(key path, value) for every free-text field that reaches the METS."""
    values = [
        ("header.label", job.header.label),
        ("header.other_type", job.header.other_type),
        ("header.other_contentinformationtype",
         job.header.other_contentinformationtype),
    ]
    for name, org in (("archivist", job.agents.archivist), ("creator", job.agents.creator)):
        values.append((f"agents.{name}.name", org.name))
        values.append((f"agents.{name}.id_value", org.id_value))
    values.append(("agents.system.name", job.agents.system.name))
    values.append(("agents.system.version", job.agents.system.version))
    for f in fields(JobAltRecordIds):
        values.append((f"alt_record_ids.{f.name}", getattr(job.alt_record_ids, f.name)))
    return values


def _xml_incompatible_character(text: str) -> str | None:
    """The first character XML 1.0 does not allow, or None.

    Control characters below U+0020 other than tab, newline and carriage
    return, lone surrogates, and U+FFFE/U+FFFF are not allowed anywhere
    in an XML document.
    """
    for char in text:
        code = ord(char)
        if (
            (code < 0x20 and char not in "\t\n\r")
            or 0xD800 <= code <= 0xDFFF
            or code in (0xFFFE, 0xFFFF)
        ):
            return char
    return None


# ── Header assembly ──


def build_header(job: Job) -> MetsHeader:
    """Construct the MetsHeader from a job, as the GUI does from its form.

    Agents with an empty name are skipped. An organisation's note is
    "{id_type}:{id_value}", left out when the value is empty. All four
    altRecordIDs are passed on; mets_builder skips the empty ones.
    """
    agents: list[Agent] = []

    for role, org in (
        ("ARCHIVIST", job.agents.archivist),
        ("CREATOR", job.agents.creator),
    ):
        name = org.name.strip()
        if not name:
            continue
        id_value = org.id_value.strip()
        note = f"{org.id_type}:{id_value}" if id_value else None
        agents.append(
            Agent(
                role=role,
                type="ORGANIZATION",
                name=name,
                note=note,
                notetype="IDENTIFICATIONCODE" if note else None,
            )
        )

    system_name = job.agents.system.name.strip()
    if system_name:
        version = job.agents.system.version.strip()
        agents.append(
            Agent(
                role="OTHER",
                type="OTHER",
                othertype="SOFTWARE",
                otherrole="PRODUCER",
                name=system_name,
                note=version or None,
                notetype="SOFTWARE VERSION" if version else None,
            )
        )

    ids = job.alt_record_ids
    alt_records = [
        AltRecordID("SUBMISSIONAGREEMENT", ids.SUBMISSIONAGREEMENT.strip()),
        AltRecordID(
            "PREVIOUSSUBMISSIONAGREEMENT",
            ids.PREVIOUSSUBMISSIONAGREEMENT.strip(),
        ),
        AltRecordID("REFERENCECODE", ids.REFERENCECODE.strip()),
        AltRecordID("PREVIOUSREFERENCECODE", ids.PREVIOUSREFERENCECODE.strip()),
    ]

    header = job.header
    return MetsHeader(
        label=header.label.strip(),
        type=header.type,
        other_type=header.other_type.strip(),
        contentinformationtype=header.contentinformationtype,
        other_contentinformationtype=header.other_contentinformationtype.strip(),
        recordstatus=header.recordstatus,
        agents=agents,
        alt_record_ids=alt_records,
    )


# ── Pipeline ──


def _file_selections(job: Job) -> list[tuple[str, list[Path], bool]]:
    """(category, paths, subdirectories) per selector, in the GUI's order."""
    files = job.files
    return [
        ("schema", files.schema, False),
        (
            "representation",
            files.representation.paths,
            files.representation.subdirectories,
        ),
        ("representationmetadata", files.representationmetadata, False),
        ("descriptivemetadata", files.descriptivemetadata, False),
        ("preservationmetadata", files.preservationmetadata, False),
        ("documentation", files.documentation, False),
    ]


def run_job(
    job: Job,
    progress_callback: Callable[[int, int], None] | None = None,
    status_callback: Callable[[str], None] | None = None,
) -> tuple[Path, list[str]]:
    """Validate a job and create its package: the GUI's Generate pipeline.

    Collects the selected files, builds the METS document and assembles
    the package. Never shows a dialog; the front end decides how to report
    the result.

    Args:
        job: The job to run.
        progress_callback: Optional callback(copied, total) during the copy
            phase, as create_package reports it.
        status_callback: Optional callback(text) at the start of each
            phase, with the texts the GUI shows in its status line.

    Returns:
        The package path (the folder, or the zip file in zip mode) and the
        collect warnings, one per skipped path. A run with warnings still
        produced a package.

    Raises:
        JobValidationError: The job is invalid. The message lists every
            validation error, one per line. It is a ValueError.
        Whatever collect_files, build_mets or create_package raise.
    """
    errors = validate_job(job)
    if errors:
        raise JobValidationError("\n".join(errors))
    output_dir = job.output.folder
    assert output_dir is not None  # validate_job has checked it

    def status(text: str) -> None:
        if status_callback:
            status_callback(text)

    header = build_header(job)

    status(STATUS_COLLECTING)
    file_categories: dict[str, dict] = {}
    collect_warnings: list[str] = []
    for category, paths, subdirectories in _file_selections(job):
        if not paths:
            continue
        files = collect_files(
            paths,
            category,
            subdirectories=subdirectories,
            warnings=collect_warnings,
        )
        # One line per selector, so a script's stderr and the GUI's log
        # file show what each listed path amounted to
        logger.info("%s: %d file(s) collected", category, len(files))
        if files:
            file_categories[category] = files

    status(STATUS_BUILDING)
    mets_tree = build_mets(header, file_categories)

    status(STATUS_ASSEMBLING)
    result_path = create_package(
        output_dir,
        mets_tree,
        file_categories,
        zip_output=job.output.zip,
        progress_callback=progress_callback,
    )
    return result_path, collect_warnings


# ── Job files ──


def load_job(path: str | Path) -> Job:
    """Read a Job from a JSON job file.

    The file is UTF-8; a byte order mark is accepted, because Windows
    Notepad adds one. Omitted sections and keys take the GUI's defaults.
    Every present key must be known and have the right type, at every
    level, and the error names the full key path. Relative paths, file
    entries and the output folder alike, are resolved against the job
    file's folder, not the working directory.

    Raises:
        ValueError: The file is not valid UTF-8 JSON (or cannot be parsed
            at all, such as one nested too deeply or holding a number of
            thousands of digits), or a key is unknown, has the wrong type,
            is an empty path, is a drive-relative path such as "C:x", or
            is a rooted path without a drive such as "\\x".
        OSError: The file cannot be read.
    """
    job_path = Path(path)
    logger.info("Reading job file %s", job_path)
    try:
        text = job_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as e:
        raise ValueError(f"{job_path} is not valid UTF-8: {e}") from None
    try:
        data = json.loads(text, object_pairs_hook=_JsonObject)
    except json.JSONDecodeError as e:
        raise ValueError(f"{job_path} is not valid JSON: {e}") from None
    except RecursionError:
        # The parser recurses per nesting level. A job file is at most
        # three levels deep, so this is not a job file; say so instead of
        # letting the CLI print a stack overflow traceback.
        raise ValueError(
            f"{job_path} is nested too deeply to be a job file"
        ) from None
    except ValueError as e:
        # Other parser limits, such as a number of thousands of digits,
        # come out as a plain ValueError whose message is advice for
        # Python developers. Name the file and say what a job-file author
        # can act on; the raw reason goes to the debug log.
        logger.debug("json.loads refused %s: %s", job_path, e)
        raise ValueError(
            f"{job_path} is not a usable job file: it holds a value the JSON "
            "parser cannot read, such as a number thousands of digits long"
        ) from None
    if not isinstance(data, dict):
        raise ValueError(
            f"{job_path} must hold a JSON object, not {_type_name(data)}"
        )
    base_dir = job_path.resolve().parent

    _check_keys(data, ("header", "agents", "alt_record_ids", "files", "output"), "")

    agents = _section(data, "agents", "agents")
    _check_keys(agents, ("archivist", "creator", "system"), "agents")

    files = _section(data, "files", "files")
    _check_keys(files, tuple(f.name for f in fields(JobFiles)), "files")
    representation = _section(files, "representation", "files.representation")
    _check_keys(representation, ("paths", "subdirectories"), "files.representation")

    output = _section(data, "output", "output")
    _check_keys(output, ("folder", "zip"), "output")
    folder_text = _read_text(output, "folder", "output", "")

    return Job(
        header=_read_strings(_section(data, "header", "header"), JobHeader, "header"),
        agents=JobAgents(
            archivist=_read_strings(
                _section(agents, "archivist", "agents.archivist"),
                OrganizationAgent, "agents.archivist",
            ),
            creator=_read_strings(
                _section(agents, "creator", "agents.creator"),
                OrganizationAgent, "agents.creator",
            ),
            system=_read_strings(
                _section(agents, "system", "agents.system"),
                SystemAgent, "agents.system",
            ),
        ),
        alt_record_ids=_read_strings(
            _section(data, "alt_record_ids", "alt_record_ids"),
            JobAltRecordIds, "alt_record_ids",
        ),
        files=JobFiles(
            schema=_read_paths(files, "schema", "files", base_dir),
            representation=RepresentationFiles(
                paths=_read_paths(
                    representation, "paths", "files.representation", base_dir
                ),
                subdirectories=_read_flag(
                    representation, "subdirectories", "files.representation", False
                ),
            ),
            representationmetadata=_read_paths(
                files, "representationmetadata", "files", base_dir
            ),
            descriptivemetadata=_read_paths(
                files, "descriptivemetadata", "files", base_dir
            ),
            preservationmetadata=_read_paths(
                files, "preservationmetadata", "files", base_dir
            ),
            documentation=_read_paths(files, "documentation", "files", base_dir),
        ),
        output=JobOutput(
            folder=(
                _resolve(folder_text, base_dir, "output.folder")
                if folder_text else None
            ),
            zip=_read_flag(output, "zip", "output", False),
        ),
    )


class _JsonObject(dict):
    """A parsed JSON object that remembers keys given more than once.

    json.loads would keep the last value and drop the first silently. The
    duplicates are reported by _check_keys, which knows the key path.
    """

    def __init__(self, pairs: list[tuple[str, object]]) -> None:
        super().__init__()
        self.duplicates: list[str] = []
        for key, value in pairs:
            if key in self:
                self.duplicates.append(key)
            self[key] = value


def _type_name(value: object) -> str:
    """Describe a JSON value's type the way a job-file author sees it."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "a boolean"
    if isinstance(value, (int, float)):
        return "a number"
    return {str: "a string", list: "a list", dict: "an object"}.get(
        type(value), type(value).__name__
    )


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _check_keys(section: dict, allowed: tuple[str, ...], path: str) -> None:
    """Reject unknown and repeated keys; both usually mean a typo."""
    for key in getattr(section, "duplicates", ()):
        raise ValueError(f"Duplicate key {_join(path, key)}")
    for key in section:
        if key not in allowed:
            raise ValueError(f"Unknown key {_join(path, key)}")


def _section(data: dict, key: str, path: str) -> dict:
    """The object under key, or an empty one when the key is omitted."""
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object, not {_type_name(value)}")
    return value


def _read_text(section: dict, key: str, path: str, default: str) -> str:
    """A string value, trimmed: whitespace around any text value is ignored."""
    value = section.get(key, default)
    if not isinstance(value, str):
        raise ValueError(
            f"{_join(path, key)} must be a string, not {_type_name(value)}"
        )
    return value.strip()


def _read_flag(section: dict, key: str, path: str, default: bool) -> bool:
    value = section.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(
            f"{_join(path, key)} must be true or false, not {_type_name(value)}"
        )
    return value


def _read_strings(section: dict, cls: type, path: str):
    """Build a dataclass whose fields are all strings, defaults from the class."""
    _check_keys(section, tuple(f.name for f in fields(cls)), path)
    return cls(**{
        f.name: _read_text(section, f.name, path, f.default)
        for f in fields(cls)
    })


def _read_paths(section: dict, key: str, path: str, base_dir: Path) -> list[Path]:
    """A list of file or folder paths, resolved against the job file's folder."""
    value = section.get(key, [])
    key_path = _join(path, key)
    if not isinstance(value, list):
        raise ValueError(
            f"{key_path} must be a list of paths, not {_type_name(value)}"
        )
    paths: list[Path] = []
    seen: set[str] = set()
    for index, entry in enumerate(value):
        if not isinstance(entry, str):
            raise ValueError(
                f"{key_path}[{index}] must be a string, not {_type_name(entry)}"
            )
        entry = entry.strip()
        if not entry:
            raise ValueError(f"{key_path}[{index}] must not be empty")
        resolved = _resolve(entry, base_dir, f"{key_path}[{index}]")
        # A path listed twice counts once, as the GUI ignores a second add.
        # Compared in normalized form, so "src", "./src" and "src/../src"
        # are one path; the first spelling is kept.
        normalized = os.path.normcase(os.path.normpath(resolved))
        if normalized not in seen:
            seen.add(normalized)
            paths.append(resolved)
    return paths


def _resolve(text: str, base_dir: Path, key_path: str) -> Path:
    """Anchor a relative path at the job file's folder; keep absolute ones.

    Two Windows forms are rejected because they are neither: a
    drive-relative path such as "C:x" (drive letter, no separator), which
    Windows resolves against that drive's current directory for the
    process, so the result would depend on where the script runs; and a
    rooted path without a drive such as "\\x", which would land on the
    job file's drive root rather than in its folder.

    Raises:
        ValueError: The path is drive-relative or rooted without a drive.
    """
    candidate = Path(text)
    if candidate.is_absolute():
        return candidate
    if candidate.drive or candidate.root:
        kind = "drive-relative" if candidate.drive else "rooted without a drive"
        raise ValueError(
            f"{key_path} must be an absolute path or a path relative to the "
            f"job file, not the {kind} '{text}'"
        )
    return base_dir / candidate
