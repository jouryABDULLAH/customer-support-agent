"""End-to-end checks for the graph against live services.

    python scripts/check_workflow_live.py
    python scripts/check_workflow_live.py --only A,B,H

Needs Qdrant and docling-serve running with the MSEGAT documents indexed, and
`GROQ_API_KEY` in the shell. Slow: every scenario is several model calls plus
CPU reranking. The structural and deterministic checks are in
`check_workflow.py` and do not need any of this.

Scenarios:

    A  greeting/thanks bypass retrieval
    B  supported single question -> grounded answer
    C  supported multi-question -> one grounded answer
    D  mixed HIGH + LOW -> no answer, ticket created
    E  grounding failure -> ticket created
    F  customer and messages persist across turns, threads and restarts
    G  ticket trusted fields are correct
    H  the reply is in the customer's language
    R  router edge cases (node-level, no retrieval)

D runs before G, which inspects the ticket D created.

Each turn is driven with `stream_mode="updates"` so the per-node outputs are
visible: `finalize_turn` clears the working fields by design, so the final
state alone cannot show what retrieval decided.
"""

import sys
import uuid

from customer_support.db.connection import connect
from customer_support.db.tickets import get_ticket
from customer_support.graph import Context, build_graph, reset_checkpointer
from customer_support.graph import nodes as graph_nodes
from customer_support.model import invoke_structured
from customer_support.observability import configure_logging, configure_tracing
from customer_support.prompts import VERIFY_GROUNDING_PROMPT
from customer_support.rag import client as rag_client
from customer_support.rag.answer import detect_language
from customer_support.rag.client import get_rag
from customer_support.schemas import GroundingResult
from langchain_core.messages import HumanMessage

FIXTURE_CUSTOMER_ID = "TEST-CUSTOMER-001"
RUN = uuid.uuid4().hex[:8]

failures: list[str] = []
state_by_scenario: dict[str, dict] = {}


def check(label: str, actual: object, expected: object) -> None:
    if actual == expected:
        print(f"  ok    {label}")
    else:
        failures.append(label)
        print(f"  FAIL  {label}: expected {expected!r}, got {actual!r}")


class CountingTenant:
    """Wraps the real tenant and counts one `search()` call per question.

    `search_question` resolves `get_documents` at call time, so replacing the
    module attribute intercepts every real search without touching the search
    module itself. Counting the questions rather than the calls is the point:
    the requirement is exactly one search per subquestion, and a retry loop
    would show up here as a second count for the same string.
    """

    def __init__(self, tenant):
        self._tenant = tenant
        self.calls: list[str] = []

    def search(self, question, *args, **kwargs):
        self.calls.append(question)
        return self._tenant.search(question, *args, **kwargs)


def run_turn(message: str, thread_id: str, count_searches: bool = False) -> tuple[dict, dict, list[str]]:
    """One graph invocation. Returns (final state, node updates, searched questions)."""
    graph = build_graph()
    config = {"configurable": {"thread_id": thread_id}}
    context = Context(customer_id=FIXTURE_CUSTOMER_ID)

    counter = None
    original = rag_client.get_documents
    if count_searches:
        counter = CountingTenant(original())
        rag_client.get_documents = lambda: counter
    try:
        updates: dict[str, dict] = {}
        for step in graph.stream(
            {"messages": [{"role": "user", "content": message}]},
            config=config,
            context=context,
            stream_mode="updates",
        ):
            updates.update(step)
    finally:
        rag_client.get_documents = original

    return graph.get_state(config).values, updates, (counter.calls if counter else [])


def scenario_a() -> None:
    """Greetings and thanks bypass retrieval entirely."""
    cases = (
        ("arabic greeting", "السلام عليكم", "ar"),
        ("english thanks", "Thanks a lot, that really helped!", "en"),
    )
    for label, message, language in cases:
        state, updates, _ = run_turn(message, f"A-{label}-{RUN}")
        print(f"  [{label}] {state['final_response'][:90]}")
        check(f"{label}: routed direct", updates["router"]["route"], "respond_directly")
        check(f"{label}: retrieval nodes never ran", "search_subquestions" in updates, False)
        check(f"{label}: no evidence", state["response_evidence"], [])
        check(f"{label}: no ticket", state["ticket_id"], None)
        check(f"{label}: replied", bool(state["final_response"]), True)
        check(f"{label}: replied in {language}", detect_language(state["final_response"]), language)


