"""Offline checks: the ServiceNow catalog definition matches the Template Specs and the approval scripts."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "servicenow"))

from catalog_definition import (APPROVER_GROUP, BUSINESS_RULES, CATEGORY, ITEMS, RITM_FIELDS,  # noqa: E402
                                SELECT, script)


def allowed(bicep: str, param: str) -> list[str]:
    text = (ROOT / "infra/templates" / bicep).read_text()
    m = re.search(r"@allowed\(\[([^\]]*)\]\)\s*param " + param, text)
    assert m, f"{param} has no @allowed list in {bicep}"
    return re.findall(r"'([^']+)'", m.group(1))


def choices(item_name: str, var: str) -> list[str]:
    item = next(i for i in ITEMS if i["name"] == item_name)
    return [c for c, _ in next(v for v in item["variables"] if v["name"] == var)["choices"]]


def test_template_spec_sizes_are_offered_and_default_is_allowed():
    sizes = allowed("vm-linux-test.bicep", "vmSize")
    assert set(sizes) <= set(choices("Azure Linux test VM", "vm_size"))
    vm = next(i for i in ITEMS if i["name"] == "Azure Linux test VM")
    assert next(v for v in vm["variables"] if v["name"] == "vm_size")["default_value"] in sizes
    skus = allowed("storage-account.bicep", "skuName")
    assert set(skus) <= set(choices("Azure storage account", "redundancy"))


def test_disallowed_options_are_marked_for_justification():
    sizes = set(allowed("vm-linux-test.bicep", "vmSize"))
    vm = next(i for i in ITEMS if i["name"] == "Azure Linux test VM")
    for value, text in next(v for v in vm["variables"] if v["name"] == "vm_size")["choices"]:
        assert ("justification" in text) == (value not in sizes), value


def test_items_have_template_specs_and_clean_variables():
    for item in ITEMS:
        assert (ROOT / "infra/templates" / f"{item['template_spec']}.bicep").exists()
        names = [v["name"] for v in item["variables"]]
        assert len(names) == len(set(names)), item["name"]
        assert {"purpose", "expires_on"} <= set(names)
        for v in item["variables"]:
            assert re.fullmatch(r"[a-z][a-z0-9_]*", v["name"])
            if v["type"] == SELECT:
                assert v.get("choices") and v.get("default_value") in [c for c, _ in v["choices"]]


def test_scripts_use_the_defined_names():
    for rule in BUSINESS_RULES:
        js = script(rule)
        assert "SYNTH-SKR-PROV" in js
        if rule["collection"] == "sc_req_item" or "category" in js:
            assert f"'{CATEGORY['title']}'" in js, rule["name"]
    assert f"'{APPROVER_GROUP['name']}'" in script(BUSINESS_RULES[1])


def test_approval_rule_only_acts_once_and_never_builds():
    js = script(BUSINESS_RULES[2])
    assert "!= 'requested'" in js                 # a second decision is ignored
    for rule in BUSINESS_RULES:                   # ServiceNow never calls Azure (pull model)
        code = script(rule).replace(CATEGORY["title"], "")
        for word in ("azure", "deploy", "http", "restmessage"):
            assert word not in code.lower(), (rule["name"], word)


def test_no_secrets_in_definition_or_scripts():
    text = (ROOT / "servicenow/catalog_definition.py").read_text() + "".join(script(r) for r in BUSINESS_RULES)
    assert not re.search(r"password|secret|BEGIN [A-Z ]*PRIVATE KEY", text, re.I)
    assert all(len(e) <= 40 and e.startswith("u_") for e, _, _ in RITM_FIELDS)


def test_only_a_decision_opens_the_gate():
    by_file = {r["script_file"]: script(r) for r in BUSINESS_RULES}
    assigns = re.compile(r"\w\.u_cloud_approval\s*=[^=]")
    setters = [f for f, js in by_file.items() if assigns.search(js)]
    assert sorted(setters) == ["approval_decided.js", "ritm_request_approval.js"]
    assert "u_cloud_approval = 'requested'" in by_file["ritm_request_approval.js"]   # starts closed
    hold = by_file["ritm_hold_approval.js"]
    assert "current.approval = gate" in hold and not assigns.search(hold)               # never opens it
    assert any(e == "u_cloud_approval" for e, _, _ in RITM_FIELDS)


def test_separation_of_duties():
    create = script(next(r for r in BUSINESS_RULES if r["script_file"] == "ritm_create_approvals.js"))
    decide = script(next(r for r in BUSINESS_RULES if r["script_file"] == "approval_decided.js"))
    for js in (create, decide):
        assert "requested_for" in js and "opened_by" in js
    assert "No eligible approver" in create          # never silently left without an approver
    # the self-approval check comes before the gate is opened
    assert decide.index("cannot approve their own request") < decide.index("ritm.u_cloud_approval = decision")
