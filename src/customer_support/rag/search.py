"""Per-subquestion retrieval over RAGent2 `search()`.

one `search()` call per subquestion. The shapes it returns are defined in
`rag/schema.py`.

Confidence comes from the cross-encoder rerank score of the best passage,
compared against a configured threshold. `search()` applies no threshold of its
own -- it always returns its nearest chunks however weak -- so a non-empty
result is NOT evidence the question was answered, and the score is the only
signal separating the two.
"""

import logging
from typing import Literal

from langsmith import traceable

from customer_support.config import RAG_CONFIDENCE_THRESHOLD
from customer_support.rag.schema import (
    EvidenceItem,
    RetrievalResult,
    SubQuestionResult,
)

logger = logging.getLogger(__name__)


def confidence_for(top_score: float | None, threshold: float | None = None) -> Literal["high", "low"]:
    """HIGH when the best passage scores at or above the threshold."""
    cutoff = RAG_CONFIDENCE_THRESHOLD if threshold is None else threshold
    return "high" if top_score is not None and top_score >= cutoff else "low"


def _source(passage) -> str | None:
    """`"document, page N"` for a passage, matching find()'s citation style."""
    if passage.document_name is None:
        return None
    if passage.page_number is not None:
        return f"{passage.document_name}, page {passage.page_number}"
    return passage.document_name


@traceable(name="search_question")
def search_question(question: str, threshold: float | None = None) -> SubQuestionResult:
    """Search one subquestion exactly once and score the result.

    `@traceable` gives each subquestion its own span in LangSmith -- without
    it the graph's `search_subquestions` node is one opaque block covering the
    whole retrieval (~86s of a 90s turn in the first live trace), with no way
    to see which question the time went to. A no-op when tracing is off.
    ragent2's internals (Qdrant query, reranking) stay untraced; splitting
    those would mean instrumenting ragent2 itself.
    """
    from customer_support.rag.client import get_documents

    passages = get_documents().search(question)
    evidence: list[EvidenceItem] = [
        {"content": p.text, "score": p.score, "source": _source(p)} for p in passages
    ]
    # Passages come back best-first, but max() states the intent without
    # depending on that ordering.
    top_score = max((item["score"] for item in evidence), default=None)
    confidence = confidence_for(top_score, threshold)

    logger.info(
        "search: %r -> %d passage(s), top_score=%s, confidence=%s",
        question,
        len(evidence),
        "none" if top_score is None else f"{top_score:.4f}",
        confidence,
    )
    return {
        "question": question,
        "evidence": evidence,
        "top_score": top_score,
        "confidence": confidence,
    }


def aggregate(results: list[SubQuestionResult]) -> RetrievalResult:
    """`all_high` only when every subquestion cleared the threshold."""
    outcome = (
        "all_high"
        if results and all(r["confidence"] == "high" for r in results)
        else "needs_escalation"
    )
    return {"results": results, "outcome": outcome}


def search_questions(
    questions: list[str], threshold: float | None = None
) -> RetrievalResult:
    """Search every subquestion exactly once and aggregate the outcome."""
    return aggregate([search_question(q, threshold) for q in questions])


def low_confidence_questions(result: RetrievalResult) -> list[str]:
    """The subquestions that need escalation."""
    return [r["question"] for r in result["results"] if r["confidence"] == "low"]
