"""The application's normalization layer over `Tenant.find()`.

Graph code depends on `RetrievalResult`, never on ragent2's own types, so the
package's `Result`/`EvidenceChunk` shape is converted exactly once, here.
"""

import logging
from dataclasses import dataclass
from typing import Literal

from ragent2.results import IGNORE, Result

logger = logging.getLogger(__name__)

EvidenceRelation = Literal["direct", "inferential", "context", "unjudged"]
ConfidenceLevel = Literal["high", "medium", "low", "unknown"]
RetrievalOutcome = Literal["usable_evidence", "only_ignored", "no_results"]


RELATION_CONFIDENCE: dict[str, ConfidenceLevel] = {
    "direct": "high",
    "inferential": "medium",
    "context": "low",
    "unjudged": "unknown",
}


@dataclass(frozen=True)
class EvidenceItem:
    """One graded passage, flattened for the graph and the UI.

    `reason` is the grader's own one-line hedge and is kept verbatim: it is what
    stops an inferential clue being reported to a customer as a fact.
    """

    content: str
    relation: EvidenceRelation
    confidence: ConfidenceLevel
    reason: str = ""
    source: str | None = None


@dataclass(frozen=True)
class RetrievalResult:
    """What one retrieval turn produced.

    Attributes:
        outcome: `usable_evidence`, `only_ignored`, or `no_results`.
        evidence: Graded passages, strongest first. Empty unless
            `usable_evidence`.
        warnings: ragent2's warnings about how the run degraded. Non-empty with
            an empty `evidence` means the run failed, not that the documents
            lack an answer.
        ignored_count: Chunks retrieved and dismissed by the grader. Never
            evidence -- the package withholds them -- but recorded so an
            `only_ignored` outcome is explainable.
    """

    outcome: RetrievalOutcome
    evidence: tuple[EvidenceItem, ...] = ()
    warnings: tuple[str, ...] = ()
    ignored_count: int = 0

    @property
    def degraded(self) -> bool:
        """True when ragent2 reported the run degraded. See `warnings`."""
        return bool(self.warnings)


def confidence_for(relation: str) -> ConfidenceLevel:
    """Map a ragent2 relation to this application's confidence level.

    Accepts the package's uppercase names; an unrecognized relation maps to
    `unknown` rather than raising, so a new grade in a later ragent2 release
    degrades instead of breaking retrieval.
    """
    return RELATION_CONFIDENCE.get(relation.lower(), "unknown")


def normalize(result: Result) -> RetrievalResult:
    """Convert one ragent2 `Result` into a `RetrievalResult`."""
    evidence = tuple(
        EvidenceItem(
            content=chunk.text,
            relation=chunk.relation.lower(),
            confidence=confidence_for(chunk.relation),
            reason=chunk.reason,
            source=chunk.source,
        )
        for chunk in result.chunks
    )
    ignored_count = sum(
        1 for entry in result.diagnostics.trace if entry.relation == IGNORE
    )

    if evidence:
        outcome = "usable_evidence"
    elif ignored_count:
        outcome = "only_ignored"
    else:
        outcome = "no_results"

    return RetrievalResult(
        outcome=outcome,
        evidence=evidence,
        warnings=tuple(result.warnings),
        ignored_count=ignored_count,
    )


def retrieve(query: str) -> RetrievalResult:
    """Run agentic retrieval for `query` and normalize what comes back."""
    from customer_support.rag.client import get_documents

    logger.info("retrieval: querying %r", query)
    result = normalize(get_documents().find(query))
    logger.info(
        "retrieval: outcome=%s evidence=%d ignored=%d warnings=%d",
        result.outcome,
        len(result.evidence),
        result.ignored_count,
        len(result.warnings),
    )
    for warning in result.warnings:
        logger.warning("retrieval: ragent2 reported degradation: %s", warning)
    return result
