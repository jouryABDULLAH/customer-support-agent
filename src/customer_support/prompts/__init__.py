"""Prompt text for the graph's LLM calls.

Import the constants from here rather than from the submodules:

    from customer_support.prompts import ROUTE_MESSAGE_PROMPT

The RAG pipeline's own prompts live separately, in
`customer_support.rag.prompts`, next to the modules that use them.
"""

from customer_support.prompts.direct_response import DIRECT_RESPONSE_PROMPT
from customer_support.prompts.router import ROUTE_MESSAGE_PROMPT
from customer_support.prompts.ticket import TICKET_DRAFT_PROMPT
from customer_support.prompts.verifier import VERIFY_GROUNDING_PROMPT

__all__ = [
    "DIRECT_RESPONSE_PROMPT",
    "ROUTE_MESSAGE_PROMPT",
    "TICKET_DRAFT_PROMPT",
    "VERIFY_GROUNDING_PROMPT",
]
