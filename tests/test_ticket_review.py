"""Offline integration checks: python -m unittest discover -s tests -v."""

import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from customer_support.db.connection import connect, migrate
from customer_support.db.customers import create_customer
from customer_support.graph import build_graph, nodes
from customer_support.schemas import TicketDraft


DRAFT = {"category": "other", "subject": "Original subject", "problem_description": "Original description"}
EDITED = {"category": "billing", "subject": "Corrected subject", "problem_description": "Corrected description"}


class TicketReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "app.db"
        self.checkpoints = str(Path(self.temp.name) / "checkpoints.db")
        with closing(migrate(self.db)) as conn:
            create_customer(conn, customer_id="customer-1")
        for name, replacement in (
            ("connect", lambda: connect(self.db)),
            ("router", lambda state: {"route": "retrieve_evidence", "response_language": "en"}),
            ("decompose_question", lambda state: {"questions": ["Original request"]}),
            ("search_subquestions", lambda state: {"retrieval": {"outcome": "needs_escalation", "results": []}}),
        ):
            patcher = patch.object(nodes, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(nodes, "invoke_structured", return_value=TicketDraft(**DRAFT))
        self.model = patcher.start()
        self.addCleanup(patcher.stop)
        self.config = {"configurable": {"thread_id": "review-thread"}}

    def tickets(self):
        with closing(connect(self.db)) as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM tickets")]

    def pause(self, graph):
        result = graph.invoke({
            "customer": {"id": "customer-1"},
            "messages": [{"role": "user", "content": "Original request"}],
        }, self.config)
        self.assertIn("__interrupt__", result)
        payload = result["__interrupt__"][0].value
        self.assertEqual(json.loads(json.dumps(payload))["subject"], DRAFT["subject"])
        self.assertEqual(self.tickets(), [])
        self.model.assert_called_once()

    def test_edits_survive_checkpoint_reopen_and_are_persisted(self):
        with SqliteSaver.from_conn_string(self.checkpoints) as saver:
            self.pause(build_graph(saver))
        with SqliteSaver.from_conn_string(self.checkpoints) as saver:
            graph = build_graph(saver)
            self.assertTrue(graph.get_state(self.config).interrupts)
            result = graph.invoke(Command(resume={"approved": True, "ticket_draft": EDITED}), self.config)
            self.assertNotIn("__interrupt__", result)
            self.assertIsNone(result["ticket_review_error"])
            self.assertIsNone(result["ticket_draft"])
        rows = self.tickets()
        self.assertEqual(len(rows), 1)
        for field in ("category", "subject"):
            self.assertEqual(rows[0][field], EDITED[field])
        self.assertTrue(rows[0]["problem_description"].startswith(EDITED["problem_description"]))
        self.assertEqual(rows[0]["customer_id"], "customer-1")
        self.assertEqual(rows[0]["original_message"], "Original request")
        self.model.assert_called_once()

    def test_decline_dictionary_does_not_create_ticket(self):
        with SqliteSaver.from_conn_string(self.checkpoints) as saver:
            graph = build_graph(saver)
            self.pause(graph)
            result = graph.invoke(Command(resume={"approved": False}), self.config)
            self.assertNotIn("__interrupt__", result)
            self.assertIsNone(result["ticket_id"])
            self.assertEqual(self.tickets(), [])

    def test_invalid_responses_reprompt_then_accept_correction(self):
        with SqliteSaver.from_conn_string(self.checkpoints) as saver:
            graph = build_graph(saver)
            self.pause(graph)
            for response in (
                "yes", {"approved": "false"}, {"approved": 1}, {},
                {"approved": True, "ticket_draft": {**EDITED, "subject": "  "}},
                {"approved": True, "ticket_draft": {**EDITED, "category": "unknown"}},
                {"approved": True, "ticket_draft": {**EDITED, "customer_id": "someone-else"}},
            ):
                with self.subTest(response=response):
                    result = graph.invoke(Command(resume=response), self.config)
                    self.assertEqual(result["__interrupt__"][0].value["error"], "invalid_review")
                    self.assertEqual(self.tickets(), [])
                    self.model.assert_called_once()
            graph.invoke(Command(resume={"approved": True, "ticket_draft": EDITED}), self.config)
            self.assertEqual(len(self.tickets()), 1)
            self.model.assert_called_once()

    def test_boolean_approval_remains_supported(self):
        with SqliteSaver.from_conn_string(self.checkpoints) as saver:
            graph = build_graph(saver)
            self.pause(graph)
            graph.invoke(Command(resume=True), self.config)
            self.assertEqual(self.tickets()[0]["subject"], DRAFT["subject"])


if __name__ == "__main__":
    unittest.main()
