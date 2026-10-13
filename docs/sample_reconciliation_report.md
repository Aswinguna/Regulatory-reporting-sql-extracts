# Reconciliation report

**30 of 30 checks passed.**

| Check | Description | Expected | Actual | Status |
|---|---|---|---|---|
| RF1.customers | Rows loaded into raw_customers equal data lines in customers.csv | 500 | 500 | PASS |
| RF1.accounts | Rows loaded into raw_accounts equal data lines in accounts.csv | 664 | 664 | PASS |
| RF1.transactions_raw | Rows loaded into raw_transactions equal data lines in transactions_raw.csv | 60170 | 60170 | PASS |
| RF2 | Raw rows = clean + rejected + superseded (no row lost or double counted) | 60170 | 60170 | PASS |
| RF3.clean | Clean row count matches independent recomputation | 59930 | 59930 | PASS |
| RF3.superseded | Superseded row count matches independent recomputation | 170 | 170 | PASS |
| RF3.ORPHAN_ACCOUNT | Rejected rows with reason ORPHAN_ACCOUNT match independent recomputation | 40 | 40 | PASS |
| RF3.INVALID_AMOUNT | Rejected rows with reason INVALID_AMOUNT match independent recomputation | 30 | 30 | PASS |
| RF4 | transaction_id is unique in clean_transactions (duplicates in = 0) | 0 | 0 | PASS |
| RF5.accounts | account_id is unique in raw_accounts (joins cannot fan out) | 0 | 0 | PASS |
| RF5.customers | customer_id is unique in raw_customers (joins cannot fan out) | 0 | 0 | PASS |
| RF6 | Every customer has a recognised risk rating (inner join cannot drop customers) | 0 | 0 | PASS |
| E1.count | Sum of transaction_count equals independent in-period clean count | 53771 | 53771 | PASS |
| E1.total | Sum of total_amount_eur equals independent in-period total to the cent | 47520545.66 | 47520545.66 | PASS |
| E1.cells | Cells (month, country, type, direction) differing from independent figures | 0 | 0 | PASS |
| E1.unknown | UNKNOWN-country transactions equal independent count of null countries in period | 110 | 110 | PASS |
| E1.nulls | Null cells in extract_monthly_volumes | 0 | 0 | PASS |
| E2.count | Large transaction row count equals independent count | 543 | 543 | PASS |
| E2.total | Large transaction total equals independent total to the cent | 11738229.05 | 11738229.05 | PASS |
| E2.ids | Transaction ids present in only one of SQL extract or independent list | 0 | 0 | PASS |
| E2.unique | Duplicate transaction ids in the extract | 0 | 0 | PASS |
| E2.threshold | Rows below the 10000.00 threshold | 0 | 0 | PASS |
| E2.nulls | Null cells in extract_large_transactions | 0 | 0 | PASS |
| X1 | Large transaction value never exceeds total in-period value (cross-extract sanity) | True | True | PASS |
| E3.count | Overdue review count equals independent count | 70 | 70 | PASS |
| E3.customers | Customers present in only one of SQL extract or independent list | 0 | 0 | PASS |
| E3.days | Customers whose days_overdue differs from independent figure | 0 | 0 | PASS |
| E3.approved | Overdue customers that are not approved | 0 | 0 | PASS |
| E3.partition | Approved customers = overdue + current (nobody falls out of the report) | 431 | 431 | PASS |
| E3.nulls | Null cells in extract_overdue_kyb_reviews | 0 | 0 | PASS |
