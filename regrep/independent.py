"""Independent recomputation of every reported figure, straight from the CSVs.

This module deliberately does not use SQL or DuckDB. It re-implements the
business rules with the standard library (csv, Decimal, datetime) so that the
reconciliation compares two separate implementations of the same rules instead
of the SQL checking itself.
"""
from __future__ import annotations

import calendar
import csv
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from .config import LARGE_TXN_THRESHOLD, PERIOD_END, PERIOD_START, REVIEW_INTERVAL_MONTHS


def add_months(d: date, months: int) -> date:
    """Add calendar months, clamping the day (31 Jan + 1 month = 28/29 Feb)."""
    carry, month_index = divmod(d.month - 1 + months, 12)
    year, month = d.year + carry, month_index + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


@dataclass
class Figures:
    raw_lines: dict = field(default_factory=dict)
    raw_rows: int = 0
    unique_ids: int = 0
    superseded: int = 0
    clean: int = 0
    rejected: Counter = field(default_factory=Counter)
    in_period_count: int = 0
    in_period_total: Decimal = Decimal("0.00")
    in_period_unknown_country: int = 0
    monthly: dict = field(default_factory=dict)      # (month, country, ptype, direction) -> (count, total)
    large: dict = field(default_factory=dict)        # transaction_id -> amount
    overdue: dict = field(default_factory=dict)      # customer_id -> days_overdue
    approved_customers: int = 0
    approved_current: int = 0


def _read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def count_data_lines(path: Path) -> int:
    with path.open(encoding="utf-8") as handle:
        return sum(1 for _ in handle) - 1  # minus the header


def compute(data_dir: Path) -> Figures:
    fig = Figures()
    for name in ("customers", "accounts", "transactions_raw"):
        fig.raw_lines[name] = count_data_lines(data_dir / f"{name}.csv")

    customers = _read(data_dir / "customers.csv")
    accounts = _read(data_dir / "accounts.csv")
    raw = _read(data_dir / "transactions_raw.csv")
    account_to_customer = {a["account_id"]: a["customer_id"] for a in accounts}
    customer_by_id = {c["customer_id"]: c for c in customers}

    # 1. keep the latest ingestion per transaction_id
    winners: dict[str, dict] = {}
    for row in raw:
        current = winners.get(row["transaction_id"])
        if current is None or row["ingested_at"] > current["ingested_at"]:
            winners[row["transaction_id"]] = row
    fig.raw_rows = len(raw)
    fig.unique_ids = len(winners)
    fig.superseded = len(raw) - len(winners)

    # 2. reject or accept each winner
    monthly: dict = defaultdict(lambda: [0, Decimal("0.00")])
    for row in winners.values():
        if row["account_id"] not in account_to_customer:
            fig.rejected["ORPHAN_ACCOUNT"] += 1
            continue
        amount = Decimal(row["amount_eur"]) if row["amount_eur"] != "" else None
        if amount is None or amount <= 0:
            fig.rejected["INVALID_AMOUNT"] += 1
            continue
        fig.clean += 1

        booked = datetime.strptime(row["booked_at"], "%Y-%m-%d %H:%M:%S")
        if not (PERIOD_START <= booked.date() <= PERIOD_END):
            continue
        country = row["counterparty_country"] or "UNKNOWN"
        key = (booked.strftime("%Y-%m"), country, row["payment_type"], row["direction"])
        monthly[key][0] += 1
        monthly[key][1] += amount
        fig.in_period_count += 1
        fig.in_period_total += amount
        if country == "UNKNOWN":
            fig.in_period_unknown_country += 1
        if amount >= LARGE_TXN_THRESHOLD:
            fig.large[row["transaction_id"]] = amount

    fig.monthly = {k: (v[0], v[1]) for k, v in monthly.items()}

    # 3. overdue KYB reviews
    for c in customers:
        if c["kyb_status"] != "approved":
            continue
        fig.approved_customers += 1
        baseline = date.fromisoformat(c["last_review_date"] or c["onboarded_at"])
        due = add_months(baseline, REVIEW_INTERVAL_MONTHS[c["risk_rating"]])
        if due < PERIOD_END:
            fig.overdue[c["customer_id"]] = (PERIOD_END - due).days
        else:
            fig.approved_current += 1

    assert set(customer_by_id) == {c["customer_id"] for c in customers}
    return fig
