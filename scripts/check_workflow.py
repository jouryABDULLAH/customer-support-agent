"""Offline checks for the graph's structure and its deterministic nodes.

    python scripts/check_workflow.py

No network, no model calls, no retrieval -- everything here is either graph
wiring or a node whose behavior is fixed. The paths that need a live model and
a live index are in `check_workflow_live.py`.

Uses the real `data/app.db` (the node reads `APP_DB_PATH`).
"""

import uuid

from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime

from customer_support.db.connection import connect, migrate
from customer_support.db.customers import create_customer, get_customer
from customer_support.graph import Context, build_graph
from customer_support.graph.checkpoint import get_checkpointer
from customer_support.graph import nodes as graph_nodes
from customer_support.graph.nodes import (
    _coverage_section,
    _unresolved_notes,
    deliver_answer,
    finalize_turn,
    load_customer_if_needed,
)
from customer_support.graph import routing as routing_module
from customer_support.graph.routing import (
    route_after_retrieval,
    route_after_router,
    route_after_verification,
)
from customer_support.observability import configure_logging, configure_tracing

FIXTURE_CUSTOMER_ID = "TEST-CUSTOMER-001"

failures: list[str] = []

EXPECTED_EDGES = {
    ("__start__", "load_customer_if_needed"),
    ("load_customer_if_needed", "router"),
    ("router", "respond_directly"),
    ("router", "decompose_question"),
    ("router", "ticket_assistant"),
    ("respond_directly", "finalize_turn"),
    ("ticket_assistant", "finalize_turn"),
    ("decompose_question", "search_subquestions"),
    ("search_subquestions", "generate_answer"),
    ("search_subquestions", "ticket_agent"),
    ("generate_answer", "verify"),
    ("verify", "deliver_answer"),
    ("verify", "revise_answer"),
    ("verify", "ticket_agent"),
    ("revise_answer", "verify"),
    ("deliver_answer", "finalize_turn"),
    ("ticket_agent", "propose_ticket"),
    ("propose_ticket", "finalize_turn"),
    ("finalize_turn", "__end__"),
}


def check(label: str, actual: object, expected: object) -> None:
    if actual == expected:
        print(f"  ok    {label}")
    else:
        failures.append(label)
        print(f"  FAIL  {label}: expected {expected!r}, got {actual!r}")


def seed_fixture_customer() -> None:
    """Make sure `TEST-CUSTOMER-001` exists. Safe to run repeatedly."""
    migrate().close()
    conn = connect()
    if get_customer(conn, FIXTURE_CUSTOMER_ID) is None:
        create_customer(
            conn,
            name="Test Customer",
            email="test-customer-001@example.com",
            phone="+966500000000",
            customer_id=FIXTURE_CUSTOMER_ID,
        )
        print(f"  (seeded {FIXTURE_CUSTOMER_ID})")
    conn.close()


def retrieval(*questions: tuple[str, str]) -> dict:
    """A synthetic `RetrievalResult` from (question, confidence) pairs."""
    results = [
        {
            "question": q,
            "evidence": [{"content": f"evidence for {q}", "score": 0.9, "source": "d"}],
            "top_score": 0.9 if c == "high" else 0.1,
            "confidence": c,
        }
        for q, c in questions
    ]
    outcome = (
        "all_high" if all(r["confidence"] == "high" for r in results)
        else "needs_escalation"
    )
    return {"results": results, "outcome": outcome}


def check_structure() -> None:
    graph = build_graph(checkpointer=get_checkpointer()).get_graph()
    nodes = set(graph.nodes)
    for name in (
        "load_customer_if_needed", "router", "respond_directly",
        "decompose_question", "search_subquestions", "generate_answer",
        "verify", "revise_answer", "deliver_answer", "ticket_agent",
        "propose_ticket", "ticket_assistant", "finalize_turn",
    ):
        check(f"node {name!r} registered", name in nodes, True)

    edges = {(e.source, e.target) for e in graph.edges}
    check("edges match the target workflow", edges, EXPECTED_EDGES)
    conditional = {(e.source, e.target) for e in graph.edges if e.conditional}
    check(
        "the three branches are conditional edges",
        conditional,
        {
            ("router", "respond_directly"),
            ("router", "decompose_question"),
            ("router", "ticket_assistant"),
            ("search_subquestions", "generate_answer"),
            ("search_subquestions", "ticket_agent"),
            ("verify", "deliver_answer"),
            ("verify", "revise_answer"),
            ("verify", "ticket_agent"),
        },
    )


