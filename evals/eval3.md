Refunds given back: $8,925,163.77 USD across 292 refunded invoices.

Query:
SELECT round(abs(sum(amount_usd)), 2) AS refunds_usd,
       count(*)                       AS n_invoices
FROM invoices_clean
WHERE status = 'refunded'

Sources: 292 refunded invoices (invoices_clean)
