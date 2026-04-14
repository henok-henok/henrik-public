# SQL Anonymizer

**v1.5.3** | Author: Henrik Hellberg Lizama | MIT License

Anonymize SQL code for safe sharing with LLMs. Runs completely offline — no API calls, no telemetry, no external resources. No data ever leaves your machine.

Download from the [Releases](../../../releases) page, or clone the repo.

---

## Quick Start

1. Double-click `Install.bat` (first time only)
2. Double-click `Start SQL Anonymizer.bat`
3. Paste SQL or upload `.sql` files
4. Click **Anonymize**
5. Copy the anonymized SQL and paste into your LLM

### Anaconda / Miniconda users

If you use conda instead of pip:

1. Double-click `Install (Conda).bat`
2. Double-click `Start SQL Anonymizer (Conda).bat`

## How It Works

### Anonymization
The tool parses SQL using [sqlglot](https://github.com/tobymao/sqlglot) to identify database objects:

| Object Type | Anonymized As |
|---|---|
| Tables & CTEs | `Table_1`, `Table_2`, ... |
| Columns | `Column_1`, `Column_2`, ... |
| Table aliases | `a`, `b`, `c`, ... |
| Column aliases | `Alias_1`, `Alias_2`, ... |
| Schemas | `Schema_1`, `Schema_2`, ... |
| Databases | `Database_1`, `Database_2`, ... |
| Procedures | `Proc_1`, `Proc_2`, ... |
| Functions | `Func_1`, `Func_2`, ... |
| String literals (variables) | `VarValue_1`, `VarValue_2`, ... |
| String literals (other) | `Value_1`, `Value_2`, ... |
| Comments | `Comment_1`, `Comment_2`, ... |

Identifiers are consistent across all statements — the same table name always maps to the same anonymized name.

### Mapping Editor
After anonymizing, a mapping table shows every replacement. You can:
- **Uncheck** items to keep them as-is (e.g., `dbo` schema is unchecked by default)
- **Edit** anonymized names to something more descriptive
- **Add manual replacements** using the find/replace fields
- **Re-anonymize** to apply your changes

### Quick Reference
After anonymizing, a collapsible "Quick Reference" panel shows a compact cheat sheet of all checked mapping entries: `AnonymizedName = OriginalName`, grouped by section. Use the built-in copy button to paste it into a separate window while chatting with an LLM. Available in both Anonymize and De-anonymize tabs.

### JSON Mapping
Save the mapping as JSON to reuse later. Load it before anonymizing — choose **Expand** to add new identifiers while keeping existing ones, or **Overwrite** to replace the mapping entirely. The JSON is also used for de-anonymization.

### De-anonymize
Paste anonymized SQL (e.g., an LLM's response) into the De-anonymize tab. It reverses the mapping to restore original names. Use the **Render as Markdown** checkbox to switch the output between raw text and rendered markdown — useful when the LLM response contains headings, lists, or fenced code blocks.

### Multiple Files
Upload multiple `.sql` files — they're concatenated with `-- === File: name.sql ===` delimiters and anonymized together with consistent naming.

### Comment Modes
- **Anonymize** (default) — replace comment text with `Comment_1`, etc. Multi-line comments preserve line count for side-by-side comparison.
- **Remove** — replace comments with empty lines, preserving line count for side-by-side comparison.

### String Literals
String literals are always extracted and shown in the mapping editor in two sections:
- **String Literals (Variables)** — from `SET @Var = 'value'`, `DECLARE @Var TYPE = 'value'`, and `EXEC proc @Param = 'value'` assignments. Unchecked by default.
- **String Literals (Other)** — all other string literals. Unchecked by default.

Individual strings can be checked/unchecked in the mapping editor.

### File Encoding
When uploading `.sql` files, select the encoding in the config bar:
- **Auto-detect** (default) — tries UTF-8, then Windows-1252, then Latin-1
- **UTF-8** — for UTF-8 encoded files
- **Windows-1252 (cp1252)** — common for SQL files exported from SQL Server Management Studio on Windows (handles Swedish characters å, ä, ö)
- **Latin-1** — ISO 8859-1 fallback

## Technical Notes

### Design Decisions
- **AST extraction + string replacement**: The tool uses sqlglot's AST to *identify* objects, then does string replacement on the original SQL. This preserves exact formatting, whitespace, and syntax that sqlglot might not roundtrip perfectly.
- **GO splitting**: SQL is split on `GO` delimiters before parsing (sqlglot doesn't handle GO).
- **Procedure body parsing**: CREATE PROCEDURE blocks are detected, and the body is split into individual statements for parsing. This handles T-SQL constructs that sqlglot can't parse as a whole.
- **Regex fallback**: If sqlglot can't parse a statement, regex patterns extract procedure names, table references, and EXEC targets.
- **sp_addextendedproperty**: Handled separately with regex since these calls follow a predictable pattern.

### Offline by Design
The app is completely offline. Streamlit telemetry is disabled via `.streamlit/config.toml`. No network calls are made, no external resources are loaded. The only network activity is the local web server on `localhost:8501` that your browser connects to.

### Limitations
- Only anonymizes SQL identifiers — does not anonymize numeric values or dates in data
- CREATE PROCEDURE and some T-SQL-specific syntax falls back to regex (less complete extraction)
- No syntax validation (formatted preview available via "Show formatted" expander)
- Single user, local only
- If the same identifier appears with inconsistent casing (e.g., `Supplier_Name` vs `supplier_name`), both are treated as one identifier and de-anonymization restores only the first-seen casing; identifiers with consistent casing are unaffected

### Requirements
- Python 3.9+
- streamlit==1.54.0
- sqlglot==28.10.1

## License

MIT — see [LICENSE](LICENSE).
