"""PostgreSQL access: schema introspection (with descriptions and value ranges) and SAFE execution."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

import psycopg2
from psycopg2 import sql as pgsql

from .config import DATABASE_URL, STATEMENT_TIMEOUT_MS

NUMERIC_TYPES = {"smallint", "integer", "bigint", "numeric", "real", "double precision"}
DATE_TYPES = {"date", "timestamp without time zone", "timestamp with time zone"}
TEXT_TYPES = {"text", "character varying", "character"}


@dataclass
class SchemaInfo:
    text: str                                   # goes into the LLM prompt
    tables: set[str]                            # allow-list for the validator
    columns: dict[str, list[str]] = field(default_factory=dict)
    # (table, column) -> description; column "" means the table itself
    comments: dict[tuple[str, str], str] = field(default_factory=dict)


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def table_exists(name: str) -> bool:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=%s",
            (name,),
        )
        return cur.fetchone() is not None
    finally:
        conn.close()


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:.6g}"
    if isinstance(v, Decimal):
        return str(v.normalize()) if v == v.to_integral() else str(round(v, 4))
    if isinstance(v, (date, datetime)):
        return v.isoformat(sep=" ") if isinstance(v, datetime) else v.isoformat()
    return str(v)


def _table_stats(cur, table: str, cols: list[tuple[str, str]], max_enum: int):
    """One round trip for ranges + row count, one for text-value samples."""
    row_count = None
    ranges: dict[str, tuple] = {}
    samples: dict[str, list[str]] = defaultdict(list)

    range_cols = [c for c, t in cols if t in NUMERIC_TYPES or t in DATE_TYPES]
    parts = [pgsql.SQL("COUNT(*)")]
    for c in range_cols:
        parts.append(pgsql.SQL("MIN({})").format(pgsql.Identifier(c)))
        parts.append(pgsql.SQL("MAX({})").format(pgsql.Identifier(c)))
    cur.execute(pgsql.SQL("SELECT {} FROM {}").format(pgsql.SQL(", ").join(parts), pgsql.Identifier(table)))
    row = cur.fetchone()
    row_count = row[0]
    for i, c in enumerate(range_cols):
        lo, hi = row[1 + 2 * i], row[2 + 2 * i]
        if lo is not None and hi is not None:
            ranges[c] = (lo, hi)

    text_cols = [c for c, t in cols if t in TEXT_TYPES]
    if text_cols and row_count:
        subs = [
            pgsql.SQL(
                "(SELECT {name} AS c, x::text AS v FROM "
                "(SELECT DISTINCT {col} AS x FROM {t} WHERE {col} IS NOT NULL LIMIT {lim}) s)"
            ).format(
                name=pgsql.Literal(c),
                col=pgsql.Identifier(c),
                t=pgsql.Identifier(table),
                lim=pgsql.Literal(max_enum + 1),
            )
            for c in text_cols
        ]
        cur.execute(pgsql.SQL(" UNION ALL ").join(subs))
        for c, v in cur.fetchall():
            samples[c].append(v)
    return row_count, ranges, samples


def load_schema(max_enum_values: int = 8) -> SchemaInfo:
    """Read tables, columns, keys, descriptions, value ranges and sample values."""
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

        # Descriptions saved with COMMENT ON TABLE / COMMENT ON COLUMN
        cur.execute(
            """
            SELECT c.relname, COALESCE(a.attname, ''), d.description
            FROM pg_catalog.pg_description d
            JOIN pg_catalog.pg_class c
              ON c.oid = d.objoid AND d.classoid = 'pg_catalog.pg_class'::regclass
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_catalog.pg_attribute a
              ON a.attrelid = c.oid AND a.attnum = d.objsubid AND d.objsubid > 0
            WHERE n.nspname = 'public' AND c.relkind IN ('r', 'v', 'm', 'p')
            """
        )
        comments = {(t, c): d for t, c, d in cur.fetchall()}
        conn.rollback()

        lines: list[str] = []
        for table, cols in columns.items():
            try:
                row_count, ranges, samples = _table_stats(cur, table, cols, max_enum_values)
            except psycopg2.Error:
                conn.rollback()
                row_count, ranges, samples = None, {}, {}

            header = f"TABLE {table}" + (f"  ({row_count:,} rows)" if row_count is not None else "")
            lines.append(header)
            if (table, "") in comments:
                lines.append(f"  -- about this table: {comments[(table, '')]}")
            for col, dtype in cols:
                notes = []
                if (table, col) in pks:
                    notes.append("PRIMARY KEY")
                if (table, col) in fks:
                    rt, rc = fks[(table, col)]
                    notes.append(f"FOREIGN KEY -> {rt}.{rc}")
                if (table, col) in comments:
                    notes.append(f"meaning: {comments[(table, col)]}")
                if col in ranges:
                    lo, hi = ranges[col]
                    notes.append(f"range: {_fmt(lo)} to {_fmt(hi)}")
                values = sorted(samples.get(col, []))
                if values:
                    if len(values) <= max_enum_values:
                        notes.append("allowed values: " + ", ".join(f"'{v}'" for v in values))
                    else:
                        notes.append("examples: " + ", ".join(f"'{v}'" for v in values[:3]))
                suffix = f"  -- {'; '.join(notes)}" if notes else ""
                lines.append(f"  {col} {dtype}{suffix}")
            lines.append("")

        return SchemaInfo(
            text="\n".join(lines).strip(),
            tables=set(columns),
            columns={t: [c for c, _ in cols] for t, cols in columns.items()},
            comments=comments,
        )
    finally:
        conn.close()


def set_description(table: str, column: str, text: str) -> None:
    """Save (or clear, if text is empty) a description. column='' describes the table."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        value = pgsql.Literal(text.strip() or None)
        if column:
            stmt = pgsql.SQL("COMMENT ON COLUMN {}.{} IS {}").format(
                pgsql.Identifier(table), pgsql.Identifier(column), value
            )
        else:
            stmt = pgsql.SQL("COMMENT ON TABLE {} IS {}").format(pgsql.Identifier(table), value)
        cur.execute(stmt)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
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
