"""The graph's nodes: one function per box in the workflow.

Each takes `State` and returns only the keys it changed. Nodes hold the
behavior; `builder.py` only wires them together, and `routing.py` only reads
state to pick an edge.

Three kinds, kept honestly apart:

* **Deterministic** -- `load_customer_if_needed`, `search_subquestions`,
  `deliver_answer`, `propose_ticket`, `finalize_turn`. No model is consulted
  where there is nothing to reason about.
* **Focused LLM calls** -- `router`, `respond_directly`, `decompose_question`,
  `generate_answer`, `verify`, `ticket_agent`. One responsibility each; the
  structured ones validate against `extra="forbid"` schemas so a model cannot
  widen its own remit.
* **Retrieval** -- `search_subquestions`, delegating to the `rag` package
  unchanged.

The one agent, `ticket_assistant`, lives in `ticket_assistant.py`.

Database connections are opened per call rather than held: `sqlite3`
connections belong to the thread that created them, LangGraph may run nodes
off-thread, and opening a local SQLite file is cheap.
"""

import logging
import re
from contextlib import closing

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

from customer_support.config import STRIP_CITATION_MARKERS
from customer_support.db.connection import connect
from customer_support.db.customers import get_customer
from customer_support.graph.context import Context
from customer_support.graph.state import State
from customer_support.model import build_model, invoke_structured
from customer_support.prompts import (
    DIRECT_RESPONSE_PROMPT,
    ROUTE_MESSAGE_PROMPT,
    TICKET_DRAFT_PROMPT,
    VERIFY_GROUNDING_PROMPT,
)
from customer_support.rag.answer import evidence_block, generate_answer, revise_answer
from customer_support.rag.prompts import CUSTOMER_NAME_NOTE
from customer_support.rag.client import get_rag
from customer_support.rag.decompose import decompose
from customer_support.rag.schema import EvidenceItem
from customer_support.rag.search import low_confidence_questions, search_questions
from customer_support.schemas import GroundingResult, RouteDecision, TicketDraft

logger = logging.getLogger(__name__)

# The customer-facing proposal for an escalated turn. Deterministic text, not
# a generated one: it makes no claim about the product, so there is nothing
# here for a model to get wrong. The draft itself is not in it -- the UI shows
# the pending draft in its own box, from state.
_TICKET_PROPOSAL = {
    "ar": (
        "لم أتمكن من الإجابة على استفسارك من المصادر المعتمدة لدي، "
        "لذلك جهّزت مسودة تذكرة دعم. هل ترغب بإرسالها؟ "
        "يمكنك أيضاً أن تطلب مني تعديل أي جزء منها."
    ),
    "en": (
        "I could not answer your question from my approved sources, so I have "
        "drafted a support ticket. Shall I submit it? You can also ask me to "
        "change any part of it."
    ),
}

# Headings for the coverage section appended to the ticket's description, in
# the ticket's language. Deterministic for the same reason as
# `_TICKET_PROPOSAL`: which questions the documents cover is already known from
# retrieval, and the ticket agent, left to restate it, flattened it into
# "nothing was answerable".
_TICKET_COVERAGE = {
    "ar": {
        "not_covered": "لا تجيب الوثائق المعتمدة عن:",
        "covered": "تغطي الوثائق ما يلي، لكن لم يُرسل أي رد للعميل:",
        "unanswered_draft": (
            "تمت صياغة رد من الوثائق لكنه لم يُجب عن سؤال العميل، ولم يُرسل. "
            "سبب المدقق:"
        ),
        "failed_draft": (
            "تمت صياغة إجابة من الوثائق لكنها لم تجتز التحقق، ولم تُرسل. "
            "سبب المدقق:"
        ),
    },
    "en": {
        "not_covered": "The approved documents do not answer:",
        "covered": "The documents cover the following, but no reply was sent to the customer:",
        "unanswered_draft": (
            "A reply was drafted from the documents but did not answer the "
            "customer's question, so it was not sent. Verifier reason:"
        ),
        "failed_draft": (
            "An answer was drafted from the documents but failed verification, "
            "so it was not sent. Verifier reason:"
        ),
    },
}

_LANGUAGE_NAMES = {"ar": "Arabic", "en": "English"}


def _settings():
    """The shared RAGent2 `Settings` every model call in this turn uses."""
    return get_rag().settings


