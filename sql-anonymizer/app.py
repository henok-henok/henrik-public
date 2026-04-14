"""SQL Anonymizer — Streamlit web application.

Anonymizes SQL code for safe sharing with LLMs. All processing runs locally.
"""

import json
import logging
from collections import OrderedDict
from pathlib import Path

import streamlit as st

from sql_module import anonymize_sql, deanonymize_sql, DIALECTS
from sp_extended_property import deanonymize_extended_properties
from search_replace_module import apply_manual_replacements

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

LOG_FILE = Path(__file__).parent / "sql_anonymizer.log"


def _setup_file_logging():
    """Configure file logging. Truncates the log on first call (app startup).

    Guards against adding duplicate handlers on Streamlit reruns.
    """
    root_logger = logging.getLogger()

    # Check if we already added our file handler
    for handler in root_logger.handlers:
        if isinstance(handler, logging.FileHandler) and handler.name == "sql_anon_file":
            return

    file_handler = logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8")
    file_handler.name = "sql_anon_file"
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    root_logger.addHandler(file_handler)
    root_logger.setLevel(logging.DEBUG)

    # Keep console output at INFO to avoid debug noise from Streamlit internals
    for h in root_logger.handlers:
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
            h.setLevel(logging.INFO)

    # Captures Python warnings.warn() calls (e.g., from third-party libraries)
    # Note: sqlglot logs via its own logger, which propagates to root automatically
    logging.captureWarnings(True)

    # Suppress sqlglot's internal parse diagnostics — they are noise.
    # sqlglot logs ERROR/WARNING for every parse quirk it recovers from internally.
    # Our code already handles all cases via the regex fallback, so these add no value.
    logging.getLogger("sqlglot").setLevel(logging.CRITICAL)

    logger.info("SQL Anonymizer started")


# --- Built-in example SQL ---
EXAMPLE_SQL_PATH = Path(__file__).parent / "example_demo.sql"


def _load_example_sql():
    """Load the example SQL from the external file."""
    try:
        return EXAMPLE_SQL_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "-- example_demo.sql not found"
    except Exception as e:
        return f"-- Failed to load example: {e}"

# Mapping section display order and labels
SECTION_LABELS = OrderedDict([
    ("tables_ctes", "Tables & CTEs"),
    ("columns", "Columns"),
    ("aliases", "Aliases"),
    ("schemas", "Schemas"),
    ("databases", "Databases"),
    ("procedures", "Procedures"),
    ("functions", "Functions"),
    ("string_literals_variables", "String Literals (Variables)"),
    ("string_literals_other", "String Literals (Other)"),
    ("comments", "Comments"),
    ("manual_replacements", "Manual Replacements"),
])


ENCODINGS = ["Auto-detect", "UTF-8", "Windows-1252 (cp1252)", "Latin-1 (iso-8859-1)"]

ENCODING_MAP = {
    "UTF-8": "utf-8-sig",
    "Windows-1252 (cp1252)": "cp1252",
    "Latin-1 (iso-8859-1)": "latin-1",
}


def _read_sql_file(uploaded_file, encoding="Auto-detect"):
    """Read an uploaded SQL file with the selected encoding."""
    raw = uploaded_file.read()
    if encoding != "Auto-detect":
        enc = ENCODING_MAP.get(encoding, "utf-8-sig")
        return raw.decode(enc, errors="replace")
    # Auto-detect: try encodings in order
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, ValueError):
            continue
    return raw.decode("latin-1", errors="replace")


def _mapping_to_json(mapping):
    """Convert mapping to JSON string for download."""
    # Convert OrderedDicts to regular dicts for JSON serialization
    serializable = {}
    for key, value in mapping.items():
        if isinstance(value, dict):
            serializable[key] = dict(value)
        else:
            serializable[key] = value
    return json.dumps(serializable, indent=2, ensure_ascii=False)


