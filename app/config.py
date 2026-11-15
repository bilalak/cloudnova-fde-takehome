"""Configuration. Defaults live here; environment variables (or a local .env) override.

Precedence: real environment > .env file > defaults below.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader (no extra dependency). Never overrides real env vars."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")


def _path(env: str, default: str) -> Path:
    p = Path(os.environ.get(env, default))
    return p if p.is_absolute() else ROOT / p


RAW_CSV: Path = _path("RAW_CSV", "data/cloudnova_invoices.csv")
DB_PATH: Path = _path("DB_PATH", "cloudnova.duckdb")
CLEANED_DIR: Path = _path("CLEANED_DIR", "data/cleaned")
AS_OF_DATE: date = date.fromisoformat(os.environ.get("AS_OF_DATE", "2026-11-15"))

# specs/schema.md §4 — fixed reference FX to USD.
FX_TO_USD: dict[str, float] = {"USD": 1.00, "EUR": 1.08, "GBP": 1.27}

# specs/schema.md §7 — list price per seat per month, USD.
LIST_PRICE_USD: dict[str, float] = {"starter": 49.0, "pro": 99.0, "enterprise": 299.0}

# specs/schema.md §9 — validation gates. Never lower these to make a run pass.
GATES = {
    "raw_rows": 5125,
    "exact_duplicates": 82,
    "quarantined": 0,
    "near_duplicates_dropped": 43,
    "final_rows": 5000,
    "accounts": 3815,
}
