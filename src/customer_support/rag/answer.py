"""Generate one grounded customer answer from retrieved evidence.

Only ever called when every subquestion cleared the confidence threshold
(`outcome == "all_high"`). A low-confidence subquestion escalates instead --
the whole point of the threshold is that this prompt never has to guess.
"""

import logging
import re

from customer_support.model import build_model
from customer_support.rag.prompts import (
    CUSTOMER_NAME_NOTE,
    GROUNDED_ANSWER_PROMPT,
    REVISE_ANSWER_PROMPT,
)
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

def evidence_block(retrieval: RetrievalResult) -> str:
    """Render the per-subquestion evidence, grouped by the question it answers.

    Shared by the answering prompt and the grounding verifier so both judge
    the same text laid out the same way -- a verifier shown a different
    rendering than the author is checking a different thing. Grouping is what
    stops evidence retrieved for one question being used to invent an answer
    to another.
    """
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


def generate_answer(
    message: str,
    retrieval: RetrievalResult,
    settings,
    language: str,
    customer_name: str | None = None,
) -> str:
    """Answer `message` from `retrieval`'s evidence, in `language`.

    `language` is `"ar"` or `"en"` and is named outright in the prompt rather
    than inferred. The evidence here is almost entirely Arabic, and asking the
    model to infer "the customer's language" let that evidence win -- an
    English question came back answered in Arabic. In the graph the value
    comes from the router; `detect_language` serves callers without one.

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

    language_name = "Arabic" if language == "ar" else "English"

    system = GROUNDED_ANSWER_PROMPT
    if customer_name:
        system += CUSTOMER_NAME_NOTE.format(name=customer_name)

    llm = build_model(settings=settings)
    response = llm.invoke(
        [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"REPLY LANGUAGE: {language_name}\n\n"
                    f"Customer's original message:\n{message}\n\n"
                    f"Evidence:\n\n{evidence_block(retrieval)}\n\n"
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


def revise_answer(
    message: str,
    retrieval: RetrievalResult,
    draft: str,
    reason: str,
    settings,
    language: str,
) -> str:
    """Correct a draft that failed grounding verification.

    The same shared rules as `generate_answer`. Only the task differs: `reason` (the verifier's finding)
    names the unsupported claims, and the prompt confines the change to them.
    The result goes back through verification; this function does not decide
    whether the correction succeeded.
    """
    if retrieval["outcome"] != "all_high":
        raise ValueError(
            "revise_answer requires outcome 'all_high'; got "
            f"{retrieval['outcome']!r}. Low-confidence questions must escalate."
        )

    language_name = "Arabic" if language == "ar" else "English"

    llm = build_model(settings=settings)
    response = llm.invoke(
        [
            {"role": "system", "content": REVISE_ANSWER_PROMPT},
            {
                "role": "user",
                "content": (
                    f"REPLY LANGUAGE: {language_name}\n\n"
                    f"Customer's original message:\n{message}\n\n"
                    f"Evidence:\n\n{evidence_block(retrieval)}\n\n"
                    f"Previous draft:\n{draft}\n\n"
                    f"Reviewer's reason it is not grounded:\n{reason}\n\n"
                    f"Write the full corrected reply in {language_name}."
                ),
            },
        ]
    )
    revised = str(response.content).strip()
    logger.info(
        "answer: revised %d -> %d chars in %s (reason: %s)",
        len(draft), len(revised), language, reason[:120],
    )
    return revised
