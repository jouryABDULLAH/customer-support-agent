"""Application configuration, read from the process environment."""

import logging
import os

RAG_TENANT = os.environ.get("RAG_TENANT", "customer_support_demo")

DOCS_DIR = os.environ.get("DOCS_DIR", "Docs")

APP_DB_PATH = os.environ.get("APP_DB_PATH", "data/app.db")

# Wall-clock ceiling for one `find()` call. ragent2 defaults to 120s.
FIND_TIMEOUT_SECONDS = float(os.environ.get("FIND_TIMEOUT_SECONDS", "420"))

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
