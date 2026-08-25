"""Explicit document ingestion into the application tenant.

Never called from application startup: indexing is minutes of OCR and LLM work
per document, and re-running it is a developer decision. `scripts/ingest_docs.py`
is the only entry point.

Re-running is safe. ragent2 hashes each file's bytes and raises
`DuplicateDocumentError` for one this tenant already has, so an unchanged file
is skipped rather than indexed twice; an edited file hashes differently and is
ingested as a new document.
"""

import logging
from pathlib import Path

from ragent2.api import IngestResult
from ragent2.errors import (
    CorruptedTextLayerError,
    DocumentTooLargeError,
    DuplicateDocumentError,
    IngestInProgressError,
)

from customer_support.config import DOCS_DIR

logger = logging.getLogger(__name__)

# What docling-serve can convert. Anything else in the folder is left alone.
SUPPORTED_SUFFIXES = {".pdf", ".docx", ".pptx", ".xlsx", ".md", ".html", ".txt"}


def discover_documents(docs_dir: str | Path = DOCS_DIR) -> list[Path]:
    """Every supported document under `docs_dir`, recursively, sorted."""
    root = Path(docs_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"Documents directory not found: {root.resolve()}")

    supported: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() in SUPPORTED_SUFFIXES:
            supported.append(path)
        else:
            logger.info(
                "ingest: skipping %s -- '%s' is not in SUPPORTED_SUFFIXES.",
                path.name,
                path.suffix or "no extension",
            )
    return supported


def ingest_file(path: Path) -> IngestResult | None:
    """Index one document. Returns `None` if it was already indexed.

    Ingestion failures are logged and swallowed so one unreadable document does
    not abandon the rest of the batch; the caller sees it in the summary counts.
    """
    from customer_support.rag.client import get_documents

    logger.info("ingest: starting %s", path.name)
    try:
        result = get_documents().add(path)
    except DuplicateDocumentError:
        logger.info("ingest: %s is already indexed; skipping.", path.name)
        return None
    except IngestInProgressError:
        logger.warning("ingest: %s is already being indexed elsewhere; skipping.", path.name)
        return None
    except (CorruptedTextLayerError, DocumentTooLargeError) as exc:
        logger.error("ingest: %s could not be indexed: %s", path.name, exc)
        return None
    except Exception:
        # A plain re-run for Groq failure during chunking (a rate limit, or a
        # `json_validate_failed` 400 that outlived ragent2's own repair retries)
        logger.exception("ingest: %s failed; continuing with the rest.", path.name)
        return None

    logger.info(
        "ingest: %s indexed as doc_id=%s with %d chunk(s).",
        result.filename,
        result.doc_id,
        result.chunk_count,
    )
    return result


def ingest_directory(docs_dir: str | Path = DOCS_DIR) -> list[IngestResult]:
    """Index every supported document under `docs_dir`.

    Sequential on purpose: each document is already dozens of concurrent LLM
    calls internally, and overlapping documents on top of that is what runs into
    Groq's rate limits.
    """
    paths = discover_documents(docs_dir)
    logger.info("ingest: %d document(s) found under %s", len(paths), Path(docs_dir).resolve())

    ingested = [result for path in paths if (result := ingest_file(path)) is not None]
    logger.info(
        "ingest: %d newly indexed, %d skipped or failed, %d chunk(s) total.",
        len(ingested),
        len(paths) - len(ingested),
        sum(result.chunk_count for result in ingested),
    )
    return ingested
