894 invoices are stuck in failed/pending, exposing $28,983,255.81 USD:
  failed     396    $13,157,652.28
  pending    498    $15,825,603.53

Query:
SELECT status,
       count(*)                    AS n_invoices,
       round(sum(amount_usd), 2)   AS exposed_usd
FROM invoices_clean
WHERE list_contains(['failed', 'pending']::VARCHAR[], status)
GROUP BY status
ORDER BY status

Sources: 894 invoices (invoices_clean)
