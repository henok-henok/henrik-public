"""SQL parsing and anonymization module.

Uses sqlglot for AST-based identifier extraction, then performs
string replacement on the original SQL to preserve formatting.
"""

import logging
import re
from collections import OrderedDict

import sqlglot
from sqlglot import exp

from constants import SQL_KEYWORDS

logger = logging.getLogger(__name__)

# Dialect mapping for sqlglot
DIALECT_MAP = {
    "T-SQL": "tsql",
    "MySQL": "mysql",
    "PostgreSQL": "postgres",
    "Snowflake": "snowflake",
    "BigQuery": "bigquery",
    "Oracle": "oracle",
    "Spark SQL": "spark",
    "DuckDB": "duckdb",
    "SQLite": "sqlite",
    "Redshift": "redshift",
    "Databricks": "databricks",
    "Presto/Trino": "trino",
}

DIALECTS = list(DIALECT_MAP.keys())

# Compiled once at import time — used in parse_block to detect ALTER PROCEDURE blocks.
_PROC_RE = re.compile(
    r"(?:CREATE|ALTER)\s+(?:PROC(?:EDURE)?|FUNCTION)\b",
    re.IGNORECASE,
)

# Cursor statements that sqlglot misparsed as Alias nodes — skip AST for these.
_CURSOR_OP_RE = re.compile(
    r"^\s*(?:OPEN|CLOSE|FETCH|DEALLOCATE)\b",
    re.IGNORECASE,
)


def _is_keyword(name):
    """Check if a name is a SQL keyword that should not be extracted."""
    return name.upper() in SQL_KEYWORDS


def split_on_go(sql_text):
    """Split SQL text on GO delimiters (case-insensitive, own line)."""
    # GO must be on its own line, possibly with whitespace
    blocks = re.split(r"(?m)^\s*GO\s*$", sql_text, flags=re.IGNORECASE)
    # Filter out empty/whitespace-only blocks
    return [b for b in blocks if b.strip()]


def _extract_procedure_body(block):
    """Extract the body of a CREATE PROCEDURE/FUNCTION block (everything after AS).

    Assumes one CREATE PROC/FUNCTION per GO-delimited block (expected by convention;
    split_on_go reduces this risk but does not enforce it).
    """
    match = re.search(
        r"(?:CREATE|ALTER)\s+(?:PROC(?:EDURE)?|FUNCTION)\s+.*?\bAS\b\s*",
        block, re.IGNORECASE | re.DOTALL,
    )
    if match:
        return block[match.end():]
    return None


def _split_body_statements(body):
    """Split a procedure body into individual statements for parsing.

    Splits on T-SQL statement keywords that appear at the start of a line.
    """
    # Split on lines that start with a major statement keyword
    pattern = re.compile(
        r"(?m)^(?=\s*(?:DECLARE|SET|TRUNCATE|INSERT|SELECT|UPDATE|DELETE|"
        r"IF|BEGIN|END|EXEC|WHILE|RETURN|PRINT|RAISERROR|THROW|"
        r"OPEN|CLOSE|FETCH|DEALLOCATE|DROP)\b)",
        re.IGNORECASE,
    )
    parts = pattern.split(body)
    return [p for p in parts if p.strip()]


def parse_block(block, dialect):
    """Parse a single SQL block with sqlglot.

    Returns list of (ast, raw_text) tuples. If parsing fails or produces
    a Command node (unsupported syntax), the ast is None.
    For CREATE PROCEDURE blocks, extracts and re-parses the body statements.
    """
    results = []

    def _is_procedure_block(stmt):
        """Check if body extraction is needed: Command nodes or CREATE/ALTER PROCEDURE/FUNCTION."""
        if isinstance(stmt, exp.Command):
            return True
        if isinstance(stmt, exp.Create):
            kind = (stmt.args.get("kind") or "").upper()
            if kind in ("PROCEDURE", "FUNCTION"):
                return True
        # sqlglot may parse ALTER PROCEDURE as AlterTable or another node type;
        # fall back to a raw-text check on the block.
        if _PROC_RE.search(block):
            return True
        return False

    try:
        statements = sqlglot.parse(block, dialect=dialect, error_level=sqlglot.ErrorLevel.WARN)
        for stmt in statements:
            if stmt is None:
                continue
            if _is_procedure_block(stmt):
                # Try to extract and parse procedure body
                body = _extract_procedure_body(block)
                if body:
                    # Full block passed as unparsed so regex can extract the proc name.
                    # Regex patterns are anchored, so overlapping with sub-statements is harmless.
                    results.append((None, block))
                    # Split body into individual statements and parse each
                    sub_statements = _split_body_statements(body)
                    for sub in sub_statements:
                        # Cursor operations (OPEN/CLOSE/FETCH/DEALLOCATE) are misparsed by
                        # sqlglot as Alias nodes, extracting the cursor variable as a column
                        # alias. Skip AST for these and use regex fallback instead.
                        if _CURSOR_OP_RE.match(sub):
                            results.append((None, sub))
                            continue
                        try:
                            sub_parsed = sqlglot.parse(sub.strip(), dialect=dialect, error_level=sqlglot.ErrorLevel.WARN)
                            for sp in sub_parsed:
                                if sp is None:
                                    continue
                                if isinstance(sp, exp.Command):
                                    results.append((None, sub))
                                else:
                                    results.append((sp, sub))
                        except Exception as e:
                            logger.debug("Failed to parse procedure sub-statement (falling back to regex): %s", e)
                            results.append((None, sub))
                else:
                    results.append((None, block))
            else:
                results.append((stmt, block))
    except Exception as e:
        logger.warning("sqlglot parse failed for block: %s", e)
        results.append((None, block))

    if not results:
        results.append((None, block))
    return results


