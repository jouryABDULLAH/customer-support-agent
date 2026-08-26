"""End-to-end prototype: decompose -> search -> confidence -> answer.

    python scripts/qa_prototype.py "How do I subscribe and what does it cost?"
    python scripts/qa_prototype.py --threshold 0.4 "..."

Prints the following diagnostics: the original message, the extracted
subquestions, the evidence and top reranker score per subquestion, each
confidence verdict, the aggregate outcome, and the grounded answer when every
subquestion cleared the threshold.
"""

import sys

from customer_support.config import RAG_CONFIDENCE_THRESHOLD
from customer_support.observability import configure_logging, configure_tracing
from customer_support.rag.answer import detect_language, generate_answer
from customer_support.rag.client import get_rag
from customer_support.rag.decompose import decompose
from customer_support.rag.search import low_confidence_questions, search_questions


def run(message: str, threshold: float, preview_chars: int = 160) -> dict:
    settings = get_rag().settings

    print("=" * 78)
    print(f"ORIGINAL MESSAGE\n  {message}")
    print("=" * 78)

    questions = decompose(message, settings)
    print(f"\nDECOMPOSITION -> {len(questions)} question(s)")
    for n, question in enumerate(questions, start=1):
        print(f"  {n}. {question}")

    retrieval = search_questions(questions, threshold)

    print(f"\nRETRIEVAL (threshold={threshold})")
    for n, result in enumerate(retrieval["results"], start=1):
        score = result["top_score"]
        shown = "None" if score is None else f"{score:.4f}"
        print(f"\n  [{n}] {result['question']}")
        print(f"      top_score={shown}  confidence={result['confidence'].upper()}"
              f"  passages={len(result['evidence'])}")
        for item in result["evidence"][:3]:
            text = item["content"].replace("\n", " ")[:preview_chars]
            print(f"        - {item['score']:.4f}  {item['source']}")
            print(f"          {text}")

    print(f"\nOUTCOME: {retrieval['outcome']}")

    if retrieval["outcome"] == "all_high":
        print("\nGROUNDED ANSWER")
        print("-" * 78)
        print(generate_answer(message, retrieval, settings, detect_language(message)))
    else:
        print("\nNEEDS ESCALATION -- unresolved subquestion(s):")
        for question in low_confidence_questions(retrieval):
            print(f"  - {question}")
        print("\n(No answer generated; no ticket created -- that is Phase 8.)")
    return retrieval


def main() -> int:
    configure_logging()
    configure_tracing()
    args = sys.argv[1:]
    threshold = RAG_CONFIDENCE_THRESHOLD
    if args and args[0] == "--threshold":
        threshold = float(args[1])
        args = args[2:]
    if not args:
        print(__doc__)
        return 1
    run(" ".join(args), threshold)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