def check_routing() -> None:
    check(
        "respond_directly route",
        route_after_router({"route": "respond_directly"}),
        "respond_directly",
    )
    check(
        "retrieve_evidence route",
        route_after_router({"route": "retrieve_evidence"}),
        "decompose_question",
    )
    check(
        "manage_ticket route",
        route_after_router({"route": "manage_ticket"}),
        "ticket_assistant",
    )
    check(
        "missing route falls back to retrieval",
        route_after_router({}),
        "decompose_question",
    )

    check(
        "all_high -> generate_answer",
        route_after_retrieval({"retrieval": retrieval(("a", "high"), ("b", "high"))}),
        "generate_answer",
    )
    check(
        "mixed high+low -> ticket_agent",
        route_after_retrieval({"retrieval": retrieval(("a", "high"), ("b", "low"))}),
        "ticket_agent",
    )
    check(
        "no retrieval -> ticket_agent",
        route_after_retrieval({}),
        "ticket_agent",
    )

    check(
        "grounded -> deliver_answer",
        route_after_verification({"grounding": {"grounded": True, "answered": True, "reason": "ok"}}),
        "deliver_answer",
    )
    check(
        "first failure -> revise_answer",
        route_after_verification({"grounding": {"grounded": False, "answered": True, "reason": "no"}}),
        "revise_answer",
    )
    check(
        "failure after revision -> ticket_agent",
        route_after_verification(
            {"grounding": {"grounded": False, "answered": True, "reason": "no"}, "answer_revision_count": 1}
        ),
        "ticket_agent",
    )
    check(
        "grounded after revision -> deliver_answer",
        route_after_verification(
            {"grounding": {"grounded": True, "answered": True, "reason": "ok"}, "answer_revision_count": 1}
        ),
        "deliver_answer",
    )
    check(
        "grounded but unanswered -> ticket_agent, never revision",
        route_after_verification(
            {"grounding": {"grounded": True, "answered": False, "reason": "says info is missing"}}
        ),
        "ticket_agent",
    )
    check(
        "grounded but unanswered after revision -> ticket_agent",
        route_after_verification(
            {
                "grounding": {"grounded": True, "answered": False, "reason": "says info is missing"},
                "answer_revision_count": 1,
            }
        ),
        "ticket_agent",
    )
    saved_max = routing_module.MAX_ANSWER_REVISIONS
    try:
        routing_module.MAX_ANSWER_REVISIONS = 0
        check(
            "MAX=0 disables revision entirely",
            route_after_verification({"grounding": {"grounded": False, "answered": True, "reason": "no"}}),
            "ticket_agent",
        )
    finally:
        routing_module.MAX_ANSWER_REVISIONS = saved_max
    check(
        "missing verdict -> ticket_agent, never revision",
        route_after_verification({}),
        "ticket_agent",
    )
    check(
        "verdict cleared to None -> ticket_agent too",
        route_after_verification({"grounding": None}),
        "ticket_agent",
    )


def check_unresolved_notes() -> None:
    mixed = _unresolved_notes({"retrieval": retrieval(("kept", "high"), ("lost", "low"))})
    check("names the low-confidence question", "lost" in mixed, True)
    check("names the high-confidence question too", "kept" in mixed, True)
    check("says nothing was sent to the customer", "no reply was sent" in mixed, True)
    check("keeps retrieval scores out of the prompt", "0.9" in mixed, False)

    grounding_failure = _unresolved_notes(
        {
            "retrieval": retrieval(("a", "high")),
            "grounding": {"grounded": False, "answered": True, "reason": "invented a 3-day timeframe"},
        }
    )
    check(
        "carries the verifier's reason",
        "invented a 3-day timeframe" in grounding_failure,
        True,
    )

    unanswered = _unresolved_notes(
        {
            "retrieval": retrieval(("a", "high")),
            "grounding": {"grounded": True, "answered": False, "reason": "freezing is not covered"},
        }
    )
    check("unanswered: carries the verifier's reason", "freezing is not covered" in unanswered, True)
    check("unanswered: says no reply was sent", "no reply was sent" in unanswered, True)


def check_coverage_section() -> None:
    mixed = _coverage_section(
        {"response_language": "en", "retrieval": retrieval(("kept", "high"), ("lost", "low"))}
    )
    not_covered, _, covered = mixed.partition("The documents cover")
    check("lists the low question under not answered", "- lost" in not_covered, True)
    check("does not list the high question as unanswered", "kept" in not_covered, False)
    check("lists the high question as covered", "- kept" in covered, True)

    all_low = _coverage_section({"response_language": "ar", "retrieval": retrieval(("lost", "low"))})
    check("arabic headings", all_low.startswith("لا تجيب الوثائق المعتمدة عن:"), True)
    check("no covered heading when nothing was covered", "تغطي الوثائق" in all_low, False)

    unanswered = _coverage_section(
        {
            "response_language": "en",
            "retrieval": retrieval(("a", "high")),
            "grounding": {"grounded": True, "answered": False, "reason": "freezing not covered"},
        }
    )
    check("unanswered draft: says it did not answer", "did not answer" in unanswered, True)
    check("unanswered draft: carries the reason", "freezing not covered" in unanswered, True)

    failed = _coverage_section(
        {
            "response_language": "en",
            "retrieval": retrieval(("a", "high")),
            "grounding": {"grounded": False, "answered": True, "reason": "invented a timeframe"},
        }
    )
    check("failed draft: says it failed verification", "failed verification" in failed, True)
    check("no retrieval -> empty section", _coverage_section({"response_language": "en"}), "")


