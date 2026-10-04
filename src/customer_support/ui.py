"""Streamlit UI for the customer-support agent: a support-request system.

    streamlit run src/customer_support/ui.py

All UI logic lives in this one file, and the dependency direction is strictly
UI -> application modules. The graph, checkpointer, DB helpers, config and
logging are consumed exactly as the CLI scripts consume them; nothing here
adds another execution path or persistence mechanism.

State ownership: LangGraph's checkpoint is the source of truth for the
conversation -- messages are always re-read from `graph.get_state()` rather
than mirrored in Streamlit. `st.session_state` holds only UI concerns: which
customer is selected, the current thread id, and the last turn's evidence /
ticket id for rendering. A ticket awaiting the customer's approval is read
from the checkpoint's pending interrupt, not stored here.
"""

import logging
import threading
import uuid
from contextlib import closing
from typing import get_args

import streamlit as st
from langgraph.types import Command

from customer_support.db.connection import connect, migrate
from customer_support.db.customers import (
    create_customer,
    get_customer,
    get_customer_by_email,
    get_customer_by_phone,
    get_customers_by_name,
)
from customer_support.db.tickets import list_tickets
from customer_support.graph import Context, build_graph
from customer_support.observability import configure_logging, configure_tracing
from customer_support.rag.client import get_rag
from customer_support.schemas import TicketCategory

logger = logging.getLogger(__name__)


@st.cache_resource
def get_graph():
    """Compile the graph once per process; also settles logging/tracing/DB."""
    configure_logging()
    configure_tracing()
    migrate().close()
    return build_graph()


@st.cache_resource
def start_warmup() -> threading.Thread:
    """Build the Qdrant client, embedder and reranker in the background.

    RAGent2 builds them lazily on the first search, which put ~50 s of setup
    on the first request. Started once per process when the app loads;
    `_run_turn` joins it before invoking, so a request that arrives mid-warmup
    waits for it instead of building a second copy of the models.
    """
    thread = threading.Thread(target=lambda: get_rag().retriever, name="rag-warmup", daemon=True)
    thread.start()
    return thread


def find_customer(query: str) -> tuple[object, str | None]:
    """Resolve a query to (customer row | None, error message | None).

    Unique identifiers (id, email, phone) are tried first; name last, and
    only when it matches exactly one customer -- an ambiguous name refuses
    with a message naming the unique alternatives.
    """
    with closing(connect()) as conn:
        row = (
            get_customer(conn, query)
            or get_customer_by_email(conn, query)
            or get_customer_by_phone(conn, query)
        )
        if row is not None:
            return row, None
        matches = get_customers_by_name(conn, query)
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        return None, (
            f"{len(matches)} customers share the name {query!r}. "
            "Log in with an email, phone, or id instead."
        )
    return None, "No customer found with that name, id, email, or phone. Register instead."


def _select_customer(row) -> None:
    """Make `row` the active customer, on a fresh conversation."""
    st.session_state["customer"] = dict(row)
    st.session_state["thread_id"] = uuid.uuid4().hex
    st.session_state.pop("last_turn", None)


@st.dialog("Register a new customer")
def register_dialog() -> None:
    name = st.text_input("Name")
    email = st.text_input("Email")
    phone = st.text_input("Phone")
    if st.button("Register", type="primary"):
        if not (name.strip() and email.strip() and phone.strip()):
            st.error("Name, email, and phone are all required.")
            return
        try:
            with closing(connect()) as conn:
                customer_id = create_customer(
                    conn,
                    name=name.strip(),
                    email=email.strip(),
                    phone=phone.strip(),
                )
                row = get_customer(conn, customer_id)
            _select_customer(row)
            st.rerun()  # closes the dialog
        except Exception as error:
            logger.exception("registration failed")
            st.error(f"Could not register: {error}")


