"""Handler for sp_addextendedproperty anonymization.

Regex-based replacement for EXEC sys.sp_addextendedproperty calls.
Replaces @level0name, @level1name, @level2name values using the
existing anonymization mapping.

Kept separate from the main sql_module for isolated debugging.
"""

import logging
import re

logger = logging.getLogger(__name__)


def anonymize_extended_properties(sql_text, mapping):
    """Replace level names in sp_addextendedproperty calls using the mapping.

    Detects EXEC sys.sp_addextendedproperty blocks and replaces
    @level0name=N'...', @level1name=N'...', @level2name=N'...' values
    using the already-built mapping.

    Args:
        sql_text: SQL text (may already be partially anonymized)
        mapping: The anonymization mapping dict

    Returns:
        SQL text with extended property level names replaced
    """
    # Build a lookup from original name to anonymized name across all sections
    name_lookup = {}
    for section, entries in mapping.items():
        if section in ("dialect", "comment_mode", "string_mode"):
            continue
        if not isinstance(entries, dict):
            continue
        for original, info in entries.items():
            if info.get("checked", True):
                name_lookup[original] = info["anonymized"]

    def _replace_level_value(match):
        """Replace the value inside @levelNname=N'...' if it exists in mapping."""
        prefix = match.group(1)  # e.g. @level0name=N'
        value = match.group(2)   # e.g. dbo
        suffix = match.group(3)  # e.g. '

        if value in name_lookup:
            return f"{prefix}{name_lookup[value]}{suffix}"
        return match.group(0)

    # Pattern matches @level0name=N'value', @level1name=N'value', @level2name=N'value'
    pattern = re.compile(
        r"(@level[012]name\s*=\s*N')(.*?)(')",
        re.IGNORECASE,
    )

    result = pattern.sub(_replace_level_value, sql_text)
    return result


def deanonymize_extended_properties(sql_text, mapping):
    """Reverse the anonymization of extended property level names.

    Args:
        sql_text: Anonymized SQL text
        mapping: The anonymization mapping dict

    Returns:
        SQL text with original level names restored
    """
    # Build reverse lookup
    reverse_lookup = {}
    for section, entries in mapping.items():
        if section in ("dialect", "comment_mode", "string_mode"):
            continue
        if not isinstance(entries, dict):
            continue
        for original, info in entries.items():
            if info.get("checked", True):
                reverse_lookup[info["anonymized"]] = original

    def _restore_level_value(match):
        prefix = match.group(1)
        value = match.group(2)
        suffix = match.group(3)

        if value in reverse_lookup:
            return f"{prefix}{reverse_lookup[value]}{suffix}"
        return match.group(0)

    pattern = re.compile(
        r"(@level[012]name\s*=\s*N')(.*?)(')",
        re.IGNORECASE,
    )

    return pattern.sub(_restore_level_value, sql_text)
