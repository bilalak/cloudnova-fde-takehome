"""Cleaning pipeline: raw CSV -> pandas -> DuckDB. Implements specs/schema.md.

Section references (§n) point at specs/schema.md. Order of operations follows §2,
except that §9 gates run *before* anything is written, because §9 requires
"fail -> write nothing".
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime

import duckdb
import pandas as pd

from app import config


class SpecUnclear(Exception):
    """Data hit a case specs/schema.md does not cover. Stop and ask; don't guess."""


# ---------------------------------------------------------------- §3 categories
PLAN_MAP = {
    "starter": "starter", "start": "starter", "tier 1": "starter",
    "pro": "pro", "professional": "pro", "tier 2": "pro",
    "enterprise": "enterprise", "ent": "enterprise", "tier 3": "enterprise",
}
CYCLE_MAP = {"monthly": "monthly", "annual": "annual", "annually": "annual", "yearly": "annual"}
STATUS_MAP = {
    "paid": "paid", "complete": "paid", "completed": "paid", "success": "paid",
    "pending": "pending", "in_review": "pending", "awaiting": "pending",
    "failed": "failed", "declined": "failed", "error": "failed",
    "refunded": "refunded", "refund": "refunded", "charged_back": "refunded",
    "void": "void", "cancelled": "void", "canceled": "void",
}
PAYMENT_MAP = {
    "credit card": "credit_card", "credit_card": "credit_card", "ach": "ach",
    "wire": "wire", "wire transfer": "wire", "invoice": "invoice",
}
CHURNED_MAP = {"true": True, "yes": True, "1": True, "y": True,
               "false": False, "no": False, "0": False, "n": False}

# §6 — higher wins.
STATUS_PRECEDENCE = {"refunded": 5, "void": 4, "paid": 3, "failed": 2, "pending": 1}

# ---------------------------------------------------------------- §4 amounts
_AMOUNT_RE = re.compile(r"^\s*([$€£]?)\s*(-?)\s*([$€£]?)([\d,]*\.?\d*)\s*(USD|EUR|GBP)?\s*$", re.I)


def parse_amount(raw: str | None) -> tuple[float | None, str | None]:
    """Return (amount_local, trailing_currency_code). Strips $ € £ , and a trailing code."""
    if raw is None:
        return None, None
    m = _AMOUNT_RE.match(raw)
    if not m or not m.group(4) or m.group(4) in {".", ","}:
        return None, None
    try:
        value = float(m.group(4).replace(",", ""))
    except ValueError:
        return None, None
    if m.group(2) == "-":
        value = -value
    code = m.group(5).upper() if m.group(5) else None
    return value, code


# ---------------------------------------------------------------- §5 dates
_YMD_DASH = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_YMD_SLASH = re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})$")
_MDY_SLASH = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_DMY_DASH = re.compile(r"^(\d{1,2})-(\d{1,2})-(\d{4})$")
_MON_NAME = re.compile(r"^[A-Za-z]{3} \d{1,2} \d{4}$")


def parse_date(raw: str | None) -> tuple[date | None, bool]:
    """Return (date, is_dash_ambiguous). None if the value fits no §5 format."""
    if raw is None:
        return None, False
    try:
        if m := _YMD_DASH.match(raw) or _YMD_SLASH.match(raw):
            y, mo, d = map(int, m.groups())
            return date(y, mo, d), False
        if m := _MDY_SLASH.match(raw):
            mo, d, y = map(int, m.groups())
            return date(y, mo, d), False
        if m := _DMY_DASH.match(raw):
            d, mo, y = map(int, m.groups())
            return date(y, mo, d), (d <= 12 and mo <= 12)
        if _MON_NAME.match(raw):
            return datetime.strptime(raw, "%b %d %Y").date(), False
    except ValueError:  # e.g. month 13 under the stated rule
        return None, False
    return None, False


# ---------------------------------------------------------------- pipeline
@dataclass
class Result:
    steps: list[tuple[str, int]] = field(default_factory=list)
    invoices: pd.DataFrame | None = None
    quarantine: pd.DataFrame | None = None
    near_dup_dropped: pd.DataFrame | None = None
    exact_dups: int = 0
    signup_dash_ambiguous: int = 0
    currency_code_mismatch: int = 0
    near_dup_identical_ties: int = 0


