Top 5 accounts by recognized revenue:
  1. ACC-7509 Stark Inc              $1,210,592.75  CSAT 4
  2. ACC-1420 Tyrell Industries      $1,208,092.75  CSAT n/a
  3. ACC-9946 Initech LLC            $1,205,642.75  CSAT 4
  4. ACC-1196 Pied Piper Partners    $1,107,352.84  CSAT 3
  5. ACC-5211 Oscorp Industries      $1,085,078.48  CSAT 5
None of these have CSAT <= 2.

Query:
SELECT a.account_id, a.account_name,
       round(a.revenue_usd, 2)                  AS revenue_usd,
       a.csat_score,
       coalesce(a.csat_score <= 2, FALSE)       AS low_csat,
       (SELECT count(*) FROM invoices_clean i
        WHERE i.account_id = a.account_id AND i.status = 'paid') AS n_paid_invoices
FROM accounts a
ORDER BY a.revenue_usd DESC, a.account_id
LIMIT 5

Sources: 8 paid invoices behind these accounts