def _extract_from_ast(statements, dialect):
    """Extract identifiers from parsed AST statements.

    Returns dict with sets of identifiers per category.
    """
    tables = set()
    ctes = set()
    columns = set()
    table_aliases = {}  # alias -> table_name
    column_aliases = set()
    schemas = set()
    views = set()
    procedures = set()   # Intentionally not populated here; procedure/function
    functions = set()    # extraction is handled by _extract_from_regex instead.
    databases = set()

    for stmt, _raw in statements:
        if stmt is None:
            continue

        # Skip SET statements (ANSI_NULLS, QUOTED_IDENTIFIER, etc.)
        if isinstance(stmt, exp.Set):
            continue

        # Handle USE [database]
        if isinstance(stmt, exp.Use):
            for node in stmt.walk():
                if isinstance(node, exp.Table):
                    if node.name:
                        databases.add(node.name)
            continue

        # Detect statement type for context
        is_create_view = isinstance(stmt, exp.Create) and stmt.args.get("kind", "").upper() == "VIEW"

        for node in stmt.walk():
            if isinstance(node, exp.Table):
                name = node.name

                # Always extract schema/database even if table name is a keyword
                if node.db:
                    schemas.add(node.db)
                if node.catalog:
                    databases.add(node.catalog)

                if name and not _is_keyword(name):
                    if is_create_view and node == stmt.find(exp.Table):
                        views.add(name)
                    else:
                        tables.add(name)

                    # Table alias
                    if node.alias:
                        if node.alias in table_aliases and table_aliases[node.alias] != name:
                            logger.warning(
                                "Alias %r used for multiple tables (%r and %r); "
                                "only the last occurrence will be tracked.",
                                node.alias, table_aliases[node.alias], name,
                            )
                        table_aliases[node.alias] = name

            elif isinstance(node, exp.Column):
                if node.name and node.name != "*" and not _is_keyword(node.name):
                    columns.add(node.name)

            elif isinstance(node, exp.ColumnDef):
                if node.name and not _is_keyword(node.name):
                    columns.add(node.name)

            elif isinstance(node, exp.Alias):
                alias_name = node.alias
                if alias_name and not _is_keyword(alias_name):
                    column_aliases.add(alias_name)

            elif isinstance(node, exp.Schema) and isinstance(node.parent, exp.Insert):
                # INSERT INTO table (col1, col2, ...) — extract target columns.
                # sqlglot represents these as Identifier nodes under Schema.
                for col_expr in node.expressions:
                    col_name = col_expr.name if hasattr(col_expr, "name") else None
                    if col_name and not _is_keyword(col_name):
                        columns.add(col_name)

            elif isinstance(node, exp.CTE):
                # CTE alias name — only extract when the CTE body is a real SELECT.
                # When sqlglot misparsing INSERT INTO t WITH (TABLOCK) (col_list) as fake
                # CTEs, the column names appear as CTE aliases with no SELECT body.
                # In that case, treat the aliases as column names instead of CTE names.
                alias_node = node.args.get("alias")
                if not alias_node:
                    continue
                alias_name = alias_node.name if hasattr(alias_node, "name") else str(alias_node)
                if not alias_name:
                    continue
                if _is_keyword(alias_name):
                    continue
                if isinstance(node.this, exp.Query):
                    # Real CTE — add to ctes (Query covers Select, Union, Subquery)
                    ctes.add(alias_name)
                else:
                    # Fake CTE from INSERT WITH (hint) (col_list) misparse — treat as column
                    columns.add(alias_name)

    return {
        "tables": tables,
        "ctes": ctes,
        "columns": columns,
        "table_aliases": table_aliases,
        "column_aliases": column_aliases,
        "schemas": schemas,
        "views": views,
        "procedures": procedures,
        "functions": functions,
        "databases": databases,
    }


