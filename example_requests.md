

## 3. Simple supported question — happy path

> كم سعر الباقة البرونزية؟


---

## 4. English question over Arabic documents

> What are the requirements to subscribe to the service?


---

## 5. Long-format request 

> السلام عليكم ورحمة الله،
> عندي استفسار بخصوص التسجيل في منصة مسجات. حاولت أسجل حساب جديد لشركتنا
> وأدخلت جميع البيانات المطلوبة، لكن عند الضغط على متابعة تظهر لي رسالة
> "الرقم الموحد غير صحيح" مع أني متأكد أن الرقم المدخل هو نفس الرقم الموجود
> في السجل التجاري. هل في طريقة معينة لكتابة الرقم أو خطوة ناقصة عندي؟
> شكراً جزيلاً لكم.


---

## 6. Long-format request (English)

> Hi there,
> I hope you're doing well. I'm evaluating MSEGAT for our company and have a
> couple of questions before we commit. What do we need to prepare to
> subscribe as a private company — documents, registrations, that kind of
> thing? And how much does the Bronze package cost? We're a small team, so
> we'd start with the cheapest tier.
> Thanks a lot in advance!

---

## 7. FAQ-style policy question

> هل يمكن تخصيص باقة بناءً على احتياجنا؟ وما هو الحد الأدنى للشحن في هذه الحالة؟

---

## 8. Mixed supported + unsupported 

> مرحباً، عندي سؤالين: كم سعر الباقة البرونزية؟ وهل يمكن ربط مسجات مع
> نظام Salesforce عن طريق API مباشرة؟

---

## Cleanup

Escalation tests create real rows in `data/app.db`. To clear tickets before
a demo:

    python -c "from customer_support.db.connection import connect; c = connect(); c.execute('DELETE FROM tickets'); c.commit()"
