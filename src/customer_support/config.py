"""Application configuration, read from the process environment."""

import os

RAG_TENANT = os.environ.get("RAG_TENANT", "customer_support_demo")

DOCS_DIR = os.environ.get("DOCS_DIR", "Docs")

# Wall-clock ceiling for one `find()` call. ragent2 defaults to 120s. 
FIND_TIMEOUT_SECONDS = float(os.environ.get("FIND_TIMEOUT_SECONDS", "420"))


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