def _customer_message(state: State) -> str:
    """The text of the turn's customer message.

    Scans back for the last human message rather than taking `messages[-1]`,
    so a node that runs after something has already been appended still reads
    what the customer actually wrote. `ticket_agent` records this verbatim.
    """
    for message in reversed(state["messages"]):
        if isinstance(message, HumanMessage):
            return str(message.content)
    raise ValueError("No customer message in this thread; nothing to act on.")


def _previous_reply(state: State) -> str:
    """What the agent last said to the customer before this turn's message.

    Skips tool calls, which the customer never saw. Empty on a first turn.
    """
    seen_customer = False
    for message in reversed(state["messages"]):
        if isinstance(message, HumanMessage):
            seen_customer = True
        elif seen_customer and isinstance(message, AIMessage) and message.content and not message.tool_calls:
            return str(message.content)
    return ""


def _language(state: State) -> str:
    """The router's `response_language` for this turn, defaulting to Arabic.

    The default is a floor, not a decision: the router sets this on every
    path, so it only applies if a node is invoked outside the graph.
    """
    return state.get("response_language") or "ar"


def _customer_name(state: State) -> str | None:
    """The customer's name, or None -- `name` is nullable in the schema."""
    customer = state.get("customer")
    return customer.get("name") if customer else None


def load_customer_if_needed(state: State, runtime: Runtime[Context]) -> dict:
    """Put the customer in state, if it is not there already.

    Reads the id from runtime context, never from the message. A checkpointed
    thread already carries the customer, so this touches the database once per
    thread rather than once per turn.

    Raises:
        LookupError: If the id is unknown. Registration belongs to the
            channel, which knows what it collected and can ask for the rest;
            a graph that invented a customer row here would attach tickets to
            an identity nobody can contact.
    """
    if state.get("customer"): # customer already in state
        return {}

    customer_id = runtime.context.customer_id
    with closing(connect()) as conn:
        row = get_customer(conn, customer_id)
    if row is None:
        raise LookupError(
            f"Customer {customer_id!r} is not in the database. Customers must "
            "be created by the channel before starting a conversation."
        )

    logger.info("customer: loaded %s from the database", customer_id)
    return {
        "customer": {
            "id": row["id"],
            "name": row["name"],
            "email": row["email"],
            "phone": row["phone"],
        }
    }


def router(state: State) -> dict:
    """Classify the turn: direct reply, retrieval, or ticket handling, and the
    reply language.

    Classification only -- it retrieves nothing and answers nothing.
    `extra="forbid"` on `RouteDecision` is what holds it to that at the
    boundary. As the first node of every turn it also resets the turn
    output, so a turn that writes none does not publish the previous one's.
    """
    pending = "yes" if state.get("ticket_draft") else "no"
    decision = invoke_structured(
        RouteDecision,
        [
            {"role": "system", "content": ROUTE_MESSAGE_PROMPT},
            {
                "role": "user",
                "content": (
                    f"PENDING TICKET DRAFT: {pending}\n\n"
                    f"PREVIOUS REPLY: {_previous_reply(state) or '(none)'}\n\n"
                    f"Message: {_customer_message(state)}"
                ),
            },
        ],
        settings=_settings(),
    )
    logger.info(
        "router: next_step=%s response_language=%s",
        decision.next_step,
        decision.response_language,
    )
    return {
        "route": decision.next_step,
        "response_language": decision.response_language,
        "final_response": None,
        "ticket_id": None,
    }


def respond_directly(state: State) -> dict:
    """Reply to a message that needs no company knowledge.

    The prompt forbids product claims, which is the whole safety story for
    this path: nothing was retrieved, so anything factual it said would come
    from model memory.
    """
    language = _language(state)
    system = DIRECT_RESPONSE_PROMPT
    name = _customer_name(state)
    if name:
        system += CUSTOMER_NAME_NOTE.format(name=name)
    llm = build_model(settings=_settings())
    response = llm.invoke(
        [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"REPLY LANGUAGE: {_LANGUAGE_NAMES[language]}\n\n"
                    f"Customer's message:\n{_customer_message(state)}"
                ),
            },
        ]
    )
    text = str(response.content).strip()
    logger.info("respond_directly: %d chars in %s", len(text), language)
    return {"final_response": text, "messages": [AIMessage(content=text)]}


def decompose_question(state: State) -> dict:
    """Split the message into independently searchable questions."""
    return {"questions": decompose(_customer_message(state), _settings())}


