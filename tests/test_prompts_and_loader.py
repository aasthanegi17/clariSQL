import pandas as pd

from clarisql.loader import clean_name, dedupe, pg_type, prepare
from clarisql.prompts import build_system_prompt


def test_prompt_includes_schema_and_notes():
    p = build_system_prompt("TABLE students\n  exam_score bigint", "exam_score is out of 100 {not a format field}")
    assert "TABLE students" in p
    assert "exam_score is out of 100 {not a format field}" in p
    assert '"needs_clarification": true or false' in p  # JSON example braces survived


def test_prompt_without_notes():
    assert "(none)" in build_system_prompt("TABLE t", "")


def test_clean_name():
    assert clean_name("Hours Studied (per week)") == "hours_studied_per_week"
    assert clean_name("2024 Sales", prefix="c_") == "c_2024_sales"
    assert clean_name("???") == "col"
    assert clean_name("Students Performance.csv".rsplit(".", 1)[0]) == "students_performance"


def test_dedupe():
    assert dedupe(["a", "a", "b", "a"]) == ["a", "a_2", "b", "a_3"]


def test_prepare_cleans_names_and_detects_dates():
    df = pd.DataFrame({
        "Order Date": ["2024-01-05", "2024-02-10", "2024-03-15"],
        "Order Date ": ["x", "y", "z"],
        "Gender": ["Male", "Female", "Male"],
        "Score": [1, 2, 3],
    })
    out = prepare(df)
    assert list(out.columns) == ["order_date", "order_date_2", "gender", "score"]
    assert pd.api.types.is_datetime64_any_dtype(out["order_date"])
    assert not pd.api.types.is_datetime64_any_dtype(out["gender"])


def test_pg_types():
    assert pg_type(pd.Series([1, 2])) == "BIGINT"
    assert pg_type(pd.Series([1.5])) == "DOUBLE PRECISION"
    assert pg_type(pd.Series(["a"])) == "TEXT"
    assert pg_type(pd.Series([True, False])) == "BOOLEAN"
