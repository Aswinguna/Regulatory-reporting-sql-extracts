"""Reconciliation checks: SQL extracts versus independently recomputed figures."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import duckdb

from .config import LARGE_TXN_THRESHOLD, REVIEW_INTERVAL_MONTHS
from .independent import Figures, compute


@dataclass(frozen=True)
class Check:
    check_id: str
    description: str
    expected: object
    actual: object

    @property
    def passed(self) -> bool:
        return self.expected == self.actual

    @property
    def status(self) -> str:
        return "PASS" if self.passed else "FAIL"


def _scalar(con: duckdb.DuckDBPyConnection, sql: str):
    return con.execute(sql).fetchone()[0]


def _no_nulls(con: duckdb.DuckDBPyConnection, table: str) -> int:
    """Total number of null cells across every column of a table."""
    columns = [r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()]
    if not columns:
        return 0
    expr = " + ".join(f"COUNT(*) FILTER (WHERE {c} IS NULL)" for c in columns)
    return int(_scalar(con, f"SELECT {expr} FROM {table}"))


def reconcile(con: duckdb.DuckDBPyConnection, data_dir: Path, figures: Figures | None = None) -> list[Check]:
    fig = figures or compute(data_dir)
    checks: list[Check] = []
    add = lambda cid, desc, exp, act: checks.append(Check(cid, desc, exp, act))

    # ---- RF: row flow from source file to staged tables ------------------
    for table, name in (("raw_customers", "customers"), ("raw_accounts", "accounts"),
                        ("raw_transactions", "transactions_raw")):
        add(f"RF1.{name}", f"Rows loaded into {table} equal data lines in {name}.csv",
            fig.raw_lines[name], _scalar(con, f"SELECT COUNT(*) FROM {table}"))

    raw = _scalar(con, "SELECT COUNT(*) FROM raw_transactions")
    clean = _scalar(con, "SELECT COUNT(*) FROM clean_transactions")
    rejected = _scalar(con, "SELECT COUNT(*) FROM rejected_transactions")
    superseded = _scalar(con, "SELECT COUNT(*) FROM superseded_transactions")
    add("RF2", "Raw rows = clean + rejected + superseded (no row lost or double counted)",
        raw, clean + rejected + superseded)
    add("RF3.clean", "Clean row count matches independent recomputation", fig.clean, clean)
    add("RF3.superseded", "Superseded row count matches independent recomputation", fig.superseded, superseded)
    for reason in ("ORPHAN_ACCOUNT", "INVALID_AMOUNT"):
        add(f"RF3.{reason}", f"Rejected rows with reason {reason} match independent recomputation",
            fig.rejected[reason],
            _scalar(con, f"SELECT COUNT(*) FROM rejected_transactions WHERE reject_reason = '{reason}'"))
    add("RF4", "transaction_id is unique in clean_transactions (duplicates in = 0)", 0,
        clean - _scalar(con, "SELECT COUNT(DISTINCT transaction_id) FROM clean_transactions"))
    add("RF5.accounts", "account_id is unique in raw_accounts (joins cannot fan out)", 0,
        _scalar(con, "SELECT COUNT(*) - COUNT(DISTINCT account_id) FROM raw_accounts"))
    add("RF5.customers", "customer_id is unique in raw_customers (joins cannot fan out)", 0,
        _scalar(con, "SELECT COUNT(*) - COUNT(DISTINCT customer_id) FROM raw_customers"))
    add("RF6", "Every customer has a recognised risk rating (inner join cannot drop customers)", 0,
        _scalar(con, "SELECT COUNT(*) FROM raw_customers WHERE risk_rating NOT IN "
                     f"({', '.join(repr(k) for k in REVIEW_INTERVAL_MONTHS)}) OR risk_rating IS NULL"))

    # ---- E1: monthly volumes ---------------------------------------------
    add("E1.count", "Sum of transaction_count equals independent in-period clean count",
        fig.in_period_count, _scalar(con, "SELECT COALESCE(SUM(transaction_count), 0) FROM extract_monthly_volumes"))
    add("E1.total", "Sum of total_amount_eur equals independent in-period total to the cent",
        fig.in_period_total, _scalar(con, "SELECT COALESCE(SUM(total_amount_eur), 0) FROM extract_monthly_volumes"))
    actual_cells = {
        (m, c, p, d): (int(n), Decimal(t))
        for m, c, p, d, n, t in con.execute(
            "SELECT reporting_month, counterparty_country, payment_type, direction, "
            "transaction_count, total_amount_eur FROM extract_monthly_volumes").fetchall()
    }
    mismatched = sum(1 for k in set(fig.monthly) | set(actual_cells) if fig.monthly.get(k) != actual_cells.get(k))
    add("E1.cells", "Cells (month, country, type, direction) differing from independent figures", 0, mismatched)
    add("E1.unknown", "UNKNOWN-country transactions equal independent count of null countries in period",
        fig.in_period_unknown_country,
        _scalar(con, "SELECT COALESCE(SUM(transaction_count), 0) FROM extract_monthly_volumes "
                     "WHERE counterparty_country = 'UNKNOWN'"))
    add("E1.nulls", "Null cells in extract_monthly_volumes", 0, _no_nulls(con, "extract_monthly_volumes"))

    # ---- E2: large transactions ------------------------------------------
    add("E2.count", "Large transaction row count equals independent count",
        len(fig.large), _scalar(con, "SELECT COUNT(*) FROM extract_large_transactions"))
    add("E2.total", "Large transaction total equals independent total to the cent",
        sum(fig.large.values(), Decimal("0.00")),
        _scalar(con, "SELECT COALESCE(SUM(amount_eur), 0) FROM extract_large_transactions"))
    actual_ids = {r[0] for r in con.execute("SELECT transaction_id FROM extract_large_transactions").fetchall()}
    add("E2.ids", "Transaction ids present in only one of SQL extract or independent list", 0,
        len(actual_ids ^ set(fig.large)))
    add("E2.unique", "Duplicate transaction ids in the extract", 0,
        _scalar(con, "SELECT COUNT(*) - COUNT(DISTINCT transaction_id) FROM extract_large_transactions"))
    add("E2.threshold", f"Rows below the {LARGE_TXN_THRESHOLD} threshold", 0,
        _scalar(con, f"SELECT COUNT(*) FROM extract_large_transactions WHERE amount_eur < {LARGE_TXN_THRESHOLD}"))
    add("E2.nulls", "Null cells in extract_large_transactions", 0, _no_nulls(con, "extract_large_transactions"))
    add("X1", "Large transaction value never exceeds total in-period value (cross-extract sanity)", True,
        _scalar(con, "SELECT COALESCE((SELECT SUM(amount_eur) FROM extract_large_transactions), 0) "
                     "<= COALESCE((SELECT SUM(total_amount_eur) FROM extract_monthly_volumes), 0)"))

    # ---- E3: overdue KYB reviews -----------------------------------------
    add("E3.count", "Overdue review count equals independent count",
        len(fig.overdue), _scalar(con, "SELECT COUNT(*) FROM extract_overdue_kyb_reviews"))
    actual_overdue = dict(con.execute("SELECT customer_id, days_overdue FROM extract_overdue_kyb_reviews").fetchall())
    add("E3.customers", "Customers present in only one of SQL extract or independent list", 0,
        len(set(actual_overdue) ^ set(fig.overdue)))
    add("E3.days", "Customers whose days_overdue differs from independent figure", 0,
        sum(1 for k, v in actual_overdue.items() if fig.overdue.get(k) != v))
    add("E3.approved", "Overdue customers that are not approved", 0,
        _scalar(con, "SELECT COUNT(*) FROM extract_overdue_kyb_reviews e "
                     "JOIN raw_customers c USING (customer_id) WHERE c.kyb_status <> 'approved'"))
    add("E3.partition", "Approved customers = overdue + current (nobody falls out of the report)",
        fig.approved_customers,
        _scalar(con, "SELECT COUNT(*) FROM extract_overdue_kyb_reviews") + fig.approved_current)
    add("E3.nulls", "Null cells in extract_overdue_kyb_reviews", 0, _no_nulls(con, "extract_overdue_kyb_reviews"))

    return checks
