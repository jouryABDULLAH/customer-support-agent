"""Application configuration, read from the process environment."""

import os

RAG_TENANT = os.environ.get("RAG_TENANT", "customer_support_demo")

DOCS_DIR = os.environ.get("DOCS_DIR", "Docs")

APP_DB_PATH = os.environ.get("APP_DB_PATH", "data/app.db")

# LangGraph thread checkpoints. Deliberately a separate file from APP_DB_PATH:
# the checkpointer owns its schema and rewrites it on library upgrades, and
# application rows must never be collateral in that.
CHECKPOINT_DB_PATH = os.environ.get("CHECKPOINT_DB_PATH", "data/checkpoints.db")

# The only product this deployment answers for currently.
TICKET_PRODUCT = "MSEGAT"

# Wall-clock ceiling for one `find()` call. ragent2 defaults to 120s.
FIND_TIMEOUT_SECONDS = float(os.environ.get("FIND_TIMEOUT_SECONDS", "420"))

# Cross-encoder rerank score at or above which a subquestion's retrieval counts
# as HIGH confidence. NOT a probability of answer correctness -- just a cutoff
# separating two observed groups. Re-run scripts/calibrate_threshold.py after
# any change to the indexed documents.
#
# Measured 2026-08-26 over the four MSEGAT documents:
#   supported (ar)            0.9815 .. 0.9964
#   supported (en)            0.8705 .. 0.9565
#   adjacent-unsupported (ar) 0.0378 .. 0.2542   e.g. "ربط مسجات مع Salesforce"
#   unsupported               0.0002 .. 0.0005
# Lowest supported 0.8705 vs highest unsupported 0.2542, so anything in
# (0.2542, 0.8705] separates them. 0.55 sits near the middle of that band,
# leaving ~0.3 of margin on each side rather than hugging either group.
#
# Safe as a single global cutoff only because we never pass `article_number` to
# search(): that is the sole trigger for ragent2's exact-match anchor path,
# which returns Qdrant RRF scores on a different scale (`is_anchor=True`).
# Every score we see is a bge-reranker score.
RAG_CONFIDENCE_THRESHOLD = float(os.environ.get("RAG_CONFIDENCE_THRESHOLD", "0.55"))

# Consumed by `observability.configure_logging()`, the central logging setup.
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# Whether `deliver_answer` strips the model's citation markers (e.g. 【1†L1-L3】)
# before the reply reaches the customer. OFF by default: during development the
# markers show which evidence passage each claim leaned on, which is worth more
# than polish. Flip on for a customer-facing deployment:
#   $env:STRIP_CITATION_MARKERS = "true"
STRIP_CITATION_MARKERS = (
    os.environ.get("STRIP_CITATION_MARKERS", "false").strip().lower()
    in ("true", "1", "yes")
)


def groq_api_key() -> str:
    """The Groq key, from the shell environment.

    Raises:
        RuntimeError: If it is unset, naming how to set it.
    """
    try:
        return os.environ["GROQ_API_KEY"]
    except KeyError:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Export it in your shell before running: "
            "$env:GROQ_API_KEY = '...'  (PowerShell)"
        ) from None
