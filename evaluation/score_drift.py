"""Score a drift run against the answer key. The only code that reads synthetic-data/data/drift_truth.json.

  python -m evaluation.score_drift runs/drift        # writes drift_scores.json + drift_report.md into the run folder
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

TRUTH = Path(__file__).resolve().parents[1] / "synthetic-data/data/drift_truth.json"


def score(preds: list[dict], truth: list[dict]) -> dict:
    gt = {t["key"]: set(t["problems"]) for t in truth}
    pred = {p["key"]: set(p["problems"]) for p in preds}
    keys = sorted(set(gt) | set(pred))
    flagged_tp = sum(bool(gt.get(k)) and bool(pred.get(k)) for k in keys)
    flagged_fp = sum(not gt.get(k) and bool(pred.get(k)) for k in keys)
    flagged_fn = sum(bool(gt.get(k)) and not pred.get(k) for k in keys)
    tp = sum(len(gt.get(k, set()) & pred.get(k, set())) for k in keys)
    fp = sum(len(pred.get(k, set()) - gt.get(k, set())) for k in keys)
    fn = sum(len(gt.get(k, set()) - pred.get(k, set())) for k in keys)
    exact = sum(gt.get(k, set()) == pred.get(k, set()) for k in gt)
    clean = [k for k in gt if not gt[k]]
    return {
        "keys": len(gt), "with_drift": sum(bool(v) for v in gt.values()),
        "drift_precision": round(flagged_tp / (flagged_tp + flagged_fp), 3) if flagged_tp + flagged_fp else None,
        "drift_recall": round(flagged_tp / (flagged_tp + flagged_fn), 3) if flagged_tp + flagged_fn else None,
        "missed_drift": flagged_fn, "false_alarms": flagged_fp,
        "clean_left_alone": f"{sum(not pred.get(k) for k in clean)}/{len(clean)}",
        "problem_precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "problem_recall": round(tp / (tp + fn), 3) if tp + fn else None,
        "exact": f"{exact}/{len(gt)}",
    }


def report(s: dict) -> str:
    rows = [("**Missed drift** (drift not reported)", f"**{s['missed_drift']} of {s['with_drift']}**"),
            ("False alarms (clean, but reported)", str(s["false_alarms"])),
            ("Drift found: precision / recall", f"{s['drift_precision']} / {s['drift_recall']}"),
            ("Clean requests left alone (including the look-alikes)", s["clean_left_alone"]),
            ("Problem codes: precision / recall", f"{s['problem_precision']} / {s['problem_recall']}"),
            ("Exactly the right problems", s["exact"])]
    out = [f"# Drift scores ({s['keys']} requests / untagged resources)", "", "| Metric | Result |", "|---|---|"]
    return "\n".join(out + [f"| {a} | {b} |" for a, b in rows]) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", help="run folder or predictions.json")
    ap.add_argument("--truth", default=str(TRUTH))
    a = ap.parse_args()
    p = Path(a.run)
    preds_path = p / "predictions.json" if p.is_dir() else p
    s = score(json.loads(preds_path.read_text()), json.loads(Path(a.truth).read_text()))
    (preds_path.parent / "drift_scores.json").write_text(json.dumps(s, indent=1))
    text = report(s)
    (preds_path.parent / "drift_report.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
