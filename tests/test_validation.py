"""Policy rules, one by one (examples are not taken from the evaluation set)."""
import base64

import pytest

from agents.pricing import Prices
from agents.validation import ValidationAgent, check_ssh_key

KEY = "ssh-ed25519 " + base64.b64encode(b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00 " + bytes(32)).decode() + " me@pc"
agent = ValidationAgent(Prices.snapshot())


def vm(**v):
    base = {"purpose": "Try a new nginx config with dummy pages.", "expires_on": "2026-12-01",
            "vm_size": "Standard_B2ats_v2", "ssh_public_key": KEY, "justification": ""}
    return {"key": "t", "item": "Azure Linux test VM", "opened_at": "2026-11-20 10:00:00", "variables": {**base, **v}}


def st(**v):
    base = {"purpose": "Hold fake invoices for the parser tests.", "expires_on": "2026-12-01",
            "redundancy": "Standard_LRS", "data_classification": "synthetic", "justification": ""}
    return {"key": "t", "item": "Azure storage account", "opened_at": "2026-11-20 10:00:00", "variables": {**base, **v}}


@pytest.mark.parametrize("req,decision,problems", [
    (vm(), "approve", []),
    (vm(vm_size="Standard_D4s_v5"), "approve_with_changes", ["size_not_allowed"]),
    (vm(expires_on="2027-01-15"), "approve_with_changes", ["expiry_too_long"]),
    (vm(expires_on="2026-11-19"), "need_info", ["expiry_invalid"]),
    (vm(expires_on=""), "need_info", ["expiry_invalid"]),
    (vm(purpose="need vm"), "need_info", ["purpose_vague"]),
    (vm(ssh_public_key="my key"), "need_info", ["ssh_key_invalid"]),
    (vm(ssh_public_key="-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----"), "reject", ["private_key"]),
    (vm(purpose="Serve production traffic for the API for a week."), "reject", ["production_or_real_data"]),
    (vm(purpose="vm", vm_size="Standard_D2s_v5"), "need_info", ["purpose_vague", "size_not_allowed"]),
    (st(), "approve", []),
    (st(redundancy="Standard_GRS"), "approve_with_changes", ["redundancy_not_allowed"]),
    (st(data_classification="confidential"), "reject", ["data_not_allowed"]),
    (st(purpose="Export of customer data for the quarterly review."), "reject", ["production_or_real_data"]),
])
def test_rules(req, decision, problems):
    r = agent.run(req)
    assert (r.decision, sorted(r.problems)) == (decision, problems)


def test_changes_and_costs():
    r = agent.run(vm(vm_size="Standard_D4s_v5", expires_on="2027-02-01"))
    assert r.changes == {"vm_size": "Standard_B2als_v2", "expires_on": "2026-12-20"}
    assert r.monthly_cost_usd == round(0.202 * 730 + 1.6896, 2) and r.recommended_cost_usd < r.monthly_cost_usd
    assert "$149.15" in r.note and "with the changes" in r.note
    assert agent.run(st(redundancy="Standard_ZRS")).monthly_cost_usd == 2.5


def test_ssh_key_checks():
    assert check_ssh_key(KEY) == (None, "")
    assert check_ssh_key("ssh-rsa !!!notbase64")[0] == "ssh_key_invalid"
    assert check_ssh_key("ssh-rsa " + KEY.split()[1])[0] == "ssh_key_invalid"      # type does not match the data
    assert check_ssh_key("PuTTY-User-Key-File-3: ssh-ed25519")[0] == "private_key"


def test_note_is_a_recommendation_only():
    note = agent.run(vm(ssh_public_key="-----BEGIN OPENSSH PRIVATE KEY-----\nx\n-----END OPENSSH PRIVATE KEY-----")).note
    assert note.startswith("[AI request validation - recommendation only") and "Rule 5" in note and "exposed" in note
