# Msegat Customer Agent: Test Cases

17 prompts. Each case lists the prompt, expected response language, expected behavior (ANSWER / ESCALATE / PARTIAL), and the facts to check against the source docs.

**Source doc keys:**
- `PRICE` = Price .docx
- `ERR` = Common Errors Msegat.docx
- `FAQ` = FAQ - AI Last change .docx
- `MAN` = Msegat User manual(2).docx

**Global pass criteria (apply to every case):**
1. Response language matches the user's language.
2. Every sub-question is addressed, in order, none skipped.
3. No invented facts. Anything not in the docs is stated as unknown and escalated (support ticket, contact page, or sales).
4. Greetings are returned briefly; closings (thanks, goodbye) get a brief close.

---

## Summary

| ID | Category | Lang | Expected behavior |
|---|---|---|---|
| TC01 | Single question | AR | ANSWER |
| TC02 | Single question | AR | ANSWER |
| TC03 | Single question (dialect) | AR | ANSWER (points to support) |
| TC04 | Single question | EN | ANSWER |
| TC05 | Single question | EN | ANSWER |
| TC06 | Greeting + single question | AR | ANSWER |
| TC07 | Greeting + single question | EN | ANSWER |
| TC08 | Multi sub-questions | AR | ANSWER |
| TC09 | Multi sub-questions | EN | ANSWER |
| TC10 | Greeting + multi + ending | AR | ANSWER |
| TC11 | Greeting + multi + ending | EN | ANSWER |
| TC12 | Unanswerable | AR | ESCALATE |
| TC13 | Unanswerable | AR | ESCALATE |
| TC14 | Mixed answerable / unanswerable | AR | PARTIAL |
| TC15 | Mixed answerable / unanswerable | AR | PARTIAL |
| TC16 | Single unanswerable | EN | ESCALATE |
| TC17 | Required question (freeze account) | AR | ANSWER or CLARIFY |

---

## 1. Single questions: Arabic

### TC01
```
كم مدة صلاحية الرصيد؟
```
- **Response language:** Arabic
- **Behavior:** ANSWER
- **Expected facts:**
  - سنة واحدة لجميع الاشتراكات، ويمكن استخدام النقاط في أي وقت خلالها. (`FAQ` الدفع والرصيد)

### TC02
```
كم تكلفة الرسالة الدولية؟
```
- **Response language:** Arabic
- **Behavior:** ANSWER
- **Expected facts:**
  - 7 نقاط للرسالة الدولية العادية، 21 نقطة لدول محددة (روسيا، العراق، اليمن، باكستان، إندونيسيا، ... ). (`FAQ` الرسائل، `MAN` تعريفات الشحن والرصيد)
  - Bonus: يجب تفعيل الإرسال الدولي من إعدادات الحساب > الإعدادات المتقدمة. (`ERR` الحساب)

### TC03
```
وش اسوي اذا سجلت دخول وقال الحساب موقوف؟
```
- **Response language:** Arabic (dialect is acceptable to mirror or respond in MSA)
- **Behavior:** ANSWER (the doc answer is itself a redirect to support)
- **Expected facts:**
  - التواصل مع الدعم الفني. (`FAQ` الحساب)
  - Bonus: قنوات التواصل: صفحة الدخول > أسفل الصفحة > تواصل معنا، أو الهاتف من الأحد إلى الخميس 9ص إلى 6م. (`FAQ` الدعم الفني)
- **Fail if:** agent invents a reason for the suspension.

---

## 2. Single questions: English

### TC04
```
How much does the sender name license cost?
```
- **Response language:** English
- **Behavior:** ANSWER
- **Expected facts:**
  - 230 SAR, valid 1 year, renewal 230 SAR. (`FAQ` اسم المرسل)
  - Not auto-renewed; must renew manually. (`FAQ`)
  - Bonus: if the name was already registered with another provider and documented in Jaber, the payment step is skipped. (`FAQ` الدفع والرصيد, `MAN`)

### TC05
```
What payment methods do you accept?
```
- **Response language:** English
- **Behavior:** ANSWER
- **Expected facts:**
  - mada, credit cards, Apple Pay, STC Pay, SADAD, bank transfer (bank transfer only after contacting sales). (`FAQ` الدفع والرصيد)

---

## 3. Greeting + single question: Arabic

### TC06
```
السلام عليكم ورحمة الله، كيف أرقي حسابي إلى بريميوم؟
```
- **Response language:** Arabic
- **Behavior:** ANSWER, returns the greeting (وعليكم السلام)
- **Expected facts:**
  - الشريط الجانبي > نوع الحساب > تفعيل تحت خيار بريميوم. (`MAN` ترقية الحساب)
  - التكلفة 1.4 نقطة للرسالة (0.4 نقطة إضافية). (`FAQ`)
  - أولوية في تسليم رسائل التحقق والإشعارات، وصول بمعدل 4 ثوان. (`FAQ`)
  - يمكن الرجوع للحساب العادي بنفس الطريقة. (`FAQ`)

