"""Live source for the drift agent: what is in the sandbox resource group, read with the Azure CLI (your az login;
read-only). VM sizes and storage SKUs come from their own list commands, since the generic list has no properties."""
from __future__ import annotations

import json
import subprocess


def _az(*args: str) -> list:
    r = subprocess.run(["az", *args, "-o", "json"], capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        raise SystemExit(f"az {' '.join(args[:3])} failed: {r.stderr.strip()[:300]}")
    return json.loads(r.stdout or "[]")


def sandbox_resources(rg: str) -> list[dict]:
    sizes = {v["name"].lower(): v["hardwareProfile"]["vmSize"] for v in _az("vm", "list", "-g", rg)}
    out = []
    for r in _az("resource", "list", "-g", rg):
        res = {"name": r["name"], "type": r["type"], "tags": r.get("tags") or {}}
        if r["type"].lower() == "microsoft.compute/virtualmachines":
            res["size"] = sizes.get(r["name"].lower())
        elif r["type"].lower() == "microsoft.storage/storageaccounts":
            res["sku"] = (r.get("sku") or {}).get("name")
        out.append(res)
    return out
