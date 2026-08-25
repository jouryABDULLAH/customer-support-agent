"""SQLite connection handling for the application database.

Every connection goes through `connect()`: rows come back as `sqlite3.Row`
(column access by name) and foreign keys are enforced -- SQLite ships with
them OFF per connection, and without the pragma the `tickets.customer_id`
reference is decoration.
"""

import sqlite3
from pathlib import Path

from customer_support.config import APP_DB_PATH

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def connect(db_path: str | Path = APP_DB_PATH) -> sqlite3.Connection:
    """Open a connection with row factory and foreign keys configured."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str | Path = APP_DB_PATH) -> sqlite3.Connection:
    """Open a connection and apply `schema.sql`. Idempotent."""
    conn = connect(db_path)
    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()
    return conn
