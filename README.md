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

When a request cannot be answered, the agent drafts a ticket and shows it in
the conversation; nothing is filed yet. Reply in the chat to change any part
of it, submit it, or drop it. The same conversation handles tickets already
submitted: ask about them, change their category, subject or description, or
cancel them. Only OPEN tickets can be changed.

Every action that writes a ticket -- submitting, changing, cancelling -- pauses
for approval, and the UI shows **Approve** / **Reject**. Customer identity and
the original request remain application-controlled; retrieval coverage is
appended when the ticket is submitted.

API callers resume the pending checkpoint using the same `thread_id`:

```python
from langgraph.types import Command

graph.invoke(Command(resume={"decisions": [{"type": "approve"}]}), config=config, context=context)
```

Use `{"type": "reject"}` to refuse; the agent then asks what to do instead.

## Checks

```powershell
python scripts/check.py             # offline suites, no services needed
python scripts/check.py --live      # full end-to-end suite
python -m unittest discover -s tests -v  # ticket assistant and approval card checks
```