def header_bar() -> None:
    """One tight row under the title: customer identity and controls."""
    customer = st.session_state.get("customer")
    if customer:
        who, new, switch = st.columns([2.4, 1.3, 1.3], vertical_alignment="center")
        who.markdown(f"**{customer['name'] or customer['id']}** · `{customer['id']}`")
        if new.button("New conversation", use_container_width=True):
            st.session_state["thread_id"] = uuid.uuid4().hex
            st.session_state.pop("last_turn", None)
            st.rerun()
        if switch.button("Switch customer", use_container_width=True):
            for key in ("customer", "thread_id", "last_turn"):
                st.session_state.pop(key, None)
            st.rerun()
        return

    query_col, login, register = st.columns([3, 1, 1], vertical_alignment="bottom")
    query = query_col.text_input(
        "Customer", placeholder="name, id, email, or phone", label_visibility="collapsed"
    )
    if login.button("Login", use_container_width=True):
        row, problem = find_customer(query.strip()) if query.strip() else (None, "Enter a name, id, email, or phone.")
        if row is None:
            st.error(problem)
        else:
            _select_customer(row)
            st.rerun()
    if register.button("Register", use_container_width=True, type="primary"):
        register_dialog()


# The approval card's text, in the turn's response language like every other
# customer-facing reply.
_APPROVAL_TEXT = {
    "ar": {
        "edit": "يمكنك تعديل تفاصيل التذكرة قبل فتحها.",
        "subject": "الموضوع",
        "category": "الفئة",
        "description": "وصف المشكلة",
        "invalid": "يرجى إدخال موضوع ووصف للمشكلة واختيار فئة صحيحة ثم المحاولة مجدداً.",
        "prompt": "لم أجد إجابة لاستفسارك في المصادر المعتمدة. هل ترغب بفتح تذكرة دعم ليتابعها أحد المختصين؟",
        "approve": "فتح التذكرة",
        "decline": "لا، شكراً",
    },
    "en": {
        "edit": "You can edit the ticket details before opening it.",
        "subject": "Subject",
        "category": "Category",
        "description": "Problem description",
        "invalid": "Enter a subject and problem description, select a valid category, and try again.",
        "prompt": "I couldn't find an answer in my approved sources. Open a support ticket so a specialist can follow up?",
        "approve": "Open ticket",
        "decline": "No thanks",
    },
}


def _run_turn(graph, graph_input, config: dict, customer: dict) -> None:
    """Invoke the graph and record what the UI shows for the turn.

    A turn that pauses for ticket approval has not reached `finalize_turn`,
    so its evidence and ticket id are not this turn's yet; nothing is
    recorded until it resumes.
    """
    try:
        with st.spinner("Processing your request... (this can take a minute or two)"):
            start_warmup().join()
            state = graph.invoke(
                graph_input,
                config=config,
                context=Context(customer_id=customer["id"]),
            )
        if "__interrupt__" in state:
            st.session_state.pop("last_turn", None)
        else:
            st.session_state["last_turn"] = {
                "evidence": state.get("response_evidence") or [],
                "ticket_id": state.get("ticket_id"),
            }
    except Exception as error:
        logger.exception("graph invocation failed")
        st.error(f"Something went wrong handling this request: {error}")


def approval_card(graph, snapshot, config: dict, customer: dict) -> None:
    """Editable ticket draft, with approve / decline. Replaces the request form
    while it is pending: the turn is not over until the customer answers."""
    pending = snapshot.interrupts[0]
    draft = pending.value
    text = _APPROVAL_TEXT[snapshot.values.get("response_language") or "ar"]

    st.caption("Response")
    with st.container(border=True):
        st.markdown(text["prompt"])
        st.caption(text["edit"])
        if draft.get("error"):
            st.error(text["invalid"])
        # Scope widgets to this review so reruns retain edits, while another
        # conversation or ticket gets its own initial values.
        review_key = f"ticket_review_{config['configurable']['thread_id']}_{pending.id}"
        with st.form(review_key):
            subject = st.text_input(text["subject"], value=draft["subject"])
            categories = get_args(TicketCategory)
            category = st.selectbox(
                text["category"], categories, index=categories.index(draft["category"])
            )
            description = st.text_area(
                text["description"], value=draft["problem_description"], height=180
            )
            approve, decline, _ = st.columns([1, 1, 2])
            approved = approve.form_submit_button(text["approve"], type="primary", use_container_width=True)
            declined = decline.form_submit_button(text["decline"], use_container_width=True)

    if approved or declined:
        if approved and not (subject.strip() and description.strip()):
            st.error(text["invalid"])
            return
        response = {"approved": approved}
        if approved:
            response["ticket_draft"] = {
                "subject": subject,
                "category": category,
                "problem_description": description,
            }
        _run_turn(graph, Command(resume=response), config, customer)
        st.rerun()


