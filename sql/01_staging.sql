-- 01_staging.sql
-- Turns the raw transaction feed into a clean table plus two audit tables.
--
-- Rules (each one is mirrored independently in regrep/independent.py):
--   1. A transaction_id may arrive more than once (exact replays and restated
--      amounts). The row with the latest ingested_at wins; the others are kept in
--      superseded_transactions so nothing disappears without a trace.
--   2. A winning row is rejected if its account does not exist (ORPHAN_ACCOUNT)
--      or its amount is null, zero or negative (INVALID_AMOUNT).
--   3. Everything else is clean.
-- Invariant checked by reconciliation: raw = clean + rejected + superseded.

CREATE OR REPLACE TABLE stg_ranked AS
SELECT
    t.*,
    ROW_NUMBER() OVER (
        PARTITION BY t.transaction_id
        ORDER BY t.ingested_at DESC
    ) AS rn
FROM raw_transactions AS t;

CREATE OR REPLACE TABLE superseded_transactions AS
SELECT * EXCLUDE (rn)
FROM stg_ranked
WHERE rn > 1;

CREATE OR REPLACE TABLE rejected_transactions AS
SELECT
    r.* EXCLUDE (rn),
    CASE
        WHEN a.account_id IS NULL THEN 'ORPHAN_ACCOUNT'
        ELSE 'INVALID_AMOUNT'
    END AS reject_reason
FROM stg_ranked AS r
LEFT JOIN raw_accounts AS a ON a.account_id = r.account_id
WHERE r.rn = 1
  AND (a.account_id IS NULL OR r.amount_eur IS NULL OR r.amount_eur <= 0);

CREATE OR REPLACE TABLE clean_transactions AS
SELECT r.* EXCLUDE (rn)
FROM stg_ranked AS r
INNER JOIN raw_accounts AS a ON a.account_id = r.account_id
WHERE r.rn = 1
  AND r.amount_eur > 0;
