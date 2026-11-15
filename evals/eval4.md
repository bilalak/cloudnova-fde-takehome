Churn rate by plan (share of accounts with churned = TRUE):
  enterprise  21.92%  (171 of 780 accounts)
  starter     18.81%  (354 of 1,882 accounts)

Query:
SELECT plan,
       count(*)                                          AS n_accounts,
       count(*) FILTER (churned)                         AS n_churned,
       round(100.0 * count(*) FILTER (churned) / count(*), 2) AS churn_rate_pct
FROM accounts
WHERE list_contains(['starter', 'enterprise']::VARCHAR[], plan)
GROUP BY plan
ORDER BY plan

Sources: 2,662 accounts
