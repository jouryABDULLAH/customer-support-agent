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
    after_agent,
    dynamic_prompt,
)
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import AIMessage, ToolMessage
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

# What the customer is told after a write tool runs. Written here rather than
# by the model: the reply is the same sentence every time, and left to
# `gpt-oss-120b` it drifted -- one observed reply ended in a stray
# "(أو أيّ\xa0\xa0...)" and pluralized "the ticket". Every tool below is
# `return_direct`, so this text is the agent's last word on the turn.
_EDIT_TEXT = {
    "ar": {
        "changed": "تم تعديل {fields}. هل ترغب بإرسال التذكرة؟",
        "no_draft": "لا توجد مسودة تذكرة حالياً.",
        "unclear": "لم يتضح لي ما تريد تعديله. ما الذي ترغب بتغييره في التذكرة؟",
        "category": "الفئة",
        "subject": "الموضوع",
        "problem_description": "وصف المشكلة",
        "join": " و",
    },
    "en": {
        "changed": "I changed the {fields}. Shall I submit the ticket?",
        "no_draft": "There is no ticket draft at the moment.",
        "unclear": "I did not catch what to change. What would you like changed on the ticket?",
        "category": "category",
        "subject": "subject",
        "problem_description": "problem description",
        "join": " and ",
    },
}

_SUBMIT_TEXT = {
    "ar": {"ok": "تم إرسال التذكرة برقم {ticket_id}.", "no_draft": _EDIT_TEXT["ar"]["no_draft"]},
    "en": {"ok": "Submitted as ticket {ticket_id}.", "no_draft": _EDIT_TEXT["en"]["no_draft"]},
}

_DISCARD_TEXT = {
    "ar": {"ok": "تم تجاهل المسودة.", "no_draft": _EDIT_TEXT["ar"]["no_draft"]},
    "en": {"ok": "Draft discarded.", "no_draft": _EDIT_TEXT["en"]["no_draft"]},
}

_UPDATE_TEXT = {
    "ar": {**_EDIT_TEXT["ar"], "changed": "تم تعديل {fields} للتذكرة {ticket_id}."},
    "en": {**_EDIT_TEXT["en"], "changed": "I changed the {fields} on ticket {ticket_id}."},
}

_CANCEL_TEXT = {
    "ar": "تم إلغاء التذكرة {ticket_id}.",
    "en": "Ticket {ticket_id} cancelled.",
}

_NOT_FOUND_TEXT = {
    "ar": "لا توجد لدى هذا العميل تذكرة بالرقم {ticket_id}.",
    "en": "This customer has no ticket {ticket_id}.",
}

_NOT_OPEN_TEXT = {
    "ar": "التذكرة {ticket_id} بحالة {status}؛ يمكن تعديل التذاكر المفتوحة (OPEN) فقط.",
    "en": "Ticket {ticket_id} is {status}; only OPEN tickets can be changed.",
}


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


def _open_ticket(conn, ticket_id: str, customer_id: str, language: str):
    """The customer's OPEN ticket, or a templated reply for the customer."""
    row = db.get_ticket(conn, ticket_id)
    if row is None or row["customer_id"] != customer_id:
        return _NOT_FOUND_TEXT[language].format(ticket_id=ticket_id)
    if row["status"] != db.OPEN:
        return _NOT_OPEN_TEXT[language].format(ticket_id=ticket_id, status=row["status"])
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


def _language(runtime: Runtime) -> str:
    return runtime.state.get("response_language") or "ar"


def _direct_reply(runtime: Runtime, text: str, **state_updates) -> Command:
    """End the turn saying `text`, with any other state changes.

    Every tool below is `return_direct`, so the agent stops here and `text` is
    its last word; `_publish_direct_return` turns it into the customer's
    reply.
    """
    return Command(update={
        "messages": [ToolMessage(text, tool_call_id=runtime.tool_call_id)],
        **state_updates,
    })