def _int_or_none(v: str | None) -> int | None:
    if v is None:
        return None
    return int(v) if re.fullmatch(r"-?\d+", v) else float("nan")  # nan -> quarantine


def _num_or_none(v: str | None) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except ValueError:
        return float("nan")


def run_pipeline(raw_csv=None) -> Result:
    res = Result()

    # §1 — read everything as strings. keep_default_na=False so region "NA" survives.
    raw = pd.read_csv(raw_csv or config.RAW_CSV, dtype=str, keep_default_na=False)
    res.steps.append(("raw", len(raw)))

    # §2.1 — trim whitespace; empty string -> NULL.
    df = raw.apply(lambda s: s.str.strip()).replace({"": None})

    # §2.2 — drop exact duplicate rows.
    before = len(df)
    df = df.drop_duplicates().reset_index(drop=True)
    res.exact_dups = before - len(df)
    res.steps.append(("after exact-duplicate drop", len(df)))

    # §2.3 — normalize categories (§3), amounts (§4), dates (§5).
    out = pd.DataFrame(index=df.index)
    reasons: list[list[str]] = [[] for _ in range(len(df))]

    def mapped(col: str, mapping: dict, quarantine: bool):
        vals = []
        for i, v in enumerate(df[col]):
            if v is None:
                if quarantine:
                    reasons[i].append(f"null_{col}")
                vals.append(None)
                continue
            key = v.lower()
            if key not in mapping:
                if quarantine:
                    reasons[i].append(f"unmapped_{col}")
                    vals.append(None)
                    continue
                raise SpecUnclear(f"{col} value {v!r} has no §3 mapping and §3 does not "
                                  f"say to quarantine it")
            vals.append(mapping[key])
        return vals

    for col in ["invoice_id", "account_id", "account_name", "region", "industry"]:
        out[col] = df[col]
    out["contact_email"] = [None if v is None else v.replace("_at_", "@").lower()
                            for v in df["contact_email"]]
    out["plan"] = mapped("plan", PLAN_MAP, quarantine=True)
    out["billing_cycle"] = mapped("billing_cycle", CYCLE_MAP, quarantine=True)
    out["status"] = mapped("status", STATUS_MAP, quarantine=True)
    out["churned"] = pd.array(mapped("churned", CHURNED_MAP, quarantine=True), dtype="boolean")
    out["payment_method"] = mapped("payment_method", PAYMENT_MAP, quarantine=False)

    # Numeric columns: a non-numeric value is a parse failure (§2.4).
    for col, fn in [("seats", _int_or_none), ("discount_pct", _num_or_none),
                    ("csat_score", _int_or_none), ("support_tickets", _int_or_none)]:
        vals = [fn(v) for v in df[col]]
        for i, v in enumerate(vals):
            if isinstance(v, float) and pd.isna(v) and df[col][i] is not None:
                reasons[i].append(f"unparsed_{col}")
        out[col] = vals
    for col in ["seats", "csat_score", "support_tickets"]:
        out[col] = pd.to_numeric(out[col]).astype("Int64")
    out["discount_pct"] = pd.to_numeric(out["discount_pct"]).astype("Float64")

    # §4 amounts.
    out["currency"] = df["currency"].str.upper()
    amounts, mismatches = [], 0
    for i, (v, cur) in enumerate(zip(df["amount"], out["currency"])):
        amt, code = parse_amount(v)
        if amt is None:
            reasons[i].append("unparsed_amount")
        if cur not in config.FX_TO_USD:
            reasons[i].append("unknown_currency")
        if code is not None and code != cur:
            mismatches += 1
        amounts.append(amt)
    if mismatches:
        raise SpecUnclear(f"{mismatches} amounts carry a trailing currency code that differs "
                          f"from the currency column; §4 does not say which wins")
    out["amount_local"] = pd.array(amounts, dtype="Float64")
    out["fx_rate"] = out["currency"].map(config.FX_TO_USD).astype("Float64")
    out["amount_usd"] = out["amount_local"] * out["fx_rate"]

    # §5 dates.
    for col in ["signup_date", "invoice_date"]:
        parsed = [parse_date(v) for v in df[col]]
        for i, (d, _) in enumerate(parsed):
            if d is None:
                reasons[i].append(f"unparsed_{col}" if df[col][i] is not None else f"null_{col}")
        out[col] = pd.array([d for d, _ in parsed], dtype="object")
        if col == "invoice_date":
            out["date_ambiguous"] = [amb for _, amb in parsed]
        else:
            res.signup_dash_ambiguous = sum(amb for _, amb in parsed)
    out["is_future_date"] = [d is not None and d > config.AS_OF_DATE for d in out["invoice_date"]]
    res.steps.append(("after normalization (no rows removed)", len(out)))

    # §2.4 — quarantine rows that failed parsing or mapping.
    bad = pd.Series([bool(r) for r in reasons], index=out.index)
    q = df[bad].copy()
    q.insert(0, "reason", [";".join(r) for r, b in zip(reasons, bad) if b])
    res.quarantine = q.reset_index(drop=True)
    out = out[~bad].reset_index(drop=True)
    res.steps.append(("after quarantine", len(out)))

    # §6 — near-duplicates: same invoice_id; highest status precedence, tie -> latest date.
    out["_prec"] = out["status"].map(STATUS_PRECEDENCE)
    out = out.sort_values(["invoice_id", "_prec", "invoice_date"],
                          ascending=[True, False, False], kind="stable")
    dup_ids = out["invoice_id"].duplicated(keep=False)
    top2 = out[dup_ids].groupby("invoice_id").head(2)
    # A tie on (precedence, date) only matters if the tied rows differ once normalized;
    # if they are identical, either pick yields the same row.
    tied = top2.groupby("invoice_id").filter(
        lambda g: len(g) == 2 and g["_prec"].nunique() == 1 and g["invoice_date"].nunique() == 1)
    res.near_dup_identical_ties = int(tied["invoice_id"].nunique())
    unresolved = tied.groupby("invoice_id").filter(
        lambda g: len(g.astype(str).drop_duplicates()) > 1)
    if len(unresolved):
        raise SpecUnclear(f"{unresolved['invoice_id'].nunique()} invoice_ids tie on both status "
                          f"precedence and invoice_date but differ in other columns; "
                          f"§6 has no further tie-break")
    keep = ~out["invoice_id"].duplicated(keep="first")
    res.near_dup_dropped = out[~keep].drop(columns="_prec").reset_index(drop=True)
    out = out[keep].drop(columns="_prec").sort_values("invoice_id").reset_index(drop=True)
    res.steps.append(("after near-duplicate resolution", len(out)))

    # §7 — derived.
    out["list_price"] = out["plan"].map(config.LIST_PRICE_USD).astype("Float64")
    out["mrr_usd"] = out["list_price"] * out["seats"] * (1 - out["discount_pct"] / 100)

    cols = ["invoice_id", "account_id", "account_name", "contact_email", "region", "industry",
            "plan", "billing_cycle", "seats", "list_price", "discount_pct", "mrr_usd",
            "currency", "amount_local", "fx_rate", "amount_usd", "status", "payment_method",
            "signup_date", "invoice_date", "date_ambiguous", "is_future_date",
            "churned", "csat_score", "support_tickets"]
    res.invoices = out[cols]
    for col in ["signup_date", "invoice_date"]:
        res.invoices[col] = pd.to_datetime(res.invoices[col]).dt.date
    return res


