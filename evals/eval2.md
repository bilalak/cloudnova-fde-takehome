APAC has the highest average MRR per active account: $6,147.30.
  APAC      $6,147.30  (753 accounts)
  NA        $5,632.84  (739 accounts)
  EMEA      $5,327.66  (781 accounts)
  LATAM     $5,187.55  (789 accounts)

Query:
SELECT region,
       round(avg(mrr_usd), 2) AS avg_mrr_usd,
       count(*)               AS n_accounts
FROM accounts
WHERE churned = FALSE
GROUP BY region
ORDER BY avg_mrr_usd DESC, region

Sources: 3,062 active (non-churned) accounts
