# Customer Support Agent

A customer-support agent that answers customer messages from indexed product documents (RAGent2 retrieval + LangGraph workflow).
Questions the documents cover are answered with cited evidence; anything else is escalated as a ticket for a human.

## Setup

Requires Python 3.12, Docker, and the private `ragent2` package.

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install ragent2            # private package, install from its wheel
pip install -e . --no-deps
pip install langgraph-checkpoint-sqlite

$env:GROQ_API_KEY = "..."      # shell only; never put it in .env
$env:PYTHONIOENCODING = "utf-8"
```

Optional variables (LangSmith tracing, log level, paths) are listed in `.env.example`.

## Run

```powershell
ragent2 up                          # starts Qdrant + docling-serve
python scripts/init_db.py           # create the SQLite database
python scripts/ingest_docs.py       # index Docs/ (run once, and after doc changes)
streamlit run src/customer_support/ui.py
```

CLI alternative: `python scripts/run_workflow.py "your message"`.

## Checks

```powershell
python scripts/check.py             # offline suites, no services needed
python scripts/check.py --live      # full end-to-end suite
```