---

## 4. Greeting + single question: English

### TC07
```
Hi there! What hours am I not allowed to send promotional messages?
```
- **Response language:** English
- **Behavior:** ANSWER, brief greeting back
- **Expected facts:**
  - 10 PM to 9 AM daily per CST; may change in some months. (`FAQ` الرسائل, `MAN`)
  - Messages sent during the block are held and delivered after it ends. (`FAQ`)
  - Bonus: promotional messages must use an AD sender name. (`ERR` الرسائل)

---

## 5. Multiple sub-questions: Arabic

### TC08
```
كم حرف عربي في الرسالة الواحدة؟ وإذا خلطت عربي وإنجليزي في نفس الرسالة كيف تنحسب؟ وهل الروابط والمسافات تنحسب من عدد الأحرف؟
```
- **Response language:** Arabic
- **Behavior:** ANSWER (3 sub-answers)
- **Expected facts:**
  1. 70 حرفًا = نقطة، وبعدها كل 67 حرفًا نقطة. (`FAQ` الرسائل)
  2. الرسالة المختلطة تحسب كرسالة عربية. (`FAQ`)
  3. نعم، الروابط والمسافات والمرفقات تحسب من طول النص. (`FAQ`)

---

## 6. Multiple sub-questions: English

### TC09
```
What's the difference between a whitelist sender name and an AD sender name? Can I activate both with one license? And how long does activation take?
```
- **Response language:** English
- **Behavior:** ANSWER (3 sub-answers)
- **Expected facts:**
  1. Whitelist: notifications, OTP, service messages. AD (ends with AD): promotional only. (`FAQ`)
  2. Yes, one license, if the name is identical with "-AD" added for the promotional one. (`FAQ`)
  3. 3 to 7 business days, excluding the submission day. (`FAQ`, `MAN`) See conflict C2.

---

## 7. Greeting + multi + ending: Arabic

### TC10
```
مرحبا، عندي كم سؤال: وش متطلبات الاشتراك للجمعيات الخيرية؟ وهل فيه فترة تجريبية مجانية؟ وكم مدة الرد على التذكرة لو رفعت وحدة؟ شكرًا لكم ويعطيكم العافية
```
- **Response language:** Arabic
- **Behavior:** ANSWER (greeting, 3 answers, closing)
- **Expected facts:**
  1. صورة السجل التجاري أو رخصة وزارة الموارد البشرية والتنمية الاجتماعية + خطاب التفويض + شهادة النطاق السعودي. (`FAQ` الاشتراك)
  2. نعم، تجربة 10 رسائل مجانية. (`FAQ` الخدمات)
  3. خلال يومي عمل. (`FAQ` الدعم الفني)
  - Bonus: يجب الرد على التذكرة خلال يومين وإلا تغلق تلقائيًا. (`ERR` الدعم الفني)

---

## 8. Greeting + multi + ending: English

### TC11
```
Good morning. I'm integrating with your API. How do I create an API key, what does error 1064 mean, and how many messages per day can I send with the free API? Thanks a lot, have a great day.
```
- **Response language:** English
- **Behavior:** ANSWER (greeting, 3 answers, closing)
- **Expected facts:**
  1. Sidebar > API Key > Create new key > copy. (`FAQ`, `MAN`)
  2. 1064: free OTP message with invalid content. Must use "Pin Code is: xxxx", "Verification Code: xxxx", or "رمز التحقق :1234", or upgrade and activate a sender name to send any content. (`MAN` error codes)
  3. 10 messages per day; more requires one of the paid integrations (WordPress, WooCommerce, OpenCart, Magento, ExpandCart, Salla, Foodics). (`FAQ` API)
  - Bonus: docs link https://msegat.docs.apiary.io/#

---

## 9. Unanswerable: Arabic

### TC12
```
هل عندكم تطبيق جوال لمسجات على الآيفون أو الأندرويد؟
```
- **Response language:** Arabic
- **Behavior:** ESCALATE
- **Why unanswerable:** no mobile app mentioned in any doc.
- **Pass:** states the info isn't available, points to support (تذكرة، أو صفحة تواصل معنا).
- **Fail if:** confirms or denies an app exists.

### TC13
```
كم سعر رسالة الواتساب الواحدة؟
```
- **Response language:** Arabic
- **Behavior:** ESCALATE
- **Why unanswerable:** WhatsApp pricing is absent. Docs only cover WhatsApp message types, the subscription flow (Facebook page required, sales contacts you), and 3 to 7 business days activation (`MAN` الواتساب).
- **Pass:** says pricing isn't available, may share the subscription steps, routes to sales.
- **Fail if:** applies SMS point pricing to WhatsApp.

