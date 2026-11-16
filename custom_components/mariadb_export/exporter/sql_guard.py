"""Reject custom SQL that is not a single read-only SELECT."""

from __future__ import annotations

from .models import RequestError

MAX_QUERY_LENGTH = 20_000

# A read-only database account is the real boundary. This guard stops the
# obvious write and file-export statements before they are sent.
_FORBIDDEN = frozenset(
    {
        "alter",
        "analyze",
        "benchmark",
        "call",
        "change",
        "commit",
        "create",
        "delete",
        "do",
        "drop",
        "dumpfile",
        "execute",
        "flush",
        "get_lock",
        "grant",
        "handler",
        "insert",
        "into",
        "kill",
        "load",
        "load_file",
        "lock",
        "optimize",
        "outfile",
        "prepare",
        "purge",
        "release_lock",
        "rename",
        "repair",
        "reset",
        "revoke",
        "rollback",
        "set",
        "shutdown",
        "sleep",
        "truncate",
        "unlock",
        "update",
        "use",
    }
)


def validate_select(sql: str) -> str:
    """Return a single SELECT with any trailing semicolon removed."""

    if "\x00" in sql:
        raise RequestError("The query contains a null byte.")
    if len(sql) > MAX_QUERY_LENGTH:
        raise RequestError("The query is too long.")
    stripped = sql.strip()
    if not stripped:
        raise RequestError("Enter a SELECT query.")
    tokens = _tokenize(stripped)
    if tokens and tokens[-1] == ";":
        if tokens.count(";") > 1:
            raise RequestError("Only one statement is allowed.")
        tokens = tokens[:-1]
        stripped = stripped.rstrip()
        if stripped.endswith(";"):
            stripped = stripped[:-1].rstrip()
    elif ";" in tokens:
        raise RequestError("Only one statement is allowed.")
    if not tokens or tokens[0] not in {"select", "with"}:
        raise RequestError("Only a single SELECT query is allowed.")
    if tokens[0] == "with" and "select" not in tokens:
        raise RequestError("Only a single SELECT query is allowed.")
    for token in tokens:
        if token in _FORBIDDEN:
            raise RequestError(f"The query uses {token}, which is not allowed.")
    if not stripped:
        raise RequestError("Enter a SELECT query.")
    return stripped


def prepare_custom(sql: str, limit: int) -> tuple[str, tuple[int, ...]]:
    """Wrap a SELECT so the server stops after the row limit."""

    cleaned = validate_select(sql)
    tokens = _tokenize(cleaned)
    # MySQL drops ORDER BY inside a derived table unless that query has LIMIT.
    if "order" in tokens and "limit" not in tokens:
        cleaned = f"{cleaned} LIMIT 18446744073709551615"
    wrapped = f"SELECT * FROM ({cleaned}) AS mariadb_export_query LIMIT %s"
    return wrapped, (limit + 1,)


def _tokenize(sql: str) -> list[str]:
    tokens: list[str] = []
    index = 0
    length = len(sql)
    while index < length:
        char = sql[index]
        if char.isspace():
            index += 1
            continue
        if char == "#":
            index = _line_end(sql, index)
            continue
        if char == "-" and _is_line_comment(sql, index):
            index = _line_end(sql, index)
            continue
        if char == "/" and index + 1 < length and sql[index + 1] == "*":
            end = sql.find("*/", index + 2)
            if end < 0:
                raise RequestError("The query has an unterminated comment.")
            index = end + 2
            continue
        if char in {"'", '"', "`"}:
            index = _skip_quoted(sql, index)
            continue
        if char == ";":
            tokens.append(";")
            index += 1
            continue
        if char.isalpha() or char == "_":
            end = index + 1
            while end < length and (sql[end].isalnum() or sql[end] == "_"):
                end += 1
            tokens.append(sql[index:end].lower())
            index = end
            continue
        index += 1
    return tokens


def _is_line_comment(sql: str, index: int) -> bool:
    if index + 1 >= len(sql) or sql[index + 1] != "-":
        return False
    return index + 2 >= len(sql) or sql[index + 2].isspace()


def _line_end(sql: str, index: int) -> int:
    end = sql.find("\n", index)
    if end < 0:
        return len(sql)
    return end + 1


def _skip_quoted(sql: str, start: int) -> int:
    quote = sql[start]
    index = start + 1
    length = len(sql)
    while index < length:
        char = sql[index]
        if char == "\\":
            index += 2
            continue
        if char == quote:
            if index + 1 < length and sql[index + 1] == quote:
                index += 2
                continue
            return index + 1
        index += 1
    raise RequestError("The query has an unterminated string.")
