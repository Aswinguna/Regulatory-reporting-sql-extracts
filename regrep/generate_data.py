"""Generate a reproducible synthetic dataset for a small business bank.

Everything is fake and seeded: the same seed always yields byte-identical CSV
files. Known data quality problems are injected on purpose, in disjoint sets of
rows, and their counts are written to injected_issues.json.
"""
from __future__ import annotations

import csv
import json
import math
import random
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from .config import DEFAULT_SEED, INJECTED, PERIOD_END

COUNTRIES = ["FR", "DE", "ES", "IT", "NL"]
COUNTRY_WEIGHTS = [0.45, 0.2, 0.15, 0.12, 0.08]
EU_COUNTERPARTIES = ["FR", "DE", "ES", "IT", "NL", "BE", "PT", "IE"]
EU_WEIGHTS = [0.4, 0.15, 0.12, 0.1, 0.08, 0.06, 0.05, 0.04]
NON_EU_COUNTERPARTIES = ["GB", "US", "CN", "IN", "CH", "AE"]
PAYMENT_TYPES = ["card", "sepa_transfer", "sepa_instant", "direct_debit", "international"]
PAYMENT_WEIGHTS = [0.4, 0.25, 0.12, 0.13, 0.10]

TXN_START = datetime(2025, 12, 1)
TXN_END = datetime(2026, 9, 30, 23, 59, 59)


