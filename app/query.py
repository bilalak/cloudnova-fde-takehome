"""Natural-language question -> parameterized SQL over the cleaned DuckDB. See specs/api.md.

Router: regex keyword intents -> fixed SQL templates (metric definitions: specs/schema.md §10).
Parameters (year, plan, top N, status) are extracted with regex, validated against
whitelists, and bound as query parameters. Anything the templates can't express is
declined — the router never guesses.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import duckdb

from app import config

DECLINE = "I can't answer that from this data"


class Declined(Exception):
    def __init__(self, reason: str, closest: str):
        super().__init__(reason)
        self.reason, self.closest = reason, closest


# ---------------------------------------------------------------- templates (§10)
@dataclass(frozen=True)
class Template:
    intent: str
    canonical: str  # the "closest supported question" shown on decline
    sql: str


TEMPLATES = {
    "revenue": Template(
        "revenue",
        "What was our total recognized revenue in USD for paid invoices in 2024?",
        """SELECT round(sum(amount_usd), 2)       AS revenue_usd,
       count(*)                            AS n_invoices,
       count(*) FILTER (date_ambiguous)    AS n_ambiguous_date,
       count(*) FILTER (is_future_date)    AS n_future_date
FROM invoices_clean
WHERE status = 'paid'
  AND (? IS NULL OR year(invoice_date) = ?)""",
    ),
    "region_mrr": Template(
        "region_mrr",
        "Which region has the highest average MRR per account?",
        """SELECT region,
       round(avg(mrr_usd), 2) AS avg_mrr_usd,
       count(*)               AS n_accounts
FROM accounts
WHERE churned = FALSE
GROUP BY region
ORDER BY avg_mrr_usd DESC, region""",
    ),
    "refunds": Template(
        "refunds",
        "How much have we given back in refunds?",
        """SELECT round(abs(sum(amount_usd)), 2) AS refunds_usd,
       count(*)                       AS n_invoices
FROM invoices_clean
WHERE status = 'refunded'""",
    ),
    "churn": Template(
        "churn",
        "What's the churn rate among Enterprise accounts vs Starter?",
        """SELECT plan,
       count(*)                                          AS n_accounts,
       count(*) FILTER (churned)                         AS n_churned,
       round(100.0 * count(*) FILTER (churned) / count(*), 2) AS churn_rate_pct
FROM accounts
WHERE list_contains(?::VARCHAR[], plan)
GROUP BY plan
ORDER BY plan""",
    ),
    "top_accounts": Template(
        "top_accounts",
        "List the top 5 accounts by revenue, and flag any with CSAT <= 2.",
        """SELECT a.account_id, a.account_name,
       round(a.revenue_usd, 2)                  AS revenue_usd,
       a.csat_score,
       coalesce(a.csat_score <= 2, FALSE)       AS low_csat,
       (SELECT count(*) FROM invoices_clean i
        WHERE i.account_id = a.account_id AND i.status = 'paid') AS n_paid_invoices
FROM accounts a
ORDER BY a.revenue_usd DESC, a.account_id
LIMIT ?""",
    ),
    "stuck": Template(
        "stuck",
        "How many invoices are stuck in pending/failed and what's the exposed $?",
        """SELECT status,
       count(*)                    AS n_invoices,
       round(sum(amount_usd), 2)   AS exposed_usd
