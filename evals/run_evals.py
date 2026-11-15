"""Eval harness — specs/evals.md, expected values in evals/expected.json (do not edit).

Run from the repo root after `python -m app clean`:
    python evals/run_evals.py

One line per case: id, expected, got, PASS / FAIL / XFAIL / XPASS.
Exit code 1 only if a case FAILs (XFAIL / XPASS do not fail the run).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.query import answer, connect  # noqa: E402

EXPECTED = json.loads((ROOT / "evals" / "expected.json").read_text())

# specs/evals.md tolerances
USD_TOL = 0.01
PCT_TOL = 0.1

# The six stakeholder questions, verbatim from data/BUSINESS_CONTEXT.md.
CORE_QUESTIONS = {
    "core_q1": "What was our total recognized revenue in USD for paid invoices in 2024?",
    "core_q2": "Which region has the highest average MRR per account?",
    "core_q3": "How much have we given back in refunds?",
    "core_q4": "What's the churn rate among Enterprise accounts vs Starter?",
    "core_q5": "List the top 5 accounts by revenue, and flag any with CSAT <= 2.",
    "core_q6": "How many invoices are stuck in pending/failed and what's the exposed $?",
}


def close(a, b, tol) -> bool:
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol + 1e-9


def short(x, n=70) -> str:
    s = x if isinstance(x, str) else json.dumps(x, default=str)
    return s if len(s) <= n else s[: n - 3] + "..."


# Each check: (res) -> (got, ok). Expected value is shown alongside.
def core_cases(c):
    return [
        ("core_q1", CORE_QUESTIONS["core_q1"], c["q1_revenue_paid_2024_usd"],
         lambda r: (r["value"], close(r["value"], c["q1_revenue_paid_2024_usd"], USD_TOL))),
        ("core_q2", CORE_QUESTIONS["core_q2"],
         {"region": c["q2_region"], "avg_mrr": c["q2_avg_mrr_by_region"]},
         lambda r: (lambda by: ({"region": r["value"], "avg_mrr": by},
                                r["value"] == c["q2_region"]
                                and by.keys() == c["q2_avg_mrr_by_region"].keys()
                                and all(close(by[k], v, USD_TOL)
                                        for k, v in c["q2_avg_mrr_by_region"].items())))
         ({row["region"]: row["avg_mrr_usd"] for row in r["rows"]})),
        ("core_q3", CORE_QUESTIONS["core_q3"],
         {"usd": c["q3_refunds_usd"], "rows": c["q3_refund_rows"]},
         lambda r: ({"usd": r["value"], "rows": r["rows"][0]["n_invoices"] if r["rows"] else None},
                    close(r["value"], c["q3_refunds_usd"], USD_TOL)
                    and bool(r["rows"]) and r["rows"][0]["n_invoices"] == c["q3_refund_rows"])),
        ("core_q4", CORE_QUESTIONS["core_q4"], c["q4_churn_pct"],
         lambda r: (r["value"], isinstance(r["value"], dict)
                    and r["value"].keys() == c["q4_churn_pct"].keys()
                    and all(close(r["value"][k], v, PCT_TOL) for k, v in c["q4_churn_pct"].items()))),
        ("core_q5", CORE_QUESTIONS["core_q5"],
         {"ids": c["q5_top5_account_ids"], "top1_usd": c["q5_top1_revenue_usd"]},
         lambda r: ({"ids": r["value"], "top1_usd": r["rows"][0]["revenue_usd"] if r["rows"] else None},
                    r["value"] == c["q5_top5_account_ids"] and bool(r["rows"])
                    and close(r["rows"][0]["revenue_usd"], c["q5_top1_revenue_usd"], USD_TOL))),
        ("core_q6", CORE_QUESTIONS["core_q6"],
         {"count": c["q6_stuck_count"], "usd": c["q6_exposed_usd"]},
         lambda r: ({"count": (r["value"] or {}).get("count"),
                     "usd": (r["value"] or {}).get("exposed_usd")},
                    isinstance(r["value"], dict) and r["value"]["count"] == c["q6_stuck_count"]
                    and close(r["value"]["exposed_usd"], c["q6_exposed_usd"], USD_TOL))),
    ]


def paraphrase_cases(p):
    cases = []
    for i, (q, exp) in enumerate(p.items(), 1):
        if isinstance(exp, list):  # account ids: exact
            check = (lambda e: lambda r: (r["value"], r["value"] == e))(exp)
        elif "churn" in q.lower():  # single-plan churn %, 0.1 pp
            check = (lambda e: lambda r: (
                (lambda v: (v, close(v, e, PCT_TOL)))(
                    next(iter(r["value"].values())) if isinstance(r["value"], dict)
                    and len(r["value"]) == 1 else r["value"])))(exp)
        else:  # USD
            check = (lambda e: lambda r: (r["value"], close(r["value"], e, USD_TOL)))(exp)
        cases.append((f"paraphrase_{i}", q, exp, check))
    return cases


def flag_case(f):
    acc = f["flagged_account"]

    def check(r):
        flagged = [row["account_id"] for row in r["rows"] if row.get("low_csat")]
        line = next((ln for ln in r["text"].splitlines() if acc in ln), "")
        return {"flagged": flagged}, acc in flagged and "LOW CSAT" in line

    return ("flag_check", f["question"], {"flagged": [acc]}, check)


def guardrail_case(q):
    return ("guardrail", q, "declined",
            lambda r: ("declined" if r["declined"] else f"answered {short(r['value'], 30)}",
                       r["declined"]))


def run() -> int:
    try:
        connect().close()
    except FileNotFoundError as e:
        print(f"ERROR — {e}")
        return 1

    cases = (core_cases(EXPECTED["core"]) + paraphrase_cases(EXPECTED["paraphrase"])
             + [flag_case(EXPECTED["flag_check"]), guardrail_case(EXPECTED["guardrail_decline"])])
    xf = EXPECTED["expected_fail"]

    results = []
    for cid, q, exp, check in cases:
        try:
            r = answer(q)
            if r["declined"] and cid != "guardrail":
                got, ok = "declined", False
            else:
                got, ok = check(r)
        except Exception as e:  # a crash is a FAIL, not a stopped run
            got, ok = f"error: {type(e).__name__}: {e}", False
        results.append((cid, exp, got, "PASS" if ok else "FAIL"))

    # Expected fail: XPASS only if the router answers Gaming.
    try:
        r = answer(xf["question"])
        got = "declined" if r["declined"] else r["value"]
        status = "XPASS" if (not r["declined"] and r["value"] == xf["answer"]) else "XFAIL"
    except Exception as e:
        got, status = f"error: {type(e).__name__}: {e}", "XFAIL"
    results.append(("expected_fail", {"answer": xf["answer"], "usd": xf["usd"]}, got, status))

    w = max(len(c[0]) for c in results)
    print(f"{'id':<{w}}  {'status':<6}  expected  ->  got")
    for cid, exp, got, status in results:
        print(f"{cid:<{w}}  {status:<6}  {short(exp)}  ->  {short(got)}")

    counts = {s: sum(1 for *_, st in results if st == s) for s in ("PASS", "FAIL", "XFAIL", "XPASS")}
    print("\n" + "  ".join(f"{k} {v}" for k, v in counts.items()) + f"  (total {len(results)})")
    if counts["XPASS"]:
        print("XPASS: the expected-fail case now passes — update specs/evals.md.")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(run())
