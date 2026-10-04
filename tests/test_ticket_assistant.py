"""Offline integration checks: python -m unittest discover -s tests -v.

The models are scripted: `ticket_agent` returns a fixed draft and the ticket
assistant replays fixed tool calls, so what is tested is the graph, the tools
and the approval step, not model judgment.
"""

import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from customer_support.db.connection import connect, migrate
from customer_support.db.customers import create_customer
from customer_support.db.tickets import create_ticket
from customer_support.graph import Context, build_graph, nodes, ticket_assistant
from customer_support.schemas import TicketDraft

DRAFT = {"category": "other", "subject": "Original subject", "problem_description": "Original description"}
QUESTION = "Can MSEGAT integrate with Salesforce?"
APPROVE = Command(resume={"decisions": [{"type": "approve"}]})
REJECT = Command(resume={"decisions": [{"type": "reject"}]})


class FakeModel(FakeMessagesListChatModel):
    """Replays scripted messages in order; tools are bound by name only."""

    def bind_tools(self, tools, **kwargs):
        return self


def call(name, **args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call-{name}"}])


def route(state):
    """The router, without a model: `ticket:` messages go to the assistant."""
    message = nodes._customer_message(state)
    return {
        "route": "manage_ticket" if message.startswith("ticket:") else "retrieve_evidence",
        "response_language": "en",
        "final_response": None,
        "ticket_id": None,
    }


class TicketAssistantTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "app.db"
        self.checkpoints = str(Path(self.temp.name) / "checkpoints.db")
        with closing(migrate(self.db)) as conn:
            create_customer(conn, customer_id="customer-1")
            create_customer(conn, customer_id="customer-2")
        self.script = []
        for target, name, replacement in (
            (nodes, "connect", lambda: connect(self.db)),
            (ticket_assistant, "connect", lambda: connect(self.db)),
            (nodes, "router", route),
            (nodes, "decompose_question", lambda state: {"questions": [QUESTION]}),
            (nodes, "search_subquestions", lambda state: {"retrieval": {
                "outcome": "needs_escalation",
                "results": [{"question": QUESTION, "confidence": "low", "evidence": [], "top_score": 0.1}],
            }}),
            (nodes, "invoke_structured", lambda *args, **kwargs: TicketDraft(**DRAFT)),
            (ticket_assistant, "build_model", lambda *args, **kwargs: self.model()),
        ):
            patcher = patch.object(target, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.config = {"configurable": {"thread_id": "thread-1"}}

    def model(self):
        """One model per test, so a graph rebuilt on the same checkpoint
        continues the script rather than restarting it."""
        if not hasattr(self, "_model"):
            self._model = FakeModel(responses=self.script)
        return self._model

    def tickets(self):
        with closing(connect(self.db)) as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM tickets ORDER BY created_at")]

    def say(self, graph, text, customer_id="customer-1"):
        return graph.invoke(
            {"messages": [{"role": "user", "content": text}]},
            self.config,
            context=Context(customer_id=customer_id),
        )

    def resume(self, graph, command):
        return graph.invoke(command, self.config, context=Context(customer_id="customer-1"))

    def test_escalation_proposes_a_draft_without_filing_it(self):
        with SqliteSaver.from_conn_string(self.checkpoints) as saver:
            result = self.say(build_graph(saver), QUESTION)
        self.assertNotIn("__interrupt__", result)
        self.assertIn("drafted a support ticket", result["final_response"])
        self.assertEqual(result["ticket_draft"]["original_message"], QUESTION)
        self.assertIn(QUESTION, result["ticket_draft"]["coverage"])
        self.assertIsNone(result["ticket_id"])
        self.assertEqual(self.tickets(), [])

    def test_edited_draft_is_filed_only_after_approval(self):
        self.script = [
            call("edit_draft", subject="Salesforce API integration"),
            call("submit_draft"),
        ]
        with SqliteSaver.from_conn_string(self.checkpoints) as saver:
            graph = build_graph(saver)
            self.say(graph, QUESTION)
            edited = self.say(graph, "ticket: make the subject about the Salesforce API")
            self.assertEqual(edited["ticket_draft"]["subject"], "Salesforce API integration")
            # The reply is the template, not the model: `edit_draft` is
            # `return_direct`, so the agent never gets another turn to speak.
            self.assertEqual(
                edited["final_response"], "I changed the subject. Shall I submit the ticket?"
            )

            paused = self.say(graph, "ticket: submit it")
            request = paused["__interrupt__"][0].value["action_requests"]
            self.assertEqual([action["name"] for action in request], ["submit_draft"])
            self.assertEqual(self.tickets(), [])

        # Approval survives reopening the checkpoint, as it would across UI reruns.
        with SqliteSaver.from_conn_string(self.checkpoints) as saver:
            result = self.resume(build_graph(saver), APPROVE)

        rows = self.tickets()
        self.assertEqual(len(rows), 1)
        self.assertEqual(result["ticket_id"], rows[0]["id"])
        self.assertIsNone(result["ticket_draft"])
        # The reply is the template, not the model: `submit_draft` is
        # `return_direct`, so the agent never gets another turn to speak.
        self.assertEqual(result["final_response"], f"Submitted as ticket {rows[0]['id']}.")
        self.assertEqual(rows[0]["subject"], "Salesforce API integration")
        self.assertEqual(rows[0]["customer_id"], "customer-1")
        self.assertEqual(rows[0]["original_message"], QUESTION)
        self.assertEqual(rows[0]["status"], "OPEN")
        self.assertTrue(rows[0]["problem_description"].startswith(DRAFT["problem_description"]))
        self.assertIn(QUESTION, rows[0]["problem_description"])

    def test_rejected_submission_keeps_the_draft(self):
        self.script = [call("submit_draft")]
        with SqliteSaver.from_conn_string(self.checkpoints) as saver:
            graph = build_graph(saver)
            self.say(graph, QUESTION)
            self.say(graph, "ticket: submit it")
            result = self.resume(graph, REJECT)
        self.assertEqual(self.tickets(), [])
        self.assertEqual(result["ticket_draft"]["subject"], DRAFT["subject"])
        self.assertIsNone(result["ticket_id"])

    def test_submitted_ticket_is_updated_and_cancelled_after_approval(self):
        with closing(connect(self.db)) as conn:
            ticket_id = create_ticket(conn, "customer-1", "MSEGAT", "other", "Old subject", "Old description", "msg")
        self.script = [
            call("update_ticket", ticket_id=ticket_id, subject="New subject", category="billing"),
            call("cancel_ticket", ticket_id=ticket_id),
            call("update_ticket", ticket_id=ticket_id, subject="Too late"),
        ]
        with SqliteSaver.from_conn_string(self.checkpoints) as saver:
            graph = build_graph(saver)
            self.say(graph, "ticket: rename it and file it under billing")
            self.assertEqual(self.tickets()[0]["subject"], "Old subject")
            result = self.resume(graph, APPROVE)
            row = self.tickets()[0]
            self.assertEqual((row["subject"], row["category"]), ("New subject", "billing"))
            self.assertEqual(row["problem_description"], "Old description")
            self.assertIn(ticket_id, result["final_response"])

            self.say(graph, "ticket: cancel it")
            result = self.resume(graph, APPROVE)
            self.assertEqual(self.tickets()[0]["status"], "CLOSED")
            self.assertEqual(result["final_response"], f"Ticket {ticket_id} cancelled.")

            self.say(graph, "ticket: rename it again")
            result = self.resume(graph, APPROVE)
            self.assertEqual(self.tickets()[0]["subject"], "New subject")
            self.assertIn("only OPEN tickets", result["final_response"])

    def test_another_customers_ticket_cannot_be_changed(self):
        with closing(connect(self.db)) as conn:
            ticket_id = create_ticket(conn, "customer-2", "MSEGAT", "other", "Theirs", "Their description", "msg")
        self.script = [call("cancel_ticket", ticket_id=ticket_id)]
        with SqliteSaver.from_conn_string(self.checkpoints) as saver:
            graph = build_graph(saver)
            self.say(graph, "ticket: cancel it")
            result = self.resume(graph, APPROVE)
        self.assertEqual(self.tickets()[0]["status"], "OPEN")
        self.assertIn(f"no ticket {ticket_id}", result["final_response"])


if __name__ == "__main__":
    unittest.main()
