"""Graph construction: register nodes, wire edges, compile.

Behavior lives in `nodes.py`, the branch conditions
in `routing.py`, prompt text in `customer_support.prompts`. Kept that way, this
file reads as the workflow diagram and stays worth reading when the shape
changes.

    START
      -> load_customer_if_needed
      -> router
         |- respond_directly ----------------------------------.
         '- decompose_question -> search_subquestions           |
              |- (all_high)      generate_answer -> verify      |
              |                     |- (grounded) deliver_answer|
              |                     '- (not)  ---.              |
              '- (needs_escalation) ------------ ticket_agent   |
                                                 -> create_ticket
      -> finalize_turn -> END
"""

from langgraph.graph import END, START, StateGraph

from customer_support.graph import nodes, routing
from customer_support.graph.checkpoint import get_checkpointer
from customer_support.graph.context import Context
from customer_support.graph.state import State


def build_graph(checkpointer=None):
    """Compile the support workflow.

    Args:
        checkpointer: `None` uses the process-wide SQLite checkpointer, which
            is what persists a conversation across invocations. Pass one
            explicitly to point a test at its own file.
    """
    builder = StateGraph(State, context_schema=Context)

    builder.add_node("load_customer_if_needed", nodes.load_customer_if_needed)
    builder.add_node("router", nodes.router)
    builder.add_node("respond_directly", nodes.respond_directly)
    builder.add_node("decompose_question", nodes.decompose_question)
    builder.add_node("search_subquestions", nodes.search_subquestions)
    builder.add_node("generate_answer", nodes.generate_answer_node)
    builder.add_node("verify", nodes.verify)
    builder.add_node("deliver_answer", nodes.deliver_answer)
    builder.add_node("ticket_agent", nodes.ticket_agent)
    builder.add_node("create_ticket", nodes.create_ticket)
    builder.add_node("finalize_turn", nodes.finalize_turn)

    builder.add_edge(START, "load_customer_if_needed")
    builder.add_edge("load_customer_if_needed", "router")

    builder.add_conditional_edges(
        "router",
        routing.route_after_router,
        ["respond_directly", "decompose_question"],
    )
    builder.add_edge("respond_directly", "finalize_turn")

    builder.add_edge("decompose_question", "search_subquestions")
    builder.add_conditional_edges(
        "search_subquestions",
        routing.route_after_retrieval,
        ["generate_answer", "ticket_agent"],
    )

    builder.add_edge("generate_answer", "verify")
    builder.add_conditional_edges(
        "verify",
        routing.route_after_verification,
        ["deliver_answer", "ticket_agent"],
    )
    builder.add_edge("deliver_answer", "finalize_turn")

    builder.add_edge("ticket_agent", "create_ticket")
    builder.add_edge("create_ticket", "finalize_turn")

    builder.add_edge("finalize_turn", END)

    return builder.compile(
        checkpointer=get_checkpointer() if checkpointer is None else checkpointer
    )
