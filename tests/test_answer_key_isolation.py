"""The agents never read the answer key; only evaluation/score.py may."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_agents_do_not_mention_the_answer_key():
    for p in (ROOT / "agents").rglob("*.py"):
        text = p.read_text()
        assert "ground_truth" not in text, p
        assert "generate_requests" not in text, p
