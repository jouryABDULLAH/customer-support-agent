"""Send one message through the graph and print what came back.

    python scripts/run_workflow.py "كم سعر الباقة البرونزية؟"
    python scripts/run_workflow.py --thread demo-1 --customer TEST-CUSTOMER-001 "..."

Reuse the same `--thread` to continue a conversation: the checkpointer
restores that thread's history and its already-loaded customer. The customer
must already exist in the database -- the graph never creates one.

Needs Qdrant and docling-serve running (`ragent2 up`) and `GROQ_API_KEY` in
the shell.
"""

import sys

from customer_support.graph import Context, build_graph
from customer_support.observability import configure_logging, configure_tracing

DEFAULT_CUSTOMER_ID = "TEST-CUSTOMER-001"
DEFAULT_THREAD_ID = "demo-thread"


def run(message: str, customer_id: str, thread_id: str, preview_chars: int = 200) -> dict:
    graph = build_graph()
    state = graph.invoke(
        {"messages": [{"role": "user", "content": message}]},
        config={"configurable": {"thread_id": thread_id}},
        context=Context(customer_id=customer_id),
    )

    print("=" * 78)
    print(f"THREAD   {thread_id}")
    print(f"CUSTOMER {state['customer']['id']}  ({state['customer']['name']})")
    print(f"MESSAGE  {message}")
    print("=" * 78)
    print("\nRESPONSE")
    print("-" * 78)
    print(state["final_response"])

    if state.get("ticket_id"):
        print(f"\nTICKET   {state['ticket_id']}")

    evidence = state.get("response_evidence") or []
    if evidence:
        print(f"\nEVIDENCE ({len(evidence)} passage(s))")
        print("-" * 78)
        for item in evidence:
            text = item["content"].replace("\n", " ")[:preview_chars]
            print(f"  {item['score']:.4f}  {item['source']}")
            print(f"          {text}")

    print(f"\nTURNS ON THIS THREAD: {len(state['messages'])} message(s)")
    return state


def main() -> int:
    configure_logging()
    configure_tracing()

    args = sys.argv[1:]
    customer_id, thread_id = DEFAULT_CUSTOMER_ID, DEFAULT_THREAD_ID
    while args and args[0] in ("--thread", "--customer"):
        if args[0] == "--thread":
            thread_id = args[1]
        else:
            customer_id = args[1]
        args = args[2:]

    if not args:
        print(__doc__)
        return 1

    run(" ".join(args), customer_id, thread_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
