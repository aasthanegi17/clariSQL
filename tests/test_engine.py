"""Engine tests with a fake LLM and fake database (no network, no Postgres needed)."""
from clarisql.engine import TextToSQLEngine
from clarisql.models import Decision


class FakeLLM:
    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.calls = 0

    def generate(self, system, messages, schema_model, retries=1):
        self.calls += 1
        return self.decisions.pop(0)


def ok_executor(sql, max_rows):
    return ["n"], [(5,)], False


def make(decisions, executor=ok_executor):
    llm = FakeLLM(decisions)
    return TextToSQLEngine(llm, "TABLE customers", {"customers"}, executor), llm


def clarify():
    return Decision(reasoning="vague", needs_clarification=True, clarifying_questions=["By revenue or orders?"])


def answer(sql="SELECT COUNT(*) FROM customers"):
    return Decision(reasoning="clear", needs_clarification=False, sql=sql)


def test_clear_question_runs_directly():
    engine, _ = make([answer()])
    res = engine.ask("how many customers?")
    assert res.status == "answer" and res.rows == [(5,)] and res.repairs == 0


def test_ambiguous_question_asks_then_answers():
    engine, llm = make([clarify(), answer()])
    first = engine.ask("top customers")
    assert first.status == "clarify" and first.questions == ["By revenue or orders?"]
    second = engine.ask("by revenue")
    assert second.status == "answer"
    assert llm.calls == 2
    assert [m["role"] for m in engine.history] == ["user", "assistant", "user", "assistant"]


def test_unsafe_sql_is_repaired():
    engine, _ = make([answer("DROP TABLE customers"), answer()])
    res = engine.ask("show all customers")
    assert res.status == "answer" and res.repairs == 1


def test_gives_up_after_max_repairs():
    engine, _ = make([answer("DROP TABLE a")] * 5)
    res = engine.ask("x")
    assert res.status == "error" and res.repairs == engine.max_repairs


def test_db_error_is_fed_back_and_fixed():
    calls = {"n": 0}

    def flaky(sql, max_rows):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError('column "nme" does not exist')
        return ["n"], [(1,)], False

    engine, _ = make([answer("SELECT nme FROM customers"), answer("SELECT 1 FROM customers")], flaky)
    res = engine.ask("names")
    assert res.status == "answer" and res.repairs == 1


def test_decision_model_rejects_inconsistent_output():
    import pytest
    with pytest.raises(ValueError):
        Decision(reasoning="x", needs_clarification=True)
    with pytest.raises(ValueError):
        Decision(reasoning="x", needs_clarification=False)

def test_write_request_is_refused_without_calling_llm():
    engine, llm = make([])
    res = engine.ask("Delete all orders")
    assert res.status == "error" and "read-only" in res.error
    assert llm.calls == 0