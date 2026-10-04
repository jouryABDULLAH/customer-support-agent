"""The ticket assistant: the graph's one agent.

A `create_agent` loop over the customer's tickets -- the pending draft and the
submitted ones. It is added to the graph as a node and shares `messages`,
`ticket_draft` and `ticket_id` with it.

Every write that reaches the database (`submit_draft`, `update_ticket`,
`cancel_ticket`) waits for the customer's approval through
`HumanInTheLoopMiddleware`, so the model can propose those actions but never
take them on its own. Edits to the pending draft need no approval: nothing is
filed until it is submitted.

Which customer the tickets belong to comes from the runtime `Context`, never
from the model. Only OPEN tickets can be changed.
"""

import logging
from contextlib import closing
from typing import Literal, NotRequired

from langchain.agents import AgentState, create_agent
from langchain.agents.middleware import (
    HumanInTheLoopMiddleware,
    ModelRequest,
    dynamic_prompt,
)
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from customer_support.config import TICKET_PRODUCT
from customer_support.db import tickets as db
from customer_support.db.connection import connect
from customer_support.graph.context import Context
from customer_support.graph.nodes import _LANGUAGE_NAMES
from customer_support.model import build_model
from customer_support.prompts import TICKET_ASSISTANT_PROMPT
from customer_support.schemas import CustomerContext, TicketCategory, TicketDraftState

logger = logging.getLogger(__name__)

# The tools that write to the database; each pauses for approval.
APPROVAL_REQUIRED = ("submit_draft", "update_ticket", "cancel_ticket")


class TicketAssistantState(AgentState):
    """The graph state keys the agent reads or writes."""

    customer: NotRequired[CustomerContext | None]
    response_language: NotRequired[Literal["ar", "en"] | None]
    ticket_draft: NotRequired[TicketDraftState | None]
    ticket_id: NotRequired[str | None]


Runtime = ToolRuntime[Context, TicketAssistantState]


def _changes(category, subject, problem_description) -> dict | str:
    """The fields being changed, or an error for the model."""
    changes = {
        name: value
        for name, value in (
            ("category", category),
            ("subject", subject),
            ("problem_description", problem_description),
        )
        if value is not None
    }
    if not changes:
        return "No field was given to change."
    if any(not value.strip() for value in changes.values()):
        return "A field cannot be changed to blank text."
    return changes


def _open_ticket(conn, ticket_id: str, customer_id: str):
    """The customer's OPEN ticket, or an error for the model."""
    row = db.get_ticket(conn, ticket_id)
    if row is None or row["customer_id"] != customer_id:
        return f"This customer has no ticket {ticket_id}."
    if row["status"] != db.OPEN:
        return f"Ticket {ticket_id} is {row['status']}; only OPEN tickets can be changed."
    return row


@tool
def list_my_tickets(runtime: Runtime) -> str:
    """List the customer's submitted tickets, newest first."""
    with closing(connect()) as conn:
        rows = db.list_tickets(conn, customer_id=runtime.context.customer_id)
    if not rows:
        return "The customer has no submitted tickets."
    return "\n".join(
        f"{row['id']} | {row['status']} | {row['category']} | {row['subject']} | "
        f"created {row['created_at'][:16]}"
        for row in rows
    )


@tool
def get_ticket(ticket_id: str, runtime: Runtime) -> str:
    """Read one of the customer's submitted tickets in full."""
    with closing(connect()) as conn:
        row = db.get_ticket(conn, ticket_id)
    if row is None or row["customer_id"] != runtime.context.customer_id:
        return f"This customer has no ticket {ticket_id}."
    return (
        f"id: {row['id']}\nstatus: {row['status']}\ncategory: {row['category']}\n"
        f"subject: {row['subject']}\ncreated: {row['created_at']}\n"
        f"problem_description:\n{row['problem_description']}\n"
        f"original_message:\n{row['original_message']}"
    )


@tool
def edit_draft(
    runtime: Runtime,
    category: TicketCategory | None = None,
    subject: str | None = None,
    problem_description: str | None = None,
) -> Command | str:
    """Change fields of the pending, not yet submitted, ticket draft.

    Pass only the fields being changed.
    """
    draft = runtime.state.get("ticket_draft")
    if not draft:
        return "There is no pending ticket draft."
    changes = _changes(category, subject, problem_description)
    if isinstance(changes, str):
        return changes
    logger.info("ticket_assistant: draft edited (%s)", ", ".join(changes))
    return Command(update={
        "ticket_draft": {**draft, **changes},
        "messages": [ToolMessage("Draft updated.", tool_call_id=runtime.tool_call_id)],
    })


