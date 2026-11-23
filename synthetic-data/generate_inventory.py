#!/usr/bin/env python3
"""Synthetic sandbox inventory for the drift agent (P5 evaluation set), with drift seeded on purpose.

Writes data/inventory.json (what the agent sees: Azure resources + ServiceNow requests, as of a date) and
data/drift_truth.json (the expected problems per request / untagged resource; read ONLY by evaluation/score_drift.py).

Each scenario is written by hand from the definitions in agents/drift.py's docstring. Some are clean on purpose but
look suspicious (tag names in other letter case, a request id in lower case, the validation agent's size change
applied, an expired resource still inside its grace period, a deleted request): those catch false alarms.

  python3 generate_inventory.py          # seed 5, as of 2026-11-25
"""
import argparse
import json
import random
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).parent
AS_OF = date(2026, 11, 25)
GRACE = 2
USERS = ["synth.aditya.banerjee", "synth.ajay.fernandes", "synth.ajay.garcia", "synth.ajay.mishra"]
VM, ST = "Azure Linux test VM", "Azure storage account"


class Builder:
    def __init__(self, rng):
        self.rng, self.n = rng, 10100
        self.resources, self.requests, self.truth, self.elsewhere = [], [], [], []

    def number(self):
        self.n += self.rng.randint(1, 4)
        return f"RITM{self.n:07d}"

    def request(self, item, approval="approved", state="succeeded", expiry_state="", changes=None, **v):
        num = self.number()
        exp = v.pop("expires_on", (AS_OF + timedelta(days=self.rng.randint(3, 20))).isoformat())
        variables = {"purpose": "synthetic test workload", "expires_on": exp, **v}
        self.requests.append({"number": num, "item": item, "u_cloud_approval": approval,
                              "u_provisioning_state": state, "u_expiry_state": expiry_state,
                              "u_ai_changes": json.dumps(changes) if changes else "", "variables": variables})
        return num, exp

    def tags(self, rid, exp, key_case=str):
        return {key_case("request-id"): rid, key_case("expires-on"): exp, "owner": self.rng.choice(USERS),
                "managed-by": "skr-provisioning"}

    def vm(self, rid, exp, size="Standard_B2ats_v2", name=None, key_case=str, parts=("nic", "osdisk", "shutdown")):
        name = name or f"vm-test-{rid.lower()}"
        t = self.tags(rid, exp, key_case)
        self.resources.append({"name": name, "type": "Microsoft.Compute/virtualMachines", "tags": t, "size": size})
        extra = {"nic": (f"{name}-nic", "Microsoft.Network/networkInterfaces"),
                 "osdisk": (f"{name}-osdisk", "Microsoft.Compute/disks"),
                 "shutdown": (f"shutdown-computevm-{name}", "Microsoft.DevTestLab/schedules")}
        for p in parts:
            self.resources.append({"name": extra[p][0], "type": extra[p][1], "tags": dict(t)})

    def storage(self, rid, exp, sku="Standard_LRS", name=None, key_case=str):
        name = name or "stskr" + rid.lower()
        self.resources.append({"name": name, "type": "Microsoft.Storage/storageAccounts",
                               "tags": self.tags(rid, exp, key_case), "sku": sku})

    def expect(self, key, problems, scenario):
        self.truth.append({"key": key, "problems": sorted(problems), "scenario": scenario})


