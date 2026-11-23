"""Drift agent rules on small hand-made inventories (the scored set is synthetic-data/data/inventory.json)."""
from datetime import date

from agents.drift import DriftAgent, plain_report, report

TODAY = date(2026, 11, 25)


def req(num="RITM0010005", item="Azure Linux test VM", approval="approved", state="succeeded", **v):
    v.setdefault("expires_on", "2026-11-30")
    v.setdefault("vm_size", "Standard_B2ats_v2")
    return {"number": num, "item": item, "u_cloud_approval": approval, "u_provisioning_state": state,
            "u_expiry_state": "", "u_ai_changes": "", "variables": v}


def vm(rid="RITM0010005", exp="2026-11-30", size="Standard_B2ats_v2", name="vm-test-ritm0010005"):
    t = {"request-id": rid, "expires-on": exp}
    return [{"name": name, "type": "Microsoft.Compute/virtualMachines", "tags": t, "size": size},
            {"name": name + "-nic", "type": "Microsoft.Network/networkInterfaces", "tags": dict(t)}]


def codes(resources, requests, today=TODAY):
    return {f.key: sorted(f.problems) for f in DriftAgent(today).run(resources, requests)}


def test_clean_and_platform_resources_are_not_drift():
    vnet = {"name": "vnet", "type": "Microsoft.Network/virtualNetworks", "tags": {"request-id": "platform"}}
    assert codes(vm() + [vnet], [req()]) == {}


def test_one_finding_per_request_not_per_resource():
    got = codes(vm(rid="RITM9999001"), [])
    assert got == {"RITM9999001": ["unknown_request"]}


def test_untagged_resources_are_reported_one_by_one():
    loose = [{"name": n, "type": "Microsoft.Compute/disks", "tags": {}} for n in ("d1", "d2")]
    assert codes(loose, []) == {"d1": ["no_request_tag"], "d2": ["no_request_tag"]}


def test_agent_changes_count_as_approved():
    r = req(vm_size="Standard_D4s_v5")
    r["u_ai_changes"] = '{"vm_size": "Standard_B2als_v2"}'
    assert codes(vm(size="Standard_B2als_v2"), [r]) == {}
    assert codes(vm(size="Standard_D4s_v5"), [r]) == {"RITM0010005": ["differs_from_request"]}


def test_grace_period_and_expiry_mismatch():
    r = req(expires_on="2026-11-23")
    assert codes(vm(exp="2026-11-23"), [r]) == {}                               # 23 + 2 days = 25: still grace
    assert codes(vm(exp="2026-11-23"), [r], date(2026, 11, 26)) == {"RITM0010005": ["expired"]}
    assert codes(vm(exp="2026-12-20"), [r]) == {"RITM0010005": ["differs_from_request"]}


def test_request_states():
    assert codes(vm(), [req(approval="requested", state="")]) == {"RITM0010005": ["not_approved"]}
    assert codes(vm(), [req(state="cancelled")]) == {"RITM0010005": ["request_closed"]}
    assert codes(vm(), [req(state="")]) == {"RITM0010005": ["outside_worker"]}
    assert codes([], [req()]) == {"RITM0010005": ["missing"]}
    deleted = req(state="deleted")
    deleted["u_expiry_state"] = "deleted"
    assert codes([], [deleted]) == {}


def test_tagged_resources_outside_the_sandbox():
    stray = {"name": "stskrdrift9999001", "type": "Microsoft.Storage/storageAccounts",
             "tags": {"request-id": "RITM9999001"}, "resource_group": "rg-skr-prov-platform"}
    assert codes(vm(), [req()]) == {}
    got = {f.key: sorted(f.problems) for f in DriftAgent(TODAY).run(vm(), [req()], [stray])}
    assert got == {"stskrdrift9999001": ["outside_sandbox"]}


def test_report_lists_findings():
    text = report(DriftAgent(TODAY).run(vm(rid="RITM9999001"), []), 2, 0, TODAY, "test")
    assert "RITM9999001" in text and "unknown_request" in text and "nothing was changed" in text


def test_plain_report_for_servicenow_has_no_markdown():
    text = plain_report(DriftAgent(TODAY).run(vm(rid="RITM9999001"), []), 2, 0, TODAY, "test")
    assert "RITM9999001" in text and "unknown_request" in text and "|" not in text and "**" not in text