def search_subquestions(state: State) -> dict:
    """Search every question exactly once and aggregate the outcome."""
    
    retrieval = search_questions(state["questions"] or [])
    logger.info(
        "retrieval: %d question(s) -> %s",
        len(retrieval["results"]),
        retrieval["outcome"],
    )
    return {"retrieval": retrieval}


def generate_answer_node(state: State) -> dict:
    """Draft one grounded answer covering every question.

    Reached only on `all_high`, so the prompt never has to reason about weak
    evidence. The draft is not the reply yet -- `verify` decides that.
    """
    draft = generate_answer(
        _customer_message(state),
        state["retrieval"],
        _settings(),
        _language(state),
        customer_name=_customer_name(state),
    )
    return {"answer_draft": draft}


def revise_answer_node(state: State) -> dict:
    """Correct the draft using the verifier's reason, then re-verify.

    Runs at most `MAX_ANSWER_REVISIONS` times per turn -- the routing after
    `verify` counts `answer_revision_count`, which this node increments only
    when it actually produces a revision. The failed draft is never appended
    to `messages`; only `deliver_answer` publishes an answer.
    """
    grounding = state.get("grounding") or {}
    revised = revise_answer(
        _customer_message(state),
        state["retrieval"],
        state["answer_draft"] or "",
        grounding.get("reason", "unknown"),
        _settings(),
        _language(state),
    )
    count = state.get("answer_revision_count", 0) + 1
    logger.info("revision %d: draft revised, re-verifying", count)
    return {"answer_draft": revised, "answer_revision_count": count}


def verify(state: State) -> dict:
    """Check every factual claim in the draft against the evidence.

    A second, narrower model call rather than trust in the first: the
    answering prompt is told to stay grounded, but "told to" is not a control.
    The verifier sees the same evidence rendering the author saw, and judges
    meaning across languages -- the evidence is Arabic while an English
    customer gets an English draft, and a check on wording would reject every
    one of those.
    """
    result = invoke_structured(
        GroundingResult,
        [
            {"role": "system", "content": VERIFY_GROUNDING_PROMPT},
            {
                "role": "user",
                "content": (
                    f"DRAFT REPLY:\n{state['answer_draft']}\n\n"
                    f"EVIDENCE:\n\n{evidence_block(state['retrieval'])}"
                ),
            },
        ],
        settings=_settings(),
    )
    logger.info(
        "grounding: grounded=%s answered=%s reason=%s",
        result.grounded, result.answered, result.reason,
    )
    return {
        "grounding": {
            "grounded": result.grounded,
            "answered": result.answered,
            "reason": result.reason,
        }
    }


# The model's invented reference markers, e.g. 【1†L1-L3】. Any preceding
# whitespace goes with the marker so removal leaves no double spaces.
_CITATION_MARKER = re.compile(r"\s*【[^】]*】")


def deliver_answer(state: State) -> dict:
    """Send the verified draft to the customer.

    Citation markers are stripped only when `STRIP_CITATION_MARKERS` is set:
    in development they show which evidence passage each claim leaned on, so
    the default keeps them. The verifier always sees the unstripped draft --
    stripping happens here, after the verdict, never before it.
    """
    answer = state["answer_draft"]
    if STRIP_CITATION_MARKERS:
        answer = _CITATION_MARKER.sub("", answer).strip()
    return {"final_response": answer, "messages": [AIMessage(content=answer)]}


def _unresolved_notes(state: State) -> str:
    """What the ticket agent is told could not be answered, and why.

    The graph already knows which questions came back weak and whether
    verification failed; handing that over as notes keeps the ticket agent
    from having to rediscover any of it, and keeps retrieval scores out of a
    prompt that has no use for them.
    """
    retrieval = state.get("retrieval")
    grounding = state.get("grounding")

    if retrieval is None:
        return "The message was escalated before any evidence was retrieved."

    if retrieval["outcome"] == "needs_escalation":
        unanswered = low_confidence_questions(retrieval)
        answered = [
            r["question"] for r in retrieval["results"] if r["confidence"] == "high"
        ]
        notes = "The approved documents do not answer:\n" + "\n".join(
            f"- {q}" for q in unanswered
        )
        if answered:
            # Named so the engineer does not re-research the whole message.
            # Nothing was sent to the customer: a partial answer would read as
            # a complete one, so the whole turn escalates.
            notes += (
                "\n\nThe documents do cover the following, but no reply was "
                "sent to the customer:\n"
                + "\n".join(f"- {q}" for q in answered)
            )
        return notes

    reason = grounding["reason"] if grounding else "unknown"
    if grounding and grounding["grounded"] and not grounding["answered"]:
        return (
            "Evidence was retrieved and an answer was drafted, but the draft "
            "did not answer the customer's question from it; no reply was sent "
            f"to the customer. Verifier reason: {reason}"
        )
    revisions = state.get("answer_revision_count", 0)
    attempted = (
        f" A corrected draft was attempted {revisions} time(s) and still "
        "failed." if revisions else ""
    )
    return (
        "Evidence was found and an answer was drafted, but it failed grounding "
        f"verification and was discarded.{attempted} Verifier reason: {reason}"
    )


