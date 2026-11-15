# Architecture

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
