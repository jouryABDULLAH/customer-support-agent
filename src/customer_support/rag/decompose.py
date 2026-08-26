"""Split a customer message into independently searchable questions.

One focused structured-output LLM call. It does not answer, classify, or
rewrite -- it only decides where one support question ends and the next
begins, which is a judgment about the customer's *intent* that a splitter on
"and"/"?" gets wrong in both directions.
"""

import logging

from ragent2.llm.client import invoke_structured

from customer_support.rag.prompts import DECOMPOSE_QUESTIONS_PROMPT
from customer_support.rag.schema import QuestionDecomposition

logger = logging.getLogger(__name__)


def decompose(message: str, settings) -> list[str]:
    """Return the independently searchable questions in `message`.

    Falls back to the message itself if the model returns nothing, so a
    degenerate decomposition cannot silently drop the customer's question.
    """
    result = invoke_structured(
        QuestionDecomposition,
        [
            {"role": "system", "content": DECOMPOSE_QUESTIONS_PROMPT},
            {"role": "user", "content": f"Input: {message}"},
        ],
        model=settings.answer_model,
        settings=settings,
        temperature=0.0,
        max_tokens=settings.metadata_max_output_tokens,
    )
    questions = [q.strip() for q in result.questions if q.strip()]
    if not questions:
        logger.warning("decompose: model returned no questions; using the message as-is.")
        return [message.strip()]
    logger.info("decompose: %d question(s) from %d char message", len(questions), len(message))
    return questions