---

## 10. Mixed answerable / unanswerable: Arabic

### TC14
```
كم سعر الباقة الذهبية بالريال؟ وهل أقدر أدفع بالتقسيط عن طريق تابي أو تمارا؟ وكم عدد أسماء المرسلين المسموح لكل سجل تجاري؟ وهل تقدرون تطلعون الفاتورة الضريبية باسم فرع ثاني للشركة؟
```
- **Response language:** Arabic
- **Behavior:** PARTIAL (answer 2, escalate 2)

| # | Sub-question | Answerable | Expected |
|---|---|---|---|
| 1 | سعر الباقة الذهبية | YES | 7,000 ريال مقابل 100,000 نقطة (`PRICE`) |
| 2 | التقسيط عبر تابي/تمارا | NO | Docs list payment methods without instalments. Agent may list the known methods but must not confirm or deny Tabby/Tamara; route to sales. |
| 3 | عدد أسماء المرسلين لكل سجل | YES (conflicting) | 5 per CR (`FAQ`, `ERR`). See conflict C1. |
| 4 | فاتورة باسم فرع آخر | NO | Docs only say invoices are auto-emailed and downloadable from إدارة الشحن والرصيد. Branch invoicing not covered; escalate. |

### TC15
```
كيف أفعّل الإرسال الدولي؟ وهل تدعمون رسائل MMS فيها فيديو؟ ووش الفرق بين حالة "أرسلت" و"استلمت"؟ وهل عندكم اتفاقية مستوى خدمة SLA مكتوبة فيها نسبة التوفر؟
```
- **Response language:** Arabic
- **Behavior:** PARTIAL (answer 2, escalate 2)

| # | Sub-question | Answerable | Expected |
|---|---|---|---|
| 1 | تفعيل الإرسال الدولي | YES | معلومات الحساب > الإعدادات المتقدمة > تفعيل الرسائل الدولية > حفظ (`MAN`, `ERR`) |
| 2 | رسائل MMS بفيديو | NO | Docs cover SMS attachments only (3MB max, pdf/jpg/jpeg/png/gif/xls/xlsx/doc/zip/rar). MMS/video not covered; escalate. Agent may mention the attachment feature but must not claim MMS support. |
| 3 | الفرق بين أرسلت واستلمت | YES | أرسلت: تم الإرسال وبانتظار الاستلام. استلمت: تم الاستلام. (`FAQ`) |
| 4 | SLA ونسبة التوفر | NO | Not in docs. Only 24h technical support and security claims exist; escalate. |

---

## 11. Single unanswerable

### TC16
```
Do you offer an on-premise deployment of Msegat that we can host on our own servers?
```
- **Response language:** English
- **Behavior:** ESCALATE
- **Why unanswerable:** no deployment options in docs. Docs only state data centers are inside KSA (`FAQ` الخدمات).
- **Pass:** says it doesn't have this info, routes to sales. May mention data residency in KSA.
- **Fail if:** says yes or no to on-premise.

---

## 12. Required question

### TC17
```
كيف اجمد حسابي في شبكات
```
- **Response language:** Arabic
- **Behavior:** ANSWER or CLARIFY
- **Notes:** "شبكات" is likely a typo for "مسجات". Two acceptable paths:
  - Interprets as مسجات: لا يمكن إيقاف أو تجميد الاشتراك، لكن صلاحية الرصيد سنة كاملة. (`FAQ` الاشتراك)
  - Asks a short clarifying question about what "شبكات" refers to, or states that freezing a telecom network line is outside Msegat's scope.
- **Fail if:** invents a freeze procedure or settings path.

---

## Known doc conflicts (affect grading)

The agent's handling of these is worth checking. A strong answer uses the dominant source or flags ambiguity; a weak one gives the minority value confidently.

| ID | Topic | Conflict |
|---|---|---|
| C1 | Sender names per CR | 5 max (`FAQ`, `ERR`) vs "no upper limit per beneficiary" (`MAN` T&C, CST rules) |
| C2 | Sender name activation time | 3 to 7 business days (`FAQ`, `MAN`) vs 3 to 6 (`MAN` T&C) |
| C3 | Allowed sender name characters | English letters/digits only, no spaces or symbols (`FAQ`, `ERR`) vs A-Z, 0-9, `-`, `()`, `.`, `&`, space (`MAN` T&C) |
| C4 | Custom package | Minimum 200,000 points (`FAQ`, `MAN`) vs "customize any amount" (`PRICE`) |
| C5 | Silver package points | Written "1,0000" in `PRICE`; likely 10,000 |
| C6 | Report viewing window | Last 72 hours (`MAN`, `FAQ` one place) vs last two days (`FAQ` another place) |
| C7 | Premium rerouting | "On your request" (`FAQ`) vs automatic at same cost (`MAN`) |
