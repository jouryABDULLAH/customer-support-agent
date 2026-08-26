"""The SQLite checkpointer backing thread persistence.

One `SqliteSaver` per process, over its own connection to
`CHECKPOINT_DB_PATH`.

The connection is opened with `check_same_thread=False` because LangGraph may
run nodes on worker threads and Streamlit serves each session on its own
thread, while `sqlite3` otherwise refuses a connection used off the thread
that created it. Serialization is then SQLite's problem, which it handles:
writes are short and the default locking mode serializes them.

`SqliteSaver.from_conn_string()` is the documented convenience, but it is a
context manager that closes the connection on exit -- fine for a script,
wrong for a saver that must outlive any one `with` block.
"""

import logging
import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from customer_support.config import CHECKPOINT_DB_PATH

logger = logging.getLogger(__name__)

_checkpointer: SqliteSaver | None = None


def get_checkpointer(db_path: str | Path = CHECKPOINT_DB_PATH) -> SqliteSaver:
    """The process-wide checkpointer, built on first use.

    `db_path` is honored only on that first call; later calls return the
    existing saver. Tests that need a different file should call
    `reset_checkpointer()` first.
    """
    global _checkpointer
    if _checkpointer is None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        _checkpointer = SqliteSaver(sqlite3.connect(path, check_same_thread=False))
        logger.info("checkpointer: sqlite at %s", path)
    return _checkpointer


def reset_checkpointer() -> None:
    """Close the checkpointer so the next `get_checkpointer()` rebuilds it.

    Exists for the persistence check, which has to prove that thread state
    survives a real teardown of the saver rather than being remembered in
    process memory.
    """
    global _checkpointer
    if _checkpointer is not None:
        _checkpointer.conn.close()
        _checkpointer = None
