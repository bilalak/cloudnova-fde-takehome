# Data-quality report — CloudNova invoices

Source: `data/cloudnova_invoices.csv` · AS_OF_DATE: 2026-11-15

## Rows at each step

| Step | Rows | Removed |
|---|---:|---:|
| raw | 5,125 |  |
| after exact-duplicate drop | 5,043 | 82 |
| after normalization (no rows removed) | 5,043 | 0 |
| after quarantine | 5,043 | 0 |
| after near-duplicate resolution | 5,000 | 43 |

## Dropped rows

- Exact duplicates dropped: **82**
- Near-duplicate rows dropped (§6): **43** across 43 invoice_ids
  - status of losing rows: paid 34, pending 7, failed 2
  - 27 of these ids differed only in raw status spelling (same canonical status); the rows are identical once normalized

## Quarantine by reason

None (0 rows). `data/cleaned/quarantine.csv` has headers only.

## Dates

- Ambiguous dash `invoice_date` (both parts ≤ 12, parsed DD-MM-YYYY): **87** rows, 2,166,194.07 USD (1,584,382.67 of it paid)
  - by year: 2021: 3, 2022: 10, 2023: 20, 2024: 29, 2025: 12, 2026: 10, 2027: 3
- Ambiguous dash `signup_date` (informational, not flagged in table): **129**
- Future `invoice_date` (> 2026-11-15, kept): **106** rows, 1,514,021.24 USD

## Final counts by status

| Status | Invoices | amount_usd |
|---|---:|---:|
| failed | 396 | 13,157,652.28 |
| paid | 3,426 | 120,136,746.46 |
| pending | 498 | 15,825,603.53 |
| refunded | 292 | -8,925,163.77 |
| void | 388 | 9,805,725.19 |
| **total** | **5,000** | **150,000,563.69** |

## Other final counts

- Invoices: 5,000 · Accounts: 3,815
- account_ids with >1 account_name: 976
- NULL contact_email: 285 · NULL industry: 412 · NULL csat_score: 607 · NULL payment_method: 623
- Emails still without '@' after `_at_` fix: 0

## Gates (§9)

| Gate | Actual | Expected | Result |
|---|---:|---:|---|
| raw rows | 5,125 | 5,125 | PASS |
| exact duplicates dropped | 82 | 82 | PASS |
| quarantined | 0 | 0 | PASS |
| near-duplicate rows dropped | 43 | 43 | PASS |
| final rows | 5,000 | 5,000 | PASS |
| duplicate invoice_ids | 0 | 0 | PASS |
| accounts | 3,815 | 3,815 | PASS |
| NULL invoice_date | 0 | 0 | PASS |
| NULL amount_usd | 0 | 0 | PASS |
| NULL plan | 0 | 0 | PASS |
| NULL status | 0 | 0 | PASS |
| refunded rows not negative | 0 | 0 | PASS |
| negative amounts outside refunded | 0 | 0 | PASS |

## Open question for finance (§4)

Local amounts already equal USD list price × FX rate, so converting them again with the briefing's FX overstates EUR (~17%) and GBP (~61%) versus list price. The pipeline follows the briefing literally; affected rows: EUR 1,048, GBP 476.
