-- 04_extract_overdue_kyb_reviews.sql
-- Extract 3: approved customers whose periodic KYB review is overdue at the end
-- of the reporting period.
--
-- Review baseline is the last review date, or the onboarding date if the
-- customer has never been reviewed. The allowed interval depends on risk rating
-- (see review_intervals). A customer is overdue when the due date is strictly
-- before the period end.
--
-- The join to review_intervals is an inner join, so an unrecognised risk rating
-- would silently drop a customer. Reconciliation guards against that.

CREATE OR REPLACE TABLE extract_overdue_kyb_reviews AS
WITH base AS (
    SELECT
        c.customer_id,
        c.legal_name,
        c.country,
        c.risk_rating,
        COALESCE(c.last_review_date, c.onboarded_at) AS review_baseline_date,
        i.months                                     AS review_interval_months
    FROM raw_customers AS c
    INNER JOIN review_intervals AS i ON i.risk_rating = c.risk_rating
    WHERE c.kyb_status = 'approved'
),
due AS (
    SELECT
        b.*,
        CAST(b.review_baseline_date + to_months(CAST(b.review_interval_months AS INTEGER)) AS DATE) AS review_due_date
    FROM base AS b
)
SELECT
    d.customer_id,
    d.legal_name,
    d.country,
    d.risk_rating,
    d.review_baseline_date,
    d.review_interval_months,
    d.review_due_date,
    date_diff('day', d.review_due_date, p.period_end) AS days_overdue
FROM due AS d
CROSS JOIN params AS p
WHERE d.review_due_date < p.period_end
ORDER BY days_overdue DESC, d.customer_id;
