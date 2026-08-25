"""RAGent2 initialization.

One `Ragent` per process (it owns the Qdrant client, the embedding models and
the cross-encoder), and one application-level tenant. Callers ask for
`get_documents()` and get a `ragent2.api.Tenant`; nothing above this module
constructs `Settings` or `Ragent`.
"""

from ragent2 import Ragent
from ragent2.config import Settings

from customer_support.config import FIND_TIMEOUT_SECONDS, RAG_TENANT, groq_api_key

_rag: Ragent | None = None


def get_rag() -> Ragent:
    """The process-wide `Ragent`, built on first use.

    `Settings` is constructed explicitly rather than through ragent2's
    `get_settings()`, which would load a `.env`; the key comes from the shell.
    """
    global _rag
    if _rag is None: # hasn't been initialized yet
        _rag = Ragent(
            settings=Settings(
                groq_api_key=groq_api_key(),
                find_timeout_seconds=FIND_TIMEOUT_SECONDS,
            )
        )
    return _rag


def get_documents():
    """The tenant-scoped document interface every RAG call goes through."""
    return get_rag().tenant(RAG_TENANT)


def check_health():
    """Probe Qdrant and docling-serve. Returns a `ragent2.health.HealthReport`."""
    return get_rag().health()
