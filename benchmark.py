"""Compare providers on a golden set.  Usage: python benchmark.py gemini openai groq

Each case is either:
  * a CLEAR question with an expected SQL (we compare result sets), or
  * an AMBIGUOUS question where the correct behaviour is to ask for clarification.
Results are printed as a table and saved to benchmark_results.csv for your report.
"""
from itertools import permutations
import csv
import sys
from decimal import Decimal

from clarisql.config import MAX_ROWS, MODELS
from clarisql.db import load_schema, run_select
from clarisql.engine import TextToSQLEngine
from clarisql.llm import LLMClient

CASES = [
    ("How many customers do we have?", "SELECT COUNT(*) FROM customers"),
    ("How many orders were cancelled?", "SELECT COUNT(*) FROM orders WHERE status='cancelled'"),
    ("List the 5 most expensive products with their prices",
     "SELECT name, price FROM products ORDER BY price DESC LIMIT 5"),
    ("How many customers are there in each country?",
     "SELECT country, COUNT(*) FROM customers GROUP BY country"),
    ("What is the total revenue from delivered orders?",
     "SELECT SUM(oi.quantity*oi.unit_price) FROM order_items oi JOIN orders o ON o.order_id=oi.order_id "
     "WHERE o.status='delivered'"),
    ("Total quantity sold per product category, counting all orders including cancelled ones",
     "SELECT p.category, SUM(oi.quantity) FROM order_items oi JOIN products p ON p.product_id=oi.product_id "
     "GROUP BY p.category"),
    ("How many orders were placed by customers from Delhi?",
     "SELECT COUNT(*) FROM orders o JOIN customers c ON c.customer_id=o.customer_id WHERE c.city='Delhi'"),
    ("Which payment method is used for the most payments?",
     "SELECT method FROM payments GROUP BY method ORDER BY COUNT(*) DESC LIMIT 1"),
    # ambiguous -> expect clarification
    ("Show me top customers", "CLARIFY"),
    ("Show recent orders", "CLARIFY"),
    ("Which products are doing best?", "CLARIFY"),
]


def norm(rows):
    def cell(v):
        return round(float(v), 2) if isinstance(v, (Decimal, float)) else str(v)
    return sorted(tuple(cell(v) for v in r) for r in rows)

def matches(expected, got):
    """True if the expected columns appear in the generated result (extra columns allowed)."""
    if not expected or not got:
        return not expected and not got
    k, n = len(expected[0]), len(got[0])
    if k > n:
        return False
    target = norm(expected)
    return any(
        norm([tuple(r[i] for i in cols) for r in got]) == target
        for cols in permutations(range(n), k)
    )

def main(providers):
    schema = load_schema()
    summary, detail = [], []
    for prov in providers:
        engine = TextToSQLEngine(LLMClient(prov), schema.text, schema.tables, run_select, MAX_ROWS)
        correct, total_time = 0, 0.0
        for question, expected in CASES:
            engine.reset()
            res = engine.ask(question)
            total_time += res.latency_s
            if expected == "CLARIFY":
                ok = res.status == "clarify"
            else:
                ok = False
                if res.status == "answer":
                    _, exp_rows, _ = run_select(expected, 10_000)
                    ok = matches(exp_rows, res.rows)
            correct += ok
            detail.append([prov, question, res.status, ok, res.repairs, f"{res.latency_s:.2f}"])
            print(f"[{prov}] {'PASS' if ok else 'FAIL'}  {question}")
            if not ok:
                print(f"      status={res.status}, sql={res.sql}")
        summary.append((prov, MODELS[prov], correct, len(CASES), total_time / len(CASES)))

    print("\n| Provider | Model | Accuracy | Avg latency (s) |\n|---|---|---|---|")
    for prov, model, c, n, t in summary:
        print(f"| {prov} | {model} | {c}/{n} ({100*c/n:.0f}%) | {t:.2f} |")

    with open("benchmark_results.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["provider", "question", "status", "correct", "repairs", "latency_s"])
        w.writerows(detail)
    print("\nSaved benchmark_results.csv")


if __name__ == "__main__":
    main(sys.argv[1:] or ["gemini", "openai", "groq"])