def check_citation_stripping() -> None:
    """`deliver_answer` honors the STRIP_CITATION_MARKERS toggle.

    Patches the flag on the nodes module (it is read as a module global), so
    both positions are exercised regardless of the process environment.
    """
    draft = "السعر 148 دولار【1†L1-L3】 أو 549 ريال 【2†L1-L3】."
    state = {"messages": [], "answer_draft": draft}
    saved = graph_nodes.STRIP_CITATION_MARKERS
    try:
        graph_nodes.STRIP_CITATION_MARKERS = False
        kept = deliver_answer(state)["final_response"]
        check("default keeps citation markers", kept, draft)

        graph_nodes.STRIP_CITATION_MARKERS = True
        stripped = deliver_answer(state)["final_response"]
        check("toggle strips the markers", stripped, "السعر 148 دولار أو 549 ريال.")
        check("message matches the stripped reply", deliver_answer(state)["messages"][0].content, stripped)
    finally:
        graph_nodes.STRIP_CITATION_MARKERS = saved


def check_finalize_turn() -> None:
    answered = finalize_turn(
        {
            "messages": [],
            "route": "retrieve_evidence",
            "response_language": "ar",
            "questions": ["q"],
            "retrieval": retrieval(("a", "high"), ("b", "high")),
            "answer_draft": "draft",
            "grounding": {"grounded": True, "answered": True, "reason": "ok"},
            "answer_revision_count": 1,
            "final_response": "answer",
        }
    )
    for field in (
        "route", "response_language", "questions", "retrieval",
        "answer_draft", "grounding",
    ):
        check(f"clears {field}", answered[field], None)
    check("clears answer_revision_count to 0", answered["answer_revision_count"], 0)
    check("publishes evidence for the UI", len(answered["response_evidence"]), 2)
    check("keeps a final_response a node set", answered["final_response"], "answer")
    check("leaves a pending ticket_draft alone", "ticket_draft" in answered, False)
    check("leaves ticket_id alone", "ticket_id" in answered, False)
    check("leaves messages alone", "messages" in answered, False)
    check("leaves customer alone", "customer" in answered, False)

    agent_turn = finalize_turn(
        {"messages": [AIMessage(content="Ticket T-1 submitted.")], "final_response": None}
    )
    check(
        "takes final_response from the agent's last message",
        agent_turn["final_response"],
        "Ticket T-1 submitted.",
    )

    direct = finalize_turn({"messages": [], "final_response": "hi"})
    check("no retrieval -> empty evidence", direct["response_evidence"], [])


def check_load_customer() -> None:
    runtime = Runtime(context=Context(customer_id=FIXTURE_CUSTOMER_ID))

    loaded = load_customer_if_needed({"messages": []}, runtime)
    check("loads the customer from the DB", loaded["customer"]["id"], FIXTURE_CUSTOMER_ID)
    check("carries the name", loaded["customer"]["name"], "Test Customer")

    already = load_customer_if_needed(
        {"messages": [], "customer": {"id": "ALREADY-IN-STATE"}}, runtime
    )
    check("skips the lookup when already in state", already, {})

    # Snapshot the count before the failed lookup and compare after, rather
    # than asserting the table holds exactly the fixture -- this runs against
    # the real app.db, and registering a real customer must not fail it.
    conn = connect()
    before = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    conn.close()

    unknown = Runtime(context=Context(customer_id=f"MISSING-{uuid.uuid4().hex}"))
    try:
        load_customer_if_needed({"messages": []}, unknown)
        check("unknown customer raises", "no exception", "LookupError")
    except LookupError:
        check("unknown customer raises LookupError", True, True)

    conn = connect()
    after = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    conn.close()
    check("no customer was created for the unknown id", after, before)


def main() -> int:
    configure_logging("WARNING")  # the check output is the signal here
    configure_tracing()

    print("fixture:")
    seed_fixture_customer()

    print("\ngraph structure:")
    check_structure()
    print("\nrouting:")
    check_routing()
    print("\nunresolved notes for the ticket agent:")
    check_unresolved_notes()
    print("\ncoverage section for the ticket description:")
    check_coverage_section()
    print("\nciting toggle (deliver_answer):")
    check_citation_stripping()
    print("\nfinalize_turn:")
    check_finalize_turn()
    print("\nload_customer_if_needed:")
    check_load_customer()

    if failures:
        print(f"\n{len(failures)} check(s) FAILED.")
        return 1
    print("\nAll workflow checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