# ---------------------------------------------------------------- §9 gates
def check_gates(res: Result) -> list[tuple[str, bool, object, object]]:
    g = config.GATES
    inv = res.invoices
    neg = inv["amount_usd"] < 0
    refunded = inv["status"] == "refunded"
    checks = [
        ("raw rows", res.steps[0][1], g["raw_rows"]),
        ("exact duplicates dropped", res.exact_dups, g["exact_duplicates"]),
        ("quarantined", len(res.quarantine), g["quarantined"]),
        ("near-duplicate rows dropped", len(res.near_dup_dropped), g["near_duplicates_dropped"]),
        ("final rows", len(inv), g["final_rows"]),
        ("duplicate invoice_ids", int(inv["invoice_id"].duplicated().sum()), 0),
        ("accounts", int(inv["account_id"].nunique()), g["accounts"]),
    ]
    for col in ["invoice_date", "amount_usd", "plan", "status"]:
        checks.append((f"NULL {col}", int(inv[col].isna().sum()), 0))
    checks.append(("refunded rows not negative", int((refunded & ~neg).sum()), 0))
    checks.append(("negative amounts outside refunded", int((~refunded & neg).sum()), 0))
    return [(name, actual == expected, actual, expected) for name, actual, expected in checks]


# ---------------------------------------------------------------- §8 outputs
ACCOUNTS_VIEW = """
CREATE VIEW accounts AS
WITH ranked AS (
    SELECT *, row_number() OVER (PARTITION BY account_id
                                 ORDER BY invoice_date DESC, invoice_id DESC) AS rn
    FROM invoices_clean
)
SELECT r.account_id, r.account_name, r.region, r.industry, r.plan, r.seats,
       r.churned, r.csat_score, r.mrr_usd,
       COALESCE(p.revenue_usd, 0) AS revenue_usd
FROM ranked r
LEFT JOIN (SELECT account_id, sum(amount_usd) AS revenue_usd
           FROM invoices_clean WHERE status = 'paid' GROUP BY account_id) p
  USING (account_id)
WHERE r.rn = 1
"""


