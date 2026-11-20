"""Claude reads a request's free text for policy rule 7 (production use or real data).

Used with ``python -m agents --reasoner claude``. Claude must return an exact quote from the request as evidence; a
quote that is not in the request is rejected (and counted), so every flag can be checked. Results are cached on disk
by (model, text hash), so a rerun costs nothing. API errors fall back to the policy regexes and are reported.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

DEFINITION = ("production_or_real_data: the request shows the resource will be used for production (real users or "
              "customers, live traffic, business operations, standing in for a production system), or will hold "
              "real company, customer, employee or personal data rather than synthetic or test data.")
SYSTEM = f"""You check requests for a cloud TEST sandbox that only allows test workloads with synthetic or test \
data. For each request decide whether its text shows this problem:

{DEFINITION}

Rules:
- If it does, return an exact quote (copied character for character, 3-25 words) from the request text that shows \
it. Otherwise return an empty string.
- Judge only what the text states. Testing WITH generated, sample, dummy, mock or synthetic data is fine.
- Mentioning a production system that is being tested against, reproduced or practised for is not enough on its \
own; the resource itself must serve production or hold real data."""
PRICE_PER_MTOK = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0)}   # USD, Nov 2026


def request_text(req: dict) -> str:
    v = req["variables"]
    return "\n".join(f"{k}: {v.get(k, '')}" for k in ("purpose", "justification", "data_classification") if k in v)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().strip(".\"'").lower()


class ClaudeReader:
    name = "claude"

    def __init__(self, model: str | None = None, effort: str = "medium", batch_size: int = 10,
                 cache: str | Path = "runs/claude-cache.json", client=None):
        if client is None:
            import anthropic  # lazy: offline runs do not need the SDK

            if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
                raise SystemExit("ANTHROPIC_API_KEY is not set in this terminal: export it first.")
            client = anthropic.Anthropic()
        self.client = client
        self.model = model or os.environ.get("PROV_CLAUDE_MODEL", "claude-opus-5-5")
        self.effort, self.batch_size = effort, batch_size
        self.cache_path = Path(cache)
        self.cache: dict = json.loads(self.cache_path.read_text()) if self.cache_path.exists() else {}
        self.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cached": 0, "read": 0}
        self.rejected: list[dict] = []
        self.errors: list[str] = []

    def _key(self, req: dict) -> str:
        return self.model + ":" + hashlib.sha256(request_text(req).encode()).hexdigest()[:20]

    def prefetch(self, reqs: list[dict]) -> None:
        """Read every request not yet in the cache, in batches (one call per batch)."""
        todo = [r for r in reqs if self._key(r) not in self.cache]
        self.usage["cached"] += len(reqs) - len(todo)
        for s in range(0, len(todo), self.batch_size):
            batch = todo[s:s + self.batch_size]
            try:
                self.cache.update(self._call(batch))
                self.usage["read"] += len(batch)
            except Exception as e:      # noqa: BLE001 - any API failure: fall back to the regexes for this batch
                self.errors.append(f"{type(e).__name__}: {str(e)[:200]}")
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self.cache, indent=1, sort_keys=True))

    def _call(self, batch: list[dict]) -> dict:
        ids = [f"R{i + 1}" for i in range(len(batch))]
        prompt = "Check these requests.\n\n" + "\n\n".join(f"### {i}\n{request_text(r)}" for i, r in zip(ids, batch))
        schema = {"type": "object", "additionalProperties": False, "required": ["requests"], "properties": {
            "requests": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["id", "production_or_real_data"],
                "properties": {"id": {"type": "string", "enum": ids},
                               "production_or_real_data": {"type": "string"}}}}}}
        resp = self.client.messages.create(
            model=self.model, max_tokens=8000, system=SYSTEM, messages=[{"role": "user", "content": prompt}],
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}})
        self.usage["calls"] += 1
        self.usage["input_tokens"] += resp.usage.input_tokens
        self.usage["output_tokens"] += resp.usage.output_tokens
        if resp.stop_reason != "end_turn":
            raise RuntimeError(f"stop_reason={resp.stop_reason}")
        by_id = {d["id"]: d for d in json.loads(next(b.text for b in resp.content if b.type == "text"))["requests"]}
        out = {}
        for i, r in zip(ids, batch):
            q = (by_id.get(i, {}).get("production_or_real_data") or "").strip()
            found = {}
            if q:
                if len(_norm(q)) >= 3 and _norm(q) in _norm(request_text(r)):
                    found["production_or_real_data"] = q
                else:
                    self.rejected.append({"request": r["key"], "quote": q})
            out[self._key(r)] = found
        return out

    def read(self, req: dict) -> dict | None:
        """Cached result, or None (caller falls back to the regexes) when Claude could not be reached."""
        return self.cache.get(self._key(req))

    def report(self) -> dict:
        pin, pout = PRICE_PER_MTOK.get(self.model, (0.0, 0.0))
        usd = (self.usage["input_tokens"] * pin + self.usage["output_tokens"] * pout) / 1e6
        return dict(self.usage, model=self.model, estimated_usd=round(usd, 4), rejected_quotes=len(self.rejected),
                    errors=self.errors[:3], fallback_batches=len(self.errors))