def scenario_b() -> None:
    """A supported question: one subquestion, searched once, HIGH, answered."""
    message = "كم سعر الباقة البرونزية؟"
    state, updates, searched = run_turn(message, f"B-{RUN}", count_searches=True)
    retrieval = updates["search_subquestions"]["retrieval"]
    questions = updates["decompose_question"]["questions"]

    print(f"  decomposed -> {questions}")
    print(f"  top_score  -> {retrieval['results'][0]['top_score']:.4f}")
    print(f"  answer     -> {state['final_response'][:120]}")

    check("routed to retrieval", updates["router"]["route"], "retrieve_evidence")
    check("one subquestion", len(questions), 1)
    check("searched exactly once", len(searched), 1)
    check("searched the decomposed question", searched, questions)
    check("confidence HIGH", retrieval["results"][0]["confidence"], "high")
    check("outcome all_high", retrieval["outcome"], "all_high")
    check("grounding passed", updates.get("verify", {}).get("grounding", {}).get("grounded"), True)
    check("answer delivered", state["final_response"], updates.get("generate_answer", {}).get("answer_draft"))
    check("no ticket", state["ticket_id"], None)
    check("evidence preserved for the UI", len(state["response_evidence"]) > 0, True)
    # The price table is the passage the reranker ranked 5th; its presence in
    # the reply is what proves evidence was not trimmed by rank.
    check("answer quotes a documented price", "148" in state["final_response"], True)
    state_by_scenario["B"] = state


def scenario_c() -> None:
    """Two supported questions in one message: each searched once, one reply."""
    message = "كيف أشترك في مسجات وما هي أسعار الباقات؟"
    state, updates, searched = run_turn(message, f"C-{RUN}", count_searches=True)
    questions = updates["decompose_question"]["questions"]
    retrieval = updates["search_subquestions"]["retrieval"]

    print(f"  decomposed -> {questions}")
    for result in retrieval["results"]:
        print(f"    {result['top_score']:.4f}  {result['confidence'].upper()}  {result['question']}")

    check("split into multiple questions", len(questions) >= 2, True)
    check("one search per subquestion", len(searched), len(questions))
    check("no question searched twice", len(set(searched)), len(searched))
    check("searched exactly the decomposed questions", searched, questions)
    check("a result per subquestion", len(retrieval["results"]), len(questions))
    check("every subquestion HIGH", all(r["confidence"] == "high" for r in retrieval["results"]), True)
    check("outcome all_high", retrieval["outcome"], "all_high")
    check("one reply for the whole message", len(updates.get("deliver_answer", {}).get("messages", [])), 1)
    check("no ticket", state["ticket_id"], None)


def scenario_d() -> None:
    """One supported and one unsupported question: no answer, a ticket."""
    message = "كم سعر الباقة البرونزية؟ وهل يمكن ربط مسجات مع Salesforce؟"
    state, updates, searched = run_turn(message, f"D-{RUN}", count_searches=True)
    retrieval = updates["search_subquestions"]["retrieval"]

    print(f"  decomposed -> {updates['decompose_question']['questions']}")
    for result in retrieval["results"]:
        print(f"    {result['top_score']:.4f}  {result['confidence'].upper()}  {result['question']}")
    print(f"  reply      -> {state['final_response'][:120]}")

    confidences = {r["confidence"] for r in retrieval["results"]}
    check("both a HIGH and a LOW subquestion", confidences, {"high", "low"})
    check("outcome needs_escalation", retrieval["outcome"], "needs_escalation")
    check("one search per subquestion", len(searched), len(retrieval["results"]))
    check("no answer was generated", "generate_answer" in updates, False)
    check("verification never ran", "verify" in updates, False)
    check("ticket agent ran", "ticket_agent" in updates, True)
    check("a ticket was created", bool(state["ticket_id"]), True)
    check(
        "the reply names the ticket",
        bool(state["ticket_id"]) and state["ticket_id"] in state["final_response"],
        True,
    )
    state_by_scenario["D"] = state


