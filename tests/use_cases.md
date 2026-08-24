# Use Cases

| ID | Title | Target function | Input | Expected output |
|----|-------|-----------------|-------|-----------------|
| UC-001 | Arabic greeting | workflow | السلام عليكم | - Routes to direct response.<br>- Responds in Arabic.<br>- RAG is not called.<br>- No ticket is created. |
| UC-002 | English greeting | router | Hello | respond_directly |
| UC-003 | Support question requires retrieval | router | كيف أقدر أغير كلمة المرور في سوق؟ | retrieve_evidence |
| UC-004 | Supported Arabic question | workflow | \<A known SOUQT2 question whose answer exists directly in the documents\> | - RAGent2 find() is called.<br>- Supporting evidence is returned.<br>- Answer is based only on that evidence.<br>- Answer is in Arabic.<br>- No ticket is created. |
| UC-005 | Supported English question | workflow | \<A known MESGAT question whose answer exists in the documents\> | - Evidence is retrieved.<br>- Answer is grounded in the evidence.<br>- Answer is in English.<br>- No ticket is created. |
| UC-006 | No evidence | retrieve_evidence | \<A question definitely not covered by any indexed document\> | outcome = no_results |
| UC-007 | Only ignored evidence | retrieve_evidence | A mocked find() result containing only relation="ignore" | outcome = only_ignored |
| UC-008 | Confidence mapping | confidence_mapping | direct / inferential / ignore | direct → high<br>inferential → medium<br>ignore → none |
| UC-009 | Grounded answer generation | generate_answer | Question: "When can I do X?"<br>Evidence: "The customer may do X within 14 days." | - Answer only states information supported by the evidence.<br>- Does not introduce unsupported conditions, durations, or details.<br>- Uses the requested response language. |
| UC-010 | Grounding verifier rejects hallucination | verify_grounding | Evidence: "Refunds are allowed within 14 days."<br>Answer: "Refunds are allowed within 14 days and are processed within 3 business days." | grounded = false |
| UC-011 | Ticket creation path | workflow | \<A support question for which find() returns no evidence\> | - Routes to Ticket Agent.<br>- Ticket is created.<br>- status = OPEN.<br>- original_message matches the user's message exactly.<br>- customer_id comes from customer context.<br>- product is classified.<br>- category is classified.<br>- subject is generated.<br>- problem_description is generated. |
| UC-012 | Ticket Agent does not rewrite trusted data | ticket_agent | Customer context + unresolved support message | Ticket Agent produces only: product, category, subject, problem_description.<br>It does not generate: customer_id, original_message, id, created_at, status. |
| UC-013 | Load customer on first turn | load_customer | customer absent from State<br>context.customer_id = TEST-CUSTOMER-001 | Customer is fetched from DB and stored in State. |
| UC-014 | Reuse customer from memory | load_customer | customer already exists in State | Customer DB lookup is skipped.<br>Existing customer state is preserved. |
