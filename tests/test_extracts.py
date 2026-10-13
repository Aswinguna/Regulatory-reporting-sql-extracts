"""Tests of the extracts themselves: do they match what was planted in the data?"""
from decimal import Decimal


def scalar(con, sql):
    return con.execute(sql).fetchone()[0]


def test_every_reconciliation_check_passes(pipeline):
    failed = [(c.check_id, c.expected, c.actual) for c in pipeline["checks"] if not c.passed]
    assert failed == []


def test_row_flow_matches_planted_issues(pipeline):
    """Staging must find exactly the problems the generator injected."""
    con, truth = pipeline["con"], pipeline["truth"]
    assert scalar(con, "SELECT COUNT(*) FROM raw_transactions") == truth["raw_transaction_rows"]
    assert scalar(con, "SELECT COUNT(*) FROM superseded_transactions") == truth["expected_superseded_rows"]
    assert scalar(con, "SELECT COUNT(*) FROM rejected_transactions") == truth["expected_rejected_rows"]
    assert scalar(con, "SELECT COUNT(*) FROM clean_transactions") == (
        truth["unique_transaction_ids"] - truth["expected_rejected_rows"])


def test_rejection_reasons_split_correctly(pipeline):
    con, truth = pipeline["con"], pipeline["truth"]
    reasons = dict(con.execute(
        "SELECT reject_reason, COUNT(*) FROM rejected_transactions GROUP BY 1").fetchall())
    assert reasons["ORPHAN_ACCOUNT"] == truth["orphan_account"]
    assert reasons["INVALID_AMOUNT"] == truth["null_amount"] + truth["zero_amount"] + truth["negative_amount"]


def test_restated_amount_wins_over_original(pipeline):
    """For a restated id, the extract must carry the later (restated) amount."""
    con = pipeline["con"]
    rows = con.execute("""
        SELECT s.transaction_id, s.amount_eur AS old_amount, c.amount_eur AS kept_amount
        FROM superseded_transactions s
        JOIN clean_transactions c USING (transaction_id)
        WHERE s.amount_eur <> c.amount_eur""").fetchall()
    assert len(rows) == pipeline["truth"]["restated_duplicates"]
    for _, old, kept in rows:
        assert kept == (old * Decimal("1.10")).quantize(Decimal("0.01"))


def test_unknown_country_rows_are_kept_not_dropped(pipeline):
    con = pipeline["con"]
    in_period_unknown = scalar(con, """
        SELECT COUNT(*) FROM clean_transactions
        WHERE counterparty_country IS NULL
          AND CAST(booked_at AS DATE) BETWEEN DATE '2026-01-01' AND DATE '2026-09-30'""")
    reported = scalar(con, "SELECT SUM(transaction_count) FROM extract_monthly_volumes "
                           "WHERE counterparty_country = 'UNKNOWN'")
    assert in_period_unknown == reported > 0


def test_out_of_period_transactions_are_excluded(pipeline):
    con = pipeline["con"]
    december = scalar(con, "SELECT COUNT(*) FROM clean_transactions WHERE booked_at < TIMESTAMP '2026-01-01'")
    assert december > 0, "the data should contain out-of-period rows for this test to mean anything"
    assert scalar(con, "SELECT COUNT(*) FROM extract_monthly_volumes WHERE reporting_month < '2026-01'") == 0


def test_never_reviewed_customers_use_onboarding_date(pipeline):
    con = pipeline["con"]
    never_reviewed_overdue = scalar(con, """
        SELECT COUNT(*) FROM extract_overdue_kyb_reviews e
        JOIN raw_customers c USING (customer_id)
        WHERE c.last_review_date IS NULL AND e.review_baseline_date = c.onboarded_at""")
    never_reviewed_total = scalar(con, """
        SELECT COUNT(*) FROM raw_customers WHERE last_review_date IS NULL AND kyb_status = 'approved'""")
    assert never_reviewed_total >= pipeline["truth"]["customers_never_reviewed"]
    assert never_reviewed_overdue <= never_reviewed_total


def test_month_end_clamping_in_review_due_date():
    from datetime import date
    from regrep.independent import add_months
    assert add_months(date(2025, 1, 31), 1) == date(2025, 2, 28)
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert add_months(date(2025, 11, 30), 3) == date(2026, 2, 28)
