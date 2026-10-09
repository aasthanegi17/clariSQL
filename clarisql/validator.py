"""Static safety checks that run BEFORE any SQL touches the database.

This is defence in depth. The real guarantee comes from the database layer
(read-only transaction + statement timeout, see db.py).
"""
from __future__ import annotations

import re
from typing import Iterable, Optional


class UnsafeSQLError(ValueError):
    """Raised when generated SQL is not a safe, single, read-only SELECT."""


FORBIDDEN_KEYWORDS = {
    "insert", "update", "delete", "drop", "alter", "truncate", "create",
    "grant", "revoke", "copy", "call", "do", "execute", "merge", "vacuum",
    "analyze", "set", "reset", "listen", "notify", "lock", "comment",
    "refresh", "reindex", "cluster", "into",
}
FORBIDDEN_FUNCTIONS = {
    "pg_sleep", "pg_read_file", "pg_read_binary_file", "pg_ls_dir",
    "lo_import", "lo_export", "dblink", "pg_terminate_backend",
    "pg_cancel_backend", "set_config", "current_setting",
}

_STRING = re.compile(r"'(?:[^']|'')*'")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"--[^\n]*")
# Functions whose syntax contains "FROM" but which are not table references.
_FROM_FUNCS = re.compile(r"\b(?:extract|substring|trim|overlay)\s*\((?:[^()]|\([^()]*\))*\)", re.I)
_TABLE_REF = re.compile(r"\b(?:from|join)\s+([a-zA-Z_][\w\.\"]*)\s*(\()?", re.I)
_CTE_NAME = re.compile(r"\b([a-zA-Z_]\w*)\s+as\s*\(", re.I)


def _mask(sql: str) -> str:
    """Remove string literals and comments so keywords inside them are ignored."""
    masked = _STRING.sub("''", sql)
    masked = _BLOCK_COMMENT.sub(" ", masked)
    masked = _LINE_COMMENT.sub(" ", masked)
    return masked


def validate_sql(sql: str, allowed_tables: Optional[Iterable[str]] = None) -> str:
    """Return the cleaned SQL or raise UnsafeSQLError."""
    if not sql or not sql.strip():
        raise UnsafeSQLError("Empty query.")

    cleaned = sql.strip()
    masked = _mask(cleaned)

    body = masked.strip().rstrip(";").strip()
    if ";" in body:
        raise UnsafeSQLError("Only a single SQL statement is allowed.")
    cleaned = cleaned.rstrip(";").strip()

    first = re.match(r"\s*(\w+)", body)
    if not first or first.group(1).lower() not in {"select", "with"}:
        raise UnsafeSQLError("Only SELECT queries are allowed.")

    lowered = body.lower()
    for word in re.findall(r"\b[a-z_]+\b", lowered):
        if word in FORBIDDEN_KEYWORDS:
            raise UnsafeSQLError(f"Forbidden keyword: {word.upper()}")
        if word in FORBIDDEN_FUNCTIONS:
            raise UnsafeSQLError(f"Forbidden function: {word}")

    if allowed_tables is not None:
        allowed = {t.lower() for t in allowed_tables}
        no_funcs = _FROM_FUNCS.sub(" ", body)
        ctes = {m.lower() for m in _CTE_NAME.findall(no_funcs)}
        for name, paren in _TABLE_REF.findall(no_funcs):
            if paren:  # set-returning function such as generate_series(...)
                continue
            table = name.replace('"', "").split(".")[-1].lower()
            if table not in allowed and table not in ctes:
                raise UnsafeSQLError(f"Unknown or disallowed table: {table}")

    return cleaned