def _money(value: float) -> Decimal:
    return Decimal(str(round(value, 2))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _write(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        for row in rows:
            writer.writerow(["" if v is None else v for v in row])


def generate(data_dir: Path, seed: int = DEFAULT_SEED, n_customers: int = 500,
             n_transactions: int = 60000) -> dict:
    rng = random.Random(seed)
    data_dir.mkdir(parents=True, exist_ok=True)

    # ---- customers -------------------------------------------------------
    customers = []
    for i in range(1, n_customers + 1):
        onboarded = date(2019, 1, 1) + timedelta(days=rng.randint(0, (date(2026, 6, 30) - date(2019, 1, 1)).days))
        status = rng.choices(["approved", "pending", "rejected"], [0.86, 0.09, 0.05])[0]
        risk = rng.choices(["low", "medium", "high"], [0.6, 0.3, 0.1])[0]
        days_ago = int(rng.expovariate(1 / 500))
        last_review = max(onboarded, PERIOD_END - timedelta(days=days_ago))
        if status != "approved" and rng.random() < 0.7:
            last_review = None
        customers.append({
            "customer_id": f"C{i:05d}",
            "legal_name": f"Synthetic Company {i:05d}",
            "country": rng.choices(COUNTRIES, COUNTRY_WEIGHTS)[0],
            "segment": rng.choices(["freelancer", "sme", "mid_market"], [0.5, 0.4, 0.1])[0],
            "onboarded_at": onboarded,
            "kyb_status": status,
            "risk_rating": risk,
            "last_review_date": last_review,
        })

    approved = [c for c in customers if c["kyb_status"] == "approved"]
    for c in rng.sample(approved, INJECTED["customers_never_reviewed"]):
        c["last_review_date"] = None

    # ---- accounts --------------------------------------------------------
    accounts = []
    n = 0
    for c in customers:
        for _ in range(rng.choices([1, 2, 3], [0.7, 0.25, 0.05])[0]):
            n += 1
            accounts.append({
                "account_id": f"A{n:06d}",
                "customer_id": c["customer_id"],
                "opened_at": c["onboarded_at"] + timedelta(days=rng.randint(0, 20)),
                "currency": "EUR",
                "status": rng.choices(["open", "closed"], [0.95, 0.05])[0],
            })
    account_ids = [a["account_id"] for a in accounts]

    # ---- base transactions (unique ids) ----------------------------------
    span = int((TXN_END - TXN_START).total_seconds())
    txns = []
    for i in range(1, n_transactions + 1):
        booked = TXN_START + timedelta(seconds=rng.randint(0, span))
        ptype = rng.choices(PAYMENT_TYPES, PAYMENT_WEIGHTS)[0]
        if ptype == "international":
            country = rng.choice(NON_EU_COUNTERPARTIES)
        else:
            country = rng.choices(EU_COUNTERPARTIES, EU_WEIGHTS)[0]
        amount = min(math.exp(rng.gauss(5.5, 1.6)), 250000.0)
        txns.append({
            "transaction_id": f"T{i:07d}",
            "account_id": rng.choice(account_ids),
            "booked_at": booked,
            "amount_eur": _money(max(amount, 0.5)),
            "direction": rng.choice(["debit", "credit"]),
            "payment_type": ptype,
            "counterparty_country": country,
            "ingested_at": booked + timedelta(minutes=rng.randint(1, 2880)),
        })

    # ---- inject problems into disjoint sets of rows ----------------------
    order = list(range(len(txns)))
    rng.shuffle(order)
    cursor = 0

    def take(k: int) -> list[int]:
        nonlocal cursor
        chunk = order[cursor:cursor + k]
        cursor += k
        return chunk

    for idx in take(INJECTED["null_counterparty_country"]):
        txns[idx]["counterparty_country"] = None
    for k, idx in enumerate(take(INJECTED["orphan_account"])):
        txns[idx]["account_id"] = f"AX{k + 1:05d}"  # never exists in accounts
    for idx in take(INJECTED["null_amount"]):
        txns[idx]["amount_eur"] = None
    for idx in take(INJECTED["zero_amount"]):
        txns[idx]["amount_eur"] = Decimal("0.00")
    for idx in take(INJECTED["negative_amount"]):
        txns[idx]["amount_eur"] = -_money(rng.uniform(5, 500))

    extra = []
    for idx in take(INJECTED["restated_duplicates"]):
        restated = dict(txns[idx])
        restated["amount_eur"] = (txns[idx]["amount_eur"] * Decimal("1.10")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        restated["ingested_at"] = txns[idx]["ingested_at"] + timedelta(days=rng.randint(1, 3))
        extra.append(restated)
    for idx in take(INJECTED["exact_duplicates"]):
        extra.append(dict(txns[idx]))

    all_txns = txns + extra
    rng.shuffle(all_txns)

    # ---- write files -----------------------------------------------------
    _write(data_dir / "customers.csv",
           ["customer_id", "legal_name", "country", "segment", "onboarded_at", "kyb_status", "risk_rating", "last_review_date"],
           [[c["customer_id"], c["legal_name"], c["country"], c["segment"], c["onboarded_at"].isoformat(),
             c["kyb_status"], c["risk_rating"],
             c["last_review_date"].isoformat() if c["last_review_date"] else None] for c in customers])
    _write(data_dir / "accounts.csv",
           ["account_id", "customer_id", "opened_at", "currency", "status"],
           [[a["account_id"], a["customer_id"], a["opened_at"].isoformat(), a["currency"], a["status"]] for a in accounts])
    _write(data_dir / "transactions_raw.csv",
           ["transaction_id", "account_id", "booked_at", "amount_eur", "direction", "payment_type",
            "counterparty_country", "ingested_at"],
           [[t["transaction_id"], t["account_id"], t["booked_at"].strftime("%Y-%m-%d %H:%M:%S"),
             t["amount_eur"], t["direction"], t["payment_type"], t["counterparty_country"],
             t["ingested_at"].strftime("%Y-%m-%d %H:%M:%S")] for t in all_txns])

    truth = dict(INJECTED)
    truth.update({
        "seed": seed,
        "customers": len(customers),
        "accounts": len(accounts),
        "raw_transaction_rows": len(all_txns),
        "unique_transaction_ids": len(txns),
        "expected_superseded_rows": INJECTED["exact_duplicates"] + INJECTED["restated_duplicates"],
        "expected_rejected_rows": INJECTED["orphan_account"] + INJECTED["null_amount"]
        + INJECTED["zero_amount"] + INJECTED["negative_amount"],
    })
    (data_dir / "injected_issues.json").write_text(json.dumps(truth, indent=2, sort_keys=True) + "\n")
    return truth


if __name__ == "__main__":
    print(json.dumps(generate(Path("build/data")), indent=2))
