# Interface
- `python -m app clean` — runs the pipeline, prints the data-quality summary.
- `python -m app ask "<question>"` — prints the answer, then `Query:` with the SQL,
  then `Sources:` with the row count behind the answer.
- Router: keyword intents -> parameterized SQL templates. Parameters: year, plan,
  top N, status. No match -> "I can't answer that from this data" plus the closest
  supported question; exit code 2. Read-only connection.
- app.query.answer(question) returns {intent, sql, params, value, rows, text} for evals.
