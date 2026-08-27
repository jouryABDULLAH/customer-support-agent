"""Streamlit UI for the customer-support agent.

    streamlit run src/customer_support/ui.py

All UI logic lives in this one file, and the dependency direction is strictly
UI -> application modules. The graph, checkpointer, DB helpers, config and
logging are consumed exactly as the CLI scripts consume them; nothing here
adds another execution path or persistence mechanism.

State ownership: LangGraph's checkpoint is the source of truth for the
conversation -- messages are always re-read from `graph.get_state()` rather
than mirrored in Streamlit. `st.session_state` holds only UI concerns: which
customer is selected, the current thread id, and the last turn's evidence /
ticket id for rendering.
"""

import logging
import uuid
from contextlib import closing

import streamlit as st

from customer_support.db.connection import connect, migrate
from customer_support.db.customers import (
    create_customer,
    get_customer,
    get_customer_by_email,
    get_customer_by_phone,
)
from customer_support.db.tickets import list_tickets
from customer_support.graph import Context, build_graph
from customer_support.observability import configure_logging, configure_tracing

logger = logging.getLogger(__name__)

# Chat avatars: plain color blocks, no icons.
_AVATARS = {"user": "🟦", "assistant": "🟧"}


@st.cache_resource
def get_graph():
    """Compile the graph once per process; also settles logging/tracing/DB."""
    configure_logging()
    configure_tracing()
    migrate().close()
    return build_graph()


def find_customer(query: str):
    """Resolve an id, email, or phone to a customer row, or None."""
    with closing(connect()) as conn:
        return (
            get_customer(conn, query)
            or get_customer_by_email(conn, query)
            or get_customer_by_phone(conn, query)
        )


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
        who, new, switch = st.columns([3, 1, 1], vertical_alignment="center")
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
        "Customer", placeholder="id, email, or phone", label_visibility="collapsed"
    )
    if login.button("Login", use_container_width=True):
        row = find_customer(query.strip()) if query.strip() else None
        if row is None:
            st.error("No customer found with that id, email, or phone. Register instead.")
        else:
            _select_customer(row)
            st.rerun()
    if register.button("Register", use_container_width=True, type="primary"):
        register_dialog()


def chat_tab(graph, customer: dict) -> None:
    """The conversation: history from the checkpoint, one invoke per message."""
    config = {"configurable": {"thread_id": st.session_state["thread_id"]}}

    # The checkpoint is the conversation's source of truth; render from it.
    values = graph.get_state(config).values
    for message in values.get("messages", []):
        role = "user" if message.type == "human" else "assistant"
        with st.chat_message(role, avatar=_AVATARS[role]):
            st.markdown(message.content)

    # Evidence and ticket acknowledgment belong to the latest turn only.
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

    # Reserved BEFORE the input so the in-flight turn (echoed message,
    # spinner, errors) renders above the box -- widgets placed after
    # `st.chat_input` would otherwise appear below it.
    turn_area = st.container()

    prompt = st.chat_input("Type your message")
    if prompt:
        with turn_area:
            with st.chat_message("user", avatar=_AVATARS["user"]):
                st.markdown(prompt)
            try:
                with st.spinner("Searching the documentation... (retrieval can take a minute or two)"):
                    state = graph.invoke(
                        {"messages": [{"role": "user", "content": prompt}]},
                        config=config,
                        context=Context(customer_id=customer["id"]),
                    )
                st.session_state["last_turn"] = {
                    "evidence": state.get("response_evidence") or [],
                    "ticket_id": state.get("ticket_id"),
                }
            except Exception as error:
                logger.exception("graph invocation failed")
                st.error(f"Something went wrong handling this message: {error}")
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


def main() -> None:
    st.set_page_config(page_title="Customer Support Agent", page_icon="💬")
    graph = get_graph()

    st.title("Customer Support Agent")
    header_bar()

    customer = st.session_state.get("customer")
    if not customer:
        st.info("Log in or register above to start.")
        return

    chat, tickets = st.tabs(["Chat", "Tickets"])
    with chat:
        chat_tab(graph, customer)
    with tickets:
        tickets_tab(customer)


main()
