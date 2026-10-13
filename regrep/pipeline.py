"""Build the database, run the SQL extracts, reconcile, and write the audit pack.

Usage:
    python -m regrep.pipeline --out build --seed 42

Exit code is 1 if any reconciliation check fails.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import duckdb

from .config import (DEFAULT_SEED, LARGE_TXN_THRESHOLD, PERIOD_END, PERIOD_START,
                     REVIEW_INTERVAL_MONTHS)
from .generate_data import generate
from .independent import compute
from .reconcile import Check, reconcile

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"
STAGING_SQL = SQL_DIR / "01_staging.sql"
EXTRACTS = [
    # (table, sql file, csv order by)
    ("extract_monthly_volumes", "02_extract_monthly_volumes.sql", "1, 2, 3, 4"),
    ("extract_large_transactions", "03_extract_large_transactions.sql", "booked_at, transaction_id"),
    ("extract_overdue_kyb_reviews", "04_extract_overdue_kyb_reviews.sql", "days_overdue DESC, customer_id"),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_raw(con: duckdb.DuckDBPyConnection, data_dir: Path) -> None:
    con.execute(f"""
        CREATE OR REPLACE TABLE raw_customers AS SELECT * FROM read_csv('{data_dir / "customers.csv"}',
            header = true, columns = {{'customer_id': 'VARCHAR', 'legal_name': 'VARCHAR', 'country': 'VARCHAR',
            'segment': 'VARCHAR', 'onboarded_at': 'DATE', 'kyb_status': 'VARCHAR', 'risk_rating': 'VARCHAR',
            'last_review_date': 'DATE'}})""")
    con.execute(f"""
        CREATE OR REPLACE TABLE raw_accounts AS SELECT * FROM read_csv('{data_dir / "accounts.csv"}',
            header = true, columns = {{'account_id': 'VARCHAR', 'customer_id': 'VARCHAR', 'opened_at': 'DATE',
            'currency': 'VARCHAR', 'status': 'VARCHAR'}})""")
    con.execute(f"""
        CREATE OR REPLACE TABLE raw_transactions AS SELECT * FROM read_csv('{data_dir / "transactions_raw.csv"}',
            header = true, columns = {{'transaction_id': 'VARCHAR', 'account_id': 'VARCHAR',
            'booked_at': 'TIMESTAMP', 'amount_eur': 'DECIMAL(18,2)', 'direction': 'VARCHAR',
            'payment_type': 'VARCHAR', 'counterparty_country': 'VARCHAR', 'ingested_at': 'TIMESTAMP'}})""")


def load_params(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(f"""
        CREATE OR REPLACE TABLE params AS SELECT
            DATE '{PERIOD_START.isoformat()}' AS period_start,
            DATE '{PERIOD_END.isoformat()}' AS period_end,
            CAST('{LARGE_TXN_THRESHOLD}' AS DECIMAL(18,2)) AS large_txn_threshold""")
    con.execute("CREATE OR REPLACE TABLE review_intervals (risk_rating VARCHAR, months INTEGER)")
    for rating, months in REVIEW_INTERVAL_MONTHS.items():
        con.execute("INSERT INTO review_intervals VALUES (?, ?)", [rating, months])


def build(con: duckdb.DuckDBPyConnection, data_dir: Path, staging_sql: Path = STAGING_SQL) -> None:
    load_raw(con, data_dir)
    load_params(con)
    con.execute(staging_sql.read_text())
    for _, sql_file, _ in EXTRACTS:
        con.execute((SQL_DIR / sql_file).read_text())


def write_pack(con: duckdb.DuckDBPyConnection, out_dir: Path, checks: list[Check], seed: int) -> None:
    extracts_dir = out_dir / "extracts"
    extracts_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "seed": seed,
        "reporting_period": [PERIOD_START.isoformat(), PERIOD_END.isoformat()],
        "large_transaction_threshold_eur": str(LARGE_TXN_THRESHOLD),
        "staging_sql_sha256": sha256(STAGING_SQL),
        "extracts": {},
        "checks_passed": sum(c.passed for c in checks),
        "checks_total": len(checks),
    }
    for table, sql_file, order in EXTRACTS:
        csv_path = extracts_dir / f"{table}.csv"
        con.execute(f"COPY (SELECT * FROM {table} ORDER BY {order}) TO '{csv_path}' (HEADER, DELIMITER ',')")
        manifest["extracts"][table] = {
            "rows": con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],
            "csv_sha256": sha256(csv_path),
            "sql_file": f"sql/{sql_file}",
            "sql_sha256": sha256(SQL_DIR / sql_file),
        }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    lines = ["| Check | Description | Expected | Actual | Status |", "|---|---|---|---|---|"]
    lines += [f"| {c.check_id} | {c.description} | {c.expected} | {c.actual} | {c.status} |" for c in checks]
    summary = f"**{manifest['checks_passed']} of {manifest['checks_total']} checks passed.**"
    (out_dir / "reconciliation_report.md").write_text(
        "# Reconciliation report\n\n" + summary + "\n\n" + "\n".join(lines) + "\n")


def run(out_dir: Path, seed: int = DEFAULT_SEED, staging_sql: Path = STAGING_SQL):
    data_dir = out_dir / "data"
    generate(data_dir, seed=seed)
    con = duckdb.connect(":memory:")
    build(con, data_dir, staging_sql)
    checks = reconcile(con, data_dir, compute(data_dir))
    return con, checks, data_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("build"))
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args(argv)

    con, checks, _ = run(args.out, args.seed)
    write_pack(con, args.out, checks, args.seed)
    failed = [c for c in checks if not c.passed]
    print(f"{len(checks) - len(failed)}/{len(checks)} reconciliation checks passed")
    for c in failed:
        print(f"FAIL {c.check_id}: expected {c.expected}, got {c.actual}  ({c.description})")
    print(f"Audit pack written to {args.out}/ (extracts, manifest.json, reconciliation_report.md)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
