"""The committed request set is what the generator produces (rerun generate_requests.py after any change)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "synthetic-data"))
import generate_requests  # noqa: E402


def test_committed_data_is_fresh():
    req, gt = generate_requests.build(11)
    assert json.loads((ROOT / "synthetic-data/data/requests.json").read_text()) == req
    assert json.loads((ROOT / "synthetic-data/data/ground_truth.json").read_text()) == gt


def test_shape():
    req, gt = generate_requests.build(11)
    assert len(req) == 40 and sum(t["messy"] for t in gt) == 4
    assert {t["decision"] for t in gt} == {"approve", "approve_with_changes", "need_info", "reject"}
    assert all("ground" not in json.dumps(r) for r in req)          # nothing answer-like leaks into requests
