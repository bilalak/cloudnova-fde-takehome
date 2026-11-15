# Prompt log (trimmed)

How the build was directed with Claude Code. User prompts are quoted as given;
the responses are summarized to the decisions that mattered. Specs and
`CLAUDE.md` were committed before this session's code (`7415583`).

---

### 1. Orientation
> analyze the current folder

Claude read the assignment, briefing, specs and `CLAUDE.md`, then re-counted the
spec's numbers from the raw CSV (5,125 rows, 82 exact duplicates, 43 duplicate
invoice_ids, 3,815 accounts, every category value covered by the §3 mappings).
All matched. It listed the missing deliverables and a build order.

### 2. Cleaning pipeline
> Read CLAUDE.md, specs/schema.md and data/BUSINESS_CONTEXT.md. Implement
> app/__init__.py, app/config.py and app/clean.py (pandas -> DuckDB) following
> specs/schema.md exactly, in the order of §2. … enforce every gate in §9: on
> failure print which gate and the actual value, exit non-zero, write nothing. …
> Do not invent rules; ask if the spec is unclear. Then run it and show me the report.

Decision points:
- **Spec conflict found:** §2 said "write outputs, run gates", §9 said "fail →
  write nothing". Resolved by gating in memory before any write, plus an atomic
  DB swap. Now recorded in schema.md §2.6.
- **Data trap caught:** region `NA` would be read by pandas as missing. Read with
  `keep_default_na=False`. Now recorded in schema.md §1.
- **"Ask if unclear" fired:** the first run stopped itself — 27 invoice_ids tied on
  status precedence *and* date, which §6 doesn't break. Inspection showed the tied
  rows differ only in raw status spelling and are identical after normalization.
  The guard was narrowed to accept only identical ties. Now in schema.md §6.
- **Spec count reconciled:** "151 of 239" dash dates is a raw-row count; after
  dedup it is 146 of 233 (87 ambiguous). Now noted in schema.md §5.
- **Failure path tested:** a truncated input failed 5 gates, exited 1, left the
  DB byte-identical. The test also exposed a crash on paths outside the repo; fixed.

### 3. Query router
> Implement app/query.py per specs/api.md and add `ask` to app/__main__.py.
> Intents and templates, using the metric definitions in specs/schema.md §10:
> revenue (optional year; default all years), region_mrr, refunds, churn (one or
> more plans), top_accounts (N, default 5, with a low_csat flag for csat_score <= 2),
> stuck (pending/failed count and exposed USD). Extract parameters with regex.
> Decline when no intent matches, or when the question asks for something the
> templates can't express (another currency, relative dates like "last quarter").
> Open DuckDB read-only. No dependencies beyond pandas and duckdb.

Decision points:
- Strict over helpful: a year on any intent other than revenue is declined rather
  than silently ignored; a dimension a template doesn't group by (industry,
  region on revenue) is declined. This is what makes the expected-fail case decline.
- Bound SQL parameters; the printed SQL shows the bound values for audit.
- Verified the read-only connection rejects a `DELETE`.
- Tested 6 core questions, 6 paraphrases and 12 decline cases by hand.
- Decline rules now written out in specs/api.md.

### 4. Eval harness
> Implement evals/run_evals.py from specs/evals.md and evals/expected.json. Call
> app.query.answer() directly. Print one line per case: id, expected, got,
> PASS / FAIL / XFAIL / XPASS. … Exit 1 only on FAIL. Do not change expected.json.

Result: 11 PASS, 1 XFAIL. The harness was checked by perturbing two expected values
in memory (both turned FAIL, exit 1); `expected.json` untouched.
Claude flagged that the core expected values equal the app's saved output in
`evals/eval1–6.md`, so they don't by themselves prove independence; an
independent recomputation from the raw CSV is listed under next steps.

### 5. README
> Write README.md for a finance stakeholder, 3-minute read, … Claim nothing the
> code doesn't do.

Every number in the README was re-queried from the DB and every behavior claim
checked against the code. The CI box in the diagram was confirmed against the
committed workflow before being drawn as built. First draft was 1,580 words;
cut to ~1,200 to fit the time budget.

### 6. Gap check
> Are we done
> Give me what is missing. Add it to readme. Update specs if needed. …

Claude listed the gaps against the assignment's deliverables: this log, spec drift
(four rules decided during the build were only in code), `.env.example`, a
`docs/architecture.*` file, and pushing to GitHub. The first four were added; specs
were updated to match the code (no behavior changed).

---

## Where the human overrode or steered
- Wrote the specs and `CLAUDE.md` first and kept prompts pinned to them.
- Required "ask if unclear" — which caught the near-duplicate tie instead of a guess.
- Supplied `evals/expected.json` and forbade editing it.
- Added the CI workflow.
- Asked for a stakeholder README that claims nothing the code doesn't do.
