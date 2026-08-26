"""Conditional-edge functions: which node runs next.

Each reads a decision another node already recorded in state and returns a
node name. They make no decisions of their own -- routing on a value someone
else computed keeps the choice visible in the checkpoint, so a replayed thread
takes the same path it took live.
"""

import logging
from typing import Literal

from customer_support.graph.state import State

logger = logging.getLogger(__name__)


def route_after_router(state: State) -> Literal["respond_directly", "decompose_question"]:
    """Direct reply, or the retrieval path.

    An absent route means the router call did not record one; retrieval is the
    safe side of that, since it can only end in a grounded answer or a ticket,
    whereas a direct reply to a support question is exactly the unsupported
    claim this graph exists to prevent.
    """
    if state.get("route") == "respond_directly":
        return "respond_directly"
    return "decompose_question"


def route_after_retrieval(state: State) -> Literal["generate_answer", "ticket_agent"]:
    """Answer only when every question cleared the threshold.

    One weak question escalates the whole turn. Answering the strong ones and
    staying silent on the rest would read to the customer as a complete answer.
    """
    retrieval = state.get("retrieval")
    if retrieval and retrieval["outcome"] == "all_high":
        return "generate_answer"
    return "ticket_agent"


def route_after_verification(state: State) -> Literal["deliver_answer", "ticket_agent"]:
    """Send the draft only if the verifier passed it.

    A failed verdict discards the draft rather than repairing it. What the
    verifier found is not a wording problem -- it is a claim the evidence does
    not support, so there is nothing to send and a human has to answer.
    """
    grounding = state.get("grounding")
    if grounding and grounding["grounded"]:
        return "deliver_answer"
    logger.info("verification failed; escalating to a ticket.")
    return "ticket_agent"
