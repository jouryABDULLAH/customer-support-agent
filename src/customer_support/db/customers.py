"""Customer persistence. Only `id` is universally required."""

import re
import sqlite3
import uuid

_PHONE_NOISE = re.compile(r"[\s()\-.‏‎]")


def normalize_phone(phone: str) -> str:
    """Strip formatting noise from a phone number so it stores and matches consistently.

    Removes spaces, dashes, dots, parentheses and the bidi marks that ride
    along when a number is pasted out of Arabic text, and rewrites a leading
    international `00` prefix as `+`. So `"+966 50-000 0000"`, `"00966500000000"`
    and `"+966500000000"` all become `"+966500000000"`.

    Deliberately does NOT convert between local and international forms:
    `"0500000000"` stays as it is rather than being guessed into
    `"+966500000000"`, because the country to assume is a product decision and
    this layer serves any tenant. Store numbers in one form -- E.164 for
    preference -- and this keeps them comparable.
    """
    cleaned = _PHONE_NOISE.sub("", phone).strip()
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    return cleaned


def create_customer(
    conn: sqlite3.Connection,
    name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    customer_id: str | None = None,
) -> str:
    """Insert a customer and return its id (generated unless supplied).

    `phone` is normalized on the way in, so the UNIQUE constraint sees one
    form per number and `get_customer_by_phone` can find it however the caller
    happens to punctuate it.
    """
    customer_id = customer_id or uuid.uuid4().hex
    conn.execute(
        "INSERT INTO customers (id, name, email, phone) VALUES (?, ?, ?, ?)",
        (customer_id, name, email, normalize_phone(phone) if phone else phone),
    )
    conn.commit()
    return customer_id


def get_customer(conn: sqlite3.Connection, customer_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM customers WHERE id = ?", (customer_id,)
    ).fetchone()


def get_customers_by_name(conn: sqlite3.Connection, name: str) -> list[sqlite3.Row]:
    """Every customer with exactly this name.

    A list, not a single row: `name` carries no UNIQUE constraint, so unlike
    id/email/phone it cannot promise one match. The caller decides what an
    ambiguous name means -- the UI, for instance, refuses to log one in.
    """
    return conn.execute(
        "SELECT * FROM customers WHERE name = ?", (name,)
    ).fetchall()


def get_customer_by_email(conn: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM customers WHERE email = ?", (email,)
    ).fetchone()


def get_customer_by_phone(conn: sqlite3.Connection, phone: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM customers WHERE phone = ?", (normalize_phone(phone),)
    ).fetchone()
