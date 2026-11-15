# Interface
- `python -m app clean` — runs the pipeline, prints the data-quality summary.
- `python -m app ask "<question>"` — prints the answer, then `Query:` with the SQL,
  then `Sources:` with the row count behind the answer.
- Router: keyword intents -> parameterized SQL templates. Parameters: year, plan,
  top N, status. No match -> "I can't answer that from this data" plus the closest
  supported question; exit code 2. Read-only connection.
- app.query.answer(question) returns {intent, sql, params, value, rows, text} for evals,
  plus `sources` (the Sources line) and `declined` (bool).

## Exit codes
0 answered · 2 declined · 1 error (database missing -> "run `python -m app clean` first",
or a query error).

## Intents (metrics per schema.md §10)
| Intent | Parameters | Sources counts |
|---|---|---|
| revenue | year (optional, one calendar year; default all years) | paid invoices |
| region_mrr | none; average MRR per non-churned account, by region | active accounts |
| refunds | none | refunded invoices |
| churn | plans (one or more; default all three) | accounts |
| top_accounts | N (default 5, 1..100); low_csat = csat_score <= 2, NULL is not low | paid invoices of those accounts |
| stuck | status: pending, failed, or both (default both) | invoices |

The revenue answer states how many of its invoices have an ambiguous or future date.
Parameters are bound, never interpolated; the printed SQL shows the bound values.

## Decline rules (exit 2, never a guess)
- No intent matches.
- Another currency (EUR, GBP, €, £, …): answers are USD only.
- Relative dates (last/this/next quarter|month|year, YTD, today, recently, …).
- Sub-year periods (months, quarters, Q1–Q4, trends, by month).
- Dimensions no template covers: industry, country, segment, payment method,
  billing cycle, seats, tickets, signups; and forecasts or "why" questions.
- A parameter the matched template can't take: region outside region_mrr; plan
  outside churn; a year outside revenue; more than one year; average/net revenue;
  lowest/least/bottom rankings; total or median MRR; top N outside 1..100.
- Empty or over-long (> 500 characters) questions.
