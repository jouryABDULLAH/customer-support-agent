"""Schemas for the graph's LLM boundaries and for its state.

Two kinds live here, and the split is deliberate:

* **Pydantic models** (`RouteDecision`, `GroundingResult`, `TicketDraft`) are
  *model output*. They carry `extra="forbid"` so a model that invents a field
  fails loudly at the boundary instead of quietly writing junk into state.
* **`TypedDict`s** (`CustomerContext`, `GroundingState`, `TicketDraftState`)
  are what the application stores in graph state. They are plain dicts because
  everything in state is round-tripped through the SQLite checkpointer's
  serializer, and a plain dict survives that unchanged; a Pydantic instance is
  a class the deserializer has to reconstruct.

So each model-facing schema has a state twin: the node validates with the
Pydantic model, then stores `.model_dump()`. Retrieval schemas are the one
exception -- in `rag/schema.py`.
"""

from typing import Literal, NotRequired, TypedDict

from pydantic import BaseModel, ConfigDict

# The taxonomy a ticket is filed under. Constrained here rather than in the
# database (migration 001 leaves `category` plain TEXT) because it is the
# model that must choose from a closed set.
TicketCategory = Literal[
    "account",
    "billing",
    "technical",
    "usage",
    "policy",
    "other",
]


class CustomerContext(TypedDict):
    """The customer, as carried in graph state."""

    id: str
    name: NotRequired[str | None]
    email: NotRequired[str | None]
    phone: NotRequired[str | None]


class RouteDecision(BaseModel):
    """Router output: where the turn goes, and which language to answer in.

    `response_language` is decided here for every route, so one classification
    call settles it for whichever node ends up replying.
    """

    model_config = ConfigDict(extra="forbid")

    next_step: Literal["respond_directly", "retrieve_evidence"]
    response_language: Literal["ar", "en"]


class GroundingResult(BaseModel):
    """Verifier output: whether every claim in the draft is supported.

    `reason` is internal -- it is logged and handed to the ticket agent when
    verification fails, never shown to the customer.
    """

    model_config = ConfigDict(extra="forbid")

    grounded: bool
    reason: str


class GroundingState(TypedDict):
    """`GroundingResult` as stored in graph state."""

    grounded: bool
    reason: str


class TicketDraft(BaseModel):
    """The only ticket fields a model is allowed to produce.

    Everything else on a ticket -- id, customer_id, product, original_message,
    status, created_at -- is supplied by the application in `create_ticket`.
    Those are trusted values; a model that could write them could corrupt the
    audit trail of what the customer actually said.
    """

    model_config = ConfigDict(extra="forbid")

    category: TicketCategory
    subject: str
    problem_description: str


class TicketDraftState(TypedDict):
    """`TicketDraft` as stored in graph state."""

    category: str
    subject: str
    problem_description: str
