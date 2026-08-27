"""Prompt text for the RAG pipeline's LLM calls.

Import the constants from here rather than from the submodules:

    from customer_support.rag.prompts import DECOMPOSE_QUESTIONS_PROMPT
"""

from customer_support.rag.prompts.decomposition import DECOMPOSE_QUESTIONS_PROMPT
from customer_support.rag.prompts.grounded_answer import (
    CUSTOMER_NAME_NOTE,
    GROUNDED_ANSWER_PROMPT,
    REVISE_ANSWER_PROMPT,
)

__all__ = [
    "CUSTOMER_NAME_NOTE",
    "DECOMPOSE_QUESTIONS_PROMPT",
    "GROUNDED_ANSWER_PROMPT",
    "REVISE_ANSWER_PROMPT",
]