def _json_to_mapping(json_str):
    """Parse JSON string into mapping OrderedDict."""
    data = json.loads(json_str)
    mapping = OrderedDict()
    for key, value in data.items():
        if isinstance(value, dict):
            mapping[key] = OrderedDict(
                (k, dict(v) if isinstance(v, dict) else v) for k, v in value.items()
            )
        else:
            mapping[key] = value
    return mapping


def _build_quick_reference_text(mapping):
    """Build a compact text block of checked mapping entries, grouped by section."""
    lines = []
    for section_key, section_label in SECTION_LABELS.items():
        entries = mapping.get(section_key, {})
        if not isinstance(entries, dict):
            continue
        checked = [
            (info.get("anonymized", ""), orig)
            for orig, info in entries.items()
            if isinstance(info, dict) and info.get("checked", True) and info.get("anonymized")
        ]
        if not checked:
            continue
        if lines:
            lines.append("")
        lines.append(section_label)
        for anon_name, orig in checked:
            lines.append(f"  {anon_name} = {orig}")
    return "\n".join(lines) if lines else "No items anonymized"


def _render_quick_reference(mapping):
    """Render the Quick Reference collapsible panel."""
    if not mapping:
        return
    text = _build_quick_reference_text(mapping)
    with st.expander("Quick Reference", expanded=False):
        st.code(text, language=None)