def scenario_e() -> None:
    """A draft with invented claims fails verification and escalates.

    Two levels. First the verifier itself, on the fixture from
    `tests/use_cases.md` UC-010, plus a positive control that a faithful
    cross-language translation still passes -- a verifier that rejected those
    would send every English customer to a ticket. Then the graph: real
    retrieval, real verifier, real ticket, with only the drafting node
    replaced by one that adds claims the evidence does not contain. Nothing is
    asserted against a mock; the mock is the hallucination being detected.
    """
    settings = get_rag().settings

    def verdict(draft: str, evidence: str) -> GroundingResult:
        return invoke_structured(
            GroundingResult,
            [
                {"role": "system", "content": VERIFY_GROUNDING_PROMPT},
                {"role": "user", "content": f"DRAFT REPLY:\n{draft}\n\nEVIDENCE:\n\n{evidence}"},
            ],
            settings=settings,
        )

    added = verdict(
        "Refunds are allowed within 14 days and are processed within 3 business days.",
        "QUESTION: refund policy\nEVIDENCE:\n  [1] (source: policy)\n  Refunds are allowed within 14 days.",
    )
    print(f"  invented claim -> grounded={added.grounded}: {added.reason}")
    check("an added timeframe is caught", added.grounded, False)

    translated = verdict(
        "Refunds are allowed within 14 days of purchase.",
        "QUESTION: سياسة الاسترجاع\nEVIDENCE:\n  [1] (source: policy)\n  يُسمح بالاسترجاع خلال 14 يومًا من الشراء.",
    )
    print(f"  translation    -> grounded={translated.grounded}: {translated.reason}")
    check("a faithful translation is not rejected", translated.grounded, True)

    # Two groups whose facts are individually true and wrong about each other.
    # A verifier that pools all evidence into one bucket passes the borrowed
    # claim, because "3 business days" really is in front of it -- just under
    # the other question.
    two_groups = (
        "QUESTION: refund policy\n"
        "EVIDENCE:\n  [1] (source: policy)\n  Refunds are allowed within 14 days."
        "\n\n---\n\n"
        "QUESTION: delivery time\n"
        "EVIDENCE:\n  [1] (source: logistics)\n  Orders are delivered within 3 business days."
    )

    borrowed = verdict(
        "Refunds are processed within 3 business days.", two_groups
    )
    print(f"  borrowed group -> grounded={borrowed.grounded}: {borrowed.reason}")
    check("evidence from another subquestion cannot justify a claim", borrowed.grounded, False)

    own_groups = verdict(
        "Refunds are allowed within 14 days, and orders are delivered within 3 business days.",
        two_groups,
    )
    print(f"  each own group -> grounded={own_groups.grounded}: {own_groups.reason}")
    check("each claim against its own group still passes", own_groups.grounded, True)

    def hallucinating_draft(state) -> dict:
        # Two real facts from the documents, then two that are nowhere in
        # them. Written in English against Arabic evidence on purpose, so the
        # graph-level check also exercises cross-language verification.
        return {
            "answer_draft": (
                "The Bronze package costs 148 USD or 549 SAR. It is activated within "
                "3 business days and comes with a 30-day money-back guarantee."
            )
        }

    original = graph_nodes.generate_answer_node
    graph_nodes.generate_answer_node = hallucinating_draft
    try:
        state, updates, _ = run_turn("كم سعر الباقة البرونزية؟", f"E-{RUN}")
    finally:
        graph_nodes.generate_answer_node = original

    print(f"  graph verdict  -> {updates.get('verify', {}).get('grounding', {}).get('reason')}")
    print(f"  reply          -> {state['final_response'][:120]}")

    check(
        "retrieval succeeded",
        updates.get("search_subquestions", {}).get("retrieval", {}).get("outcome"),
        "all_high",
    )
    check("the verifier rejected the draft", updates.get("verify", {}).get("grounding", {}).get("grounded"), False)
    check("the draft was not delivered", "deliver_answer" in updates, False)
    check("escalated to the ticket agent", "ticket_agent" in updates, True)
    check("a ticket was created", bool(state["ticket_id"]), True)
    check(
        "the unverified draft never reached the customer",
        "money-back" in state["final_response"],
        False,
    )


def scenario_f() -> None:
    """Customer and messages across turns, across threads, across a restart."""
    lookups: list[str] = []
    original = graph_nodes.get_customer

    def counting_get_customer(conn, customer_id):
        lookups.append(customer_id)
        return original(conn, customer_id)

    graph_nodes.get_customer = counting_get_customer
    thread = f"F-{RUN}"
    try:
        first, _, _ = run_turn("مرحبا", thread)
        check("first turn loads the customer", len(lookups), 1)
        check("customer in state", first["customer"]["id"], FIXTURE_CUSTOMER_ID)
        check("first turn has 2 messages", len(first["messages"]), 2)

        second, _, _ = run_turn("شكرا لك", thread)
        check("same thread does not re-query the DB", len(lookups), 1)
        check("customer preserved", second["customer"]["id"], FIXTURE_CUSTOMER_ID)
        check("messages accumulated", len(second["messages"]), 4)

        other, _, _ = run_turn("Hello", f"F-other-{RUN}")
        check("a new thread reloads the customer", len(lookups), 2)
        check("new thread starts its own history", len(other["messages"]), 2)
    finally:
        graph_nodes.get_customer = original

    # Tear the checkpointer down completely -- new saver, new connection, new
    # compiled graph -- so what comes back can only have come off disk.
    reset_checkpointer()
    restored = build_graph().get_state({"configurable": {"thread_id": thread}}).values
    check("thread survives a checkpointer restart", len(restored["messages"]), 4)
    check("customer survives it too", restored["customer"]["id"], FIXTURE_CUSTOMER_ID)
    print(f"  restored {len(restored['messages'])} messages for {thread} from disk")


