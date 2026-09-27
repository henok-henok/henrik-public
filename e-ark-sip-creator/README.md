# E-ARK SIP Creator

Desktop application for creating E-ARK SIP packages conforming to [E-ARK SIP v2.1.0](https://earksip.dilcis.eu/).

Fill in METS header values, select files through the GUI, and generate a standards-compliant SIP package with SHA-256 checksums and normalized filenames. Since 1.1.0 the same package can be made without the GUI, from a job file (see [Headless use](#headless-use)).

**Version:** 1.1.0-beta.2
**Authors:** Henrik Hellberg Lizama & Axel Wennerlund
**License:** MIT

> **Beta release** — feature-complete but intended for early testers. Please report any bugs or issues you find.

---

## What's new in 1.1.0-beta.2

This is the first 1.1.0 release. 1.1.0-beta.1 and 1.0.0-beta.2 were never
published, so everything under this heading and the two "What's new"
headings below is new since 1.0.0-beta.1.

- **Package identifier.** `mets/@OBJID` is now the package name (the
  folder name, or the zip name without `.zip`), and the root `structMap`
  div carries a `LABEL` equal to it, as CSIP requires. Before, OBJID was a
  random `IP_<uuid>` and the root div had no LABEL.
- **Clear error for a broken job file.** A job file the parser cannot
  read, nested too deeply or holding a number thousands of digits long,
  gives one error line naming the file and exit code 1, not a traceback.
- **Logging.** The headless run logs the job file it reads and how many
  files each selector produced; the GUI writes the file counts to its log
  file too.
- **Broken Unicode in a path.** A descriptive metadata file, or an
  output folder, whose path holds an unpaired UTF-16 character (Windows
  allows these) no longer stops the run.
- **Old file dates.** Files dated before 1980, including before 1970
  (extracts without timestamps often show 1970), no longer stop a zip
  package from being made; their date inside the zip is set to the
  earliest date the zip format can hold, while the METS keeps the real
  date. A creation time before 1970 no longer fails the run with
  "Invalid argument".
- **Package names across modes.** A folder package and a zip package in
  the same output folder can never share a name, so no two packages share
  a package identifier.

### What only you can check

These need real material or your environment:

- Run your external validator (the E-ARK validator, or commons-ip) on a
  package made from real material. In particular, `mets/@OBJID` now
  equals the package folder name (or the zip name without `.zip`), and
  the root `structMap` div's `LABEL` equals the OBJID. Both follow CSIP
  as we read it; the validator confirms the exact rule.
- Real file names and folder trees from a delivery: non-ASCII names,
  deep trees, read-only files from optical media, network shares with
  per-folder permissions.
- The headless chain: `cli.py` and `load_job`/`run_job` from your own
  Python scripts, with your job files.
- The exe is unsigned, so Windows may show "Windows protected your PC"
  on first start. Click "More info", then "Run anyway".
- **If something goes wrong, send the log.** The program writes
  `eark_sip_creator.log` next to the exe. If that folder is read-only,
  it goes to `%LOCALAPPDATA%\EarkSipCreator\` or the temp folder instead.
  It holds the most recent run only and is replaced the next time the
  program starts, so after an error, copy it before opening the program
  again. For the command line, keep the log with
  `python cli.py job.json 2> run.log`.

## What's new in 1.1.0-beta.1 (unpublished, included here)

- **Headless use.** The tool runs without the GUI: `python cli.py
  my_archive.job.json` from the command line, or `from sip_job import
  load_job, run_job` in a Python script. The job file mirrors the form;
  see `job.example.json` and [Headless use](#headless-use). The GUI and
  the command line share one module, so they make the same package from
  the same values. The form itself is unchanged.
- **Unique package names.** When `IP_<timestamp>` is already taken, `_1`,
  `_2`, … is appended, so two packages made within the same second no
  longer stop with an error, also when the runs happen in parallel.
- **Safer runs.** A source file that disappears or changes during packaging
  is now an error instead of a silently incomplete package, and Ctrl+C
  removes the half-written package. A listed folder with no files, or a
  subfolder that cannot be read, gives a warning, like a missing path.
  Read-only source files work in zip mode too.
- **Names are kept across folders.** Files with the same name in different
  folders, such as an `index.html` per folder, are no longer renamed with
  `_1`, `_2`; only names that would collide in the same folder are.
- **Descriptive metadata type.** Each `dmdSec` gets its `MDTYPE` from the
  file's root element (EAD, MODS or DC), otherwise `OTHER` with the root
  element's name, or the file extension for a file that is not XML. Before,
  every descriptive file was labelled EAD.
- **Schema-validated output.** Every kind of package the tool makes has
  been validated against the METS, xlink and DILCIS schemas the METS
  points at, as part of the project's automated tests. All of them pass.
  (The tests and the schema copies live in the development repository,
  not in this download.)

## What's new in 1.0.0-beta.2 (unpublished, included here)

These fixes to the generated METS.xml come from beta feedback and a check
against the published E-ARK schemas:

- `xsi:schemaLocation` is now set, using the schema locations from the
  official E-ARK SIP METS profile v2.1.0, so validators can find the schemas.
- Administrative metadata is written as a single `amdSec`, with `techMD`
  before `digiprovMD`, as the METS schema requires.
- The `rep_1` structMap div no longer carries an `ADMID` pointing at
  package-level preservation metadata.
- CONTENTINFORMATIONTYPE `OTHER`: the custom value now goes into
  `csip:OTHERCONTENTINFORMATIONTYPE`, and `csip:CONTENTINFORMATIONTYPE`
  stays `OTHER`. Previously the custom value replaced `OTHER`, which the
  CSIP schema rejects. TYPE `Other` works the same way: TYPE stays `Other`
  and the custom value goes into `csip:OTHERTYPE`.
- Each descriptive metadata file gets its own `dmdSec` (METS allows one
  `mdRef` per section), and metadata-only packages no longer get an empty,
  invalid `fileSec`.
- An unused `xmlns:ext` namespace declaration is removed.

Other fixes:

- Files whose names differ only in case, such as `Report.txt` and
  `report.txt`, no longer overwrite each other on Windows.
- Folder names are converted to ASCII like file names, so spaces become
  underscores. Folders that differ only in case are merged under one
  spelling, so every METS link matches the package.
- If package generation fails, the error is now shown and Generate is
  re-enabled. Previously the window froze.
- The agent ID-type fields are now fixed dropdowns.
- Safer file names. Some Unicode characters turn into path characters when
  converted to ASCII: a fullwidth `：` becomes `:`, and `‥` becomes `..`.
  Such names could previously write outside the package or produce an
  empty file. They are now replaced with `_`, as are `#` and `%`, which
  break METS links. Reserved Windows names such as `CON` are made safe.
- The tool never writes outside the package and never overwrites an
  existing file or package. If generation fails partway, the incomplete
  output is removed.
- If the exe's folder is read-only (for example a network share), the log
  file goes to `%LOCALAPPDATA%\EarkSipCreator\` or the temp folder instead
  of stopping the app from starting.

---

## Quick Start

### Windows (no install needed)

Download `EarkSipCreator.exe` from [Releases](../../releases) and run it.

### From source

```bash
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/Mac

pip install -r requirements.txt
python app.py
```

---

## Usage

1. **METS Header** — set LABEL, TYPE, CONTENTINFORMATIONTYPE, RECORDSTATUS
2. **Agents** — define Archivist, Creator, and System (software) agents
3. **Alt Record IDs** — enter SUBMISSIONAGREEMENT (required) and optional reference codes
4. **File Selection** — add files/folders for each category:
   - Schemas, Representations, Representation Metadata
   - Descriptive Metadata, Preservation Metadata, Documentation
5. **Output** — pick a destination folder, optionally create a ZIP
6. Click **Generate SIP Package**

A `test_data/` folder is included with sample files for all categories so you can try it immediately.

**Log file.** The program writes `eark_sip_creator.log` next to the exe, or in `%LOCALAPPDATA%\EarkSipCreator\` or the temp folder if that folder is read-only. It holds the most recent run only and is replaced the next time the program starts, so after an error, copy it before starting the program again. The command line logs to stderr instead: `python cli.py job.json 2> run.log` keeps it.

### Output structure

```
IP_20250115T143022/
├── METS.xml
├── schemas/
├── metadata/
│   ├── descriptive/
│   ├── other/
│   └── preservation/
├── representations/
│   └── rep_1/
│       ├── data/
│       └── metadata/
└── documentation/
```

---

## Headless use

Since 1.1.0 the tool also runs without the GUI, from a job file that
mirrors the form. This needs Python with `requirements.txt` installed;
there is no console exe.

```bash
python cli.py my_archive.job.json
```

`job.example.json` shows every key with placeholder values and points at
`test_data/`; create an `output` folder next to it first, because the
output folder must exist, as in the GUI. Name real job files
`<name>.job.json`, which the included `.gitignore` keeps out of git.
Omitted keys take the GUI's defaults. Relative paths are resolved against
the job file's folder, not the working directory. The file is UTF-8; a
byte order mark from Notepad is fine.

| Exit code | Meaning | stdout |
|---|---|---|
| 0 | Package created, no warnings | The package path, one line |
| 1 | Invalid job: unreadable file, unknown key, wrong type, or validation errors (listed on stderr) | Nothing |
| 2 | Generation failed (details on stderr) | Nothing |
| 3 | Package created, with warnings, for example a listed path that does not exist, or a listed folder with no files | The package path, one line |

Only the package path goes to stdout, so a script can capture it. Both
stdout and stderr are UTF-8.

From Python:

```python
from sip_job import load_job, run_job

job = load_job("my_archive.job.json")
package_path, warnings = run_job(job)
```

---

## Architecture

| Module | Purpose |
|--------|---------|
| `app.py` | customtkinter GUI and entry point |
| `cli.py` | Command-line entry point for headless use |
| `sip_job.py` | Job model, job-file loading, validation and the generate pipeline shared by the GUI and the CLI |
| `eark_core.py` | File collection, metadata gathering, SHA-256 hashing, filename normalization |
| `mets_builder.py` | METS XML generation (lxml, pure functions + dataclasses) |
| `package_assembler.py` | Folder structure creation, file copying, optional ZIP |

All modules are independently testable. Only `app.py` imports the GUI toolkit; the others never do.

---

## Building the .exe

```bash
pyinstaller EarkSipCreator.spec --noconfirm
```

Output: `dist/EarkSipCreator.exe`

---

## Standards

- [E-ARK SIP v2.1.0](https://earksip.dilcis.eu/)
- [E-ARK CSIP](https://earkcsip.dilcis.eu/)

## Dependencies

- Python 3.10+
- lxml
- customtkinter
- PyInstaller (build only)
