# Architecture

Data flows left to right. Everything runs locally; no network calls, no API keys.

```mermaid
flowchart LR
    CSV["data/cloudnova_invoices.csv<br/>5,125 raw rows"] --> CLEAN["app/clean.py<br/>normalize · parse · dedup · gates"]
    CLEAN --> DB[("cloudnova.duckdb<br/>invoices_clean table<br/>accounts view")]
    CLEAN --> Q["data/cleaned/quarantine.csv"]
    CLEAN --> DQ["data/cleaned/data_quality_report.md"]
    USER(["Question"]) --> ROUTER["app/query.py<br/>keyword router → SQL template"]
    DB -- "read-only" --> ROUTER
    ROUTER --> OUT["Answer + SQL + Sources<br/>or decline + closest question"]
    EVALS["evals/run_evals.py<br/>12 cases vs expected.json"] --> ROUTER
    CI[".github/workflows/evals.yml<br/>on push: clean → evals"] -.-> CLEAN
    CI -.-> EVALS
```

| Component | File | Spec |
|---|---|---|
| Config (paths, FX, list prices, AS_OF_DATE, gate values; env overrides) | `app/config.py` | CLAUDE.md |
| Cleaning pipeline: trim → exact dedup → normalize/parse → quarantine → near-dup → derive → gates → write | `app/clean.py` | `specs/schema.md` |
| Store: `invoices_clean` (5,000 rows, PK invoice_id), `accounts` view (3,815 rows) | `cloudnova.duckdb` | `specs/schema.md` §8 |
| Router: regex intents → 6 parameterized SQL templates, read-only | `app/query.py` | `specs/api.md` |
| CLI: `clean`, `ask` | `app/__main__.py` | `specs/api.md` |
| Eval harness | `evals/run_evals.py`, `evals/expected.json` | `specs/evals.md` |
| CI: rebuild + evals on push | `.github/workflows/evals.yml` | — |