def scenario_g() -> None:
    """The ticket from D carries the trusted fields the application supplied."""
    state = state_by_scenario.get("D")
    if state is None:
        print("  (skipped: scenario D did not run)")
        return

    original_message = "كم سعر الباقة البرونزية؟ وهل يمكن ربط مسجات مع Salesforce؟"
    conn = connect()
    row = get_ticket(conn, state["ticket_id"])
    conn.close()

    check("the ticket is in the database", row is not None, True)
    if row is None:
        return

    print(f"  category={row['category']}  subject={row['subject']}")
    check("status OPEN", row["status"], "OPEN")
    check("product MSEGAT", row["product"], "MSEGAT")
    check("customer_id from runtime context", row["customer_id"], FIXTURE_CUSTOMER_ID)
    check("original_message stored verbatim", row["original_message"], original_message)
    check("a subject was drafted", bool(row["subject"].strip()), True)
    check("a problem description was drafted", bool(row["problem_description"].strip()), True)
    check(
        "category is from the approved taxonomy",
        row["category"] in ("account", "billing", "technical", "usage", "policy", "other"),
        True,
    )
    check("created_at is ISO-8601 UTC", row["created_at"].endswith("+00:00"), True)


def scenario_r() -> None:
    """Router edge cases the prompt promises but nothing exercised.

    Calls the real `router` node directly with a synthetic state -- a real
    structured model call each, without paying for retrieval. These are the
    misroutes that matter: a wrong direct-route here means the model answers a
    support question from its own memory.
    """
    cases = (
        # Mixed greeting + support question: the greeting must not win.
        ("mixed greeting+question routes to retrieval",
         "Hi there! How much does the Bronze package cost?", "retrieve_evidence", "en"),
        # A complaint with no question mark is still a support message.
        ("complaint without a question routes to retrieval",
         "تظهر لي رسالة الرقم الموحد غير صحيح ولا أستطيع إكمال التسجيل", "retrieve_evidence", "ar"),
        # Latin identifiers inside an Arabic message do not flip the language.
        ("arabic with latin product name stays ar",
         "عندي مشكلة في MSEGAT API", "retrieve_evidence", "ar"),
    )
    for label, message, expected_route, expected_language in cases:
        result = graph_nodes.router({"messages": [HumanMessage(content=message)]})
        print(f"  {result['route']:<18} {result['response_language']}  {message[:60]}")
        check(label, result["route"], expected_route)
        check(f"{label}: language {expected_language}", result["response_language"], expected_language)


def scenario_h() -> None:
    """The reply follows the customer's language, not the evidence's."""
    arabic, ar_updates, _ = run_turn("ما هي متطلبات الاشتراك في الخدمة؟", f"H-ar-{RUN}")
    check("arabic message -> response_language ar", ar_updates["router"]["response_language"], "ar")
    check("arabic reply", detect_language(arabic["final_response"]), "ar")
    print(f"  ar -> {arabic['final_response'][:90]}")

    english, en_updates, _ = run_turn(
        "What are the requirements to subscribe to the service?", f"H-en-{RUN}"
    )
    questions = en_updates["decompose_question"]["questions"]
    check("english message -> response_language en", en_updates["router"]["response_language"], "en")
    check("english reply despite arabic evidence", detect_language(english["final_response"]), "en")
    check("retrieval still searched in arabic", detect_language(questions[0]), "ar")
    print(f"  en -> {english['final_response'][:90]}")
    print(f"  searched in arabic: {questions}")


SCENARIOS = {
    "A": ("direct message bypasses retrieval", scenario_a),
    "B": ("supported single question", scenario_b),
    "C": ("supported multi-question", scenario_c),
    "D": ("mixed HIGH + LOW -> ticket", scenario_d),
    "E": ("grounding failure -> ticket", scenario_e),
    "F": ("customer and thread persistence", scenario_f),
    "G": ("ticket trusted fields", scenario_g),
    "H": ("response language", scenario_h),
    "R": ("router edge cases", scenario_r),
}


def main() -> int:
    configure_logging("WARNING")  # the scenario output is the signal here
    configure_tracing()

    args = sys.argv[1:]
    selected = list(SCENARIOS)
    if args and args[0] == "--only":
        selected = [s.strip().upper() for s in args[1].split(",")]

    for key in selected:
        title, run_scenario = SCENARIOS[key]
        print(f"\n{key}. {title}")
        print("-" * 78)
        run_scenario()

    print("\n" + "=" * 78)
    if failures:
        print(f"{len(failures)} check(s) FAILED:")
        for label in failures:
            print(f"  - {label}")
        return 1
    print("All live workflow checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
