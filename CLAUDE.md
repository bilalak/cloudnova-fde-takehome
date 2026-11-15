# Working rules
- specs/ is the source of truth. If code and spec disagree, stop and ask.
- Rule changes go into specs/ first, then code, in the same commit.
- Python 3.10+, pandas + duckdb only. No other dependencies.
- Paths, FX rates, list prices, AS_OF_DATE live in app/config.py (env overrides).
- Validation gates are never lowered to make a run pass.
- Every dropped or quarantined row is counted in the data-quality report.
- The ask path opens DuckDB read-only and never invents an answer.
- Do not edit evals/expected.json to make a case pass.
- Nothing outside the specs; ideas go to README "Next steps".
