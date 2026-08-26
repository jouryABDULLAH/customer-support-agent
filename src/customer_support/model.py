"""The application's single seam onto the chat model.

Every LLM call in this project goes through `build_model` or
`invoke_structured` here, and nothing outside this module imports
`ragent2.llm.client`. RAGent2 is a private package whose LLM client is not
really part of its documented surface, so confining it to one file means
swapping it later (for a plain `ChatGroq`, or another provider) is one edit
rather than a search across the codebase.

What is being borrowed from RAGent2, and why it is worth the coupling:

  * the connection details for this environment -- the me-central-1 Groq base
    URL, the transport retry budget, the request timeout; and
  * `invoke_structured`'s repair loop for Groq's `json_validate_failed` 400,
    where the model emits JSON its own schema rejects. That failure was
    observed live during Phase 1 ingestion, and the loop re-serializes the
    rejected output rather than redoing the work.

Both default to `settings.answer_model`. Callers pass a `ragent2.config.Settings`
-- usually `get_rag().settings`, so the whole process shares one configuration
-- or omit it and let this module fetch that same shared one.
"""

from ragent2.llm.client import build_llm as _build_llm
from ragent2.llm.client import invoke_structured as _invoke_structured


def _shared_settings():
    """The process-wide `Settings`, imported lazily to avoid an import cycle."""
    from customer_support.rag.client import get_rag

    return get_rag().settings


def build_model(temperature: float | None = None, *, settings=None, model: str | None = None):
    """A chat model for free-form generation.

    Args:
        temperature: `None` uses `settings.answer_temperature`, which is tuned
            for prose. Pass 0.0 where reproducibility matters more.
        settings: `ragent2.config.Settings`; `None` uses the shared one.
        model: Groq model id; `None` uses `settings.answer_model`.
    """
    settings = settings or _shared_settings()
    return _build_llm(
        model or settings.answer_model,
        settings.answer_temperature if temperature is None else temperature,
        settings=settings,
    )


def invoke_structured(
    schema,
    messages,
    *,
    settings=None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    model: str | None = None,
):
    """Call the model for structured output validated against `schema`.

    Retries Groq's `json_validate_failed` 400 by asking the model to re-emit
    its own rejected output as valid JSON.

    Args:
        schema: A Pydantic model; use `extra="forbid"` so the model cannot
            invent fields.
        temperature: Defaults to 0.0 -- these calls are classifications and
            extractions, where sampling buys nothing.
        max_tokens: `None` uses `settings.metadata_max_output_tokens`, the
            ceiling RAGent2 tuned for short-verdict calls. Groq reserves
            `prompt + max_tokens` against the per-minute token limit, so a
            needlessly large ceiling costs throughput, not just headroom.
    """
    settings = settings or _shared_settings()
    return _invoke_structured(
        schema,
        messages,
        model=model or settings.answer_model,
        settings=settings,
        temperature=temperature,
        max_tokens=(
            settings.metadata_max_output_tokens if max_tokens is None else max_tokens
        ),
    )
