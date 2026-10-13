-- 03_extract_large_transactions.sql
-- Extract 2: every clean transaction at or above the large transaction
-- threshold in the reporting period, enriched with customer context.
--
-- One row per transaction_id. The joins are inner joins on purpose: staging has
-- already rejected orphan accounts, and reconciliation proves that no row is
-- lost here.

CREATE OR REPLACE TABLE extract_large_transactions AS
SELECT
    t.transaction_id,
    t.booked_at,
    t.account_id,
    c.customer_id,
    c.country                                    AS customer_country,
    c.risk_rating,
    c.kyb_status,
    t.payment_type,
    t.direction,
    COALESCE(t.counterparty_country, 'UNKNOWN')  AS counterparty_country,
    t.amount_eur
FROM clean_transactions AS t
INNER JOIN raw_accounts  AS a ON a.account_id  = t.account_id
INNER JOIN raw_customers AS c ON c.customer_id = a.customer_id
CROSS JOIN params AS p
WHERE CAST(t.booked_at AS DATE) BETWEEN p.period_start AND p.period_end
  AND t.amount_eur >= p.large_txn_threshold
ORDER BY t.booked_at, t.transaction_id;
