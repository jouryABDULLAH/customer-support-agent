"""Exercise the actual Streamlit review form without model or network calls."""

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
    values={"response_language": "en"},
    interrupts=[SimpleNamespace(id="review-1", value={
        "subject": "Original subject", "category": "other",
        "problem_description": "Original description",
    })],
)
if "submitted" not in st.session_state:
    with patch("customer_support.ui._run_turn", capture):
        approval_card(None, snapshot, {"configurable": {"thread_id": "thread-1"}}, {"id": "customer-1"})
'''


class TicketReviewUITests(unittest.TestCase):
    def test_form_submits_edited_fields_on_same_thread(self):
        app = AppTest.from_string(APP, default_timeout=30).run()
        self.assertFalse(app.exception)
        app.text_input[0].input("Edited subject")
        app.selectbox[0].select("billing")
        app.text_area[0].input("Edited problem")
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["submitted"], {
            "approved": True,
            "ticket_draft": {"subject": "Edited subject", "category": "billing", "problem_description": "Edited problem"},
        })
        self.assertEqual(app.session_state["submitted_thread"], "thread-1")

    def test_blank_subject_stays_editable_and_decline_still_works(self):
        app = AppTest.from_string(APP, default_timeout=30).run()
        app.text_input[0].input("   ")
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.error), 1)
        self.assertEqual(app.text_input[0].value, "   ")
        app.button[1].click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["submitted"], {"approved": False})


if __name__ == "__main__":
    unittest.main()
