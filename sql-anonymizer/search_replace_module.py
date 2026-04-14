"""Search and replace module for manual text replacements.

Applied as a final pass after structured anonymization.
Entries are saved in the JSON mapping and reapplied on future loads.
"""

import logging

logger = logging.getLogger(__name__)


def apply_manual_replacements(sql_text, replacements):
    """Apply manual find/replace pairs to SQL text.

    Args:
        sql_text: The SQL text to modify
        replacements: Dict of {find_text: replace_text}

    Returns:
        Modified SQL text
    """
    result = sql_text
    # Sort by length descending to replace longest first
    sorted_pairs = sorted(replacements.items(), key=lambda x: len(x[0]), reverse=True)
    for find_text, replace_text in sorted_pairs:
        result = result.replace(find_text, replace_text)
    return result
