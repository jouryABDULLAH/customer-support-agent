"""The LangGraph customer-support workflow.

    from customer_support.graph import Context, build_graph

    graph = build_graph()
    state = graph.invoke(
        {"messages": [{"role": "user", "content": message}]},
        config={"configurable": {"thread_id": thread_id}},
        context=Context(customer_id=customer_id),
    )
    print(state["final_response"])

One `invoke()` is one customer message. Reuse the `thread_id` for every
message in a conversation; the checkpointer restores that thread's history
and its loaded customer.
"""

from customer_support.graph.builder import build_graph
from customer_support.graph.checkpoint import get_checkpointer, reset_checkpointer
from customer_support.graph.context import Context
from customer_support.graph.state import State

__all__ = [
    "Context",
    "State",
    "build_graph",
    "get_checkpointer",
    "reset_checkpointer",
]
