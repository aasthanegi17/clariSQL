"""Load CSV files into PostgreSQL (used by the web UI and by db/load_csv.py)."""
from __future__ import annotations

import re
import warnings

import pandas as pd


def clean_name(name, prefix: str = "c_", limit: int = 60) -> str:
    """Turn any header into a safe lowercase SQL identifier."""
    n = re.sub(r"\W+", "_", str(name).strip().lower()).strip("_") or "col"
    if n[0].isdigit():
        n = prefix + n
    return n[:limit]


def dedupe(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for n in names:
        if n in seen:
            seen[n] += 1
            n = f"{n}_{seen[n]}"[:60]
        else:
            seen[n] = 1
        out.append(n)
    return out


def _rewind(source) -> None:
    if hasattr(source, "seek"):
        source.seek(0)


def _read(source, **kw) -> pd.DataFrame:
    try:
        return pd.read_csv(source, **kw)
    except UnicodeDecodeError:
        _rewind(source)
        return pd.read_csv(source, encoding="latin-1", **kw)


def read_csv(source) -> pd.DataFrame:
    """Read a path or uploaded file; handles Excel-style ';' separators and odd encodings."""
    df = _read(source)
    if df.shape[1] == 1 and re.search(r"[;\t|]", str(df.columns[0])):
        _rewind(source)
        df = _read(source, sep=None, engine="python")
    return df


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Clean column names and convert text columns that are really dates."""
    df = df.copy()
    df.columns = dedupe([clean_name(c) for c in df.columns])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for c in df.columns:
            if not (df[c].dtype == object or pd.api.types.is_string_dtype(df[c])):
                continue
            sample = df[c].dropna().astype(str).head(200)
            if len(sample) == 0 or (sample.str.len() >= 6).mean() < 0.95:
                continue
            if pd.to_datetime(sample, errors="coerce").notna().mean() > 0.95:
                df[c] = pd.to_datetime(df[c], errors="coerce")
    return df


def pg_type(s: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(s):
        return "BOOLEAN"
    if pd.api.types.is_integer_dtype(s):
        return "BIGINT"
    if pd.api.types.is_float_dtype(s):
        return "DOUBLE PRECISION"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "TIMESTAMP"
    return "TEXT"


def load_dataframe(df: pd.DataFrame, table: str, replace: bool = False) -> tuple[int, int]:
    """Create `table` from df and insert all rows. Returns (rows, columns).

    Raises FileExistsError if the table exists and replace is False.
    """
    from psycopg2 import sql
    from psycopg2.extras import execute_values

    from .db import get_conn, table_exists

    if df is None or df.empty or len(df.columns) == 0:
        raise ValueError("The file has no data.")
    table = clean_name(table, prefix="t_")
    if table_exists(table) and not replace:
        raise FileExistsError(table)

    df = prepare(df)
    types = {c: pg_type(df[c]) for c in df.columns}
    records = [tuple(r) for r in df.astype(object).where(df.notna(), None).itertuples(index=False, name=None)]

    conn = get_conn()
    try:
        cur = conn.cursor()
        if replace:
            cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(table)))
        columns_ddl = sql.SQL(", ").join(
            sql.SQL("{} {}").format(sql.Identifier(c), sql.SQL(t)) for c, t in types.items()
        )
        cur.execute(sql.SQL("CREATE TABLE {} ({})").format(sql.Identifier(table), columns_ddl))
        insert = sql.SQL("INSERT INTO {} ({}) VALUES %s").format(
            sql.Identifier(table), sql.SQL(", ").join(sql.Identifier(c) for c in df.columns)
        )
        execute_values(cur, insert.as_string(conn), records, page_size=1000)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return len(df), len(df.columns)