def write_outputs(res: Result, report_md: str) -> None:
    """Build the DB in a temp file and swap it in, so a crash never leaves a half-written DB."""
    db_path = config.DB_PATH
    tmp = db_path.with_suffix(db_path.suffix + ".tmp")
    tmp.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    try:
        con.register("inv_df", res.invoices)
        con.execute("CREATE TABLE invoices_clean AS SELECT * FROM inv_df")
        con.execute("ALTER TABLE invoices_clean ADD PRIMARY KEY (invoice_id)")
        con.execute(ACCOUNTS_VIEW)
        n_acc = con.execute("SELECT count(*) FROM accounts").fetchone()[0]
        if n_acc != config.GATES["accounts"]:
            raise RuntimeError(f"accounts view has {n_acc} rows, gate expects "
                               f"{config.GATES['accounts']}")
    finally:
        con.close()
    os.replace(tmp, db_path)

    config.CLEANED_DIR.mkdir(parents=True, exist_ok=True)
    res.quarantine.to_csv(config.CLEANED_DIR / "quarantine.csv", index=False)
    (config.CLEANED_DIR / "data_quality_report.md").write_text(report_md)


# ---------------------------------------------------------------- report
def _rel(p) -> str:
    try:
        return str(p.relative_to(config.ROOT))
    except ValueError:
        return str(p)


