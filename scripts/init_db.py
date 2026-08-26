"""Create (or update) the application database from schema.sql.

    python scripts/init_db.py [db_path]

Idempotent; existing data is untouched.
"""

import sys

from customer_support.config import APP_DB_PATH
from customer_support.db.connection import init_db


def main() -> int:
    db_path = sys.argv[1] if len(sys.argv) > 1 else APP_DB_PATH
    conn = init_db(db_path) # initialize
    tables = [ # print
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        )
    ]
    conn.close() # close
    print(f"Initialized {db_path} with tables: {', '.join(tables)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