FROM invoices_clean
WHERE list_contains(?::VARCHAR[], status)
GROUP BY status
ORDER BY status""",
    ),
}

# ---------------------------------------------------------------- routing rules
# Order matters: more specific intents first ("recurring revenue" is MRR, not revenue).
INTENT_PATTERNS = [
    ("refunds", r"\brefund(s|ed)?\b|\bgiven back\b|\bpaid back\b|\bcharge ?backs?\b"),
    ("churn", r"\bchurn(ed|ing|s)?\b|\battrition\b"),
    ("stuck", r"\bstuck\b|\bpending\b|\bfailed\b|\bexposed\b|\bexposure\b|\bat risk\b"),
    ("top_accounts", r"\b(top|biggest|largest|best)\b.*\b(accounts?|customers?|clients?)\b"),
    ("region_mrr", r"\bmrr\b"),
    ("revenue", r"\brevenue\b|\bsales\b|\bearn(ed|ings)?\b|\bbring in\b|\bbrought in\b"),
]

PLAN_PATTERNS = {
    "starter": r"\b(starter|start|tier 1)\b",
    "pro": r"\b(pro|professional|tier 2)\b",
    "enterprise": r"\b(enterprise|ent|tier 3)\b",
}
YEAR_RE = r"\b(20\d{2}|19\d{2})\b"
WORD_NUMS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
             "eight": 8, "nine": 9, "ten": 10, "twenty": 20}
TOP_N_RE = r"\btop\s+(\d+|" + "|".join(WORD_NUMS) + r")\b"
MAX_TOP_N = 100

# Things no template can express -> decline (checked for every intent).
UNSUPPORTED = [
    (r"[€£]|\b(eur|euros?|gbp|pounds?|sterling|cad|aud|jpy|yen|inr|chf|local currency)\b",
     "answers are only available in USD"),
    (r"\b(last|this|next|previous|past|prior|current|coming)\s+(\d+\s+)?"
     r"(years?|quarters?|months?|weeks?|days?|fiscal)\b"
     r"|\b(ytd|qtd|mtd|year[- ]to[- ]date|yesterday|today|tomorrow|recent(ly)?|lately)\b",
     "relative dates are not supported; ask about a specific calendar year"),
    (r"\b(q[1-4]|quarters?|quarterly|january|february|march|april|june|july|august|september|"
     r"october|november|december|may\s+20\d{2}|by month|per month|monthly trend|over time|"
     r"trend|weekly|daily)\b",
     "only whole calendar years are supported"),
    (r"\b(industr(y|ies)|countr(y|ies)|segments?|payment methods?|billing cycles?|seats?|"
     r"emails?|tickets?|signups?|sign[- ]ups?|forecast|predict|projected|growth|why)\b",
     "that dimension or analysis is not covered by the supported questions"),
]

# Per-intent: dimensions the template does not group or filter by.
FORBIDDEN_BY_INTENT = {
    "revenue": [r"\bregions?\b", r"\bplans?\b|\btiers?\b", *PLAN_PATTERNS.values(),
                r"\b(per|each|by)\s+(account|customer)", r"\baverage\b|\bmean\b|\bmedian\b",
                r"\bnet\b"],
    "refunds": [r"\bregions?\b", r"\bplans?\b|\btiers?\b", *PLAN_PATTERNS.values(), YEAR_RE],
    "stuck": [r"\bregions?\b", r"\bplans?\b|\btiers?\b", *PLAN_PATTERNS.values(), YEAR_RE],
    "churn": [r"\bregions?\b", YEAR_RE],
    "top_accounts": [r"\bregions?\b", *PLAN_PATTERNS.values(), YEAR_RE,
                     r"\b(lowest|least|bottom|worst|smallest)\b"],
    "region_mrr": [*PLAN_PATTERNS.values(), YEAR_RE,
                   r"\b(lowest|least|bottom|worst|smallest|total|sum|median)\b"],
}
REQUIRED_BY_INTENT = {"region_mrr": (r"\bregions?\b", "MRR is only broken down by region")}


def _normalize(q: str) -> str:
    q = q.lower().strip()
    q = re.sub(r"monthly recurring revenue", "mrr", q)
    q = re.sub(r"\s+", " ", q)
    return q


def _closest(q: str) -> str:
    words = set(re.findall(r"[a-z]+", q))
    best = max(TEMPLATES.values(),
               key=lambda t: len(words & set(re.findall(r"[a-z]+", t.canonical.lower()))))
    return best.canonical


def route(question: str) -> tuple[str, dict]:
    """Return (intent, params) or raise Declined."""
    if not question or not question.strip():
        raise Declined("empty question", TEMPLATES["revenue"].canonical)
    if len(question) > 500:
        raise Declined("question too long", TEMPLATES["revenue"].canonical)
    q = _normalize(question)

    intent = next((name for name, pat in INTENT_PATTERNS if re.search(pat, q)), None)
    if intent is None:
        raise Declined("no supported question matches", _closest(q))
    closest = TEMPLATES[intent].canonical

    for pat, why in UNSUPPORTED:
        if re.search(pat, q):
            raise Declined(why, closest)
    for pat in FORBIDDEN_BY_INTENT[intent]:
        if m := re.search(pat, q):
            raise Declined(f"'{m.group(0).strip()}' can't be applied to this question", closest)
    if intent in REQUIRED_BY_INTENT:
        pat, why = REQUIRED_BY_INTENT[intent]
        if not re.search(pat, q):
            raise Declined(why, closest)

    params: dict = {}
    if intent == "revenue":
        years = sorted(set(re.findall(YEAR_RE, q)))
        if len(years) > 1:
            raise Declined("only one calendar year at a time is supported", closest)
        params["year"] = int(years[0]) if years else None
    elif intent == "churn":
        plans = [p for p, pat in PLAN_PATTERNS.items() if re.search(pat, q)]
        params["plans"] = plans or list(PLAN_PATTERNS)
    elif intent == "top_accounts":
        m = re.search(TOP_N_RE, q)
        n = 5 if not m else (int(m.group(1)) if m.group(1).isdigit() else WORD_NUMS[m.group(1)])
        if not 1 <= n <= MAX_TOP_N:
            raise Declined(f"top N must be between 1 and {MAX_TOP_N}", closest)
        params["n"] = n
    elif intent == "stuck":
        has_p, has_f = bool(re.search(r"\bpending\b", q)), bool(re.search(r"\bfailed\b", q))
        params["statuses"] = (["pending"] if has_p and not has_f else
                              ["failed"] if has_f and not has_p else ["failed", "pending"])
    return intent, params


def _bind(intent: str, params: dict) -> list:
    return {
        "revenue": lambda: [params["year"], params["year"]],
        "churn": lambda: [params["plans"]],
        "top_accounts": lambda: [params["n"]],
        "stuck": lambda: [params["statuses"]],
    }.get(intent, lambda: [])()


def _render_sql(sql: str, binds: list) -> str:
    """SQL with bound values inlined — display only; execution uses real parameters."""
    out = sql
    for b in binds:
        lit = ("NULL" if b is None else
               "[" + ", ".join(f"'{x}'" for x in b) + "]" if isinstance(b, list) else str(b))
        out = out.replace("?", lit, 1)
    return out


# ---------------------------------------------------------------- answer text
def _usd(x) -> str:
    return f"${x:,.2f}"


def _summarize(intent: str, params: dict, rows: list[dict]):
    """Return (value, text, n_source_rows, source_label)."""
    if intent == "revenue":
        r = rows[0]
        scope = f"in {params['year']}" if params["year"] else "across all years"
        if not r["n_invoices"]:
            return None, f"No paid invoices found {scope}.", 0, "paid invoices"
        text = f"Recognized revenue (paid invoices) {scope}: {_usd(r['revenue_usd'])} USD."
        notes = []
        if r["n_ambiguous_date"]:
            notes.append(f"{r['n_ambiguous_date']} have ambiguous DD-MM/MM-DD dates")
        if r["n_future_date"]:
            notes.append(f"{r['n_future_date']} are dated after {config.AS_OF_DATE}")
        if notes:
            text += f"\nCaveat: of these {r['n_invoices']:,} invoices, " + "; ".join(notes) + "."
        return r["revenue_usd"], text, r["n_invoices"], "paid invoices (invoices_clean)"

    if intent == "region_mrr":
        top = rows[0]
        lines = [f"{top['region']} has the highest average MRR per active account: "
                 f"{_usd(top['avg_mrr_usd'])}."]
        lines += [f"  {r['region']:<6} {_usd(r['avg_mrr_usd']):>12}  ({r['n_accounts']:,} accounts)"
                  for r in rows]
        return top["region"], "\n".join(lines), sum(r["n_accounts"] for r in rows), \
            "active (non-churned) accounts"

    if intent == "refunds":
        r = rows[0]
        return r["refunds_usd"], (f"Refunds given back: {_usd(r['refunds_usd'] or 0)} USD "
                                  f"across {r['n_invoices']:,} refunded invoices."), \
            r["n_invoices"], "refunded invoices (invoices_clean)"

    if intent == "churn":
        value = {r["plan"]: r["churn_rate_pct"] for r in rows}
        lines = ["Churn rate by plan (share of accounts with churned = TRUE):"]
        lines += [f"  {r['plan']:<10} {r['churn_rate_pct']:>6.2f}%  "
                  f"({r['n_churned']:,} of {r['n_accounts']:,} accounts)" for r in rows]
        return value, "\n".join(lines), sum(r["n_accounts"] for r in rows), "accounts"

    if intent == "top_accounts":
        lines = [f"Top {params['n']} accounts by recognized revenue:"]
        for i, r in enumerate(rows, 1):
            csat = "n/a" if r["csat_score"] is None else r["csat_score"]
            flag = "  <-- LOW CSAT (<= 2)" if r["low_csat"] else ""
            lines.append(f"  {i}. {r['account_id']} {r['account_name']:<20} "
                         f"{_usd(r['revenue_usd']):>15}  CSAT {csat}{flag}")
        n_low = sum(r["low_csat"] for r in rows)
        lines.append(f"{n_low} of these have CSAT <= 2." if n_low
                     else "None of these have CSAT <= 2.")
        return [r["account_id"] for r in rows], "\n".join(lines), \
            sum(r["n_paid_invoices"] for r in rows), "paid invoices behind these accounts"

    if intent == "stuck":
        n = sum(r["n_invoices"] for r in rows)
        usd = round(sum(r["exposed_usd"] for r in rows), 2)
        lines = [f"{n:,} invoices are stuck in {'/'.join(params['statuses'])}, "
                 f"exposing {_usd(usd)} USD:"]
        lines += [f"  {r['status']:<8} {r['n_invoices']:>5,}  {_usd(r['exposed_usd']):>16}"
                  for r in rows]
        return {"count": n, "exposed_usd": usd}, "\n".join(lines), n, "invoices (invoices_clean)"
    raise AssertionError(intent)


# ---------------------------------------------------------------- public API
def connect() -> duckdb.DuckDBPyConnection:
    if not config.DB_PATH.exists():
        raise FileNotFoundError(f"{config.DB_PATH} not found — run `python -m app clean` first")
    return duckdb.connect(str(config.DB_PATH), read_only=True)


def answer(question: str, con: duckdb.DuckDBPyConnection | None = None) -> dict:
    """Return {intent, sql, params, value, rows, text, sources, declined}."""
    try:
        intent, params = route(question)
    except Declined as d:
        return {"intent": None, "sql": None, "params": {}, "value": None, "rows": [],
                "text": f"{DECLINE} ({d.reason}).\nClosest supported question: {d.closest}",
                "sources": None, "declined": True}

    tpl = TEMPLATES[intent]
    binds = _bind(intent, params)
    own = con is None
    con = con or connect()
    try:
        cur = con.execute(tpl.sql, binds)
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        if own:
            con.close()
    if not rows:
        value, text, n_src, label = None, "No matching rows.", 0, "rows"
    else:
        value, text, n_src, label = _summarize(intent, params, rows)
    return {"intent": intent, "sql": _render_sql(tpl.sql, binds), "params": params,
            "value": value, "rows": rows, "text": text,
            "sources": f"{n_src:,} {label}", "declined": False}


def main(question: str) -> int:
    try:
        res = answer(question)
    except FileNotFoundError as e:
        print(f"ERROR — {e}")
        return 1
    except duckdb.Error as e:
        print(f"ERROR — query failed: {e}")
        return 1
    print(res["text"])
    if res["declined"]:
        return 2
    print(f"\nQuery:\n{res['sql']}\n\nSources: {res['sources']}")
    return 0
