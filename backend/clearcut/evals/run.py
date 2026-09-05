"""Run the eval against a fixture and print a report a human reads."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from clearcut.agents.adjudicate import AdjudicationAgent
from clearcut.agents.breakdown import BreakdownAgent
from clearcut.agents.research import ResearchAgent
from clearcut.agents.triage import TriageAgent
from clearcut.core.consistency import reconcile
from clearcut.core.screenplay import load_screenplay, parse_screenplay
from clearcut.evals.harness import load_truth, render, score

ROOT = Path(__file__).resolve().parents[3]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("fixture", nargs="?", default="the_long_odds_v1")
    ap.add_argument("--breakdown-only", action="store_true",
                    help="score recall and depiction without spending research or rulings")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    script_path = ROOT / "assets" / "screenplays" / f"{args.fixture}.txt"
    truth_path = ROOT / "assets" / "screenplays" / f"{args.fixture}.groundtruth.json"
    if not truth_path.exists():
        print(f"No ground truth for '{args.fixture}'", file=sys.stderr)
        return 2

    quiet = (lambda e: None) if args.json else (lambda e: print(f"  [{e.agent}] {e.message}", flush=True))

    script = parse_screenplay(load_screenplay(script_path))
    items = BreakdownAgent(emit=quiet).run(script)

    rulings = None
    if not args.breakdown_only:
        decisions = TriageAgent(emit=quiet).run(items)
        evidence = ResearchAgent(emit=quiet, deep_verify=False).run(decisions)
        adj = AdjudicationAgent(emit=quiet).run(decisions, evidence)
        # Same reconciliation the pipeline applies. An eval that skips a
        # production step is measuring something nobody ships.
        for change in reconcile(items, adj):
            quiet_msg = (
                f"reconciled {change.value}: {change.was.value} -> {change.now.value}"
            )
            if not args.json:
                print(f"  [adjudicate] {quiet_msg}", flush=True)
        rulings = {k: v.verdict for k, v in adj.items()}

    res = score(load_truth(truth_path), items, rulings)
    if args.json:
        print(json.dumps(res.to_dict(), indent=2))
    else:
        print()
        print(render(res))

    # Recall is the gate. Anything below it is a product that is not safe to sell.
    return 0 if res.recall == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