def main():
    if "logging_initialized" not in st.session_state:
        _setup_file_logging()
        st.session_state["logging_initialized"] = True
    st.set_page_config(page_title="SQL Anonymizer", layout="wide")
    st.title("SQL Anonymizer")

    st.markdown(
        """
        <style>
        /* Tab nav bar only — scoped to tab-list to avoid hitting buttons in tab panels */
        .stTabs [data-baseweb="tab-list"] [data-baseweb="tab"],
        .stTabs [data-baseweb="tab-list"] button,
        .stTabs [data-baseweb="tab-list"] button span {
            font-size: 1.2rem !important;
        }
        /* Output area text — slight increase from Streamlit default (~0.875rem) */
        .stMarkdown p, .stMarkdown li, .stMarkdown code,
        .stCode, .stCode code {
            font-size: 1.01rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # --- Config bar ---
    config_cols = st.columns([2, 2, 2])
    with config_cols[0]:
        dialect = st.selectbox("SQL Dialect", DIALECTS, index=0)
    with config_cols[1]:
        comment_mode = st.radio("Comments", ["Anonymize", "Remove"], horizontal=True)
    with config_cols[2]:
        file_encoding = st.selectbox("File Encoding", ENCODINGS, index=0)
    string_mode = "Anonymize"

    # --- How to use ---
    with st.expander("How to use", expanded=False):
        st.markdown(
            "**Anonymize workflow**\n"
            "- Paste SQL in the text area (or upload `.sql` files) → select dialect and options → click **Anonymize**\n"
            "- Copy the anonymized output and paste into your LLM\n\n"
            "**De-anonymize workflow**\n"
            "- Switch to the **De-anonymize** tab → paste the LLM response → click **De-anonymize**\n"
            "- Copy the restored SQL\n\n"
            "**Mapping**\n"
            "- After anonymizing, review the mapping table: toggle items on/off, rename anonymized values, or add manual find/replace entries\n"
            "- Use **Download mapping JSON** to save the mapping and **Load mapping JSON** to reuse it in future sessions\n\n"
            "**Config options**\n"
            f"- **SQL Dialect**: select the dialect that matches your SQL (T-SQL by default, {len(DIALECTS)} options)\n"
            "- **Comments**: Anonymize (replace comment text) or Remove (strip all comments)\n"
            "- **String literals**: always extracted and shown in the mapping — toggle individually\n"
            "- **File Encoding**: Auto-detect works for most files; use Windows-1252 for SQL Server exports with special characters"
        )

    # --- Tabs ---
    tab_anon, tab_deanon = st.tabs(["Anonymize", "De-anonymize"])

    # === Anonymize Tab ===
    with tab_anon:
        _render_anonymize_tab(dialect, comment_mode, string_mode, file_encoding)

    # === De-anonymize Tab ===
    with tab_deanon:
        _render_deanonymize_tab()


def _render_anonymize_tab(dialect, comment_mode, string_mode, file_encoding="Auto-detect"):
    """Render the Anonymize tab content."""

    # --- JSON mapping bar ---
    json_col1, json_col2 = st.columns([1, 1])
    with json_col1:
        json_file = st.file_uploader("Load mapping JSON", type=["json"], key="load_json_anon")
        if json_file is not None:
            if st.session_state.get("json_file_name_anon") != json_file.name:
                try:
                    json_content = json_file.read().decode("utf-8")
                    st.session_state["pending_json_anon"] = _json_to_mapping(json_content)
                    st.session_state["json_file_name_anon"] = json_file.name
                    st.session_state.pop("json_loaded_anon", None)
                except Exception as e:
                    logger.exception("Failed to parse mapping JSON")
                    st.error(f"Failed to parse JSON: {e}")
                    st.session_state.pop("pending_json_anon", None)

            if "pending_json_anon" in st.session_state and "json_loaded_anon" not in st.session_state:
                exp_col, ovr_col = st.columns([1, 1])
                with exp_col:
                    if st.button("Expand", type="primary", key="json_expand_anon"):
                        existing = st.session_state.get("existing_mapping", OrderedDict())
                        loaded = st.session_state["pending_json_anon"]
                        merged = OrderedDict(existing)
                        for section, entries in loaded.items():
                            if section in merged and isinstance(merged[section], dict):
                                for k, v in entries.items():
                                    if k not in merged[section]:
                                        merged[section][k] = v
                            else:
                                merged[section] = entries
                        st.session_state["existing_mapping"] = merged
                        st.session_state["json_loaded_anon"] = True
                        st.rerun()
                with ovr_col:
                    if st.button("Overwrite", type="primary", key="json_overwrite_anon"):
                        st.session_state["existing_mapping"] = st.session_state["pending_json_anon"]
                        st.session_state["json_loaded_anon"] = True
                        st.rerun()
            elif "json_loaded_anon" in st.session_state:
                st.success("Mapping loaded")

    with json_col2:
        if "mapping" in st.session_state:
            json_str = _mapping_to_json(st.session_state["mapping"])
            st.download_button(
                "Download mapping JSON",
                data=json_str,
                file_name="sql_mapping.json",
                mime="application/json",
                type="primary",
            )

    st.divider()

    # --- Input area ---
    input_col1, input_col2 = st.columns([1, 1])

    with input_col1:
        # File uploader
        uploaded_files = st.file_uploader(
            "Upload .sql files",
            type=["sql"],
            accept_multiple_files=True,
            key="sql_files",
        )

        # Handle file uploads — concatenate into text area
        current_file_names = sorted(f.name for f in uploaded_files) if uploaded_files else []
        prev_file_names = st.session_state.get("loaded_file_names", [])
        if uploaded_files and current_file_names != prev_file_names:
            parts = []
            for f in uploaded_files:
                parts.append(f"-- === File: {f.name} ===")
                parts.append(_read_sql_file(f, file_encoding))
            st.session_state["sql_input"] = "\n".join(parts)
            st.session_state["sql_input_area"] = st.session_state["sql_input"]
            st.session_state["files_loaded"] = True
            st.session_state["loaded_file_names"] = current_file_names
            for key in ["mapping", "anonymized_sql"]:
                st.session_state.pop(key, None)

    with input_col2:
        if st.button("Load example", type="primary"):
            st.session_state["sql_input_area"] = _load_example_sql()
            # Clear previous results
            for key in ["mapping", "anonymized_sql", "files_loaded", "loaded_file_names", "json_loaded_anon"]:
                st.session_state.pop(key, None)
            st.rerun()

    # Initialize widget state if not set (first load or after file upload)
    if "sql_input_area" not in st.session_state and "sql_input" in st.session_state:
        st.session_state["sql_input_area"] = st.session_state["sql_input"]

    sql_input = st.text_area(
        "SQL Input",
        height=300,
        key="sql_input_area",
        placeholder="Paste SQL here or upload .sql files above...",
    )

    if sql_input.strip():
        with st.expander("Show formatted", expanded=False):
            st.code(sql_input, language="sql")

    # --- Anonymize button ---
    if st.button("Anonymize", disabled=not sql_input.strip(), type="primary"):
        existing = st.session_state.get("existing_mapping", None)
        try:
            anonymized, mapping = anonymize_sql(
                sql_input, dialect, existing, comment_mode, string_mode
            )
            # Apply any pre-loaded manual replacements immediately
            manual = (existing or {}).get("manual_replacements", {})
            if manual:
                reps = {
                    orig: info["anonymized"]
                    for orig, info in manual.items()
                    if isinstance(info, dict) and info.get("checked", True)
                }
                anonymized = apply_manual_replacements(anonymized, reps)
            st.session_state["mapping"] = mapping
            st.session_state["anonymized_sql"] = anonymized
            st.session_state["original_sql"] = sql_input
            st.session_state["dialect"] = dialect
            st.session_state["comment_mode"] = comment_mode
            st.session_state["string_mode"] = string_mode
            st.rerun()
        except Exception as e:
            logger.exception("Anonymization failed")
            st.error(f"Anonymization failed: {e}")

    # --- Results (after anonymize) ---
    if "mapping" in st.session_state and "anonymized_sql" in st.session_state:
        st.divider()
        _render_mapping_and_output()


def _render_mapping_panel(mapping, updated_mapping):
    """Render original SQL expander, mapping table, and manual replacements.

    Mutates updated_mapping in place. Returns whether re-anonymize was clicked.
    """
    with st.expander("Original SQL", expanded=False):
        st.code(st.session_state.get("original_sql", ""), language="sql")

    _render_quick_reference(mapping)

    # Mapping header with re-anonymize button
    header_col, btn_col = st.columns([3, 1])
    with header_col:
        st.subheader("Mapping")
    with btn_col:
        re_anon_clicked = st.button("Re-anonymize", key="re_anonymize_btn", type="primary", use_container_width=True)

    for section_key, section_label in SECTION_LABELS.items():
        entries = mapping.get(section_key, {})
        if not isinstance(entries, dict) or not entries:
            continue

        # Section header with bulk toggle button
        if section_key == "manual_replacements":
            st.markdown(f"**{section_label}**")
        else:
            all_checked = all(
                st.session_state.get(f"chk_{section_key}_{orig}", info.get("checked", True))
                for orig, info in entries.items()
            )
            hdr_cols = st.columns([4, 1])
            with hdr_cols[0]:
                st.markdown(f"**{section_label}**")
            with hdr_cols[1]:
                label = "Deselect All" if all_checked else "Select All"
                if st.button(label, key=f"toggle_{section_key}", type="primary", use_container_width=True):
                    new_val = not all_checked
                    for orig in entries:
                        st.session_state[f"chk_{section_key}_{orig}"] = new_val
                    st.rerun()

        section_data = OrderedDict()
        for original, info in entries.items():
            cols = st.columns([0.5, 3, 3])
            with cols[0]:
                key = f"chk_{section_key}_{original}"
                checkbox_kwargs = {
                    "label": "##",
                    "key": key,
                    "label_visibility": "collapsed",
                }
                if key not in st.session_state:
                    checkbox_kwargs["value"] = info.get("checked", True)
                checked = st.checkbox(**checkbox_kwargs)
            with cols[1]:
                display = original[:80] + "..." if len(original) > 80 else original
                st.text_input(
                    "Original",
                    value=display,
                    disabled=True,
                    key=f"orig_{section_key}_{original}",
                    label_visibility="collapsed",
                )
            with cols[2]:
                new_anon = st.text_input(
                    "Anonymized",
                    value=info.get("anonymized", ""),
                    key=f"anon_{section_key}_{original}",
                    label_visibility="collapsed",
                )

            section_data[original] = {
                "anonymized": new_anon,
                "checked": checked,
            }

        updated_mapping[section_key] = section_data

    # Manual replacement inputs
    st.markdown("**Add Manual Replacement**")
    find_col, replace_col, add_col = st.columns([2, 2, 1])
    with find_col:
        find_text = st.text_input("Find", key="manual_find", label_visibility="collapsed", placeholder="Find...")
    with replace_col:
        replace_text = st.text_input("Replace", key="manual_replace", label_visibility="collapsed", placeholder="Replace with...")
    with add_col:
        if st.button("Add", key="add_manual", type="primary"):
            if find_text and replace_text:
                if "manual_replacements" not in updated_mapping:
                    updated_mapping["manual_replacements"] = OrderedDict()
                updated_mapping["manual_replacements"][find_text] = {
                    "anonymized": replace_text,
                    "checked": True,
                }
                for key in ("dialect", "comment_mode", "string_mode"):
                    if key in mapping:
                        updated_mapping[key] = mapping[key]
                st.session_state["mapping"] = updated_mapping
                st.rerun()

    # Preserve metadata
    for key in ("dialect", "comment_mode", "string_mode"):
        if key in mapping:
            updated_mapping[key] = mapping[key]

    return re_anon_clicked


def _render_mapping_and_output():
    """Render the mapping editor and anonymized output.

    Default: side-by-side [left: anonymized SQL, right: original SQL + mapping].
    Expanded: full-width anonymized SQL with mapping panel in a collapsed expander below.
    """
    mapping = st.session_state["mapping"]
    updated_mapping = OrderedDict()
    is_expanded = st.session_state.get("anon_panel_expanded", False)

    if is_expanded:
        # --- Full-width layout ---
        hdr_col, toggle_col = st.columns([5, 1])
        with hdr_col:
            st.subheader("Anonymized SQL")
        with toggle_col:
            if st.button("Side by side", key="anon_collapse_btn"):
                st.session_state["anon_panel_expanded"] = False
                st.rerun()
        st.code(st.session_state["anonymized_sql"], language="sql")

        with st.expander("Mapping & Original SQL", expanded=False):
            re_anon_clicked = _render_mapping_panel(mapping, updated_mapping)
    else:
        # --- Side-by-side layout (default) ---
        left_col, right_col = st.columns([1, 1])

        with right_col:
            re_anon_clicked = _render_mapping_panel(mapping, updated_mapping)

        with left_col:
            hdr_col, toggle_col = st.columns([3, 1])
            with hdr_col:
                st.subheader("Anonymized SQL")
            with toggle_col:
                if st.button("Full width", key="anon_expand_btn"):
                    st.session_state["anon_panel_expanded"] = True
                    st.rerun()
            st.code(st.session_state["anonymized_sql"], language="sql")

    # Handle re-anonymize (after both sections are built)
    if re_anon_clicked:
        st.session_state["mapping"] = updated_mapping
        original = st.session_state.get("original_sql", "")
        d = st.session_state.get("dialect", "T-SQL")
        cm = st.session_state.get("comment_mode", "Anonymize")
        sm = st.session_state.get("string_mode", "Anonymize")

        try:
            anonymized, new_mapping = anonymize_sql(original, d, updated_mapping, cm, sm)

            manual = updated_mapping.get("manual_replacements", {})
            if manual:
                replacements = {
                    orig: info["anonymized"]
                    for orig, info in manual.items()
                    if isinstance(info, dict) and info.get("checked", True)
                }
                anonymized = apply_manual_replacements(anonymized, replacements)
                new_mapping["manual_replacements"] = manual

            st.session_state["mapping"] = new_mapping
            st.session_state["anonymized_sql"] = anonymized
            st.rerun()
        except Exception as e:
            logger.exception("Re-anonymization failed")
            st.error(f"Re-anonymization failed: {e}")


def _render_deanonymize_tab():
    """Render the De-anonymize tab content."""

    # JSON bar for de-anonymize
    json_file = st.file_uploader("Load mapping JSON", type=["json"], key="load_json_deanon")
    if json_file is not None:
        if st.session_state.get("json_file_name_deanon") != json_file.name:
            try:
                json_content = json_file.read().decode("utf-8")
                st.session_state["deanon_mapping"] = _json_to_mapping(json_content)
                st.session_state["json_file_name_deanon"] = json_file.name
                st.session_state["json_loaded_deanon"] = True
                st.session_state.pop("deanonymized_sql", None)
                st.success("Mapping loaded for de-anonymization")
            except Exception as e:
                logger.exception("Failed to load mapping JSON for de-anonymization")
                st.error(f"Failed to load JSON: {e}")

    # Use session mapping if available
    deanon_mapping = st.session_state.get("deanon_mapping", st.session_state.get("mapping", None))

    if deanon_mapping:
        json_str = _mapping_to_json(deanon_mapping)
        st.download_button(
            "Download mapping JSON",
            data=json_str,
            file_name="sql_mapping.json",
            mime="application/json",
            type="primary",
            key="download_deanon_json",
        )

    st.divider()

    anon_input = st.text_area(
        "Paste anonymized SQL",
        height=300,
        key="deanon_input",
        placeholder="Paste anonymized SQL here...",
    )

    if anon_input.strip():
        with st.expander("Show formatted", expanded=False):
            st.code(anon_input, language="sql")

    if deanon_mapping is None:
        st.warning("No mapping available. Load a JSON mapping file or anonymize SQL first.")

    btn_col, chk_col = st.columns([2, 3])
    with btn_col:
        de_anon_clicked = st.button("De-anonymize", disabled=not anon_input.strip() or deanon_mapping is None, type="primary")
    with chk_col:
        st.checkbox("Render as Markdown", value=False, key="render_as_markdown")
    if de_anon_clicked:
        try:
            # Reverse the mapping
            result = deanonymize_sql(anon_input, deanon_mapping)

            # Also reverse sp_addextendedproperty names
            result = deanonymize_extended_properties(result, deanon_mapping)

            # Reverse manual replacements
            manual = deanon_mapping.get("manual_replacements", {})
            if manual:
                reverse_replacements = {
                    info["anonymized"]: orig
                    for orig, info in manual.items()
                    if isinstance(info, dict) and info.get("checked", True)
                }
                result = apply_manual_replacements(result, reverse_replacements)

            st.session_state["deanonymized_sql"] = result
            st.rerun()
        except Exception as e:
            logger.exception("De-anonymization failed")
            st.error(f"De-anonymization failed: {e}")

    if "deanonymized_sql" in st.session_state:
        is_expanded = st.session_state.get("deanon_panel_expanded", False)

        render_as_markdown = st.session_state.get("render_as_markdown", False)

        if is_expanded:
            hdr_col, toggle_col = st.columns([5, 1])
            with hdr_col:
                st.subheader("De-anonymized SQL")
            with toggle_col:
                if st.button("Side by side", key="deanon_collapse_btn"):
                    st.session_state["deanon_panel_expanded"] = False
                    st.rerun()
            result = st.session_state["deanonymized_sql"]
            if render_as_markdown:
                st.markdown(result, unsafe_allow_html=False)
            else:
                st.code(result, language="sql")
            _render_quick_reference(deanon_mapping)
            with st.expander("Anonymized SQL", expanded=False):
                st.code(anon_input, language="sql")
        else:
            left_col, right_col = st.columns([1, 1])
            with left_col:
                hdr_col, toggle_col = st.columns([3, 1])
                with hdr_col:
                    st.subheader("De-anonymized SQL")
                with toggle_col:
                    if st.button("Full width", key="deanon_expand_btn"):
                        st.session_state["deanon_panel_expanded"] = True
                        st.rerun()
                result = st.session_state["deanonymized_sql"]
                if render_as_markdown:
                    st.markdown(result, unsafe_allow_html=False)
                else:
                    st.code(result, language="sql")
            with right_col:
                with st.expander("Anonymized SQL", expanded=False):
                    st.code(anon_input, language="sql")
                _render_quick_reference(deanon_mapping)


if __name__ == "__main__":
    main()
