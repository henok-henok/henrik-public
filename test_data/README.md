# Test Data for E-ARK SIP Creator

Sample files for testing the app. Use these folder paths in the GUI:

## How to use

1. Run the app (`python app.py` or `EarkSipCreator.exe`)
2. Fill in the header fields (see suggested values below)
3. Point each file selector to the matching folder:

| GUI Section              | Folder to select                         |
|--------------------------|------------------------------------------|
| Schemas                  | `test_data/schemas/`                     |
| Representations          | `test_data/representations/`             |
| Representation Metadata  | `test_data/representation_metadata/`     |
| Descriptive Metadata     | `test_data/descriptive_metadata/`        |
| Preservation Metadata    | `test_data/preservation_metadata/`       |
| Documentation            | `test_data/documentation/`               |

4. Pick an output folder (e.g. a temp directory)
5. Click **Generate SIP Package**

### Suggested header values

- **LABEL:** Test Archive Package
- **TYPE:** Datasets
- **CONTENTINFORMATIONTYPE:** citserms_v2_1
- **RECORDSTATUS:** TEST
- **ARCHIVIST name:** Test Organization AB
- **ARCHIVIST ID type:** ORG, value: 556000-0001
- **CREATOR name:** Municipal Archive
- **CREATOR ID type:** ORG, value: 200000-0002
- **SYSTEM name:** Test Database, version: 1.0
- **SUBMISSIONAGREEMENT:** SA-TEST-2024-001

### Testing subdirectories

The `representations/` folder contains a `subdir/` with a nested file.
Check **"Include subdirectories"** on the Representations selector to
verify that nested files are picked up and placed under
`representations/rep_1/data/subdir/` in the output.

## Folder structure

```
test_data/
├── README.md
├── schemas/
│   └── ERMS.xsd                    → Schemas selector
├── representations/
│   ├── sample_data.xml             → Representations selector
│   ├── report.csv
│   └── subdir/
│       └── nested_file.txt         → (with "Include subdirectories")
├── representation_metadata/
│   └── rep_metadata.xml            → Representation Metadata selector
├── descriptive_metadata/
│   └── ead_metadata.xml            → Descriptive Metadata selector
├── preservation_metadata/
│   └── premis.xml                  → Preservation Metadata selector
└── documentation/
    └── submission_agreement.txt    → Documentation selector
```
