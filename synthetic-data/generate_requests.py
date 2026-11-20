#!/usr/bin/env python3
"""Synthetic SKR Cloud catalog requests with known right answers (P3 evaluation set).

Writes data/requests.json (what the agent sees: request + catalog variables) and data/ground_truth.json (the
expected decision, problems, changes and cost; read ONLY by evaluation/score.py).

Every answer follows from docs/request-policy.md. The "messy" requests break rule 7 (production use or real data)
in wording that avoids the policy's own words: that is where reading the text matters.

  python3 generate_requests.py            # seed 11, requests dated 2026-11-16..20
"""
import argparse
import base64
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).parent
PRICES = json.loads((HERE / "data/prices.json").read_text())
ALLOWED_SIZES = ["Standard_B2ats_v2", "Standard_B2als_v2"]
BIG_SIZES = ["Standard_D2s_v5", "Standard_D4s_v5"]
USERS = ["synth.aditya.banerjee", "synth.ajay.fernandes", "synth.ajay.garcia", "synth.ajay.mishra",
         "synth.ajay.muller"]

GOOD_PURPOSE_VM = [
    "Load test of the orders API before the December release, with generated orders only.",
    "Try the new log shipping agent configuration on a throwaway Ubuntu box.",
    "Reproduce the nginx 502 bug from INC0010598 with a copy of the config.",
    "Build and test the internal CLI tool packaging for Ubuntu 22.04.",
    "Practice the disk-full runbook steps before the on-call rotation.",
    "Benchmark two JSON parsers with synthetic catalogue data.",
    "Test the Ansible role for the new monitoring agent against a clean VM.",
    "Developer sandbox for the payments retry library, unit and integration tests with mocks.",
    "Evaluate a Python 3.13 upgrade of the batch scripts using sample files.",
    "Run the training lab for new joiners on Linux basics.",
    "Dry run of the certificate renewal script against a self-signed test certificate.",
    "Try the open-source feature flag service with dummy flags.",
]
GOOD_PURPOSE_ST = [
    "Store generated test fixtures for the catalogue import job.",
    "Scratch space for the data pipeline unit tests (synthetic parquet files).",
    "Hold build artefacts for the CLI tool test pipeline.",
    "Static test site for the accessibility checker, dummy pages only.",
    "Landing zone to test the blob lifecycle policy with fake log files.",
    "Test the backup export format with a synthetic sample database dump.",
    "Sample images for the thumbnail service load test (stock test images).",
]
VAGUE = ["test", "testing", "for work", "VM needed", "dev", "as discussed", "project"]
# rule 7 in the policy's own words (phrasing A)
PROD_A = ["Host the production checkout service until the new cluster is ready.",
          "Run live traffic for the loyalty API for two weeks."]
DATA_A = ["Keep an export of real customer data for analysis.",
          "Store personal data from the HR system for a report."]
# rule 7 without the policy's words (phrasing B: the messy subset)
PROD_B = ["Shoppers will hit this box for the Black Friday checkout until the scale set is fixed.",
          "Our storefront points its DNS here while the main web tier is rebuilt next week.",
          "Point the mobile app's order-tracking calls here during the sale weekend."]
DATA_B = ["Analysts need last month's orders table with buyer names, addresses and phone numbers.",
          "Copy of the payroll extract so finance can reconcile salaries offline.",
          "Upload the support team's call recordings with members to test transcription."]
GOOD_JUSTIFICATION = "The load test needs 4 vCPUs to reach 2,000 requests per second; measured on a B2als."


