# Test findings: Arabic cases

Run: 2026-09-28, 11 Arabic cases from `msegat_agent_test_cases.md`
(TC01, 02, 03, 06, 08, 10, 12, 13, 14, 15, 17). Customer `TEST-CUSTOMER-001`.
Every ticket prompt was declined, so no test tickets were written.

Totals: ~20 min (1,208 s across cases), 38 model calls. Retrieval is ~55–60 s
per sub-question.

## Verdict: unexpected behavior found

| ID | What it tests | Expected | Got | Result |
|---|---|---|---|---|
| TC01 | Credit validity period | ANSWER | Answered: 1 year, usable anytime | PASS |
| TC02 | International message cost | ANSWER | Answered: 7 / 21 points + country list | PASS (bonus: enabling international sending, not mentioned) |
| TC03 | "Account suspended" on login (dialect) | ANSWER (contact support) | Answered: contact support via تواصل معنا | PASS (bonus: phone hours, not mentioned) |
| TC06 | Greeting + upgrade to Premium | ANSWER + return greeting | Greeting returned; steps correct | PARTIAL: cost (1.4 points), priority delivery missing |
| TC08 | 3 questions on character counting | ANSWER ×3 | All 3 answered correctly | PASS |
| TC10 | Greeting + charity requirements + free trial + ticket response time + thanks | ANSWER ×3 | **Escalated** | FAIL |
| TC12 | Mobile app? (not in docs) | ESCALATE | Escalated (LOW 0.09) | PASS |
| TC13 | WhatsApp message price (not in docs) | ESCALATE | Escalated (LOW 0.01) | PASS |
| TC14 | Gold price + Tabby/Tamara + sender names per CR + branch invoice | PARTIAL | Escalated whole turn | EXPECTED BY DESIGN (see 2) |
| TC15 | Enable international + MMS video + sent vs delivered + SLA | PARTIAL | Escalated whole turn | EXPECTED BY DESIGN (see 2) |
| TC17 | Freeze account ("شبكات" typo) | ANSWER (can't freeze) or CLARIFY | **Escalated** (LOW 0.007) | FAIL |

Checked on every case and found correct: all replies were in Arabic, no facts
were invented, and the verifier never passed an unsupported claim.

## Issues

### 1. Answerable question escalated because decomposition changed its meaning (TC10)
The customer asked a general "is there a free trial?". Decomposition copied
the charity context from the first question into it:
`هل هناك فترة تجريبية مجانية للجمعيات الخيرية؟`. That version scored LOW
(0.226), so the whole turn escalated. The other two sub-questions scored HIGH
(0.786, 0.975), and the FAQ does cover the free trial (10 free messages).
- Where to look: `rag/prompts/decomposition.py`. Carrying context forward is
  right for a missing product name, but wrong for a qualifier that belongs to
  another question.

### 2. Mixed answerable/unanswerable questions escalate as a whole (TC14, TC15)
This is by design (`route_after_retrieval`: one LOW escalates the turn; no
partial answers). The test file expects answers to the answerable parts plus
an escalation for the rest. This is a product decision, not a bug.

### 3. Freeze-account answer exists in the docs but is never retrieved (TC17)
The FAQ says the subscription cannot be paused or frozen (credit stays valid
for a year). With the "شبكات" typo, search scored 0.007. The earlier manual
run with the correct "مسجات" also missed this passage: the top hit (0.736) was
the username passage. The verifier then caught the non-answer and escalated.
So this is a retrieval gap, not only a typo problem. There is also no
clarifying-question path for the "CLARIFY" option.
- Where to look: how the FAQ entry is chunked and worded ("إيقاف أو تجميد
  الاشتراك" vs the customer's "أجمد حسابي").

### 4. Ticket descriptions misstate what is unresolved (TC10, TC14)
`_unresolved_notes` lists which questions the docs DO cover, but the ticket
agent wrote that none of them had an answer:
- TC14: "الوثائق المتاحة لا تحتوي على إجابات لهذه الاستفسارات" (gold price
  and sender names are covered).
- TC10: "لم يتم العثور على إجابة في الوثائق الحالية" (requirements and
  response time are covered).
TC15 got this right. The engineer would re-research questions that are
already answered.
- Where to look: `prompts/ticket.py`, `<problem_description>`: require
  separating covered from uncovered questions.

### 5. Answer covers the question but skips related expected facts (TC06, minor)
The upgrade steps were correct. The cost (1.4 points per message) and the
priority-delivery benefit, both in the FAQ, were left out. The verifier's
coverage rule only fails an omitted answer to the question asked, so this
passes by design. TC02 and TC03 also missed their "bonus" facts.

## Not tested here
- Closings (thanks/goodbye): TC10 was the only Arabic case with a closing, and
  it escalated.
- Ticket approval (approve path): every ticket was declined on purpose.
