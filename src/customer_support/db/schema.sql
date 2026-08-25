-- Authoritative application schema. Idempotent: safe to run on every init.
--
-- `status` is CHECK-constrained because the four states are approved and the
-- DB is the last line of defense against drift. `product` and `category` are
-- deliberately plain TEXT: their taxonomy belongs to the (LLM) draft schema,
-- which is still under revision, and the DB must not hard-code it.

-- `email` and `phone` are UNIQUE so a lookup by either identifies exactly one
-- customer. SQLite treats NULLs as distinct, so any number of customers may
-- still have neither.
CREATE TABLE IF NOT EXISTS customers (
    id    TEXT PRIMARY KEY,
    name  TEXT,
    email TEXT UNIQUE,
    phone TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS tickets (
    id                  TEXT PRIMARY KEY,
    customer_id         TEXT NOT NULL REFERENCES customers(id),
    product             TEXT NOT NULL,
    category            TEXT NOT NULL,
    subject             TEXT NOT NULL,
    problem_description TEXT NOT NULL,
    original_message    TEXT NOT NULL,
    status              TEXT NOT NULL
        CHECK (status IN ('OPEN', 'IN_PROGRESS', 'RESOLVED', 'CLOSED')),
    created_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tickets_customer_id ON tickets (customer_id);
CREATE INDEX IF NOT EXISTS idx_tickets_product     ON tickets (product);
CREATE INDEX IF NOT EXISTS idx_tickets_status      ON tickets (status);
CREATE INDEX IF NOT EXISTS idx_tickets_created_at  ON tickets (created_at);
