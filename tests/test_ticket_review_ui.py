"""Exercise the actual Streamlit approval card without model or network calls."""

import unittest

from streamlit.testing.v1 import AppTest


APP = '''
from types import SimpleNamespace
from unittest.mock import patch
import streamlit as st
from customer_support.ui import approval_card

def capture(graph, command, config, customer):
    st.session_state["submitted"] = command.resume
    st.session_state["submitted_thread"] = config["configurable"]["thread_id"]

snapshot = SimpleNamespace(
    values={"response_language": "en", "ticket_draft": {
        "subject": "Draft subject", "category": "other",
        "problem_description": "Draft description",
    }},
    interrupts=[SimpleNamespace(id="review-1", value={
        "action_requests": [{"name": "submit_draft", "args": {}}],
        "review_configs": [],
    })],
)
if "submitted" not in st.session_state:
    with patch("customer_support.ui._run_turn", capture):
        approval_card(None, snapshot, {"configurable": {"thread_id": "thread-1"}}, {"id": "customer-1"})
'''


class ApprovalCardUITests(unittest.TestCase):
    def test_shows_the_draft_being_submitted(self):
        app = AppTest.from_string(APP, default_timeout=30).run()
        self.assertFalse(app.exception)
        shown = [element.value for element in app.markdown]
        self.assertIn("Draft subject", shown)
        self.assertIn("Draft description", shown)

    def test_approve_resumes_on_the_same_thread(self):
        app = AppTest.from_string(APP, default_timeout=30).run()
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["submitted"], {"decisions": [{"type": "approve"}]})
        self.assertEqual(app.session_state["submitted_thread"], "thread-1")

    def test_reject_resumes_with_a_rejection(self):
        app = AppTest.from_string(APP, default_timeout=30).run()
        app.button[1].click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["submitted"], {"decisions": [{"type": "reject"}]})


if __name__ == "__main__":
    unittest.main()
