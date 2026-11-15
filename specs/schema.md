# Schema spec — CloudNova invoices (nalTrack B)

## 1. Input
data/cloudnova_invoices.csv — 5,125 rows, 19 columns, read as strings.

## 2. Order of operations
1. Trim whitespace everywhere; empty string -> NULL.
2. Drop exact duplicate rows (82) -> 5,043.
3. Normalize categories (§3), parse amounts (§4) and dates (§5).
4. Quarantine rows that fail parsing or mapping, with a reason (expected 0).
5. Resolve near-duplicates (§6) -> 5,000 rows, invoice_id unique.
6. Derive columns (§7), write outputs (§8), run gates (§9).

## 3. Categories (case-insensitive)
- plan: starter|start|tier 1 -> starter; pro|professional|tier 2 -> pro;
  enterprise|ent|tier 3 -> enterprise.
- billing_cycle: monthly -> monthly; annual|annually|yearly -> annual.
- status: paid|complete|completed|success -> paid; pending|in_review|awaiting -> pending;
  failed|declined|error -> failed; refunded|refund|charged_back -> refunded;
  void|cancelled|canceled -> void.
- payment_method: credit card|credit_card -> credit_card; ach -> ach;
  wire|wire transfer -> wire; invoice -> invoice; blank -> NULL.
- churned: true|yes|1|y -> TRUE; false|no|0|n -> FALSE.
- contact_email: "_at_" -> "@", lowercase; blank stays NULL.
- Unmapped plan/status/cycle/churned value -> quarantine.

## 4. Amounts
- amount_local: strip $, €, £, commas, trailing currency code; keep sign.
- fx_rate: USD 1.00, EUR 1.08, GBP 1.27 (config).
- amount_usd = amount_local * fx_rate.
- OPEN QUESTION for finance: local amounts already equal USD list price * rate,
  so this conversion overstates EUR (~17%) and GBP (~61%) versus list price.
  We follow the briefing literally and flag it.

## 5. Dates (signup_date, invoice_date)
- YYYY-MM-DD, YYYY/MM/DD: year first.
- MM/DD/YYYY for slashes (no slash date has a first part > 12).
- DD-MM-YYYY for dashes (151 of 239 dash invoice dates have a first part > 12).
- "Jan 5 2024": month name.
- date_ambiguous = TRUE for dash invoice dates with both parts <= 12.
- is_future_date = TRUE where invoice_date > AS_OF_DATE. Rows are kept.

## 6. Near-duplicates (same invoice_id, 43 ids)
Keep the row with the highest status precedence:
refunded > void > paid > failed > pending. Tie: latest invoice_date.
Rationale: terminal states are later events. This also removes the only two
negative amounts carried by a "paid" row.

## 7. Derived
- list_price: starter 49, pro 99, enterprise 299.
- mrr_usd = list_price * seats * (1 - discount_pct/100); same for monthly and annual.

## 8. Outputs
- DuckDB table invoices_clean (one row per invoice).
- DuckDB view accounts: one row per account_id, attributes from the latest invoice
  (invoice_date, then invoice_id): account_name, region, industry, plan, seats,
  churned, csat_score, mrr_usd; plus revenue_usd = sum(amount_usd) of paid invoices.
  Note: 976 account_ids carry more than one account_name; account_id is the key.
- data/cleaned/quarantine.csv (with reason), data/cleaned/data_quality_report.md.

## 9. Gates (fail -> exit non-zero, write nothing)
raw 5,125 · exact duplicates 82 · quarantined 0 · near-duplicate rows dropped 43 ·
final 5,000 · invoice_id unique · accounts 3,815 · no NULL in invoice_date,
amount_usd, plan, status · refunded rows all negative · no other negative amounts.

## 10. Metric definitions
- Recognized revenue: sum(amount_usd) where status = 'paid'.
- Refunds given back: abs(sum(amount_usd)) where status = 'refunded'.
- Active MRR per account: mrr_usd from accounts where churned = FALSE.
- Churn rate by plan: share of accounts with churned = TRUE.
- Exposed $: sum(amount_usd) where status in ('pending','failed').