def build_report(res: Result, gates) -> str:
    inv = res.invoices
    L = ["# Data-quality report — CloudNova invoices", "",
         f"Source: `{_rel(config.RAW_CSV)}` · AS_OF_DATE: {config.AS_OF_DATE}",
         "", "## Rows at each step", "", "| Step | Rows | Removed |", "|---|---:|---:|"]
    prev = None
    for name, n in res.steps:
        L.append(f"| {name} | {n:,} | {'' if prev is None else f'{prev - n:,}'} |")
        prev = n

    L += ["", "## Dropped rows", "",
          f"- Exact duplicates dropped: **{res.exact_dups}**",
          f"- Near-duplicate rows dropped (§6): **{len(res.near_dup_dropped)}** "
          f"across {res.near_dup_dropped['invoice_id'].nunique()} invoice_ids"]
    if len(res.near_dup_dropped):
        vc = res.near_dup_dropped["status"].value_counts()
        L.append("  - status of losing rows: " + ", ".join(f"{k} {v}" for k, v in vc.items()))
        L.append(f"  - {res.near_dup_identical_ties} of these ids differed only in raw status "
                 f"spelling (same canonical status); the rows are identical once normalized")

    L += ["", "## Quarantine by reason", ""]
    if len(res.quarantine):
        L += ["| Reason | Rows |", "|---|---:|"]
        for r, n in res.quarantine["reason"].str.split(";").explode().value_counts().items():
            L.append(f"| {r} | {n} |")
    else:
        L.append("None (0 rows). `data/cleaned/quarantine.csv` has headers only.")

    amb = inv[inv["date_ambiguous"]]
    fut = inv[inv["is_future_date"]]
    L += ["", "## Dates", "",
          f"- Ambiguous dash `invoice_date` (both parts ≤ 12, parsed DD-MM-YYYY): **{len(amb)}** "
          f"rows, {amb['amount_usd'].sum():,.2f} USD "
          f"({amb.loc[amb.status == 'paid', 'amount_usd'].sum():,.2f} of it paid)"
          + ("\n  - by year: " + ", ".join(f"{y}: {n}" for y, n in amb["invoice_date"].map(lambda d: d.year).value_counts().sort_index().items()) if len(amb) else ""),
          f"- Ambiguous dash `signup_date` (informational, not flagged in table): "
          f"**{res.signup_dash_ambiguous}**",
          f"- Future `invoice_date` (> {config.AS_OF_DATE}, kept): **{len(fut)}** rows, "
          f"{fut['amount_usd'].sum():,.2f} USD"]

    L += ["", "## Final counts by status", "", "| Status | Invoices | amount_usd |",
          "|---|---:|---:|"]
    for s, g in inv.groupby("status"):
        L.append(f"| {s} | {len(g):,} | {g['amount_usd'].sum():,.2f} |")
    L.append(f"| **total** | **{len(inv):,}** | **{inv['amount_usd'].sum():,.2f}** |")

    L += ["", "## Other final counts", "",
          f"- Invoices: {len(inv):,} · Accounts: {inv['account_id'].nunique():,}",
          f"- account_ids with >1 account_name: "
          f"{int((inv.groupby('account_id')['account_name'].nunique() > 1).sum())}",
          f"- NULL contact_email: {int(inv['contact_email'].isna().sum())} · "
          f"NULL industry: {int(inv['industry'].isna().sum())} · "
          f"NULL csat_score: {int(inv['csat_score'].isna().sum())} · "
          f"NULL payment_method: {int(inv['payment_method'].isna().sum())}",
          f"- Emails still without '@' after `_at_` fix: "
          f"{int((inv['contact_email'].notna() & ~inv['contact_email'].fillna('').str.contains('@')).sum())}",
          "", "## Gates (§9)", "", "| Gate | Actual | Expected | Result |", "|---|---:|---:|---|"]
    for name, ok, actual, expected in gates:
        L.append(f"| {name} | {actual:,} | {expected:,} | {'PASS' if ok else 'FAIL'} |")

    L += ["", "## Open question for finance (§4)", "",
          "Local amounts already equal USD list price × FX rate, so converting them again "
          "with the briefing's FX overstates EUR (~17%) and GBP (~61%) versus list price. "
          "The pipeline follows the briefing literally; affected rows: "
          + ", ".join(f"{c} {n:,}" for c, n in inv["currency"].value_counts().items()
                      if c != "USD") + "."]
    return "\n".join(L) + "\n"


def main() -> int:
    try:
        res = run_pipeline()
    except SpecUnclear as e:
        print(f"STOP — spec unclear: {e}", file=sys.stderr)
        return 3
    except FileNotFoundError as e:
        print(f"ERROR — input not found: {e}", file=sys.stderr)
        return 1

    gates = check_gates(res)
    report = build_report(res, gates)
    failed = [g for g in gates if not g[1]]
    if failed:
        print(report)
        for name, _, actual, expected in failed:
            print(f"GATE FAILED: {name}: actual {actual}, expected {expected}", file=sys.stderr)
        print("Nothing written.", file=sys.stderr)
        return 1

    write_outputs(res, report)
    print(report)
    print(f"Wrote {_rel(config.DB_PATH)} (invoices_clean, accounts) and "
          f"{_rel(config.CLEANED_DIR)}/{{quarantine.csv, data_quality_report.md}}")
    return 0
