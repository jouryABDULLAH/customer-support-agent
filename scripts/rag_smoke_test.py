"""Prove the retrieval path end to end and record what `find()` really returns.

    ragent2 up
    python scripts/ingest_docs.py
    python scripts/rag_smoke_test.py

Prints, for each query: the raw ragent2 `Result` structure (types and fields, so
the runtime contract is recorded rather than assumed) and the `RetrievalResult`
this application normalizes it into.
"""

import logging
import sys
from dataclasses import fields, is_dataclass

from customer_support.rag.client import get_documents
from customer_support.rag.retrieval import normalize


def describe(value: object, indent: str = "  ") -> str:
    """Render a dataclass instance as field: type = value lines."""
    if not is_dataclass(value):
        return f"{indent}{type(value).__name__} = {value!r}"
    lines = [f"{indent}{type(value).__name__}:"]
    for spec in fields(value):
        item = getattr(value, spec.name)
        rendered = repr(item)
        if len(rendered) > 160:
            rendered = rendered[:157] + "..."
        lines.append(f"{indent}  .{spec.name}: {type(item).__name__} = {rendered}")
    return "\n".join(lines)


def run(query: str, label: str) -> None:
    print("\n" + "=" * 78)
    print(f"{label}\nQUERY: {query}")
    print("=" * 78)

    result = get_documents().find(query)

    print(f"\nRAW type: {type(result).__module__}.{type(result).__name__}")
    print(f"  bool(result) = {bool(result)}   len(result) = {len(result)}")
    print(f"  warnings = {result.warnings}")
    print(describe(result.diagnostics))
    for number, chunk in enumerate(result.chunks, start=1):
        print(f"\n  -- chunk {number} --")
        print(describe(chunk, indent="    "))

    normalized = normalize(result)
    print("\nNORMALIZED:")
    print(f"  outcome       = {normalized.outcome}")
    print(f"  degraded      = {normalized.degraded}")
    print(f"  ignored_count = {normalized.ignored_count}")
    print(f"  warnings      = {normalized.warnings}")
    for number, item in enumerate(normalized.evidence, start=1):
        print(
            f"  [{number}] relation={item.relation} confidence={item.confidence} "
            f"source={item.source}"
        )
        print(f"      reason: {item.reason}")
        print(f"      text:   {item.content[:200]!r}")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(name)s: %(message)s")

    documents = get_documents()
    indexed = documents.list()
    print(f"Tenant {documents.user_id!r} has {len(indexed)} document(s):")
    for document in indexed:
        print(f"  - {document.name}  (doc_id={document.doc_id})")
    if not indexed:
        print("Nothing indexed. Run scripts/ingest_docs.py first.")
        return 1

    if len(sys.argv) > 1:
        for query in sys.argv[1:]:
            run(query, "SUPPLIED QUERY")
        return 0

    print("\nPass one or more queries as arguments to test them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
