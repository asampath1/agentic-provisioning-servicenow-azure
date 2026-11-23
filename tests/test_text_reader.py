"""The Claude reader with a stand-in client (no API key, no network)."""
import json
from types import SimpleNamespace

from agents.pricing import Prices
from agents.text_reader import ClaudeReader
from agents.validation import ValidationAgent
from tests.test_validation import vm


class Fake:
    def __init__(self, invent=False, fail=False):
        self.calls, self.invent, self.fail = 0, invent, fail

    def create(self, **kw):
        self.calls += 1
        if self.fail:
            raise RuntimeError("boom")
        ids = kw["output_config"]["format"]["schema"]["properties"]["requests"]["items"]["properties"]["id"]["enum"]
        prompt = kw["messages"][0]["content"]
        out = []
        for i in ids:
            purpose = prompt.split(f"### {i}\n", 1)[1].split("\n", 1)[0].removeprefix("purpose: ")
            hit = "shoppers" in purpose.lower()
            q = ("not in the text at all" if self.invent else " ".join(purpose.split()[:5])) if hit else ""
            out.append({"id": i, "production_or_real_data": q})
        return SimpleNamespace(stop_reason="end_turn", usage=SimpleNamespace(input_tokens=500, output_tokens=50),
                               content=[SimpleNamespace(type="text", text=json.dumps({"requests": out}))])


def reader(tmp_path, **kw):
    return ClaudeReader(client=SimpleNamespace(messages=Fake(**kw)), cache=tmp_path / "c.json")


def test_claude_flags_with_a_checked_quote(tmp_path):
    r = reader(tmp_path)
    reqs = [dict(vm(purpose="Shoppers will use this box for checkout during the sale."), key="x"), dict(vm(), key="y")]
    r.prefetch(reqs)
    agent = ValidationAgent(Prices.snapshot(), reader=r)
    a, b = agent.run(reqs[0]), agent.run(reqs[1])
    assert a.decision == "reject" and a.evidence == {"production_or_real_data": "Shoppers will use this box"}
    assert b.decision == "approve" and r.client.messages.calls == 1
    r.prefetch(reqs)                                            # cached: no second call
    assert r.client.messages.calls == 1 and r.report()["cached"] == 2


def test_invented_quotes_are_rejected(tmp_path):
    r = reader(tmp_path, invent=True)
    req = dict(vm(purpose="Shoppers will use this box for checkout during the sale."), key="x")
    r.prefetch([req])
    assert r.read(req) == {} and r.rejected


def test_api_failure_falls_back_to_regexes(tmp_path):
    r = reader(tmp_path, fail=True)
    req = dict(vm(purpose="Serve production traffic for the API for a week."), key="x")
    r.prefetch([req])
    assert r.read(req) is None and r.errors
    assert ValidationAgent(Prices.snapshot(), reader=r).run(req).decision == "reject"     # regexes still apply


def test_a_rejected_key_stops_the_run(tmp_path):
    import pytest

    from agents.text_reader import ClaudeReader

    class AuthenticationError(Exception):
        pass

    class Client:
        class messages:
            @staticmethod
            def create(**kw):
                raise AuthenticationError("401 Invalid bearer token")

    reader = ClaudeReader(client=Client(), cache=tmp_path / "c.json")
    req = {"key": "R1", "variables": {"purpose": "x", "justification": "y"}}
    with pytest.raises(SystemExit):
        reader.prefetch([req])
