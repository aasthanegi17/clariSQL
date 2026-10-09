"""PostgreSQL access: schema introspection and SAFE query execution."""
from __future__ import annotations

from dataclasses import dataclass
from collections import defaultdict

import psycopg2
from psycopg2 import sql as pgsql

from .config import DATABASE_URL, STATEMENT_TIMEOUT_MS


@dataclass
class SchemaInfo:
    text: str          # human-readable schema that goes into the LLM prompt
    tables: set[str]   # allow-list used by the validator


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def load_schema(max_enum_values: int = 8) -> SchemaInfo:
    """Read tables, columns, keys and low-cardinality values from the database."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
            ORDER BY table_name, ordinal_position
            """
        )
        columns: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for table, col, dtype in cur.fetchall():
            columns[table].append((col, dtype))

        cur.execute(
            """
            SELECT tc.table_name, kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = 'public'
            """
        )
        pks = {(t, c) for t, c in cur.fetchall()}

        cur.execute(
            """
            SELECT tc.table_name, kcu.column_name, ccu.table_name, ccu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public'
            """
        )
        fks = {(t, c): (rt, rc) for t, c, rt, rc in cur.fetchall()}

        lines: list[str] = []
        for table, cols in columns.items():
            lines.append(f"TABLE {table}")
            for col, dtype in cols:
                notes = []
                if (table, col) in pks:
                    notes.append("PRIMARY KEY")
                if (table, col) in fks:
                    rt, rc = fks[(table, col)]
                    notes.append(f"FOREIGN KEY -> {rt}.{rc}")
                if dtype in ("text", "character varying"):
                    cur.execute(
                        pgsql.SQL("SELECT DISTINCT {c} FROM {t} WHERE {c} IS NOT NULL LIMIT %s").format(
                            c=pgsql.Identifier(col), t=pgsql.Identifier(table)
                        ),
                        (max_enum_values + 1,),
                    )
                    values = [r[0] for r in cur.fetchall()]
                    if 0 < len(values) <= max_enum_values:
                        notes.append("allowed values: " + ", ".join(f"'{v}'" for v in sorted(values)))
                suffix = f"  -- {'; '.join(notes)}" if notes else ""
                lines.append(f"  {col} {dtype}{suffix}")
            lines.append("")
        return SchemaInfo(text="\n".join(lines).strip(), tables=set(columns))
    finally:
        conn.close()


def run_select(sql: str, max_rows: int) -> tuple[list[str], list[tuple], bool]:
    """Execute a SELECT in a READ ONLY transaction with a statement timeout.

    Even if the validator missed something, PostgreSQL itself will refuse writes.
    Returns (column_names, rows, truncated).
    """
    conn = get_conn()
    try:
        conn.set_session(readonly=True, autocommit=False)
        with conn.cursor() as cur:
            cur.execute(f"SET LOCAL statement_timeout = {int(STATEMENT_TIMEOUT_MS)}")
            cur.execute(sql)
            columns = [d.name for d in cur.description]
            rows = cur.fetchmany(max_rows + 1)
        truncated = len(rows) > max_rows
        return columns, rows[:max_rows], truncated
    finally:
        conn.rollback()
        conn.close()
