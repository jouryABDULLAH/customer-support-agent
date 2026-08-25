"""Customer persistence. Only `id` is universally required."""

import sqlite3
import uuid


def create_customer(
    conn: sqlite3.Connection,
    name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    customer_id: str | None = None,
) -> str:
    """Insert a customer and return its id (generated unless supplied)."""
    customer_id = customer_id or uuid.uuid4().hex
    conn.execute(
        "INSERT INTO customers (id, name, email, phone) VALUES (?, ?, ?, ?)",
        (customer_id, name, email, phone),
    )
    conn.commit()
    return customer_id


def get_customer(conn: sqlite3.Connection, customer_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM customers WHERE id = ?", (customer_id,)
    ).fetchone()


def get_customer_by_email(conn: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM customers WHERE email = ?", (email,)
    ).fetchone()