@tool
def submit_draft(runtime: Runtime) -> Command | str:
    """Submit the pending ticket draft as an OPEN ticket."""
    draft = runtime.state.get("ticket_draft")
    if not draft:
        return "There is no pending ticket draft."
    with closing(connect()) as conn:
        ticket_id = db.create_ticket(
            conn,
            customer_id=runtime.context.customer_id,
            product=TICKET_PRODUCT,
            category=draft["category"],
            subject=draft["subject"],
            problem_description="\n\n".join(
                part for part in (draft["problem_description"], draft["coverage"]) if part
            ),
            original_message=draft["original_message"],
        )
    logger.info(
        "ticket: created %s for customer %s (product=%s, category=%s)",
        ticket_id, runtime.context.customer_id, TICKET_PRODUCT, draft["category"],
    )
    return Command(update={
        "ticket_draft": None,
        "ticket_id": ticket_id,
        "messages": [
            ToolMessage(f"Submitted as ticket {ticket_id}.", tool_call_id=runtime.tool_call_id)
        ],
    })


@tool
def discard_draft(runtime: Runtime) -> Command | str:
    """Drop the pending ticket draft without submitting it."""
    if not runtime.state.get("ticket_draft"):
        return "There is no pending ticket draft."
    logger.info("ticket_assistant: draft discarded")
    return Command(update={
        "ticket_draft": None,
        "messages": [ToolMessage("Draft discarded.", tool_call_id=runtime.tool_call_id)],
    })


@tool
def update_ticket(
    ticket_id: str,
    runtime: Runtime,
    category: TicketCategory | None = None,
    subject: str | None = None,
    problem_description: str | None = None,
) -> str:
    """Change fields of one of the customer's OPEN submitted tickets.

    Pass only the fields being changed.
    """
    changes = _changes(category, subject, problem_description)
    if isinstance(changes, str):
        return changes
    with closing(connect()) as conn:
        row = _open_ticket(conn, ticket_id, runtime.context.customer_id)
        if isinstance(row, str):
            return row
        db.update_ticket(conn, ticket_id, **changes)
    logger.info("ticket: updated %s (%s)", ticket_id, ", ".join(changes))
    return f"Ticket {ticket_id} updated."


@tool
def cancel_ticket(ticket_id: str, runtime: Runtime) -> str:
    """Cancel one of the customer's OPEN submitted tickets."""
    with closing(connect()) as conn:
        row = _open_ticket(conn, ticket_id, runtime.context.customer_id)
        if isinstance(row, str):
            return row
        db.update_ticket_status(conn, ticket_id, "CLOSED")
    logger.info("ticket: cancelled %s", ticket_id)
    return f"Ticket {ticket_id} cancelled."


@dynamic_prompt
def _system_prompt(request: ModelRequest) -> str:
    """The instructions, plus the customer's name, this turn's reply language
    and the pending draft."""
    state = request.state
    customer = state.get("customer") or {}
    draft = state.get("ticket_draft")
    pending = (
        f"category: {draft['category']}\nsubject: {draft['subject']}\n"
        f"problem_description:\n{draft['problem_description']}"
        if draft
        else "none"
    )
    language = _LANGUAGE_NAMES[state.get("response_language") or "ar"]
    return (
        f"{TICKET_ASSISTANT_PROMPT}\n\nREPLY LANGUAGE: {language}\n\n"
        f"CUSTOMER NAME: {customer.get('name') or 'unknown'}\n\n"
        f"PENDING DRAFT:\n{pending}"
    )


def build_ticket_assistant():
    """Compile the agent, to be added to the graph as a node."""
    return create_agent(
        build_model(0.0),
        tools=[
            list_my_tickets,
            get_ticket,
            edit_draft,
            submit_draft,
            discard_draft,
            update_ticket,
            cancel_ticket,
        ],
        middleware=[
            _system_prompt,
            HumanInTheLoopMiddleware(
                interrupt_on={
                    name: {"allowed_decisions": ["approve", "reject"]}
                    for name in APPROVAL_REQUIRED
                }
            ),
        ],
        state_schema=TicketAssistantState,
        context_schema=Context,
        name="ticket_assistant",
    )
