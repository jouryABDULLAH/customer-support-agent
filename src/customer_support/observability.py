"""Centralized logging and LangSmith tracing setup.

Every entry point calls `configure_logging()` and then `configure_tracing()`
before doing anything else. Order matters for tracing: langsmith caches env
reads (`get_env_var` is `lru_cache`d in `langsmith/utils.py`), so the tracing
environment must be settled before any code queries it.

Tracing is wired entirely through environment variables -- this module never
constructs a `langsmith.Client` and never contacts LangSmith, so enabling it
here cannot fail on bad credentials. LangChain picks the variables up on its
own when a model call happens.

Variables (export in the shell; this application reads the process
environment and never loads a `.env` file):

    LANGSMITH_TRACING=true      turn tracing on
    LANGSMITH_API_KEY           required for tracing to actually be enabled
    LANGSMITH_PROJECT           optional; defaults to "customer-support-agent"
    LANGSMITH_ENDPOINT          optional; only for EU/self-hosted instances

If tracing is requested but no API key is present, tracing is forced OFF with
a warning and the application continues normally.
"""

import logging
import os

from customer_support.config import LOG_LEVEL

logger = logging.getLogger(__name__)

DEFAULT_LANGSMITH_PROJECT = "customer-support-agent"

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


def _tracing_requested() -> bool:
    """Whether the environment asks for tracing, under either spelling.

    langsmith itself compares the value against the literal `"true"`, so a
    shell that exports `True` or `1` would silently not trace; any truthy
    spelling is accepted here and normalized to `"true"` on enable.
    """
    for name in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2"):
        if os.environ.get(name, "").strip().lower() in ("true", "1", "yes"):
            return True
    return False


def _clear_langsmith_env_cache() -> None:
    """Drop langsmith's cached env reads so our mutations are seen.

    `langsmith.utils.get_env_var` is `lru_cache`d; without this, a value read
    before `configure_tracing()` ran would shadow whatever it set.
    """
    from langsmith import utils as ls_utils

    ls_utils.get_env_var.cache_clear()


def configure_tracing() -> bool:
    """Wire LangSmith tracing from the environment. Returns True if enabled.

    Never contacts LangSmith and never validates the key -- it only settles
    the environment LangChain reads. Missing credentials therefore cannot
    break anything: tracing is forced off and the application runs normally.
    """
    if not _tracing_requested():
        logger.info("tracing: disabled (LANGSMITH_TRACING is not set).")
        return False

    if not (os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY")):
        # Both spellings are forced off: langsmith falls back to the legacy
        # LANGCHAIN_ name, so disabling only one would leave tracing on.
        os.environ["LANGSMITH_TRACING"] = "false"
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        _clear_langsmith_env_cache()
        logger.warning(
            "tracing: requested but LANGSMITH_API_KEY is not set; tracing is "
            "disabled for this run. Export it in your shell to enable: "
            '$env:LANGSMITH_API_KEY = "..."  (PowerShell)'
        )
        return False

    os.environ["LANGSMITH_TRACING"] = "true"
    project = os.environ.get("LANGSMITH_PROJECT") or os.environ.get("LANGCHAIN_PROJECT")
    if not project:
        project = DEFAULT_LANGSMITH_PROJECT
        os.environ["LANGSMITH_PROJECT"] = project
    _clear_langsmith_env_cache()

    endpoint = os.environ.get("LANGSMITH_ENDPOINT") or os.environ.get("LANGCHAIN_ENDPOINT")
    logger.info(
        "tracing: enabled, project=%r%s (key presence checked only; not validated).",
        project,
        f", endpoint={endpoint}" if endpoint else "",
    )
    return True
