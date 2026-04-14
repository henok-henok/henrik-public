# E-ARK SIP Creator

Desktop application for creating E-ARK SIP packages conforming to [E-ARK SIP v2.1.0](https://earksip.dilcis.eu/).

Fill in METS header values, select files through the GUI, and generate a standards-compliant SIP package with SHA-256 checksums and normalized filenames.

**Version:** 1.0.0-beta.1
**Authors:** Henrik Hellberg Lizama & Axel Wennerlund
**License:** MIT

> **Beta release** — feature-complete but intended for early testers. Please report any bugs or issues you find.

---

## Quick Start

### Windows (no install needed)

Download `EarkSipCreator.exe` from [Releases](../../../releases) and run it.

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

### Output structure

```
IP_20250115T143022/
├── METS.xml
├── schemas/
├── metadata/
│   ├── descriptive/
│   └── preservation/
├── representations/
│   └── rep_1/
│       ├── data/
│       └── metadata/
└── documentation/
```

---

## Architecture

| Module | Purpose |
|--------|---------|
| `app.py` | customtkinter GUI and entry point |
| `eark_core.py` | File collection, metadata gathering, SHA-256 hashing, filename normalization |
| `mets_builder.py` | METS XML generation (lxml, pure functions + dataclasses) |
| `package_assembler.py` | Folder structure creation, file copying, optional ZIP |

All modules are independently testable. The GUI imports the other three but they have no dependency on it.

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
