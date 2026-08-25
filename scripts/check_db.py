"""Phase 2 gate checks for the application database. Uses a scratch DB file.

    python scripts/check_db.py

Covers: customer create/fetch (including id-only and by-email lookup), ticket
create/read with an exact `original_message` round-trip (Arabic + emoji),
filtered listing, status update, the CHECK constraint on status, and
foreign-key enforcement on `customer_id`.
"""

import sqlite3
import tempfile
from pathlib import Path

from customer_support.db import customers, tickets
from customer_support.db.connection import init_db

failures: list[str] = []


def check(label: str, actual: object, expected: object) -> None:
    if actual == expected:
        print(f"  ok    {label}")
    else:
        failures.append(label)
        print(f"  FAIL  {label}: expected {expected!r}, got {actual!r}")


def main() -> int:
    scratch = Path(tempfile.mkdtemp()) / "check_app.db"
    conn = init_db(scratch)
    init_db(scratch).close()  # idempotent re-init must not fail

    print("customers:")
    full_id = customers.create_customer(
        conn,
        name="Test Customer",
        email="test-customer-001@example.com",
        phone="0500000000",
        customer_id="TEST-CUSTOMER-001",
    )
    bare_id = customers.create_customer(conn)  # only id is required
    row = customers.get_customer(conn, full_id)
    check("create/fetch", (row["name"], row["phone"]), ("Test Customer", "0500000000"))
    check("caller-supplied id kept", full_id, "TEST-CUSTOMER-001")
    row = customers.get_customer_by_email(conn, "test-customer-001@example.com")
    check("fetch by email", row["id"], full_id)
    row = customers.get_customer_by_phone(conn, "0500000000")
    check("fetch by phone", row["id"], full_id)
    check("unknown phone is None", customers.get_customer_by_phone(conn, "0000"), None)

    print("\nphone normalization:")
    check("strips spaces and dashes",
          customers.normalize_phone("+966 50-000 0000"), "+966500000000")
    check("00 prefix becomes +",
          customers.normalize_phone("00966500000000"), "+966500000000")
    check("already canonical is unchanged",
          customers.normalize_phone("+966500000000"), "+966500000000")
    check("local form is left alone",
          customers.normalize_phone("0500000000"), "0500000000")
    intl_id = customers.create_customer(conn, phone="+966 55-111 2222")
    check("stored normalized",
          customers.get_customer(conn, intl_id)["phone"], "+966551112222")
    check("found via a differently punctuated form",
          customers.get_customer_by_phone(conn, "00966 55 111 2222")["id"], intl_id)
    row = customers.get_customer(conn, bare_id)
    check("id-only customer", (row["name"], row["email"], row["phone"]), (None, None, None))
    check("missing customer is None", customers.get_customer(conn, "nope"), None)

    print("\ntickets:")
    original = "الرسالة لا تُرسل ويظهر الخطأ 403 😕 — لماذا؟\nمع سطرٍ ثانٍ."
    ticket_id = tickets.create_ticket(
        conn,
        customer_id=full_id,
        product="MSEGAT",
        category="technical",
        subject="فشل إرسال الرسائل",
        problem_description="العميل يواجه الخطأ 403 عند الإرسال.",
        original_message=original,
    )
    row = tickets.get_ticket(conn, ticket_id)
    check("status starts OPEN", row["status"], "OPEN")
    check("original_message round-trips exactly", row["original_message"], original)
    check("created_at is ISO UTC", row["created_at"].endswith("+00:00"), True)
    check("customer_id preserved", row["customer_id"], full_id)

    tickets.create_ticket(
        conn, full_id, "SOUQT2", "billing", "s", "d", "m"
    )
    check("list all", len(tickets.list_tickets(conn)), 2)
    check("list by product", len(tickets.list_tickets(conn, product="MSEGAT")), 1)
    check("list by customer+status",
          len(tickets.list_tickets(conn, customer_id=full_id, status="OPEN")), 2)

    check("update status", tickets.update_ticket_status(conn, ticket_id, "RESOLVED"), True)
    check("status updated", tickets.get_ticket(conn, ticket_id)["status"], "RESOLVED")
    check("update missing ticket", tickets.update_ticket_status(conn, "nope", "OPEN"), False)

    print("\nconstraints:")
    try:
        customers.create_customer(conn, email="test-customer-001@example.com")
        check("UNIQUE rejects duplicate email", "no error", "IntegrityError")
    except sqlite3.IntegrityError:
        check("UNIQUE rejects duplicate email", True, True)
    try:
        customers.create_customer(conn, phone="0500000000")
        check("UNIQUE rejects duplicate phone", "no error", "IntegrityError")
    except sqlite3.IntegrityError:
        check("UNIQUE rejects duplicate phone", True, True)
    # SQLite treats NULLs as distinct, so "no email/phone" is not a duplicate.
    customers.create_customer(conn)
    check("multiple NULL emails/phones allowed",
          customers.get_customer(conn, bare_id) is not None, True)
    try:
        tickets.update_ticket_status(conn, ticket_id, "GARBAGE")
        check("CHECK rejects bad status", "no error", "IntegrityError")
    except sqlite3.IntegrityError:
        check("CHECK rejects bad status", True, True)
    try:
        tickets.create_ticket(conn, "no-such-customer", "p", "c", "s", "d", "m")
        check("FK rejects unknown customer", "no error", "IntegrityError")
    except sqlite3.IntegrityError:
        check("FK rejects unknown customer", True, True)

    conn.close()
    if failures:
        print(f"\n{len(failures)} check(s) FAILED.")
        return 1
    print("\nAll database checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