def build(seed: int) -> Builder:
    b = Builder(random.Random(seed))
    b.resources.append({"name": "vnet-skr-sandbox", "type": "Microsoft.Network/virtualNetworks",
                        "tags": {"request-id": "platform", "expires-on": "never"}})
    # clean: built by the worker, as approved
    for _ in range(6):
        num, exp = b.request(VM, vm_size="Standard_B2ats_v2")
        b.vm(num, exp)
        b.expect(num, [], "clean VM")
    for _ in range(4):
        num, exp = b.request(ST, redundancy="Standard_LRS")
        b.storage(num, exp)
        b.expect(num, [], "clean storage account")
    # clean but suspicious-looking
    num, exp = b.request(VM, vm_size="Standard_D4s_v5", changes={"vm_size": "Standard_B2als_v2"})
    b.vm(num, exp, size="Standard_B2als_v2")
    b.expect(num, [], "clean: the agent's size change was applied")
    num, exp = b.request(ST, redundancy="Standard_GRS", changes={"redundancy": "Standard_LRS"})
    b.storage(num, exp)
    b.expect(num, [], "clean: the agent's redundancy change was applied")
    num, exp = b.request(VM, vm_size="Standard_B2ats_v2")
    b.vm(num, exp, key_case=lambda k: k.title().replace("Id", "ID"))
    b.expect(num, [], "clean: tag names in other letter case")
    num, exp = b.request(ST, redundancy="Standard_LRS")
    b.storage(num.lower(), exp)
    b.expect(num, [], "clean: request id in lower case")
    num, exp = b.request(VM, vm_size="Standard_B2ats_v2", expiry_state="expired",
                         expires_on=(AS_OF - timedelta(days=GRACE - 1)).isoformat())
    b.vm(num, exp)
    b.expect(num, [], "clean: expired, still inside the grace period")
    num, _ = b.request(VM, vm_size="Standard_B2ats_v2", state="deleted", expiry_state="deleted",
                       expires_on=(AS_OF - timedelta(days=5)).isoformat())
    b.expect(num, [], "clean: deleted on expiry, nothing left")
    b.request(VM, approval="requested", state="", vm_size="Standard_B2ats_v2")    # pending, nothing built: clean
    b.request(ST, approval="rejected", state="", redundancy="Standard_LRS")        # rejected, nothing built: clean

    # drift
    b.resources.append({"name": "stadhoctest01", "type": "Microsoft.Storage/storageAccounts",
                        "tags": {"owner": "synth.ajay.garcia"}, "sku": "Standard_LRS"})
    b.expect("stadhoctest01", ["no_request_tag"], "storage account without any request tag")
    b.resources.append({"name": "vm-old-demo-osdisk", "type": "Microsoft.Compute/disks", "tags": {}})
    b.expect("vm-old-demo-osdisk", ["no_request_tag"], "leftover disk, no tags")
    exp = (AS_OF + timedelta(days=7)).isoformat()
    b.storage("RITM9999001", exp, name="stportaltest01")
    b.expect("RITM9999001", ["unknown_request"], "portal deployment with a made-up request id")
    b.vm("RITM9999002", exp, name="vm-portal-test")
    b.expect("RITM9999002", ["unknown_request"], "portal VM with a made-up request id")
    num, exp = b.request(VM, approval="requested", state="", vm_size="Standard_B2ats_v2")
    b.vm(num, exp)
    b.expect(num, ["not_approved"], "built from the portal before approval")
    num, exp = b.request(ST, approval="rejected", state="", redundancy="Standard_LRS")
    b.storage(num, exp)
    b.expect(num, ["not_approved"], "built from the portal although rejected")
    num, exp = b.request(VM, state="cancelled", vm_size="Standard_B2ats_v2")
    b.vm(num, exp)
    b.expect(num, ["request_closed"], "request cancelled, VM exists")
    num, exp = b.request(ST, state="deleted", expiry_state="deleted", redundancy="Standard_LRS")
    b.storage(num, exp)
    b.expect(num, ["request_closed"], "request says deleted, storage account still there")
    num, exp = b.request(VM, state="", vm_size="Standard_B2ats_v2")
    b.vm(num, exp)
    b.expect(num, ["outside_worker"], "approved, built from the portal: the worker would build it again")
    num, exp = b.request(VM, vm_size="Standard_B2ats_v2", expiry_state="expired",
                         expires_on=(AS_OF - timedelta(days=GRACE + 3)).isoformat())
    b.vm(num, exp)
    b.expect(num, ["expired"], "past expiry and grace, not deleted")
    num, exp = b.request(ST, redundancy="Standard_LRS", expiry_state="reminded",
                         expires_on=(AS_OF - timedelta(days=GRACE + 1)).isoformat())
    b.storage(num, exp)
    b.expect(num, ["expired"], "past expiry and grace, owner never asked")
    num, exp = b.request(VM, vm_size="Standard_B2ats_v2")
    b.vm(num, exp, size="Standard_B2als_v2")
    b.expect(num, ["differs_from_request"], "resized after the build")
    num, exp = b.request(VM, vm_size="Standard_D2s_v5", changes={"vm_size": "Standard_B2ats_v2"})
    b.vm(num, exp, size="Standard_B2als_v2")
    b.expect(num, ["differs_from_request"], "size neither requested nor approved")
    num, exp = b.request(ST, redundancy="Standard_LRS")
    b.storage(num, (date.fromisoformat(exp) + timedelta(days=30)).isoformat())
    b.expect(num, ["differs_from_request"], "expires-on tag extended by hand")
    num, exp = b.request(ST, redundancy="Standard_LRS")
    b.vm(num, exp)
    b.expect(num, ["differs_from_request"], "a VM carries a storage account request")
    num, exp = b.request(VM, vm_size="Standard_B2ats_v2")
    b.vm(num, "", parts=("nic",))
    b.expect(num, ["no_expiry_tag"], "VM without an expiry date (tag emptied)")
    num, _ = b.request(VM, vm_size="Standard_B2ats_v2")
    b.expect(num, ["missing"], "request says built, VM deleted by hand")
    num, _ = b.request(ST, redundancy="Standard_LRS", expiry_state="reminded")
    b.expect(num, ["missing"], "request says built, storage account gone")
    b.elsewhere.append({"name": "stskrportal0001", "type": "Microsoft.Storage/storageAccounts",
                        "tags": {"request-id": "RITM9999003", "expires-on": "2026-12-01"},
                        "resource_group": "rg-skr-prov-platform"})
    b.expect("stskrportal0001", ["outside_sandbox"], "portal deployment into the platform resource group")
    return b


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=5)
    a = ap.parse_args()
    b = build(a.seed)
    rng = random.Random(a.seed + 1)
    rng.shuffle(b.resources)
    rng.shuffle(b.requests)
    data = HERE / "data"
    (data / "inventory.json").write_text(json.dumps(
        {"as_of": AS_OF.isoformat(), "grace_days": GRACE, "resources": b.resources, "requests": b.requests,
         "elsewhere": b.elsewhere}, indent=1))
    (data / "drift_truth.json").write_text(json.dumps(b.truth, indent=1))
    drift = sum(bool(t["problems"]) for t in b.truth)
    print(f"{len(b.resources)} resources, {len(b.requests)} requests; {len(b.truth)} keys scored, {drift} with drift.")


if __name__ == "__main__":
    main()
