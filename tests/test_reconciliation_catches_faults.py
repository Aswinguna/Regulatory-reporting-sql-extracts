"""Fault injection: a reconciliation check is only worth having if it can fail.

Each test breaks the pipeline in a realistic way and asserts that the
reconciliation layer reports it.
"""
import hashlib

import duckdb

from regrep import pipeline
from regrep.independent import compute
from regrep.reconcile import reconcile


def failed_ids(checks):
    return {c.check_id for c in checks if not c.passed}


def fresh_build(data_dir, staging_sql=pipeline.STAGING_SQL):
    con = duckdb.connect(":memory:")
    pipeline.build(con, data_dir, staging_sql)
    return con


def test_missing_deduplication_is_caught(pipeline_fixture_dir, tmp_path):
    """Bug: staging forgets to keep only the latest row per transaction_id."""
    original = pipeline.STAGING_SQL.read_text()
    broken_rule = "WHERE r.rn = 1\n  AND r.amount_eur > 0;"
    assert broken_rule in original, "staging SQL changed; update this test"
    broken = tmp_path / "broken_staging.sql"
    broken.write_text(original.replace(broken_rule, "WHERE r.amount_eur > 0;"))

    con = fresh_build(pipeline_fixture_dir, broken)
    failed = failed_ids(reconcile(con, pipeline_fixture_dir))
    assert {"RF2", "RF3.clean", "RF4", "E1.count", "E1.total"} <= failed


def test_deleted_row_in_extract_is_caught(pipeline_fixture_dir):
    """Someone removes one row from the large transaction extract."""
    con = fresh_build(pipeline_fixture_dir)
    con.execute("DELETE FROM extract_large_transactions WHERE transaction_id = "
                "(SELECT transaction_id FROM extract_large_transactions LIMIT 1)")
    failed = failed_ids(reconcile(con, pipeline_fixture_dir))
    assert {"E2.count", "E2.total", "E2.ids"} <= failed


def test_one_cent_difference_is_caught(pipeline_fixture_dir):
    """A single cent of drift in one cell must break the total and the cell check."""
    con = fresh_build(pipeline_fixture_dir)
    con.execute("UPDATE extract_monthly_volumes SET total_amount_eur = total_amount_eur + 0.01 "
                "WHERE rowid = 0")
    failed = failed_ids(reconcile(con, pipeline_fixture_dir))
    assert {"E1.total", "E1.cells"} <= failed


def test_silently_dropped_null_country_rows_are_caught(pipeline_fixture_dir):
    """Bug: a WHERE counterparty_country IS NOT NULL sneaks into the extract."""
    con = fresh_build(pipeline_fixture_dir)
    con.execute("DELETE FROM extract_monthly_volumes WHERE counterparty_country = 'UNKNOWN'")
    failed = failed_ids(reconcile(con, pipeline_fixture_dir))
    assert {"E1.unknown", "E1.count", "E1.total"} <= failed


def test_unrecognised_risk_rating_is_caught(pipeline_fixture_dir):
    """An unknown rating would be dropped by the inner join; RF6 must flag it."""
    con = fresh_build(pipeline_fixture_dir)
    con.execute("UPDATE raw_customers SET risk_rating = 'critical' WHERE customer_id = 'C00001'")
    failed = failed_ids(reconcile(con, pipeline_fixture_dir))
    assert "RF6" in failed


def test_fan_out_from_duplicate_account_is_caught(pipeline_fixture_dir):
    """A duplicated account row would double count transactions in joins."""
    con = fresh_build(pipeline_fixture_dir)
    con.execute("INSERT INTO raw_accounts SELECT * FROM raw_accounts LIMIT 1")
    failed = failed_ids(reconcile(con, pipeline_fixture_dir))
    assert "RF5.accounts" in failed or "RF1.accounts" in failed


def test_threshold_change_is_caught(pipeline_fixture_dir):
    """Lowering the threshold in SQL only (not in the independent side) must show up."""
    con = fresh_build(pipeline_fixture_dir)
    con.execute("UPDATE params SET large_txn_threshold = 5000")
    con.execute((pipeline.SQL_DIR / "03_extract_large_transactions.sql").read_text())
    failed = failed_ids(reconcile(con, pipeline_fixture_dir))
    # Rows between 5,000 and 10,000 now appear, so count, total and id set all differ,
    # while the "below threshold" check still passes because it reads the same params.
    assert {"E2.count", "E2.total", "E2.ids"} <= failed


def test_same_seed_gives_identical_extract_files(tmp_path):
    """Reproducibility: two runs, same seed, byte-identical extracts."""
    hashes = []
    for name in ("a", "b"):
        out = tmp_path / name
        con, checks, _ = pipeline.run(out, seed=7)
        pipeline.write_pack(con, out, checks, 7)
        hashes.append({p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in sorted((out / "extracts").glob("*.csv"))})
    assert hashes[0] == hashes[1]
    assert len(hashes[0]) == 3


def test_different_seed_gives_different_data_but_still_reconciles(tmp_path):
    con, checks, data_dir = pipeline.run(tmp_path / "s", seed=99)
    assert all(c.passed for c in checks)
    assert compute(data_dir).clean > 0
