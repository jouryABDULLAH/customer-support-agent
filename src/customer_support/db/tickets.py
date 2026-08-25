"""Ticket persistence.

`create_ticket` generates the id and timestamp, sets status OPEN, and stores `original_message` exactly as given.

The LLM-drafted fields (product, category, subject, problem_description)
arrive as plain strings; their taxonomy is validated upstream, not here.
"""

import sqlite3
import uuid
from datetime import datetime, timezone

OPEN = "OPEN"
STATUSES = ("OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED")


def create_ticket(
    conn: sqlite3.Connection,
    customer_id: str,
    product: str,
    category: str,
    subject: str,
    problem_description: str,
    original_message: str,
) -> str:
    """Insert an OPEN ticket and return its generated id."""
    ticket_id = uuid.uuid4().hex
    created_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO tickets
            (id, customer_id, product, category, subject,
             problem_description, original_message, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ticket_id,
            customer_id,
            product,
            category,
            subject,
            problem_description,
            original_message,
            OPEN,
            created_at,
        ),
    )
    conn.commit()
    return ticket_id


def get_ticket(conn: sqlite3.Connection, ticket_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM tickets WHERE id = ?", (ticket_id,)
    ).fetchone()


def list_tickets(
    conn: sqlite3.Connection,
    customer_id: str | None = None,
    product: str | None = None,
    status: str | None = None,
) -> list[sqlite3.Row]:
    """Tickets newest first, optionally filtered on any combination given."""
    clauses, params = [], []
    for column, value in (
        ("customer_id", customer_id),
        ("product", product),
        ("status", status),
    ):
        if value is not None:
            clauses.append(f"{column} = ?")
            params.append(value)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return conn.execute(
        f"SELECT * FROM tickets {where} ORDER BY created_at DESC", params
    ).fetchall()


def update_ticket_status(
    conn: sqlite3.Connection, ticket_id: str, status: str
) -> bool:
    """Set a ticket's status. Returns False if the ticket does not exist.

    An invalid status raises `sqlite3.IntegrityError` from the schema's CHECK
    constraint.
    """
    cursor = conn.execute(
        "UPDATE tickets SET status = ? WHERE id = ?", (status, ticket_id)
    )
    conn.commit()
    return cursor.rowcount > 0
