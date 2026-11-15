# Eval spec
Expected values were computed independently of the pipeline. Tolerance: $0.01,
0.1 percentage points; counts and IDs exact.
Core (6): the stakeholder questions in BUSINESS_CONTEXT.md.
Paraphrase (3): reworded/parameterized questions, to show the router is not a
lookup of six literal strings.
Flag check (1): CSAT <= 2 flag renders. No top-5 account has low CSAT, so the case
asks for the top 15, where ACC-5925 must be flagged.
Runner: `python evals/run_evals.py` calls app.query.answer() directly and prints
PASS / FAIL / XFAIL / XPASS per case. The expected-fail case is XFAIL if the router
declines or answers wrongly, XPASS if it answers Gaming. Exit 1 only on FAIL.
Guardrail (1): unanswerable question is declined, not answered.
Expected fail (1): "Which industry brings in the most paid revenue?" — answerable
from the data (Gaming) but outside the template set, so the router declines.