def ssh_public(rng):
    blob = base64.b64encode(b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00 " + rng.randbytes(32)).decode()
    return f"ssh-ed25519 {blob} {rng.choice(USERS).split('.', 1)[1]}@laptop"


def ssh_private(rng):
    body = base64.b64encode(b"openssh-key-v1\x00" + rng.randbytes(180)).decode()
    lines = [body[i:i + 70] for i in range(0, len(body), 70)]
    return "-----BEGIN OPENSSH PRIVATE KEY-----\n" + "\n".join(lines) + "\n-----END OPENSSH PRIVATE KEY-----"


def ssh_bad(rng):
    return rng.choice(["my laptop key", "ssh-ed25519", "AAAAC3NzaC1lZDI1NTE5AAAAIBr9 (copied from email)",
                       "see attachment"])


def vm_cost(size):
    return round(PRICES["vm_hourly"][size] * 730 + PRICES["os_disk_monthly"]["S4 LRS"], 2)


def st_cost(sku):
    return round(PRICES["blob_hot_gb_month"][sku] * 100, 2)


SEVERITY = {"reject": 3, "need_info": 2, "approve_with_changes": 1, "approve": 0}
OUTCOME = {"size_not_allowed": "approve_with_changes", "redundancy_not_allowed": "approve_with_changes",
           "expiry_too_long": "approve_with_changes", "expiry_invalid": "need_info", "purpose_vague": "need_info",
           "ssh_key_invalid": "need_info", "private_key": "reject", "data_not_allowed": "reject",
           "production_or_real_data": "reject"}


def build(seed: int):
    rng = random.Random(seed)
    base = datetime(2026, 11, 16, 9, 0)
    requests, truth = [], []
    n = 0

    def add(item, problems, purpose=None, size=None, sku=None, data="synthetic", expiry_days=None,
            key=None, justification="", messy=False):
        nonlocal n
        n += 1
        opened = base + timedelta(hours=rng.randrange(0, 4 * 24 + 8), minutes=rng.choice([0, 15, 30, 45]))
        days = expiry_days if expiry_days is not None else rng.randint(3, 30)
        expires = "" if days == "missing" else (opened.date() + timedelta(days=days)).isoformat()
        v = {"purpose": purpose if purpose is not None else
             rng.choice(GOOD_PURPOSE_VM if item == "vm" else GOOD_PURPOSE_ST),
             "expires_on": expires, "justification": justification}
        changes = {}
        if item == "vm":
            v["vm_size"] = size or rng.choice(ALLOWED_SIZES)
            v["ssh_public_key"] = key if key is not None else ssh_public(rng)
            cost = vm_cost(v["vm_size"])
            if "size_not_allowed" in problems:
                changes["vm_size"] = "Standard_B2als_v2"
        else:
            v["redundancy"] = sku or "Standard_LRS"
            v["data_classification"] = data
            cost = st_cost(v["redundancy"])
            if "redundancy_not_allowed" in problems:
                changes["redundancy"] = "Standard_LRS"
        if "expiry_too_long" in problems:
            changes["expires_on"] = (opened.date() + timedelta(days=30)).isoformat()
        decision = max((OUTCOME[p] for p in problems), key=SEVERITY.get, default="approve")
        key_ = f"req:{n:03d}"
        requests.append({"key": key_, "item": "Azure Linux test VM" if item == "vm" else "Azure storage account",
                         "requested_for": rng.choice(USERS), "opened_at": opened.strftime("%Y-%m-%d %H:%M:%S"),
                         "variables": v})
        truth.append({"key": key_, "decision": decision, "problems": sorted(problems),
                      "changes": changes if decision == "approve_with_changes" else {},
                      "monthly_cost_usd": cost, "messy": messy})

    pick = lambda seq: seq.pop(rng.randrange(len(seq)))      # noqa: E731  (each text used once)
    good_vm, good_st = GOOD_PURPOSE_VM[:], GOOD_PURPOSE_ST[:]
    # ---- VMs (26)
    for _ in range(9):
        add("vm", set(), purpose=pick(good_vm))
    for size in BIG_SIZES:
        add("vm", {"size_not_allowed"}, purpose=pick(good_vm), size=size, justification=GOOD_JUSTIFICATION)
    add("vm", {"size_not_allowed"}, size="Standard_D4s_v5", purpose="Faster builds for the CLI tool test pipeline.")
    add("vm", {"size_not_allowed", "expiry_too_long"}, size="Standard_D2s_v5", expiry_days=60,
        purpose="Long-running soak test of the queue consumer with generated messages.")
    add("vm", {"expiry_too_long"}, expiry_days=45, purpose="Shared Linux box for the platform team's test scripts.")
    add("vm", {"expiry_too_long"}, expiry_days=90, purpose="Keep a reference VM to compare kernel updates against.")
    add("vm", {"expiry_invalid"}, expiry_days=-2, purpose="Retest the cron job fix from last sprint on Ubuntu.")
    for p in VAGUE[:2]:
        add("vm", {"purpose_vague"}, purpose=p)
    add("vm", {"purpose_vague", "size_not_allowed"}, purpose=VAGUE[2], size="Standard_D4s_v5")
    for _ in range(2):
        add("vm", {"ssh_key_invalid"}, key=ssh_bad(rng))
    add("vm", {"private_key"}, key=ssh_private(rng))
    add("vm", {"private_key"}, key=ssh_private(rng), size="Standard_B2als_v2")
    add("vm", {"production_or_real_data"}, purpose=PROD_A[0])
    for p in PROD_B[:2]:
        add("vm", {"production_or_real_data"}, purpose=p, messy=True)
    # ---- storage accounts (14)
    for _ in range(5):
        add("st", set(), purpose=pick(good_st))
    add("st", {"redundancy_not_allowed"}, sku="Standard_GRS", justification="Want a copy in another region.")
    add("st", {"redundancy_not_allowed"}, sku="Standard_ZRS")
    add("st", {"data_not_allowed"}, data="internal", purpose="Shared folder for the team's planning spreadsheets.")
    add("st", {"data_not_allowed"}, data="confidential", purpose="Archive of signed supplier contracts.")
    add("st", {"production_or_real_data"}, purpose=DATA_A[0])
    for p in DATA_B[:2]:
        add("st", {"production_or_real_data"}, purpose=p, messy=True)
    add("st", {"purpose_vague"}, purpose=VAGUE[3])
    add("st", {"expiry_too_long"}, expiry_days=120, purpose=pick(good_st))
    order = list(range(len(requests)))
    rng.shuffle(order)
    keys = {requests[i]["key"]: f"req:{j + 1:03d}" for j, i in enumerate(order)}
    requests = [dict(requests[i], key=keys[requests[i]["key"]]) for i in order]
    truth = sorted([dict(t, key=keys[t["key"]]) for t in truth], key=lambda t: t["key"])
    return requests, truth


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=11)
    a = ap.parse_args()
    req, gt = build(a.seed)
    (HERE / "data/requests.json").write_text(json.dumps(req, indent=1) + "\n")
    (HERE / "data/ground_truth.json").write_text(json.dumps(gt, indent=1) + "\n")
    from collections import Counter
    print(f"{len(req)} requests: {dict(Counter(t['decision'] for t in gt))}; messy {sum(t['messy'] for t in gt)}")


if __name__ == "__main__":
    main()
