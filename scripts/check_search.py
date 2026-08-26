"""Offline checks for confidence and aggregation. No services needed.

    python scripts/check_search.py

Covers the branches a live search cannot produce: `search()` applies no score
threshold and is "empty only when nothing is indexed", so on a populated tenant
`top_score=None` is unreachable in practice -- it is still the contract when a
tenant is empty, so it is verified here with synthetic input. Also pins the
`>=` boundary, which live scores would only hit by coincidence.
"""

from customer_support.rag.search import (
    RetrievalResult,
    SubQuestionResult,
    aggregate,
    confidence_for,
    low_confidence_questions,
)

failures: list[str] = []


def check(label: str, actual: object, expected: object) -> None:
    if actual == expected:
        print(f"  ok    {label}")
    else:
        failures.append(label)
        print(f"  FAIL  {label}: expected {expected!r}, got {actual!r}")


def result(question: str, score: float | None, threshold: float = 0.30) -> SubQuestionResult:
    return {
        "question": question,
        "evidence": [] if score is None else [{"content": "t", "score": score, "source": "d"}],
        "top_score": score,
        "confidence": confidence_for(score, threshold),
    }


def main() -> int:
    print("confidence threshold:")
    check("above threshold is high", confidence_for(0.9, 0.30), "high")
    check("at threshold is high (>=)", confidence_for(0.30, 0.30), "high")
    check("just below is low", confidence_for(0.2999, 0.30), "low")
    check("far below is low", confidence_for(0.001, 0.30), "low")
    check("no evidence is low", confidence_for(None, 0.30), "low")
    check("negative score is low", confidence_for(-4.2, 0.30), "low")

    print("\nempty search result (tenant with nothing indexed):")
    empty = result("unanswerable", None)
    check("top_score is None", empty["top_score"], None)
    check("confidence is low", empty["confidence"], "low")
    check("evidence is empty", empty["evidence"], [])

    print("\naggregation:")
    all_high: RetrievalResult = aggregate([result("a", 0.8), result("b", 0.5)])
    check("every high -> all_high", all_high["outcome"], "all_high")
    check("results preserved", len(all_high["results"]), 2)

    mixed = aggregate([result("a", 0.8), result("b", 0.01)])
    check("one low -> needs_escalation", mixed["outcome"], "needs_escalation")
    check("names the low subquestion", low_confidence_questions(mixed), ["b"])

    none_high = aggregate([result("a", 0.01), result("b", None)])
    check("all low -> needs_escalation", none_high["outcome"], "needs_escalation")
    check("names both", low_confidence_questions(none_high), ["a", "b"])

    single = aggregate([result("a", 0.8)])
    check("single high -> all_high", single["outcome"], "all_high")
    check("empty input -> needs_escalation", aggregate([])["outcome"], "needs_escalation")

    if failures:
        print(f"\n{len(failures)} check(s) FAILED.")
        return 1
    print("\nAll search/confidence checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
