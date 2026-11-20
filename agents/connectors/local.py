"""Offline source: the synthetic requests (synthetic-data/data/requests.json). Writes go to a local outbox."""
from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "synthetic-data/data"


class LocalRequests:
    def __init__(self, outbox: Path | None = None):
        self.outbox = outbox

    def pending(self) -> list[dict]:
        return json.loads((DATA / "requests.json").read_text())

    def write(self, req: dict, fields: dict, note: str) -> None:
        if self.outbox:
            with open(self.outbox, "a", encoding="utf-8") as f:
                f.write(json.dumps({"request": req["key"], "fields": fields, "work_note": note}) + "\n")
