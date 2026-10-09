"""Pydantic models: the strict contract between the LLM and our code."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, model_validator


class Decision(BaseModel):
    """What the LLM must return for every turn.

    Either it asks clarifying questions, or it returns SQL (never both).
    """

    reasoning: str = Field(description="One or two sentences explaining the decision")
    needs_clarification: bool
    clarifying_questions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    sql: Optional[str] = None

    @model_validator(mode="after")
    def _consistency(self) -> "Decision":
        if self.needs_clarification:
            self.clarifying_questions = [q for q in self.clarifying_questions if q.strip()][:3]
            if not self.clarifying_questions:
                raise ValueError("needs_clarification=true requires at least one question")
            self.sql = None
        else:
            if not self.sql or not self.sql.strip():
                raise ValueError("needs_clarification=false requires a non-empty 'sql'")
            self.clarifying_questions = []
        return self
