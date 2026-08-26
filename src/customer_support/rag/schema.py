"""Retrieval schemas. 

Every retrieval shape the application passes around lives in this module, so
there is one place to read the contract and one place to change it. Deliberately
a leaf: it imports nothing from `customer_support.rag`, so any module in that
package can import it without a cycle.

`QuestionDecomposition` is a Pydantic model because it is *model output* and
needs strict validation (`extra="forbid"`) at the LLM boundary. The rest are
`TypedDict`s because they are internal shapes the application builds itself,
where a runtime validator would only cost time.
"""

from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict


class QuestionDecomposition(BaseModel):
    """Structured output of the decomposition call: one entry per question."""

    model_config = ConfigDict(extra="forbid")

    questions: list[str]


class EvidenceItem(TypedDict):
    """One retrieved passage.

    `score` is the cross-encoder rerank score, which stands in for that
    judgment.
    """

    content: str
    score: float
    source: str | None


class SubQuestionResult(TypedDict):
    """One subquestion's retrieval outcome.

    `top_score` is the highest `score` among `evidence`, and `None` when
    `evidence` is empty -- which happens only when the tenant has nothing
    indexed, since `search()` applies no score threshold of its own.
    """

    question: str
    evidence: list[EvidenceItem]
    top_score: float | None
    confidence: Literal["high", "low"]


class RetrievalResult(TypedDict):
    """Every subquestion's result, plus the aggregate verdict.

    `all_high` only when every subquestion cleared the threshold; a single low
    one makes the whole turn `needs_escalation`. Low-confidence subquestions
    are kept in `results`, not dropped -- see `low_confidence_questions`.
    """

    results: list[SubQuestionResult]
    outcome: Literal["all_high", "needs_escalation"]