def _extract_from_regex(raw_text):
    """Regex fallback for blocks that sqlglot couldn't parse.

    Conservative extraction: only clearly identifiable object names.
    Avoids extracting from comments or string literals.
    """
    tables = set()
    schemas = set()
    procedures = set()
    functions = set()
    databases = set()
    views = set()

    def clean_id(s):
        return s.strip("[] \t\n")

    def _parse_dotted_name(full_name):
        """Parse a dotted name like [catalog].[schema].[name] into parts.

        Preserves empty parts (e.g. catalog..name has empty schema).
        """
        parts = [clean_id(p) for p in full_name.split(".")]
        return parts

    # CREATE/ALTER PROCEDURE [schema].[name]
    proc_match = re.search(
        r"(?:CREATE|ALTER)\s+PROC(?:EDURE)?\s+((?:\[?[\w]+\]?\.)*\[?[\w]+\]?)",
        raw_text, re.IGNORECASE,
    )
    if proc_match:
        parts = _parse_dotted_name(proc_match.group(1))
        if parts:
            procedures.add(parts[-1])
        if len(parts) >= 2:
            schemas.add(parts[-2])

    # CREATE FUNCTION [schema].[name]
    func_match = re.search(
        r"CREATE\s+FUNCTION\s+((?:\[?[\w]+\]?\.)*\[?[\w]+\]?)",
        raw_text, re.IGNORECASE,
    )
    if func_match:
        parts = _parse_dotted_name(func_match.group(1))
        if parts:
            functions.add(parts[-1])
        if len(parts) >= 2:
            schemas.add(parts[-2])

    # EXEC [catalog]..[proc] or EXEC [schema].[proc]
    # Pattern handles double dots (catalog..proc)
    # ^\s* anchors to line start intentionally — avoids false positives from
    # mid-line EXEC occurrences (rare in practice; the AST path handles those).
    for m in re.finditer(r"^\s*EXEC(?:UTE)?\s+((?:\[?[\w]+\]?\.\.?)*\[?[\w]+\]?)", raw_text, re.IGNORECASE | re.MULTILINE):
        full = m.group(1)
        if full.lower().startswith("sys."):
            continue
        parts = _parse_dotted_name(full)
        # Filter empty parts for counting but keep position info
        non_empty = [p for p in parts if p]
        if not non_empty or non_empty[-1].startswith("@"):
            continue
        procedures.add(non_empty[-1])
        # Detect catalog..proc pattern (has empty middle part)
        if ".." in full:
            databases.add(non_empty[0])
        elif len(non_empty) == 3:
            databases.add(non_empty[0])
            if non_empty[1]:
                schemas.add(non_empty[1])
        elif len(non_empty) == 2:
            schemas.add(non_empty[0])

    def _add_qualified_table(full_name, target_set):
        """Parse a qualified name and add parts to appropriate sets."""
        parts = _parse_dotted_name(full_name)
        non_empty = [p for p in parts if p]
        if non_empty:
            target_set.add(non_empty[-1])
        if ".." in full_name and len(non_empty) >= 2:
            databases.add(non_empty[0])
        elif len(non_empty) >= 3:
            databases.add(non_empty[0])
            schemas.add(non_empty[1])
        elif len(non_empty) == 2:
            schemas.add(non_empty[0])

    # FROM/JOIN/INTO table references (only clearly qualified names)
    for m in re.finditer(
        r"(?:FROM|JOIN)\s+((?:\[?[\w]+\]?\.)+\[?[\w]+\]?)",
        raw_text, re.IGNORECASE,
    ):
        _add_qualified_table(m.group(1), tables)

    # TRUNCATE TABLE / INSERT INTO / UPDATE with qualified names
    for m in re.finditer(
        r"(?:TRUNCATE\s+TABLE|INSERT\s+INTO|UPDATE)\s+((?:\[?[\w]+\]?\.)+\[?[\w]+\]?)",
        raw_text, re.IGNORECASE,
    ):
        _add_qualified_table(m.group(1), tables)

    # DROP TABLE [IF EXISTS] tablename (including temp tables with # prefix).
    # The # is stripped to match the name sqlglot extracts from AST (it strips # too),
    # so both paths produce the same entry in tables_ctes.
    for m in re.finditer(
        r"DROP\s+TABLE(?:\s+IF\s+EXISTS)?\s+(\[?#?[\w]+\]?)",
        raw_text, re.IGNORECASE,
    ):
        name = clean_id(m.group(1)).lstrip("#")
        if name and not _is_keyword(name):
            tables.add(name)

    # USE [database]
    use_match = re.search(r"USE\s+\[?([\w]+)\]?", raw_text, re.IGNORECASE)
    if use_match:
        databases.add(clean_id(use_match.group(1)))

    return {
        "tables": tables,
        "ctes": set(),
        "columns": set(),  # Don't extract columns from regex — too error-prone
        "table_aliases": {},
        "column_aliases": set(),
        "schemas": schemas,
        "views": views,
        "procedures": procedures,
        "functions": functions,
        "databases": databases,
    }


def _merge_extracted(base, addition):
    """Merge two extracted identifier dicts."""
    for key in base:
        if isinstance(base[key], set):
            base[key] |= addition.get(key, set())
        elif isinstance(base[key], dict):
            base[key].update(addition.get(key, {}))
    return base