def request_tab(graph, customer: dict) -> None:
    """Submit a support request; the conversation renders as an email-like
    thread of Request/Response blocks, not chat bubbles.

    Underneath it is still the same graph thread: one submitted request is one
    invocation on the current `thread_id`, and history is re-read from the
    checkpoint. A request becomes a ticket only when the graph escalates it
    and the customer approves the drafted ticket.
    """
    config = {"configurable": {"thread_id": st.session_state["thread_id"]}}
    snapshot = graph.get_state(config)

    # The checkpoint is the conversation's source of truth; render from it.
    # Customer text gets its newlines preserved (markdown collapses single
    # ones); agent responses render as-is -- the model emits real markdown.
    for message in snapshot.values.get("messages", []):
        is_request = message.type == "human"
        st.caption("Request" if is_request else "Response")
        with st.container(border=True):
            content = str(message.content)
            st.markdown(content.replace("\n", "  \n") if is_request else content)

    if snapshot.interrupts:
        approval_card(graph, snapshot, config, customer)
        return

    # Ticket acknowledgment and evidence belong to the latest response only.
    last_turn = st.session_state.get("last_turn")
    if last_turn:
        if last_turn.get("ticket_id"):
            st.info(f"Support ticket created: {last_turn['ticket_id']}")
        evidence = last_turn.get("evidence") or []
        if evidence:
            with st.expander(f"Evidence ({len(evidence)} passages)"):
                for item in evidence:
                    st.caption(f"{item['score']:.4f} — {item['source'] or 'unknown'}")
                    st.markdown(item["content"])
                    st.divider()

    # Reserved BEFORE the form so the in-flight request and spinner render
    # above it, in the thread where the exchange will appear.
    turn_area = st.container()

    st.divider()
    with st.form("new_request", clear_on_submit=True):
        text = st.text_area(
            "Describe your request",
            height=140,
            placeholder="Describe your question or problem...",
        )
        submitted = st.form_submit_button("Submit Request", type="primary")

    if submitted and text.strip():
        request = text.strip()
        with turn_area:
            st.caption("Request")
            with st.container(border=True):
                st.markdown(request.replace("\n", "  \n"))
            _run_turn(
                graph,
                {"messages": [{"role": "user", "content": request}]},
                config,
                customer,
            )
        st.rerun()


def tickets_tab(customer: dict) -> None:
    """The customer's tickets, newest first."""
    with closing(connect()) as conn:
        rows = list_tickets(conn, customer_id=customer["id"])
    if not rows:
        st.caption("No tickets for this customer.")
        return
    for row in rows:
        title = f"{row['status']} · {row['subject']} · {row['category']} · {row['created_at'][:16]}"
        with st.expander(title):
            st.markdown(f"**Problem**\n\n{row['problem_description']}")
            st.markdown(f"**Original message**\n\n> {row['original_message']}")
            st.caption(f"ticket {row['id']} · product {row['product']}")


# Per-paragraph auto direction: an Arabic paragraph renders right-to-left and
# right-aligned, an English one left-to-right, decided by its first strong
# character -- no per-message language logic, and markdown structure is kept.
# Also applied to the request text area so Arabic is typed RTL.
_RTL_CSS = """<style>
[data-testid="stMarkdownContainer"] :is(p, li, h1, h2, h3, h4),
textarea {
    unicode-bidi: plaintext;
    text-align: start;
}
.stButton button p { white-space: nowrap; }
</style>"""


def main() -> None:
    st.set_page_config(page_title="Customer Support Agent", page_icon="💬")
    st.markdown(_RTL_CSS, unsafe_allow_html=True)
    graph = get_graph()
    start_warmup()

    st.title("Customer Support Agent")
    header_bar()

    customer = st.session_state.get("customer")
    if not customer:
        st.info("Log in or register above to start.")
        return

    request, tickets = st.tabs(["New Request", "Tickets"])
    with request:
        request_tab(graph, customer)
    with tickets:
        tickets_tab(customer)


if __name__ == "__main__":
    main()
