"""SQLite connection handling and migrations for the application database.

Every connection goes through `connect()`: rows come back as `sqlite3.Row`
(column access by name) and foreign keys are enforced -- SQLite ships with
them OFF per connection, and without the pragma the `tickets.customer_id`
reference is decoration.

Schema changes are versioned migrations in `migrations/NNN_*.sql`, applied in
order by `migrate()`. The applied version lives in SQLite's own
`PRAGMA user_version` header field, so no bookkeeping table is needed. Each
migration runs exactly once per database; write plain DDL, no `IF NOT EXISTS`.
"""

import sqlite3
from pathlib import Path

from customer_support.config import APP_DB_PATH

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def connect(db_path: str | Path = APP_DB_PATH) -> sqlite3.Connection:
    """Open a connection with row factory and foreign keys configured."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrate(
    db_path: str | Path = APP_DB_PATH,
    migrations_dir: str | Path = _MIGRATIONS_DIR,
) -> sqlite3.Connection:
    """Open a connection and apply every migration newer than the DB's version.

    Returns the connection at the latest version. A fresh database starts at
    `user_version` 0 and receives every migration; an up-to-date one receives
    none. `migrations_dir` is overridable for tests only.
    """
    conn = connect(db_path)
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for path in sorted(Path(migrations_dir).glob("*.sql")):
        version = int(path.name.split("_")[0])
        if version > current:
            conn.executescript(path.read_text(encoding="utf-8"))
            # PRAGMA takes no parameters; `version` is int()-parsed above.
            conn.execute(f"PRAGMA user_version = {version}")
            conn.commit()
    return conn


# The historical name; scripts and callers may use either.
init_db = migrate
