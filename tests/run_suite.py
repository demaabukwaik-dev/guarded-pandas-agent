"""
Runs the full case suite against the agent.

Not a pytest suite: each case calls the model, so this is slow and needs
the model available. Run it directly:

    python tests/run_suite.py

Labels:
    ok      → answerable, should answer     (scored)
    reject  → refusable, should be refused  (scored)
    edge    → borderline                    (observed only, not scored)
    vague   → ambiguous                     (observed only, not scored)
"""

import json
from pathlib import Path

from agent.loop import solve
from agent.data import load_data


CASES_FILE = Path(__file__).parent / "cases.json"


def _passed(result, label):
    """A string result means the agent rejected the request."""
    rejected = isinstance(result, str)
    if label == "ok":
        return not rejected
    if label == "reject":
        return rejected
    return None   # edge / vague, not scored


def run():
    df = load_data()
    cases = json.loads(CASES_FILE.read_text())

    totals = {"ok": [0, 0], "reject": [0, 0]}   # label -> [passed, scored]
    crashes = []

    for group, items in cases.items():
        print(f"\n=== {group.upper()} ===")

        for c in items:
            try:
                result = solve(c["q"], df, verbose=False)
            except Exception as e:
                # A crash is a bug, not a refusal: count it as a failure
                # and keep going so one case cannot stop the whole run.
                result = None
                crashes.append((c["q"], f"{type(e).__name__}: {e}"))
                ok = False if c["label"] in totals else None
            else:
                ok = _passed(result, c["label"])

            mark = {True: "ok", False: "XX", None: "--"}[ok]
            print(f"  [{mark}] {c['q'][:55]}")

            if ok is not None:
                totals[c["label"]][0] += ok
                totals[c["label"]][1] += 1

    a_pass, a_all = totals["ok"]
    r_pass, r_all = totals["reject"]
    print(f"\n{'=' * 40}")
    print(f"Answerable: {a_pass}/{a_all}")
    print(f"Refusable:  {r_pass}/{r_all}")

    if crashes:
        print(f"\n{len(crashes)} crash(es):")
        for q, err in crashes:
            print(f"  {q[:50]}  ->  {err[:80]}")


if __name__ == "__main__":
    run()