@tool(return_direct=True)
def edit_draft(
    runtime: Runtime,
    category: TicketCategory | None = None,
    subject: str | None = None,
    problem_description: str | None = None,
) -> Command:
    """Change fields of the pending, not yet submitted, ticket draft.

    Pass only the fields being changed. Do not write a reply afterwards: the
    customer is told what changed and asked whether to submit.
    """
    text = _EDIT_TEXT[_language(runtime)]
    draft = runtime.state.get("ticket_draft")
    if not draft:
        return _direct_reply(runtime, text["no_draft"])
    changes = _changes(category, subject, problem_description)
    if isinstance(changes, str):
        return _direct_reply(runtime, text["unclear"])
    logger.info("ticket_assistant: draft edited (%s)", ", ".join(changes))
    return _direct_reply(
        runtime,
        text["changed"].format(fields=text["join"].join(text[name] for name in changes)),
        ticket_draft={**draft, **changes},
    )


@tool(return_direct=True)
def submit_draft(runtime: Runtime) -> Command:
    """Submit the pending ticket draft as an OPEN ticket."""
    text = _SUBMIT_TEXT[_language(runtime)]
    draft = runtime.state.get("ticket_draft")
    if not draft:
        return _direct_reply(runtime, text["no_draft"])
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
    return _direct_reply(
        runtime, text["ok"].format(ticket_id=ticket_id), ticket_draft=None, ticket_id=ticket_id
    )


@tool(return_direct=True)
def discard_draft(runtime: Runtime) -> Command:
    """Drop the pending ticket draft without submitting it."""
    text = _DISCARD_TEXT[_language(runtime)]
    if not runtime.state.get("ticket_draft"):
        return _direct_reply(runtime, text["no_draft"])
    logger.info("ticket_assistant: draft discarded")
    return _direct_reply(runtime, text["ok"], ticket_draft=None)


@tool(return_direct=True)
def update_ticket(
    ticket_id: str,
    runtime: Runtime,
    category: TicketCategory | None = None,
    subject: str | None = None,
    problem_description: str | None = None,
) -> Command:
    """Change fields of one of the customer's OPEN submitted tickets.

    Pass only the fields being changed.
    """
    language = _language(runtime)
    text = _UPDATE_TEXT[language]
    changes = _changes(category, subject, problem_description)
    if isinstance(changes, str):
        return _direct_reply(runtime, text["unclear"])
    with closing(connect()) as conn:
        row = _open_ticket(conn, ticket_id, runtime.context.customer_id, language)
        if isinstance(row, str):
            return _direct_reply(runtime, row)
        db.update_ticket(conn, ticket_id, **changes)
    logger.info("ticket: updated %s (%s)", ticket_id, ", ".join(changes))
    fields = text["join"].join(text[name] for name in changes)
    return _direct_reply(runtime, text["changed"].format(fields=fields, ticket_id=ticket_id))


@tool(return_direct=True)
def cancel_ticket(ticket_id: str, runtime: Runtime) -> Command:
    """Cancel one of the customer's OPEN submitted tickets."""
    language = _language(runtime)
    with closing(connect()) as conn:
        row = _open_ticket(conn, ticket_id, runtime.context.customer_id, language)
        if isinstance(row, str):
            return _direct_reply(runtime, row)
        db.update_ticket_status(conn, ticket_id, "CLOSED")
    logger.info("ticket: cancelled %s", ticket_id)
    return _direct_reply(runtime, _CANCEL_TEXT[language].format(ticket_id=ticket_id))


@after_agent
def _publish_direct_return(state: TicketAssistantState, runtime) -> dict | None:
    """Say what a `return_direct` tool answered.

    Such a tool ends the agent's turn, leaving its own result as the last
    message. The customer is shown `messages`, and a `ToolMessage` is not a
    reply, so it is republished as one.
    """
    last = state["messages"][-1]
    if not isinstance(last, ToolMessage):
        return None
    return {"messages": [AIMessage(str(last.content))]}


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
            _publish_direct_return,
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
