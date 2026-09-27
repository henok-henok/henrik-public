"""Command-line entry point: create an E-ARK SIP package from a job file.

Usage:
    python cli.py JOB.json

The job file mirrors the GUI form; see job.example.json and the README.
Only the package path is written to stdout, so a calling script can
capture it. Everything else goes to stderr through logging. Both streams
are UTF-8.

Exit codes:
    0  package created, no warnings
    1  invalid job: the file cannot be read or parsed, or validation fails
    2  generation failed
    3  package created, with warnings (for example a listed path that does
       not exist, or a listed folder with no files)

A wrong command line (argparse usage error) also exits 2, with the usage
text on stderr and nothing on stdout.

This module never imports tkinter or customtkinter, so it runs on a
machine with no display.
"""

import argparse
import logging
import sys

from sip_job import load_job, run_job, validate_job

EXIT_OK = 0
EXIT_INVALID_JOB = 1
EXIT_GENERATION_FAILED = 2
EXIT_CREATED_WITH_WARNINGS = 3

logger = logging.getLogger(__name__)


def _use_utf8(stream) -> None:
    """Make an output stream UTF-8, whatever the console code page.

    When stdout is a pipe, Python on Windows falls back to the ANSI code
    page, so a package path with å, ä or ö would reach the calling script
    in cp1252 while it decodes UTF-8. The contract is UTF-8 for both
    streams. A character UTF-8 cannot encode (a lone surrogate from a
    malformed file name) is escaped rather than crashing the run after the
    package exists.
    """
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="backslashreplace")


def main(argv: list[str] | None = None) -> int:
    """Run one job file. Returns the exit code."""
    # Before the parser: a usage error is written to stderr by argparse,
    # and the UTF-8 contract covers that text too (it may quote a path)
    _use_utf8(sys.stdout)
    _use_utf8(sys.stderr)

    parser = argparse.ArgumentParser(
        description=(
            "Create an E-ARK SIP package from a JSON job file, without the GUI."
        ),
        epilog=(
            "Exit codes: 0 created, 1 invalid job, 2 generation failed, "
            "3 created with warnings. stdout holds only the package path."
        ),
    )
    parser.add_argument(
        "job_file",
        help="the job file (UTF-8 JSON, see job.example.json)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stderr,
    )

    try:
        job = load_job(args.job_file)
    except (ValueError, OSError) as e:
        logger.error("%s", e)
        return EXIT_INVALID_JOB

    errors = validate_job(job)
    if errors:
        for error in errors:
            logger.error("%s", error)
        return EXIT_INVALID_JOB

    try:
        package_path, warnings = run_job(job)
    except Exception:
        logger.exception("Generation failed")
        return EXIT_GENERATION_FAILED

    # The one line on stdout: the package path, for the calling script
    print(package_path)
    if warnings:
        logger.warning(
            "Package created with %d warning(s), see above", len(warnings)
        )
        return EXIT_CREATED_WITH_WARNINGS
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
