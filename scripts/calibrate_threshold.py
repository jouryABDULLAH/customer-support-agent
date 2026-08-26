"""Observe reranker scores on known-supported and known-unsupported questions.

    python scripts/calibrate_threshold.py

Prints a score table used to choose `RAG_CONFIDENCE_THRESHOLD`. The score is a
bge-reranker score, not a probability -- this picks a cutoff that separates two
observed groups, nothing more.

Includes "adjacent" questions: plausible MSEGAT-flavored questions the
documents do not actually answer. Those are where a threshold earns its value;
an obviously off-topic question separates from anything.
"""

from customer_support.config import RAG_CONFIDENCE_THRESHOLD, configure_logging
from customer_support.rag.search import search_question

SUPPORTED_AR = [
    "كم سعر الباقة البرونزية؟",
    "ما هي متطلبات الاشتراك في الخدمة؟",
    "ما هي الباقات المتاحة للاشتراك في مسجات؟",
    "لماذا تظهر رسالة الرقم الموحد غير صحيح؟",
]
SUPPORTED_EN = [
    "What is the price of the Bronze package?",
    "What are the requirements to subscribe to the service?",
]
ADJACENT_UNSUPPORTED_AR = [
    "هل يمكن ربط مسجات مع Salesforce؟",
    "ما هو رقم الآيبان الخاص بحساب مسجات البنكي؟",
]
UNSUPPORTED = [
    "What is the capital of France?",
    "كم مدة الإجازة السنوية للموظفين؟",
    "How do I return a laptop to Amazon?",
]

GROUPS = [
    ("SUPPORTED (ar)", SUPPORTED_AR),
    ("SUPPORTED (en)", SUPPORTED_EN),
    ("ADJACENT-UNSUPPORTED (ar)", ADJACENT_UNSUPPORTED_AR),
    ("UNSUPPORTED", UNSUPPORTED),
]


def main() -> int:
    configure_logging("WARNING")  # the table is the output; keep it readable
    observed: dict[str, list[float]] = {}

    for label, questions in GROUPS:
        print(f"\n{label}")
        print("-" * 78)
        for question in questions:
            result = search_question(question)
            score = result["top_score"]
            observed.setdefault(label, []).append(score if score is not None else 0.0)
            top = result["evidence"][0]["source"] if result["evidence"] else "(none)"
            shown = "None" if score is None else f"{score:.4f}"
            print(f"  {shown:>8}  n={len(result['evidence']):<3} {question}")
            print(f"            top source: {top}")

    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    for label, scores in observed.items():
        print(f"  {label:<28} min={min(scores):.4f}  max={max(scores):.4f}")

    supported = observed.get("SUPPORTED (ar)", []) + observed.get("SUPPORTED (en)", [])
    unsupported = (
        observed.get("ADJACENT-UNSUPPORTED (ar)", []) + observed.get("UNSUPPORTED", [])
    )
    if supported and unsupported:
        print(f"\n  lowest supported   : {min(supported):.4f}")
        print(f"  highest unsupported: {max(unsupported):.4f}")
        gap = min(supported) - max(unsupported)
        print(f"  separation         : {gap:+.4f}")
        if gap > 0:
            print(f"  -> any threshold in ({max(unsupported):.4f}, {min(supported):.4f}] separates them")
        else:
            print("  -> GROUPS OVERLAP: no threshold separates them cleanly")
    print(f"\n  configured RAG_CONFIDENCE_THRESHOLD = {RAG_CONFIDENCE_THRESHOLD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
