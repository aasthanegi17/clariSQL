"""Plain-English notes about the data (definitions the AI cannot guess from column names)."""
from __future__ import annotations

import os
from pathlib import Path

NOTES_PATH = Path(os.getenv("NOTES_FILE", Path(__file__).resolve().parent.parent / "notes.md"))


def load_notes() -> str:
    try:
        return NOTES_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def save_notes(text: str) -> None:
    NOTES_PATH.write_text(text.strip() + "\n", encoding="utf-8")
