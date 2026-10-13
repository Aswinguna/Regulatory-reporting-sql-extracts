# Regulatory Reporting SQL Extracts with Reconciliation Checks

Version-controlled SQL extracts for regulatory-style reporting on synthetic banking data, where every figure can be traced back to source and every extract is covered by automated tests.

All data is synthetic and generated from a seed. Nothing here implements an official regulatory return: the extracts are modelled on the kind of requests a Risk and Compliance team receives from regulators, auditors and internal controllers.

## What it does

A small business bank has a raw transaction feed with the usual problems: replayed rows, restated amounts, missing values and references to accounts that do not exist. The pipeline cleans the feed, produces three extracts, and then proves each one is right by recomputing every figure a second, independent way.

| Extract | Question it answers |
|---|---|
| `extract_monthly_volumes` | How many transactions and how much value, by month, counterparty country, payment type and direction? |
| `extract_large_transactions` | Which transactions of EUR 10,000 or more occurred in the period, and for which customer? |
| `extract_overdue_kyb_reviews` | Which approved customers are overdue for their periodic KYB review, and by how many days? |

Reporting period: 1 January 2026 to 30 September 2026. Business rules (threshold, review intervals by risk rating) live in `regrep/config.py` and feed both the SQL and the independent check.

## Quick start

```bash
pip install -r requirements.txt
python -m regrep.pipeline --out build     # generate data, run extracts, reconcile
python -m pytest                          # 17 tests
```

The pipeline exits with code 1 if any reconciliation check fails, so it can gate a scheduled job or CI run.

Output in `build/`:

- `extracts/*.csv`: the three extracts, deterministic row order
- `reconciliation_report.md`: every check with expected value, actual value and status (a sample is in `docs/`)
- `manifest.json`: row counts, SHA-256 of each extract and each SQL file, seed and reporting period, so a delivered file can be tied to the exact code that produced it

## Repository layout

```
sql/
  01_staging.sql                    dedupe, reject, classify; keeps audit tables
  02_extract_monthly_volumes.sql
  03_extract_large_transactions.sql
  04_extract_overdue_kyb_reviews.sql
regrep/
  generate_data.py                  seeded synthetic data with planted problems
  independent.py                    business rules re-implemented without SQL
  reconcile.py                      30 checks comparing SQL output to independent figures
  pipeline.py                       build, extract, reconcile, write audit pack
tests/
  test_extracts.py                  extracts versus the problems that were planted
  test_reconciliation_catches_faults.py   deliberately broken pipelines must fail
```

## How the reconciliation works

**1. Nothing disappears silently.** Staging splits the raw feed into `clean_transactions`, `rejected_transactions` (with a reason) and `superseded_transactions`. Check `RF2` asserts raw rows = clean + rejected + superseded. On the default seed that is 60,170 = 59,930 + 70 + 170.

**2. Two implementations of the same rules.** `regrep/independent.py` reads the CSVs with the standard library (`csv`, `Decimal`, `datetime`) and recomputes counts, totals to the cent, per-cell figures, the set of large transaction ids and each customer's days overdue. The SQL and Python results must agree exactly. This avoids the trap of SQL checking itself.

**3. Structural guards.** Uniqueness of join keys (so joins cannot fan out), no nulls in any extract column, and a check that every customer has a recognised risk rating, because an inner join on `review_intervals` would otherwise drop a customer without any error.

**4. Cross-extract sanity.** The large transaction total can never exceed the in-period total.

## Planted data problems

The generator injects known problems into disjoint sets of rows and records the counts in `injected_issues.json`. Tests assert that staging finds exactly what was planted.

| Problem | Rows | Handling |
|---|---|---|
| Exact replay of a transaction | 150 | Latest `ingested_at` wins, the rest go to `superseded_transactions` |
| Restated amount (same id, later ingestion, amount +10%) | 20 | The restated amount is reported, the original is kept as superseded |
| Account id not in accounts | 40 | Rejected as `ORPHAN_ACCOUNT` |
| Null, zero or negative amount | 15, 8, 7 | Rejected as `INVALID_AMOUNT` |
| Missing counterparty country | 120 | Kept and reported as `UNKNOWN`, so totals still tie out |
| Customer never reviewed | 8 | Review baseline falls back to the onboarding date |
| Transactions before the reporting period | many | Excluded from extracts, still counted in row flow |

## Fault injection tests

A check that cannot fail proves nothing, so `test_reconciliation_catches_faults.py` breaks the pipeline on purpose and asserts the right checks light up:

- staging forgets to deduplicate
- one row is deleted from an extract
- one cent of drift in a single cell
- rows with an unknown country are silently filtered out
- an unrecognised risk rating that an inner join would drop
- a duplicated account row that would double count transactions
- the large transaction threshold changed on one side only

It also checks that the same seed produces byte-identical extract files.

## Design decisions

- **DuckDB for the SQL layer.** Runs in memory with no setup, supports window functions and `DECIMAL`. Money is `DECIMAL(18,2)` in SQL and `Decimal` in Python, never floating point.
- **Latest ingestion wins for duplicates.** A restated amount should replace the original, not be summed with it. The superseded row is retained for audit.
- **Reject rather than repair.** Rows with orphan accounts or invalid amounts are quarantined with a reason, not silently corrected, so a controller can decide what to do with them.
- **Report unknowns explicitly.** A null counterparty country becomes `UNKNOWN` instead of being dropped, because dropping it would make the extract disagree with the source total.
- **Parameters in one place.** Period, threshold and review intervals are defined once and loaded into SQL tables, so SQL and Python cannot use different values.
- **Month-end clamping.** Review due dates add calendar months and clamp the day (31 January plus one month is 28 or 29 February), implemented in both SQL and Python and unit tested.

## Limitations

- The data is synthetic and uniformly random, so it has none of the structure of real customer behaviour. For example, some large transactions sit on accounts of customers whose KYB status is `rejected`; in real data that would itself be a finding.
- The extracts are illustrative, not an implementation of a specific regulatory template.
- Reconciliation here compares two implementations written by one person. In production the second source would be an upstream system of record or a control total supplied by the data owner.
- No orchestration, scheduling or access control. The pipeline is a single command.
