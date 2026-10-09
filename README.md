# ClariSQL: Text-to-SQL with a Clarification Engine

Ask questions about a PostgreSQL database in plain English. If the question is vague
("show me top customers"), the system **asks a follow-up question instead of guessing**.
Clear questions are converted to SQL, validated, executed safely, and shown as a table.

**Stack:** Python, PostgreSQL, Pydantic, Gemini / OpenAI / Groq, Streamlit

## How it works

```
User question
     |
     v
LLM (schema + rules in prompt, JSON reply validated by Pydantic `Decision`)
     |-- ambiguous --> ask clarifying questions --> user answers --> back to LLM (with history)
     |-- clear -----> SQL
                        |
                        v
              Validator (SELECT only, one statement, allow-listed tables, no dangerous functions)
                        |
                        v
        PostgreSQL (READ ONLY transaction + 5 s statement timeout, max 200 rows)
                        |-- error --> error sent back to LLM --> corrected SQL (max 2 repairs)
                        v
                  Result table + SQL + assumptions
```

## Setup

```bash
# 1. Install
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 2. Start PostgreSQL (or use any existing Postgres and edit DATABASE_URL)
docker compose up -d

# 3. Configure keys (all three are free-tier friendly; use at least one)
cp .env.example .env        # then edit .env

# 4. Create and fill the sample e-commerce database
python -m db.seed

# 5. Run
streamlit run streamlit_app.py        # web UI
python cli.py --provider groq         # or terminal version
```

Free API keys: Gemini (aistudio.google.com), Groq (console.groq.com), OpenAI (platform.openai.com).

## Try these

| Question | Expected behaviour |
|---|---|
| How many customers do we have? | Direct answer |
| Total revenue by product category | Direct answer (joins 3 tables) |
| Show me top customers | **Asks:** by revenue or orders? |
| Show recent orders | **Asks:** what time window? |
| ...then reply "by revenue, last 30 days" | Generates SQL using your answers |
| Delete all orders | Refused (only SELECT allowed) |

## Project layout

```
clarisql/
  config.py      settings from .env
  models.py      Pydantic `Decision` (the structured-output contract)
  prompts.py     system prompt: clarification rules + SQL rules
  llm.py         one client for Gemini / OpenAI / Groq, JSON parsing + retry
  validator.py   static SQL safety checks
  db.py          schema introspection + read-only execution
  engine.py      the clarification + self-repair pipeline
db/              schema.sql and seed.py (sample data)
streamlit_app.py web UI          cli.py terminal UI
benchmark.py     compares providers, writes benchmark_results.csv
tests/           validator + engine tests (no API or DB needed)
```

## Testing and benchmark

```bash
pytest -q                                   # unit tests
python benchmark.py gemini openai groq      # accuracy + latency table for your report
```

The benchmark has 8 clear questions (checked by comparing result sets against hand-written
SQL) and 3 ambiguous ones (correct behaviour = ask for clarification).

## Safety layers (good for the viva)

1. Prompt only allows a single SELECT.
2. `validator.py` blocks write keywords, multiple statements, dangerous functions, unknown tables.
3. PostgreSQL runs the query in a `READ ONLY` transaction (the database refuses writes itself).
4. 5-second statement timeout and 200-row cap.
5. For production you would also use a dedicated DB user with SELECT-only grants.

## Ideas to extend

- Use a real company-style database with 15+ tables; test how accuracy drops as schema grows.
- Add few-shot examples or schema retrieval (embed table descriptions, send only relevant tables).
- Add result charts, query history, and CSV export.
- Log every question, SQL and feedback; measure how often clarification was actually needed.
- Add a "user-feedback" thumbs up/down to build your own evaluation set.
