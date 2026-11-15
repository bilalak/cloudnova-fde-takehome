Recognized revenue (paid invoices) in 2024: $32,686,371.05 USD.
Caveat: of these 891 invoices, 20 have ambiguous DD-MM/MM-DD dates.

Query:
SELECT round(sum(amount_usd), 2)       AS revenue_usd,
       count(*)                            AS n_invoices,
       count(*) FILTER (date_ambiguous)    AS n_ambiguous_date,
       count(*) FILTER (is_future_date)    AS n_future_date
FROM invoices_clean
WHERE status = 'paid'
  AND (2024 IS NULL OR year(invoice_date) = 2024)

Sources: 891 paid invoices (invoices_clean)
