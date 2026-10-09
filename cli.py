"""Terminal version:  python cli.py --provider groq"""
import argparse

from clarisql.config import DEFAULT_PROVIDER, MAX_ROWS
from clarisql.db import load_schema, run_select
from clarisql.engine import TextToSQLEngine
from clarisql.llm import LLMClient


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default=DEFAULT_PROVIDER, choices=["gemini", "openai", "groq"])
    args = ap.parse_args()

    schema = load_schema()
    engine = TextToSQLEngine(LLMClient(args.provider), schema.text, schema.tables, run_select, MAX_ROWS)
    print(f"ClariSQL ({args.provider}). Type 'new' to reset, 'quit' to exit.\n")

    while True:
        q = input("you> ").strip()
        if q in {"quit", "exit"}:
            break
        if q == "new":
            engine.reset()
            print("(conversation reset)")
            continue
        if not q:
            continue
        res = engine.ask(q)
        if res.status == "clarify":
            print("\nI need a bit more detail:")
            for i, question in enumerate(res.questions, 1):
                print(f"  {i}. {question}")
            print()
        elif res.status == "error":
            print(f"\nError: {res.error}\n")
        else:
            print(f"\nSQL:\n{res.sql}\n")
            for a in res.assumptions:
                print(f"assumption: {a}")
            print(" | ".join(res.columns))
            for row in res.rows[:20]:
                print(" | ".join(str(v) for v in row))
            extra = " (truncated)" if res.truncated else ""
            print(f"\n{len(res.rows)} rows{extra}, {res.repairs} repairs, {res.latency_s:.2f}s\n")


if __name__ == "__main__":
    main()
