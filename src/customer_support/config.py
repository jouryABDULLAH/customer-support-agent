"""Application configuration, read from the process environment."""

import logging
import os

RAG_TENANT = os.environ.get("RAG_TENANT", "customer_support_demo")

DOCS_DIR = os.environ.get("DOCS_DIR", "Docs")

APP_DB_PATH = os.environ.get("APP_DB_PATH", "data/app.db")

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

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# "OFF" is this project's addition, not a stdlib level -- configure_logging()
# handles it separately via logging.disable() rather than a numeric level.
_LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}
_LOG_LEVEL_NAMES = frozenset(_LOG_LEVELS) | {"OFF"}


def configure_logging(level_name: str | None = None) -> None:
    """Set up root logging for a script, honoring `LOG_LEVEL` (env or arg).

    `level_name` defaults to `LOG_LEVEL`. Any of DEBUG/INFO/WARNING/ERROR/
    CRITICAL behaves as the stdlib normally does. `OFF` is this project's
    addition: it calls `logging.disable()`, which suppresses every log call
    process-wide -- stronger than setting a level, since a level only filters
    at each logger and can be defeated by a library that sets its own.

    Raises:
        ValueError: If `level_name` is not one of the names above.
    """
    name = (level_name or LOG_LEVEL).upper()
    if name not in _LOG_LEVEL_NAMES:
        raise ValueError(
            f"Unknown LOG_LEVEL {name!r}; expected one of {sorted(_LOG_LEVEL_NAMES)}."
        )
    if name == "OFF":
        logging.disable(logging.CRITICAL)
        return
    logging.disable(logging.NOTSET)  # undo a previous OFF, if any
    logging.basicConfig(
        level=_LOG_LEVELS[name],
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        force=True,
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
