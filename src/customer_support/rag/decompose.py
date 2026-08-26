"""Split a customer message into independently searchable questions.

One focused structured-output LLM call. It does not answer, classify, or
rewrite -- it only decides where one support question ends and the next
begins, which is a judgment about the customer's *intent* that a splitter on
"and"/"?" gets wrong in both directions.
"""

import logging

from pydantic import BaseModel, ConfigDict
from ragent2.llm.client import invoke_structured

logger = logging.getLogger(__name__)


class QuestionDecomposition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[str]


_PROMPT = """\
You split a customer support message into independently searchable questions.

<rules>
- Preserve the customer's meaning. Never answer, classify, or judge a question.
- Return ONE question when the message contains only one support question.
- Split only genuinely independent questions -- ones that would be looked up
  in different places.
- Never split a condition, cause, or detail away from the question it belongs
  to. "if", "when", "because" and "after" almost always signal one question.
- Make each question searchable on its own: resolve pronouns and carry over
  the product name, so a reader who sees only that one question understands it.
- Preserve product names, error codes, numbers and other identifiers exactly.
- Write each question in the SAME language as the customer's message.
- Invent nothing that is not in the message.
</rules>

<examples>
Input: How can I login in MSEGAT and is it possible to freeze my account?
Output: ["How can I login in MSEGAT?", "Is it possible to freeze my MSEGAT account?"]

Input: How can I reset my password if I no longer have access to my email?
Output: ["How can I reset my password if I no longer have access to my email?"]

Input: كيف أشترك في مسجات وما هي أسعار الباقات؟
Output: ["كيف أشترك في مسجات؟", "ما هي أسعار باقات مسجات؟"]

Input: لماذا يظهر الخطأ 403 عند إرسال رسالة رغم وجود رصيد كافٍ؟
Output: ["لماذا يظهر الخطأ 403 عند إرسال رسالة رغم وجود رصيد كافٍ؟"]
</examples>"""


def decompose(message: str, settings) -> list[str]:
    """Return the independently searchable questions in `message`.

    Falls back to the message itself if the model returns nothing, so a
    degenerate decomposition cannot silently drop the customer's question.
    """
    result = invoke_structured(
        QuestionDecomposition,
        [
            {"role": "system", "content": _PROMPT},
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
