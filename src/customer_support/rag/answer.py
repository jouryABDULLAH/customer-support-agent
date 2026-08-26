"""Generate one grounded customer answer from retrieved evidence.

Only ever called when every subquestion cleared the confidence threshold
(`outcome == "all_high"`). A low-confidence subquestion escalates instead --
the whole point of the threshold is that this prompt never has to guess.
"""

import logging
import re

from customer_support.model import build_model
from customer_support.rag.prompts import GROUNDED_ANSWER_PROMPT
from customer_support.rag.schema import RetrievalResult

logger = logging.getLogger(__name__)

_ARABIC = re.compile(r"[؀-ۿ]")


def detect_language(message: str) -> str:
    """`"ar"` or `"en"` for the customer's message.

    Deterministic on purpose: the evidence here is almost entirely Arabic, and
    asking the answering model to infer "the customer's language" let that
    evidence win -- an English question came back answered in Arabic. Naming
    the target language outright removes the inference. Presence of Arabic
    script decides it; a message mixing scripts (Arabic with a Latin product
    name) is Arabic, which is the common real case.
    """
    return "ar" if _ARABIC.search(message) else "en"

def _evidence_block(retrieval: RetrievalResult) -> str:
    """Render the per-subquestion evidence the model is allowed to use."""
    blocks: list[str] = []
    for result in retrieval["results"]:
        passages = [
            f"  [{n}] (source: {item['source'] or 'unknown'})\n  {item['content']}"
            for n, item in enumerate(result["evidence"], start=1)
        ]
        blocks.append(
            f"QUESTION: {result['question']}\nEVIDENCE:\n"
            + ("\n\n".join(passages) if passages else "  (none)")
        )
    return "\n\n---\n\n".join(blocks)


def generate_answer(message: str, retrieval: RetrievalResult, settings) -> str:
    """Answer `message` from `retrieval`'s evidence, in the customer's language.

    Every retrieved passage is passed, not just the top-scoring few. Reranker
    scores are not reliable *within* a query: asked for package prices, the
    reranker put the section's intro ("below are the prices in SAR and USD")
    at 0.885 and the actual price table at 0.017, rank 5. Trimming by rank
    therefore drops the answer while keeping a passage that only promises it.
    The threshold's job is deciding whether to answer at all; it is not a
    within-query relevance ranking.
    """
    if retrieval["outcome"] != "all_high":
        raise ValueError(
            "generate_answer requires outcome 'all_high'; got "
            f"{retrieval['outcome']!r}. Low-confidence questions must escalate."
        )

    language = detect_language(message)
    language_name = "Arabic" if language == "ar" else "English"

    llm = build_model(settings=settings)
    response = llm.invoke(
        [
            {"role": "system", "content": GROUNDED_ANSWER_PROMPT},
            {
                "role": "user",
                "content": (
                    f"REPLY LANGUAGE: {language_name}\n\n"
                    f"Customer's original message:\n{message}\n\n"
                    f"Evidence:\n\n{_evidence_block(retrieval)}\n\n"
                    f"Write the entire reply in {language_name}."
                ),
            },
        ]
    )
    answer = str(response.content).strip()
    logger.info(
        "answer: generated %d chars in %s for %d subquestion(s)",
        len(answer), language, len(retrieval["results"]),
    )
    return answer
