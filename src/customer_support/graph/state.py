"""The graph's state.

The fields fall into three lifetimes, and `finalize_turn` is what enforces the
difference:

**Conversation-lived** -- survives every turn:
    `messages`, `customer`

**Turn-lived** -- working values, cleared before `END` so the next turn cannot
read a stale one:
    `route`, `response_language`, `questions`, `retrieval`, `answer_draft`,
    `grounding`, `ticket_draft`

**Turn output** -- what the UI renders for the turn that just ended. Written
fresh on every turn (never carried over), and readable from the state
`invoke()` returns:
    `final_response`, `response_evidence`, `ticket_id`
"""

from typing import Literal, NotRequired

from langgraph.graph import MessagesState

from customer_support.rag.schema import EvidenceItem, RetrievalResult
from customer_support.schemas import (
    CustomerContext,
    GroundingState,
    TicketDraftState,
)


class State(MessagesState):
    """State for one conversation thread.

    Attributes:
        customer: Loaded once per thread by `load_customer_if_needed`.
        route: The router's decision for this turn.
        response_language: `"ar"` or `"en"`, set by the router. The single
            source of truth for every customer-facing node in the turn.
        questions: The independently searchable questions the message was
            decomposed into. Carried from `decompose_question` to
            `search_subquestions`.
        retrieval: Per-question evidence, scores and the aggregate outcome.
        answer_draft: The grounded answer before verification. Becomes
            `final_response` only if `grounding["grounded"]` is true.
        grounding: The verifier's verdict on `answer_draft`.
        answer_revision_count: How many times this turn's draft has been
            revised after a failed verdict. Absent means 0 -- read it as
            `state.get("answer_revision_count", 0)`. Incremented only by
            `revise_answer`; never reset by `generate_answer`.
        ticket_draft: The ticket agent's three reasoned fields, before
            `create_ticket` adds the trusted ones.
        ticket_id: The ticket created this turn, or `None` if none was.
        final_response: What was said to the customer this turn. Also appended
            to `messages`; kept separately so the UI does not have to guess
            which message belongs to this turn.
        response_evidence: The passages behind this turn's response, for the
            UI's evidence expander. Empty when the turn did not retrieve.
    """

    customer: NotRequired[CustomerContext | None]

    route: NotRequired[Literal["respond_directly", "retrieve_evidence"] | None]
    response_language: NotRequired[Literal["ar", "en"] | None]

    questions: NotRequired[list[str] | None]
    retrieval: NotRequired[RetrievalResult | None]
    answer_draft: NotRequired[str | None]
    grounding: NotRequired[GroundingState | None]
    answer_revision_count: NotRequired[int]

    ticket_draft: NotRequired[TicketDraftState | None]
    ticket_id: NotRequired[str | None]

    final_response: NotRequired[str | None]
    response_evidence: NotRequired[list[EvidenceItem]]
