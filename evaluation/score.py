"""Score a validation run against the answer key. The only code that reads synthetic-data/data/ground_truth.json.

  python -m evaluation.score runs/latest        # writes scores.json + report.md into the run folder
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

TRUTH = Path(__file__).resolve().parents[1] / "synthetic-data/data/ground_truth.json"
DECISIONS = ["approve", "approve_with_changes", "need_info", "reject"]
BLOCKING = {"need_info", "reject"}


def f1(p, r):
    return 0.0 if p + r == 0 else 2 * p * r / (p + r)


def score(preds: list[dict], truth: list[dict]) -> dict:
    gt = {t["key"]: t for t in truth}
    pred = {p["key"]: p for p in preds}
    keys = [k for k in gt if k in pred]
    conf = Counter((gt[k]["decision"], pred[k]["decision"]) for k in keys)
    correct = sum(gt[k]["decision"] == pred[k]["decision"] for k in keys)
    per_class = {}
    for d in DECISIONS:
        tp = conf[(d, d)]
        fp = sum(conf[(t, d)] for t in DECISIONS if t != d)
        fn = sum(conf[(d, p)] for p in DECISIONS if p != d)
        per_class[d] = f1(tp / (tp + fp) if tp + fp else 0, tp / (tp + fn) if tp + fn else 0)
    wrong_approvals = [k for k in keys if gt[k]["decision"] in BLOCKING and pred[k]["decision"] not in BLOCKING]
    over_blocked = [k for k in keys if gt[k]["decision"] not in BLOCKING and pred[k]["decision"] in BLOCKING]
    tp = fp = fn = 0
    for k in keys:
        t, p = set(gt[k]["problems"]), set(pred[k]["problems"])
        tp, fp, fn = tp + len(t & p), fp + len(p - t), fn + len(t - p)
    awc = [k for k in keys if gt[k]["decision"] == "approve_with_changes"]
    changes_ok = sum(pred[k]["decision"] == "approve_with_changes" and pred[k]["changes"] == gt[k]["changes"]
                     for k in awc)
    errs = [abs(pred[k]["monthly_cost_usd"] - gt[k]["monthly_cost_usd"]) / gt[k]["monthly_cost_usd"]
            for k in keys if pred[k].get("monthly_cost_usd") is not None and gt[k]["monthly_cost_usd"]]
    messy = [k for k in keys if gt[k]["messy"]]
    return {
        "requests": len(keys), "missing": len(gt) - len(keys),
        "wrong_approvals": len(wrong_approvals), "should_block": sum(gt[k]["decision"] in BLOCKING for k in keys),
        "wrong_approval_keys": wrong_approvals,
        "over_blocked": len(over_blocked),
        "decision_accuracy": round(correct / len(keys), 3), "decision_macro_f1": round(sum(per_class.values()) / 4, 3),
        "problems_precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "problems_recall": round(tp / (tp + fn), 3) if tp + fn else None,
        "changes_exact": f"{changes_ok}/{len(awc)}",
        "cost_within_10pct": f"{sum(e <= 0.10 for e in errs)}/{len(errs)}",
        "cost_mean_abs_pct_error": round(100 * sum(errs) / len(errs), 2) if errs else None,
        "messy_correct": f"{sum(gt[k]['decision'] == pred[k]['decision'] for k in messy)}/{len(messy)}",
        "confusion": {t: {p: conf[(t, p)] for p in DECISIONS} for t in DECISIONS},
    }


def report(s: dict) -> str:
    rows = [
        ("**Wrong approvals** (should be rejected or sent back, recommended for approval)",
         f"**{s['wrong_approvals']} of {s['should_block']}**"),
        ("Over-blocking (fine or fixable, but rejected or sent back)", str(s["over_blocked"])),
        ("Decision accuracy / macro F1", f"{s['decision_accuracy']:.0%} / {s['decision_macro_f1']}"),
        ("Problems found (precision / recall)", f"{s['problems_precision']} / {s['problems_recall']}"),
        ("Approve-with-changes: exact changes", s["changes_exact"]),
        ("Cost estimate within 10%", f"{s['cost_within_10pct']} (mean error {s['cost_mean_abs_pct_error']}%)"),
        ("Messy subset (production or real data in other words): decision right", s["messy_correct"]),
    ]
    out = [f"# Validation scores ({s['requests']} requests)", "", "| Metric | Result |", "|---|---|"]
    out += [f"| {a} | {b} |" for a, b in rows]
    out += ["", "Decision confusion (rows = truth, columns = predicted):", "",
            "| truth \\ predicted | " + " | ".join(DECISIONS) + " |", "|---" * (len(DECISIONS) + 1) + "|"]
    out += [f"| {t} | " + " | ".join(str(s["confusion"][t][p]) for p in DECISIONS) + " |" for t in DECISIONS]
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", help="run folder or predictions.json")
    ap.add_argument("--truth", default=str(TRUTH))
    ap.add_argument("--out", help="folder for scores.json + report.md (default: the run folder)")
    a = ap.parse_args()
    p = Path(a.run)
    preds_path = p / "predictions.json" if p.is_dir() else p
    s = score(json.loads(preds_path.read_text()), json.loads(Path(a.truth).read_text()))
    out = Path(a.out) if a.out else preds_path.parent
    out.mkdir(parents=True, exist_ok=True)
    (out / "scores.json").write_text(json.dumps(s, indent=1))
    text = report(s)
    (out / "report.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
