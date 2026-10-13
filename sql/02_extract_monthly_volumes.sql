-- 02_extract_monthly_volumes.sql
-- Extract 1: transaction counts and value by month, counterparty country,
-- payment type and direction for the reporting period.
--
-- A missing counterparty country is reported as UNKNOWN rather than dropped, so
-- the extract total still ties back to the clean transaction total.

CREATE OR REPLACE TABLE extract_monthly_volumes AS
SELECT
    strftime(date_trunc('month', t.booked_at), '%Y-%m') AS reporting_month,
    COALESCE(t.counterparty_country, 'UNKNOWN')          AS counterparty_country,
    t.payment_type,
    t.direction,
    COUNT(*)                                             AS transaction_count,
    SUM(t.amount_eur)                                    AS total_amount_eur
FROM clean_transactions AS t
CROSS JOIN params AS p
WHERE CAST(t.booked_at AS DATE) BETWEEN p.period_start AND p.period_end
GROUP BY 1, 2, 3, 4
ORDER BY 1, 2, 3, 4;