def _letter_alias(idx):
    """Convert index to alias letter(s): 0-25 -> a-z, 26+ -> aa, ab, ..."""
    if idx < 26:
        return chr(ord("a") + idx)
    return chr(ord("a") + idx // 26 - 1) + chr(ord("a") + idx % 26)


def _build_mapping(extracted, existing_mapping=None):
    """Build anonymization mapping from extracted identifiers.

    Returns OrderedDict with sections. Each entry: {original: {anonymized: str, checked: bool}}
    """
    mapping = OrderedDict()

    if existing_mapping:
        # Migrate old 'string_literals' key to new split sections
        if "string_literals" in existing_mapping and isinstance(existing_mapping["string_literals"], dict):
            if "string_literals_other" not in existing_mapping:
                existing_mapping["string_literals_other"] = existing_mapping.pop("string_literals")
            else:
                existing_mapping.pop("string_literals", None)

        # Deep copy existing mapping
        for section, entries in existing_mapping.items():
            if section in ("dialect", "comment_mode", "string_mode"):
                continue
            mapping[section] = OrderedDict(
                (k, dict(v)) for k, v in entries.items()
            ) if isinstance(entries, dict) else entries

    def _next_counter(section, prefix):
        """Get next counter for a section prefix."""
        if section not in mapping:
            return 1
        existing_nums = []
        for v in mapping[section].values():
            anon = v.get("anonymized", "")
            if anon.startswith(prefix):
                try:
                    existing_nums.append(int(anon[len(prefix):]))
                except ValueError:
                    pass
        return max(existing_nums, default=0) + 1

    def _add_to_section(section, names, prefix, default_checked=True):
        if section not in mapping:
            mapping[section] = OrderedDict()
        counter = _next_counter(section, prefix)
        for name in sorted(names):
            if name not in mapping[section]:
                mapping[section][name] = {
                    "anonymized": f"{prefix}{counter}",
                    "checked": default_checked,
                }
                counter += 1

    # Tables & CTEs
    tables_and_ctes = extracted["tables"] | extracted["ctes"] | extracted["views"]
    _add_to_section("tables_ctes", tables_and_ctes, "Table_")

    # Columns
    _add_to_section("columns", extracted["columns"], "Column_")

    # Aliases - table aliases get single letters, column aliases get Alias_N
    section = "aliases"
    if section not in mapping:
        mapping[section] = OrderedDict()

    # Table aliases: a, b, c, ..., aa, ab, ...
    used_letters = set()
    for v in mapping[section].values():
        anon = v.get("anonymized", "")
        if len(anon) <= 2 and anon.isalpha():
            used_letters.add(anon)

    letter_idx = 0
    for alias in sorted(extracted["table_aliases"].keys()):
        if alias not in mapping[section]:
            while _letter_alias(letter_idx) in used_letters:
                letter_idx += 1
            anon = _letter_alias(letter_idx)
            mapping[section][alias] = {
                "anonymized": anon,
                "checked": True,
            }
            used_letters.add(anon)
            letter_idx += 1

    # Column aliases
    alias_counter = _next_counter(section, "Alias_")
    for alias in sorted(extracted["column_aliases"]):
        if alias in mapping[section]:
            # Collision with table alias — skip to avoid overwrite
            logger.debug("Column alias %r skipped — already exists as table alias", alias)
            continue
        mapping[section][alias] = {
            "anonymized": f"Alias_{alias_counter}",
            "checked": True,
        }
        alias_counter += 1

    # Schemas
    _add_to_section("schemas", extracted["schemas"], "Schema_")
    # Mark dbo as unchecked by default
    if "schemas" in mapping and "dbo" in mapping["schemas"]:
        if existing_mapping is None or "schemas" not in existing_mapping or "dbo" not in existing_mapping.get("schemas", {}):
            mapping["schemas"]["dbo"]["checked"] = False

    # Databases
    _add_to_section("databases", extracted["databases"], "Database_")

    # Procedures
    _add_to_section("procedures", extracted["procedures"], "Proc_")

    # Functions
    _add_to_section("functions", extracted["functions"], "Func_")

    return mapping


def _mask_string_literals(sql_text):
    """Replace string literal content with placeholders to protect from identifier replacement.

    Handles: 'value', N'value', 'it''s' (escaped quotes in T-SQL).
    Returns (masked_text, placeholder_map) where placeholder_map is {placeholder: original_span}.
    """
    placeholder_map = {}
    counter = [0]

    def _replacer(match):
        placeholder = f"__STR_{counter[0]}__"
        placeholder_map[placeholder] = match.group(0)
        counter[0] += 1
        return placeholder

    # N?'...' with escaped quotes (doubled single quotes)
    pattern = re.compile(r"N?'(?:[^']|'')*'", re.DOTALL)
    masked = pattern.sub(_replacer, sql_text)

    return masked, placeholder_map


def _unmask_string_literals(masked_text, placeholder_map):
    """Restore string literal placeholders back to original content."""
    result = masked_text
    for placeholder, original in sorted(placeholder_map.items(), key=lambda x: len(x[0]), reverse=True):
        result = result.replace(placeholder, original)
    return result


def _apply_mapping(sql_text, mapping):
    """Apply anonymization mapping to SQL text via string replacement.

    Three phases:
    1. Mask all string literals with placeholders (protects them from identifier replacement)
    2. Identifier replacements on masked text (bracket-quoted and unquoted)
    3. Unmask string literals, then apply string literal replacements
    """
    IDENTIFIER_SECTIONS = {"tables_ctes", "columns", "aliases", "schemas", "databases", "procedures", "functions"}
    STRING_SECTIONS = {"string_literals_variables", "string_literals_other"}

    # Phase 1: Mask string literals
    masked_text, placeholder_map = _mask_string_literals(sql_text)

    # Phase 2: Identifier replacements on masked text
    alias_map = {}
    id_replacements = []
    for section, entries in mapping.items():
        if section not in IDENTIFIER_SECTIONS:
            continue
        if not isinstance(entries, dict):
            continue
        for original, info in entries.items():
            if info.get("checked", True):
                if section == "aliases":
                    alias_map[original] = info["anonymized"]
                else:
                    id_replacements.append((original, info["anonymized"]))

    id_replacements.sort(key=lambda x: len(x[0]), reverse=True)
    # Longer identifiers are replaced first to avoid partial matches (e.g. "OrderDetail" before "Order").
    # Same-name identifiers across sections (e.g. table "Status" and column "Status") are safe because
    # each gets a unique anonymized name during mapping. Manual edits that create duplicate
    # anonymized names are unsupported and may produce unpredictable output.
    # Aliases are handled separately in a single-pass replacement (see below) to prevent
    # double-substitution when an anonymized alias letter coincidentally matches another original alias.

    result = masked_text
    for original, anonymized in id_replacements:
        # Replace bracket-quoted form: [Original]
        result = result.replace(f"[{original}]", f"[{anonymized}]")

        # Replace unquoted form with word boundary awareness
        pattern = re.compile(r"(?<!\[)(?<!\w)" + re.escape(original) + r"(?!\w)(?!\])", re.IGNORECASE)
        result = pattern.sub(anonymized, result)

    # Single-pass alias replacement — all aliases are substituted simultaneously so that
    # no anonymized letter can be picked up by a subsequent alias replacement.
    if alias_map:
        sorted_aliases = sorted(alias_map.keys(), key=len, reverse=True)
        alias_pattern = re.compile(
            r"(?<!\[)(?<!\w)(" + "|".join(re.escape(a) for a in sorted_aliases) + r")(?!\w)(?!\])",
            re.IGNORECASE,
        )
        alias_lookup = {k.lower(): v for k, v in alias_map.items()}

        def _alias_replacer(m):
            return alias_lookup.get(m.group(1).lower(), m.group(1))

        for orig in sorted_aliases:
            result = result.replace(f"[{orig}]", f"[{alias_map[orig]}]")

        result = alias_pattern.sub(_alias_replacer, result)

    # Phase 3: Unmask string literals, then apply string literal replacements
    result = _unmask_string_literals(result, placeholder_map)

    str_replacements = []
    for section, entries in mapping.items():
        if section not in STRING_SECTIONS:
            continue
        if not isinstance(entries, dict):
            continue
        for original, info in entries.items():
            if info.get("checked", True):
                str_replacements.append((original, info["anonymized"]))

    str_replacements.sort(key=lambda x: len(x[0]), reverse=True)

    for original, anonymized in str_replacements:
        # Only replace within single-quote contexts: 'original' and N'original'
        result = result.replace(f"N'{original}'", f"N'{anonymized}'")
        result = result.replace(f"'{original}'", f"'{anonymized}'")

    return result


def anonymize_sql(sql_text, dialect_name="T-SQL", existing_mapping=None,
                  comment_mode="Anonymize", string_mode="Anonymize"):
    """Main entry point: anonymize SQL text.

    Args:
        sql_text: Raw SQL string (may contain GO delimiters)
        dialect_name: User-friendly dialect name (e.g. "T-SQL")
        existing_mapping: Optional pre-existing mapping dict to extend
        comment_mode: "Anonymize", "Keep", or "Remove"
        string_mode: "Anonymize" or "Keep"

    Returns:
        (anonymized_sql, mapping) tuple
    """
    dialect = DIALECT_MAP.get(dialect_name, "tsql")

    # Step 1: Split on GO
    blocks = split_on_go(sql_text)
    if not blocks:
        return sql_text, existing_mapping or OrderedDict()

    # Step 2: Parse each block
    all_statements = []
    for block in blocks:
        parsed = parse_block(block, dialect)
        all_statements.extend(parsed)

    # Step 3: Extract identifiers from AST
    ast_count = sum(1 for stmt, _ in all_statements if stmt is not None)
    fallback_count = sum(1 for stmt, _ in all_statements if stmt is None)
    logger.debug("Blocks parsed: %d via AST, %d via regex fallback", ast_count, fallback_count)
    ast_extracted = _extract_from_ast(all_statements, dialect)

    # Step 4: Regex fallback for unparsed blocks
    for stmt, raw in all_statements:
        if stmt is None:
            regex_extracted = _extract_from_regex(raw)
            ast_extracted = _merge_extracted(ast_extracted, regex_extracted)

    # Step 5: Build mapping
    mapping = _build_mapping(ast_extracted, existing_mapping)

    # Step 6: Extract and handle comments
    mapping = _extract_and_map_comments(sql_text, all_statements, mapping, comment_mode, existing_mapping)

    # Step 7: Extract and handle string literals
    mapping = _extract_and_map_strings(all_statements, mapping, string_mode, existing_mapping)

    # Step 8: Apply mapping to original text
    # Apply comments first (if removing), then identifiers, then strings
    anonymized = sql_text
    comment_ph_map = {}

    if comment_mode == "Remove":
        anonymized = remove_comments(anonymized)
    elif comment_mode == "Anonymize":
        anonymized = _replace_comments(anonymized, mapping.get("comments", {}))
        # Mask Comment_N tokens AFTER _replace_comments so only the generated tokens
        # are masked — not original source comments that happen to match the pattern.
        # Must stay in this order; do not move _mask_replaced_comments before _replace_comments.
        anonymized, comment_ph_map = _mask_replaced_comments(anonymized)

    # Apply identifier + string replacements
    anonymized = _apply_mapping(anonymized, mapping)

    if comment_mode == "Anonymize":
        anonymized = _unmask_replaced_comments(anonymized, comment_ph_map)

    # Apply sp_addextendedproperty handling (regex-based, uses mapping)
    from sp_extended_property import anonymize_extended_properties
    anonymized = anonymize_extended_properties(anonymized, mapping)

    # Store modes in mapping for JSON persistence
    mapping["dialect"] = dialect_name
    mapping["comment_mode"] = comment_mode
    mapping["string_mode"] = string_mode

    string_count = len(mapping.get("string_literals_variables", {})) + len(mapping.get("string_literals_other", {}))
    logger.info(
        "Anonymization complete — tables/CTEs: %d, columns: %d, aliases: %d, "
        "procedures: %d, functions: %d, schemas: %d, databases: %d, strings: %d, comments: %d",
        len(mapping.get("tables_ctes", {})),
        len(mapping.get("columns", {})),
        len(mapping.get("aliases", {})),
        len(mapping.get("procedures", {})),
        len(mapping.get("functions", {})),
        len(mapping.get("schemas", {})),
        len(mapping.get("databases", {})),
        string_count,
        len(mapping.get("comments", {})),
    )

    return anonymized, mapping


def _extract_and_map_comments(sql_text, statements, mapping, comment_mode, existing_mapping):
    """Extract comments from SQL and map them. Keys are full delimited comment strings."""
    if comment_mode == "Keep":
        return mapping

    comments = []
    seen = set()

    # Extract full delimited comment strings via regex (covers both parsed and unparsed blocks)
    # Single-line comments: strip block comment regions first so "--" inside /* */ is not extracted.
    text_no_blocks = re.sub(r"/\*.*?\*/", "", sql_text, flags=re.DOTALL)
    for m in re.finditer(r"--[^\n]*", text_no_blocks):
        full_comment = m.group(0)
        if full_comment.strip() and full_comment not in seen:
            seen.add(full_comment)
            comments.append(full_comment)

    # Multi-line comments: full "/* ... */" string
    for m in re.finditer(r"/\*.*?\*/", sql_text, re.DOTALL):
        full_comment = m.group(0)
        if full_comment.strip() and full_comment not in seen:
            seen.add(full_comment)
            comments.append(full_comment)

    if "comments" not in mapping:
        mapping["comments"] = OrderedDict()

    counter = 1
    for v in mapping["comments"].values():
        anon = v.get("anonymized", "")
        if anon.startswith("Comment_"):
            try:
                num = int(anon[8:])
                counter = max(counter, num + 1)
            except ValueError:
                pass

    for comment_text in comments:
        if comment_text not in mapping["comments"]:
            mapping["comments"][comment_text] = {
                "anonymized": f"Comment_{counter}",
                "checked": True,
            }
            counter += 1

    return mapping


def _extract_and_map_strings(statements, mapping, string_mode, existing_mapping):
    """Extract string literals from AST and map them, split by context.

    Variable assignments (SET @Var = 'value') go into string_literals_variables.
    All other string literals go into string_literals_other.
    """
    if string_mode == "Keep":
        return mapping

    var_strings = set()
    other_strings = set()

    for stmt, _raw in statements:
        if stmt is None:
            continue
        for node in stmt.walk():
            if isinstance(node, exp.Literal) and node.args.get("is_string"):
                val = node.this
                if val and len(val) > 1 and not val.lstrip("-").isdigit():
                    # Skip: empty strings, single-char flag values ('Y', 'N', 'A' etc.) —
                    # these are ubiquitous SQL conventions, not client-identifying data.
                    # Single-char strings are too common to be worth anonymizing and would
                    # clutter the mapping with dozens of noise entries. Users needing to
                    # anonymize a specific single-char value can use manual replacements.
                    # Also skips pure numeric strings (e.g. '0', '-1') which are never sensitive.
                    # Detect context: walk up parents to find variable assignment.
                    # Handles both SET @Var = 'value' (SetItem) and
                    # DECLARE @Var TYPE = 'value' (DeclareItem).
                    is_var_assignment = False
                    parent = node.parent
                    while parent:
                        if isinstance(parent, exp.SetItem):
                            eq = parent.find(exp.EQ)
                            if eq and eq.find(exp.Parameter):
                                is_var_assignment = True
                            break
                        if isinstance(parent, exp.DeclareItem):
                            is_var_assignment = True
                            break
                        parent = parent.parent
                    if is_var_assignment:
                        var_strings.add(val)
                    else:
                        other_strings.add(val)

    # Regex fallback: extract string literals from EXEC parameter assignments
    # in unparsed statements (stmt is None). Catches @Param = 'value' patterns.
    # Skip sp_addextendedproperty — handled by sp_extended_property.py.
    for stmt, _raw in statements:
        if stmt is not None:
            continue
        if not re.search(r"\bEXEC(?:UTE)?\b", _raw, re.IGNORECASE):
            continue
        if re.search(r"\bsp_addextendedproperty\b", _raw, re.IGNORECASE):
            continue
        for m in re.finditer(r"@\w+\s*=\s*N?'((?:[^']|'')*)'", _raw):
            val = m.group(1)
            if val and len(val) > 1 and not val.lstrip("-").isdigit():
                # Same filter as AST path: skip single-char flags and numeric strings.
                var_strings.add(val)

    # Regex fallback: extract string literals from comparison expressions
    # (col = 'value', col <> 'value') in unparsed statements.
    # Catches strings in large queries that fail sqlglot parsing (e.g. 25-JOIN UPDATEs).
    # Comments are stripped first to avoid picking up strings in comment text.
    # These are off by default (string_literals_other uses checked: False).
    for stmt, _raw in statements:
        if stmt is not None:
            continue
        raw_no_comments = re.sub(r"--[^\n]*", "", _raw)
        for m in re.finditer(r"(?:=|<>|!=)\s*N?'((?:[^']|'')*)'", raw_no_comments):
            val = m.group(1)
            if val and len(val) > 1 and not val.lstrip("-").isdigit():
                other_strings.add(val)

    # Build string_literals_variables section
    if "string_literals_variables" not in mapping:
        mapping["string_literals_variables"] = OrderedDict()

    counter = 1
    for v in mapping["string_literals_variables"].values():
        anon = v.get("anonymized", "")
        if anon.startswith("VarValue_"):
            try:
                num = int(anon[9:])
                counter = max(counter, num + 1)
            except ValueError:
                pass

    for val in sorted(var_strings):
        if val not in mapping["string_literals_variables"]:
            mapping["string_literals_variables"][val] = {
                "anonymized": f"VarValue_{counter}",
                "checked": False,
            }
            counter += 1

    # Build string_literals_other section
    if "string_literals_other" not in mapping:
        mapping["string_literals_other"] = OrderedDict()

    counter = 1
    for v in mapping["string_literals_other"].values():
        anon = v.get("anonymized", "")
        if anon.startswith("Value_"):
            try:
                num = int(anon[6:])
                counter = max(counter, num + 1)
            except ValueError:
                pass

    for val in sorted(other_strings):
        if val not in mapping["string_literals_other"]:
            mapping["string_literals_other"][val] = {
                "anonymized": f"Value_{counter}",
                "checked": False,
            }
            counter += 1

    return mapping


def remove_comments(sql_text):
    """Remove all comments from SQL text, preserving line count."""
    def _multi_line_replacer(match):
        line_count = match.group(0).count("\n")
        return "\n" * line_count

    # Replace multi-line comments with equivalent empty lines
    result = re.sub(r"/\*.*?\*/", _multi_line_replacer, sql_text, flags=re.DOTALL)
    # Replace single-line comments with empty string (line itself stays)
    result = re.sub(r"--.*?$", "", result, flags=re.MULTILINE)
    return result


def _mask_replaced_comments(text):
    """Replace Comment_N tokens in already-replaced comment delimiters with placeholders.

    Protects `/* Comment_N */` and `-- Comment_N` tokens from being modified by
    `_apply_mapping`, which would otherwise corrupt the delimiters or inject extra
    text into the token names.

    Returns (masked_text, placeholder_map).
    """
    counter = [0]
    placeholder_map = {}

    def _replacer(match):
        key = f"__CMT_{counter[0]}__"
        placeholder_map[key] = match.group(0)
        counter[0] += 1
        return key

    # Match /* Comment_N */ and /* Comment_N\n\n...\n*/ multi-line forms (blank-line filler)
    pattern_block = re.compile(r"/\*\s*Comment_\d+.*?\*/", re.DOTALL)
    text = pattern_block.sub(_replacer, text)

    # Match -- Comment_N (to end of line)
    pattern_line = re.compile(r"--\s*Comment_\d+[^\n]*")
    text = pattern_line.sub(_replacer, text)

    return text, placeholder_map


def _unmask_replaced_comments(text, placeholder_map):
    """Restore comment placeholders back to their Comment_N tokens."""
    # Sort by key length descending so a shorter key (e.g. __CMT_9__) is not
    # mistakenly matched inside a longer one (e.g. __CMT_99__).
    for key, original in sorted(placeholder_map.items(), key=lambda x: len(x[0]), reverse=True):
        text = text.replace(key, original)
    return text


def _replace_comments(sql_text, comment_mapping):
    """Replace full delimited comment strings with anonymized versions."""
    result = sql_text
    if not comment_mapping:
        return result

    # Interleaved masking: after placing each Comment_N token, immediately mask it
    # so shorter comment keys cannot match inside already-replaced tokens.
    # Assumption: __CMTTMP_ is not a valid SQL substring in any input.
    temp_map = {}
    counter = [0]

    def _mask_placed(text):
        def _replacer(m):
            key = f"__CMTTMP_{counter[0]}__"
            temp_map[key] = m.group(0)
            counter[0] += 1
            return key
        text = re.sub(r"/\*\s*Comment_\d+[\s\S]*?\*/", _replacer, text)
        text = re.sub(r"--\s*Comment_\d+[^\n]*", _replacer, text)
        return text

    # Sort by length descending to replace longest first
    sorted_comments = sorted(comment_mapping.items(), key=lambda x: len(x[0]), reverse=True)

    for original, info in sorted_comments:
        if not info.get("checked", True):
            continue
        anonymized = info["anonymized"]

        # Wrap anonymized value in the correct comment delimiters.
        # Block comments use blank-line filler (not "--") to preserve line count
        # without introducing "--" that could be matched by shorter comment keys.
        if original.startswith("--"):
            replacement = f"-- {anonymized}"
        else:
            line_count = original.count("\n")
            if line_count == 0:
                replacement = f"/* {anonymized} */"
            else:
                replacement = f"/* {anonymized}" + "\n" * line_count + "*/"

        result = result.replace(original, replacement)
        result = _mask_placed(result)  # protect the token just placed

    # Unmask all (longest key first to avoid partial matches on __CMTTMP_9__ vs __CMTTMP_99__)
    for key, val in sorted(temp_map.items(), key=lambda x: len(x[0]), reverse=True):
        result = result.replace(key, val)

    return result


def deanonymize_sql(anonymized_sql, mapping):
    """Reverse the anonymization using a mapping.

    Args:
        anonymized_sql: The anonymized SQL text
        mapping: The mapping dict (from anonymize or loaded from JSON)

    Returns:
        De-anonymized SQL text
    """
    # Build reverse replacements: anonymized -> original
    replacements = []
    comment_replacements = []
    for section, entries in mapping.items():
        if section in ("dialect", "comment_mode", "string_mode"):
            continue
        if not isinstance(entries, dict):
            continue
        for original, info in entries.items():
            if info.get("checked", True):
                if section == "comments":
                    comment_replacements.append((info["anonymized"], original))
                else:
                    replacements.append((info["anonymized"], original))

    # Sort by length descending
    replacements.sort(key=lambda x: len(x[0]), reverse=True)

    result = anonymized_sql
    for anonymized, original in replacements:
        # Replace bracket-quoted form
        result = result.replace(f"[{anonymized}]", f"[{original}]")

        # Replace N'anonymized' form
        result = result.replace(f"N'{anonymized}'", f"N'{original}'")

        # Replace plain 'anonymized' form
        result = result.replace(f"'{anonymized}'", f"'{original}'")

        # Replace unquoted form with word boundary
        pattern = re.compile(r"(?<!\[)(?<!\w)" + re.escape(anonymized) + r"(?!\w)(?!\])")
        result = pattern.sub(original, result)

    # Reverse comment replacements: "-- Comment_N" -> original full comment
    comment_replacements.sort(key=lambda x: len(x[0]), reverse=True)
    for anonymized, original in comment_replacements:
        if original.startswith("--"):
            result = result.replace(f"-- {anonymized}", original)
        else:
            # Build the same line-preserving pattern used during anonymization
            line_count = original.count("\n")
            if line_count == 0:
                anon_comment = f"/* {anonymized} */"
            else:
                # Must match the blank-line filler pattern used by _replace_comments
                anon_comment = f"/* {anonymized}" + "\n" * line_count + "*/"
            result = result.replace(anon_comment, original)

    return result


# --- CLI for testing ---
if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if len(sys.argv) < 2:
        print("Usage: python sql_module.py <sql_file_or_folder> [dialect]")
        sys.exit(1)

    target = Path(sys.argv[1])
    dialect = sys.argv[2] if len(sys.argv) > 2 else "T-SQL"

    def read_sql_file(path):
        """Read SQL file, trying utf-8-sig first then cp1252."""
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                return path.read_text(encoding=enc)
            except (UnicodeDecodeError, ValueError):
                continue
        return path.read_text(encoding="latin-1", errors="replace")

    # Read SQL file(s)
    if target.is_dir():
        sql_files = sorted(target.glob("*.sql"))
        parts = []
        for f in sql_files:
            parts.append(f"-- === File: {f.name} ===")
            parts.append(read_sql_file(f))
        sql_text = "\n".join(parts)
    else:
        sql_text = read_sql_file(target)

    print("=" * 60)
    print("ORIGINAL SQL (first 500 chars):")
    print("=" * 60)
    print(sql_text[:500])
    print("...")

    anonymized, mapping = anonymize_sql(sql_text, dialect)

    print("\n" + "=" * 60)
    print("MAPPING:")
    print("=" * 60)
    for section, entries in mapping.items():
        if section in ("dialect", "comment_mode", "string_mode"):
            print(f"\n{section}: {entries}")
            continue
        if not isinstance(entries, dict):
            continue
        print(f"\n--- {section} ---")
        for original, info in entries.items():
            checked = "x" if info["checked"] else " "
            anon = info["anonymized"]
            display_orig = original[:60] + "..." if len(original) > 60 else original
            print(f"  [{checked}] {display_orig} -> {anon}")

    print("\n" + "=" * 60)
    print("ANONYMIZED SQL:")
    print("=" * 60)
    print(anonymized)
