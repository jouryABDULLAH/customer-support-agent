# Example support requests

Paste-ready messages for testing the agent through the UI, ordered easy →
hard. Each entry says what it exercises and where the answer lives. Source
documents are in `Docs/MSEGAT/`.

Expected latency: direct replies are a few seconds; anything that retrieves
takes ~1.5 minutes per subquestion (CPU reranker).

---

## 1. Greeting — direct path

> السلام عليكم

**Tests:** router bypasses retrieval entirely; instant Arabic reply; no
evidence expander, no ticket.
**Path:** `router → respond_directly`. No document.

---

## 2. Question announcement — preamble rule

> بسألك سؤال عن مسجات

**Tests:** the product is named but there is nothing to look up yet — the
router must reply with an invitation to ask, not run a 90-second search.
**Path:** `router → respond_directly` (preamble rule). No document.

---

## 3. Simple supported question — happy path

> كم سعر الباقة البرونزية؟

**Tests:** single-question retrieval, HIGH confidence (~0.98), grounded
answer quoting the actual prices (148 USD / 549 SAR), evidence expander
populated, verification passes.
**Path:** full pipeline `decompose → search → generate → verify → deliver`.
**Source:** `Price .docx`.

---

## 4. English question over Arabic documents

> What are the requirements to subscribe to the service?

**Tests:** cross-language: English in → Arabic search question → English
answer built from Arabic evidence; verifier's translation rule.
**Path:** full pipeline; decomposition translates the query.
**Source:** `Msegat User manual(2).docx`.

---

## 5. Long-format request — complaint narrative with an error code

> السلام عليكم ورحمة الله،
> عندي استفسار بخصوص التسجيل في منصة مسجات. حاولت أسجل حساب جديد لشركتنا
> وأدخلت جميع البيانات المطلوبة، لكن عند الضغط على متابعة تظهر لي رسالة
> "الرقم الموحد غير صحيح" مع أني متأكد أن الرقم المدخل هو نفس الرقم الموجود
> في السجل التجاري. هل في طريقة معينة لكتابة الرقم أو خطوة ناقصة عندي؟
> شكراً جزيلاً لكم.

**Tests:** routing a real-world message (greeting + story + question +
thanks) to retrieval, not to the direct path; decomposition must preserve the
error string «الرقم الموحد غير صحيح» exactly and strip the pleasantries.
**Path:** full pipeline.
**Source:** `Common Errors Msegat.docx`.

---

## 6. Long-format request — two questions inside pleasantries (English)

> Hi there,
> I hope you're doing well. I'm evaluating MSEGAT for our company and have a
> couple of questions before we commit. What do we need to prepare to
> subscribe as a private company — documents, registrations, that kind of
> thing? And how much does the Bronze package cost? We're a small team, so
> we'd start with the cheapest tier.
> Thanks a lot in advance!

**Tests:** decomposition into exactly two searchable Arabic questions with
the product name carried over; one search per subquestion; one coherent
English reply covering both (no "Question 1/2" headings); evidence drawn from
two documents.
**Path:** full pipeline, multi-question.
**Sources:** `Msegat User manual(2).docx` + `Price .docx`.

---

## 7. FAQ-style policy question

> هل يمكن تخصيص باقة بناءً على احتياجنا؟ وما هو الحد الأدنى للشحن في هذه الحالة؟

**Tests:** a conditional/policy answer (custom packages require charging
≥ 200,000 points) — the decomposition must NOT split the condition away from
the request it modifies; grounded answer with a specific number.
**Path:** full pipeline.
**Source:** `FAQ - AI Last change .docx`.

---

## 8. Mixed supported + unsupported — escalation to a ticket

> مرحباً، عندي سؤالين: كم سعر الباقة البرونزية؟ وهل يمكن ربط مسجات مع
> نظام Salesforce عن طريق API مباشرة؟

**Tests:** one subquestion HIGH (~0.98) and one LOW (~0.25) → **no partial
answer is sent**; a ticket is created; the reply names the ticket id; the
Tickets tab shows status OPEN, a drafted subject/category, and the original
message stored verbatim. The ticket's description should mention both what
was unanswerable and what the documents do cover.
**Path:** `decompose → search → needs_escalation → ticket_agent →
create_ticket`. The verifier and answer generator never run.
**Source:** `Price .docx` answers half; nothing answers Salesforce — that is
the point.

---

## Cleanup

Escalation tests create real rows in `data/app.db`. To clear tickets before
a demo:

    python -c "from customer_support.db.connection import connect; c = connect(); c.execute('DELETE FROM tickets'); c.commit()"
