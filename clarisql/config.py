import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional
    pass

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/clarisql"
)
DEFAULT_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")

MODELS = {
    "gemini": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    "openai": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    "groq": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
}

MAX_ROWS = int(os.getenv("MAX_ROWS", "200"))          # rows returned to the UI
STATEMENT_TIMEOUT_MS = int(os.getenv("STATEMENT_TIMEOUT_MS", "5000"))
MAX_REPAIR_ATTEMPTS = int(os.getenv("MAX_REPAIR_ATTEMPTS", "2"))