def ticket_agent(state: State) -> dict:
    """Draft the three ticket fields that need reasoning.

    Category, subject and problem description only. The draft also records
    the customer's message and `_coverage_section` now, because it is
    submitted on a later turn, when both are gone from state. Everything else
    a ticket is trusted for -- who it belongs to, when, which product, what
    status -- is added at submission from values the application holds.
    """
    draft = invoke_structured(
        TicketDraft,
        [
            {"role": "system", "content": TICKET_DRAFT_PROMPT},
            {
                "role": "user",
                "content": (
                    f"TICKET LANGUAGE: {_LANGUAGE_NAMES[_language(state)]}\n\n"
                    f"CUSTOMER'S MESSAGE:\n{_customer_message(state)}\n\n"
                    f"UNRESOLVED:\n{_unresolved_notes(state)}"
                ),
            },
        ],
        settings=_settings(),
    )
    logger.info("ticket_agent: category=%s subject=%r", draft.category, draft.subject)
    return {
        "ticket_draft": {
            **draft.model_dump(),
            "original_message": _customer_message(state),
            "coverage": _coverage_section(state),
        }
    }


def _coverage_section(state: State) -> str:
    """What the documents did and did not answer, for the ticket description.

    Built from retrieval and the verdict, never from the model. The verifier's
    reason is internal and always English; it is included as written.
    """
    retrieval = state.get("retrieval")
    if retrieval is None:
        return ""
    text = _TICKET_COVERAGE[_language(state)]

    if retrieval["outcome"] == "needs_escalation":
        section = text["not_covered"] + "\n" + "\n".join(
            f"- {q}" for q in low_confidence_questions(retrieval)
        )
        covered = [
            r["question"] for r in retrieval["results"] if r["confidence"] == "high"
        ]
        if covered:
            section += "\n\n" + text["covered"] + "\n" + "\n".join(
                f"- {q}" for q in covered
            )
        return section

    grounding = state.get("grounding")
    reason = grounding["reason"] if grounding else "unknown"
    if grounding and grounding["grounded"] and not grounding["answered"]:
        return f"{text['unanswered_draft']} {reason}"
    return f"{text['failed_draft']} {reason}"


def propose_ticket(state: State) -> dict:
    """Show the customer the drafted ticket and ask before submitting it.

    Nothing is persisted here: the draft stays in state, and the customer's
    reply -- submit, change something, or drop it -- goes to
    `ticket_assistant` on the next turn.
    """
    text = _TICKET_PROPOSAL[_language(state)]
    return {"final_response": text, "messages": [AIMessage(content=text)]}


def finalize_turn(state: State) -> dict:
    """Publish the turn's output and clear its working fields.

    Everything in the turn-lived group is set back to `None` so the next turn
    on this thread starts clean -- without this, turn 2 could read turn 1's
    retrieval or route from the checkpoint and act on it. `ticket_draft` is
    conversation-lived and left alone: a pending draft waits for the
    customer's answer.

    `ticket_assistant` replies through `messages` only, so its turn's
    `final_response` is taken from the last message.
    """
    retrieval = state.get("retrieval")
    evidence: list[EvidenceItem] = (
        [item for result in retrieval["results"] for item in result["evidence"]]
        if retrieval
        else []
    )
    final_response = state.get("final_response")
    last = state["messages"][-1] if state["messages"] else None
    if final_response is None and isinstance(last, AIMessage):
        final_response = str(last.content)
    return {
        "response_evidence": evidence,
        "final_response": final_response,
        "route": None,
        "response_language": None,
        "questions": None,
        "retrieval": None,
        "answer_draft": None,
        "grounding": None,
        "answer_revision_count": 0,
    }
