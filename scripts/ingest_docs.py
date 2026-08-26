"""Index the documents under Docs/ into the application tenant.

    ragent2 up
    python scripts/ingest_docs.py [docs_dir]
    LOG_LEVEL=OFF python scripts/ingest_docs.py   # silent
    LOG_LEVEL=DEBUG python scripts/ingest_docs.py # verbose

Explicit developer operation; nothing calls this on application startup.
"""

import sys

from customer_support.config import DOCS_DIR, configure_logging
from customer_support.rag.client import check_health
from customer_support.rag.ingestion import ingest_directory


def main() -> int:
    configure_logging()
    docs_dir = sys.argv[1] if len(sys.argv) > 1 else DOCS_DIR

    report = check_health()
    print(report)
    if not report.healthy:
        print("\nServices are not reachable. Start them with `ragent2 up`.")
        return 1

    ingest_directory(docs_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
