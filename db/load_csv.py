"""Command-line loader.  Usage: python -m db.load_csv file.csv [table_name]

Replaces the table if it already exists. (The web UI has an Upload button too.)
"""
import sys
from pathlib import Path

from clarisql.loader import clean_name, load_dataframe, read_csv


def main(path: str, table: str | None = None) -> None:
    df = read_csv(path)
    table = clean_name(table or Path(path).stem, prefix="t_")
    rows, cols = load_dataframe(df, table, replace=True)
    print(f"Loaded {rows} rows into table '{table}' ({cols} columns).")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python -m db.load_csv file.csv [table_name]")
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
