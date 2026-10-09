"""The Clarification Engine: decide -> (ask | generate) -> validate -> run -> self-repair."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Literal, Optional

from .config import MAX_REPAIR_ATTEMPTS, MAX_ROWS
from .models import Decision
from .prompts import REPAIR_TEMPLATE, build_system_prompt
from .validator import UnsafeSQLError, validate_sql

Executor = Callable[[str, int], tuple[list[str], list[tuple], bool]]

WRITE_INTENT = re.compile(
    r"^\s*(please\s+|can you\s+|could you\s+)?(delete|drop|truncate|insert|erase|wipe|alter)\b",
    re.I,
)


@dataclass
class EngineResult:
    status: Literal["clarify", "answer", "error"]
    reasoning: str = ""
    questions: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    sql: Optional[str] = None
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    truncated: bool = False
    repairs: int = 0
    latency_s: float = 0.0
    error: Optional[str] = None


class TextToSQLEngine:
    """Stateful per conversation: the history lets users answer clarifying questions."""

    HISTORY_WINDOW = 12

    def __init__(
        self,
        llm,
        schema_text: str,
        allowed_tables: Iterable[str],
        executor: Executor,
        max_rows: int = MAX_ROWS,
        max_repairs: int = MAX_REPAIR_ATTEMPTS,
    ):
        self.llm = llm
        self.schema_text = schema_text
        self.allowed_tables = set(allowed_tables)
        self.executor = executor
        self.max_rows = max_rows
        self.max_repairs = max_repairs
        self.history: list[dict] = []

    def reset(self) -> None:
        self.history.clear()

    def _window(self) -> list[dict]:
        msgs = self.history[-self.HISTORY_WINDOW :]
        while msgs and msgs[0]["role"] != "user":
            msgs = msgs[1:]
        return msgs

    # ------------------------------------------------------------------ public
    def ask(self, user_text: str) -> EngineResult:
        start = time.perf_counter()
        if WRITE_INTENT.match(user_text):
            return EngineResult(
                "error",
                error="ClariSQL is read-only. I can answer questions about the data, "
                      "but I can't change it. Try asking to view or count the records instead.",
            )

        system = build_system_prompt(self.schema_text)
        self.history.append({"role": "user", "content": user_text})

        try:
            decision = self.llm.generate(system, self._window(), Decision)
        except Exception as exc:  # network, quota, invalid JSON twice...
            self.history.pop()
            return EngineResult("error", error=f"LLM call failed: {exc}", latency_s=time.perf_counter() - start)

        self.history.append({"role": "assistant", "content": decision.model_dump_json()})

        if decision.needs_clarification:
            return EngineResult(
                "clarify",
                reasoning=decision.reasoning,
                questions=decision.clarifying_questions,
                latency_s=time.perf_counter() - start,
            )
        return self._execute_with_repair(system, decision, start)

    # ----------------------------------------------------------------- internals
    def _execute_with_repair(self, system: str, decision: Decision, start: float) -> EngineResult:
        scratch = list(self._window())  # includes the assistant decision just added
        current = decision
        repairs = 0

        while True:
            sql = current.sql or ""
            try:
                clean = validate_sql(sql, self.allowed_tables)
                columns, rows, truncated = self.executor(clean, self.max_rows)
                # remember the final (possibly repaired) decision in the real history
                self.history[-1] = {"role": "assistant", "content": current.model_dump_json()}
                return EngineResult(
                    "answer",
                    reasoning=current.reasoning,
                    assumptions=current.assumptions,
                    sql=clean,
                    columns=columns,
                    rows=rows,
                    truncated=truncated,
                    repairs=repairs,
                    latency_s=time.perf_counter() - start,
                )
            except Exception as exc:
                error = str(exc).strip() or exc.__class__.__name__
                if repairs >= self.max_repairs:
                    return EngineResult(
                        "error",
                        reasoning=current.reasoning,
                        sql=sql,
                        repairs=repairs,
                        error=error,
                        latency_s=time.perf_counter() - start,
                    )
                repairs += 1
                scratch.append({"role": "user", "content": REPAIR_TEMPLATE.format(sql=sql, error=error)})
                try:
                    current = self.llm.generate(system, scratch, Decision)
                except Exception as llm_exc:
                    return EngineResult(
                        "error", sql=sql, repairs=repairs,
                        error=f"Repair failed: {llm_exc}", latency_s=time.perf_counter() - start,
                    )
                if current.needs_clarification:
                    self.history[-1] = {"role": "assistant", "content": current.model_dump_json()}
                    return EngineResult(
                        "clarify", reasoning=current.reasoning,
                        questions=current.clarifying_questions,
                        latency_s=time.perf_counter() - start,
                    )
                scratch.append({"role": "assistant", "content": current.model_dump_json()})
