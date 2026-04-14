"""Shared constants for sql_anonymizer."""

# T-SQL control-flow keywords that sqlglot misparses as Column/Table nodes
# when procedure body splitting produces fragments it can't fully parse.
# Intentionally narrow: only keywords that never appear as real column names.
# Words like OUTPUT, KEY, DEFAULT, IDENTITY are valid column names and excluded.
SQL_KEYWORDS = frozenset({
    "RETURN", "WHILE", "BEGIN", "END", "IF", "ELSE", "PRINT",
    "RAISERROR", "THROW", "BREAK", "CONTINUE", "GOTO", "WAITFOR",
    "TRY", "CATCH", "SET", "DECLARE", "EXEC", "EXECUTE", "GO", "USE",
    "SELECT", "INSERT", "UPDATE", "DELETE", "FROM", "WHERE", "JOIN",
    "ON", "AND", "OR", "NOT", "IN", "EXISTS", "GROUP", "ORDER", "BY",
    "HAVING", "UNION", "ALL", "AS", "INTO", "VALUES",
    "CREATE", "ALTER", "DROP", "PROCEDURE", "FUNCTION",
    "WITH", "CASE", "WHEN", "THEN", "NULL", "IS",
    "LIKE", "BETWEEN", "DISTINCT",
    "COMMIT", "ROLLBACK", "TRANSACTION", "TRUNCATE",
    "GRANT", "REVOKE", "DENY", "INNER", "LEFT", "RIGHT", "OUTER",
    "CROSS", "FULL", "ASC", "DESC",
    "OPEN", "CLOSE", "FETCH", "DEALLOCATE", "CURSOR",
    "*",
})
