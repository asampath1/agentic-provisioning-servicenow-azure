"""Validate SKR Cloud catalog requests against the policy and recommend.

  python -m agents --out runs/latest                      # offline: the 40 synthetic requests
  python -m agents --live-prices --out runs/live-prices   # same, with today's Azure retail prices
  python -m agents --source servicenow --out runs/pdi     # live PDI, dry run (nothing written)
  python -m agents --source servicenow --write            # posts the work note + AI fields
  python -m agents --reasoner claude --out runs/claude    # Claude reads the free text for rule 7
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .connectors.local import LocalRequests
from .pricing import Prices
from .validation import ValidationAgent, prediction


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="runs/latest")
    ap.add_argument("--source", choices=["local", "servicenow"], default="local")
    ap.add_argument("--write", action="store_true", help="servicenow only: really post (default: dry run)")
    ap.add_argument("--live-prices", action="store_true", help="current Azure retail prices instead of the snapshot")
    ap.add_argument("--reasoner", choices=["heuristic", "claude"], default="heuristic",
                    help="who reads the free text for rule 7: policy regexes (default) or Claude (ANTHROPIC_API_KEY)")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    outbox = out / "work_notes.jsonl"
    outbox.unlink(missing_ok=True)
    if a.source == "servicenow":
        from .connectors.servicenow import ServiceNowRequests
        src = ServiceNowRequests(write=a.write)
    else:
        src = LocalRequests(outbox)
    prices = Prices.live() if a.live_prices else Prices.snapshot()
    pending = src.pending()
    reader = None
    if a.reasoner == "claude":
        from .text_reader import ClaudeReader
        reader = ClaudeReader()
        reader.prefetch(pending)
    agent = ValidationAgent(prices, reader=reader)
    results = []
    for req in pending:
        r = agent.run(req)
        cost = "" if r.monthly_cost_usd is None else f"{r.monthly_cost_usd:.2f}"
        src.write(req, {"u_ai_recommendation": r.decision, "u_ai_monthly_cost": cost,
                        "u_ai_changes": json.dumps(r.changes, sort_keys=True) if r.changes else ""}, r.note)
        results.append(r)
        if a.verbose:
            print(f"\n=== {r.key} {r.item}\n{r.note}")
    (out / "predictions.json").write_text(json.dumps([prediction(r) for r in results], indent=1))
    (out / "validations.json").write_text(json.dumps([vars(r) for r in results], indent=1))
    if a.source == "servicenow":
        with open(outbox, "w", encoding="utf-8") as f:
            for w in src.writes:
                f.write(json.dumps(w) + "\n")
        failed = [w for w in src.writes if a.write and not w["sent"]]
        if failed:
            print(f"! {len(failed)} write(s) failed, e.g. HTTP {failed[0].get('status')}")
    run = {"source": a.source, "written": bool(a.write and a.source == "servicenow"), "prices": prices.source,
           "reasoner": a.reasoner, "requests": len(results), "decisions": dict(Counter(r.decision for r in results))}
    if reader:
        run["claude"] = reader.report()
        c = run["claude"]
        print(f"Claude ({c['model']}): {c['read']} read in {c['calls']} call(s), {c['cached']} cached, "
              f"{c['input_tokens']} in / {c['output_tokens']} out tokens, about ${c['estimated_usd']}; "
              f"{c['rejected_quotes']} quote(s) rejected, {c['fallback_batches']} batch(es) fell back to regexes.")
    (out / "run.json").write_text(json.dumps(run, indent=1))
    print(f"Validated {len(results)} requests: {run['decisions']} (prices: {prices.source}).")
    print(f"Wrote {out}/ predictions.json, validations.json, work_notes.jsonl, run.json")


if __name__ == "__main__":
    main()
