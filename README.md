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

When the UI escalates a request, the graph pauses for ticket review. Edit the
subject, category, and problem description, then choose **Open ticket**, or
decline to finish without creating one. Customer identity and the original
request remain application-controlled; retrieval coverage is appended when saved.

API callers resume the pending checkpoint using the same `thread_id`:

```python
from langgraph.types import Command

graph.invoke(Command(resume={
    "approved": True,
    "ticket_draft": {
        "category": "billing",
        "subject": "Corrected subject",
        "problem_description": "Corrected problem description",
    },
}), config=config)
```

Use `{"approved": False}` to decline, or `{"approved": True}` to approve
unchanged. Invalid input pauses again for correction. The implementation follows
[LangGraph's interrupt rules](https://docs.langchain.com/oss/python/langgraph/interrupts):
one JSON-serializable interrupt in a dedicated node, outside exception handlers,
with ticket creation in a separate node after approval.

## Checks

```powershell
python scripts/check.py             # offline suites, no services needed
python scripts/check.py --live      # full end-to-end suite
python -m unittest discover -s tests -v  # ticket review and Streamlit form checks
```
