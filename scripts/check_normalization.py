"""Offline checks for the retrieval normalization layer. No services needed.

    python scripts/check_normalization.py

Covers UC-007 (only_ignored) and UC-008 (confidence mapping) from
tests/use_cases.md, plus the two outcome cases and the degraded-run
distinction. These use synthetic `ragent2.results.Result` values because
`only_ignored` and a grader outage cannot be produced on demand from real
documents; the live path is exercised by scripts/rag_smoke_test.py instead.
"""

from ragent2.results import ChunkTrace, EvidenceChunk, FindDiagnostics, Result

from customer_support.rag.retrieval import confidence_for, normalize

failures: list[str] = []


def check(label: str, actual: object, expected: object) -> None:
    if actual == expected:
        print(f"  ok    {label} = {actual!r}")
    else:
        failures.append(f"{label}: expected {expected!r}, got {actual!r}")
        print(f"  FAIL  {label}: expected {expected!r}, got {actual!r}")


def main() -> int:
    print("UC-008 confidence mapping (approved, plus the relations the real API adds):")
    check("DIRECT", confidence_for("DIRECT"), "high")
    check("INFERENTIAL", confidence_for("INFERENTIAL"), "medium")
    check("CONTEXT", confidence_for("CONTEXT"), "low")
    check("UNJUDGED", confidence_for("UNJUDGED"), "unknown")
    check("unrecognized relation", confidence_for("SOMETHING_NEW"), "unknown")

    print("\nusable_evidence:")
    result = normalize(
        Result(
            chunks=(
                EvidenceChunk(
                    chunk_id="c1",
                    text="Refunds are allowed within 14 days.",
                    relation="DIRECT",
                    score=3,
                    reason="States the refund window outright.",
                    document_name="policy.pdf",
                    page_number=2,
                ),
                EvidenceChunk(
                    chunk_id="c2",
                    text="Support operates 9-5.",
                    relation="CONTEXT",
                    score=1,
                    reason="Background for interpreting the window.",
                    document_name="policy.pdf",
                ),
            ),
            diagnostics=FindDiagnostics(query="refund window?"),
        )
    )
    check("outcome", result.outcome, "usable_evidence")
    check("evidence count", len(result.evidence), 2)
    check("relation lowercased", result.evidence[0].relation, "direct")
    check("confidence", result.evidence[0].confidence, "high")
    check("source with page", result.evidence[0].source, "policy.pdf, page 2")
    check("grader reason kept", result.evidence[0].reason, "States the refund window outright.")
    check("source without page", result.evidence[1].source, "policy.pdf")
    check("degraded", result.degraded, False)

    print("\nUC-007 only_ignored (IGNORE never reaches chunks; read from diagnostics.trace):")
    result = normalize(
        Result(
            chunks=(),
            diagnostics=FindDiagnostics(
                query="unrelated question",
                trace=(
                    ChunkTrace(chunk_id="c9", relation="IGNORE", returned=False),
                    ChunkTrace(chunk_id="c8", relation="IGNORE", returned=False),
                ),
            ),
        )
    )
    check("outcome", result.outcome, "only_ignored")
    check("ignored_count", result.ignored_count, 2)
    check("no evidence", len(result.evidence), 0)

    print("\nno_results (nothing retrieved at all):")
    result = normalize(Result(chunks=(), diagnostics=FindDiagnostics(query="nothing")))
    check("outcome", result.outcome, "no_results")
    check("ignored_count", result.ignored_count, 0)
    check("degraded", result.degraded, False)

    print("\ndegraded run stays distinguishable from a documented absence:")
    result = normalize(
        Result(
            chunks=(),
            warnings=("Grading failed for 3 chunks.",),
            diagnostics=FindDiagnostics(query="x"),
        )
    )
    check("outcome", result.outcome, "no_results")
    check("degraded", result.degraded, True)
    check("warnings carried", result.warnings, ("Grading failed for 3 chunks.",))

    print("\nUNJUDGED is evidence nobody read, not evidence dismissed:")
    result = normalize(
        Result(
            chunks=(
                EvidenceChunk(
                    chunk_id="c1", text="t", relation="UNJUDGED", score=None,
                    document_name="d.pdf",
                ),
            ),
            warnings=("The grader was unavailable.",),
            diagnostics=FindDiagnostics(query="x"),
        )
    )
    check("outcome", result.outcome, "usable_evidence")
    check("confidence", result.evidence[0].confidence, "unknown")
    check("degraded", result.degraded, True)

    if failures:
        print(f"\n{len(failures)} check(s) FAILED.")
        return 1
    print("\nAll normalization checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
