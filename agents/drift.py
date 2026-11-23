"""Drift agent: compares what is in the Azure sandbox with the approved requests in ServiceNow. Report only.

Every resource in the sandbox should belong to an approved, built request (tag `request-id`) and carry its expiry
(tag `expires-on`). Resources are grouped by request; each group (or each untagged resource) gets the problems below.
The agent never deletes anything: drift is for a person to look at (design decision 3).

  no_request_tag        no request-id tag (the platform's own resources are tagged request-id=platform)
  no_expiry_tag         no valid expires-on date
  unknown_request       the request-id is not a ServiceNow request in the SKR Cloud category
  not_approved          the request was never approved (still waiting, or rejected)
  request_closed        the request was cancelled, blocked or already deleted, but the resource exists
  outside_worker        approved, but not built by the worker: the worker would build it a second time
  expired               past expires-on plus the grace period: the expiry worker should have deleted it
  differs_from_request  size, redundancy, item type or expiry differ from the approved request (after the agent's
                        changes)
  missing               the request says built, but nothing in the sandbox carries its request-id
  outside_sandbox       a resource with a request-id tag outside the sandbox resource group, where the sandbox
                        policies do not apply (e.g. deployed from the portal into the Template Spec's own group)

  python -m agents.drift --out runs/drift                     # offline: the synthetic inventory (evaluation set)
  python -m agents.drift --source live --out runs/drift-live  # az CLI login + SN_* variables; report only
  python -m agents.drift --source live --write                # also opens (or updates) one ServiceNow incident
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import date, timedelta

PRIMARY = {"microsoft.compute/virtualmachines": "VM", "microsoft.storage/storageaccounts": "storage account"}
CLOSED = {"cancelled", "blocked", "deleted"}
SEVERITY_ORDER = ["unknown_request", "not_approved", "request_closed", "no_request_tag", "outside_worker", "expired",
                  "differs_from_request", "no_expiry_tag", "missing", "outside_sandbox"]


@dataclass
class Finding:
    key: str                                   # request-id, or the resource name when it has none
    resources: list = field(default_factory=list)
    problems: dict = field(default_factory=dict)   # code -> explanation


def tag(tags: dict | None, name: str) -> str:
    for k, v in (tags or {}).items():
        if k.strip().lower() == name:
            return str(v).strip()
    return ""


def parse_day(s: str) -> date | None:
    try:
        return date.fromisoformat((s or "").strip()[:10])
    except ValueError:
        return None


def final_values(req: dict) -> dict:
    """The request as approved: catalog variables with the validation agent's changes applied."""
    v = dict(req.get("variables") or {})
    try:
        v.update(json.loads(req.get("u_ai_changes") or "{}"))
    except ValueError:
        pass
    return v


class DriftAgent:
    name = "drift"

    def __init__(self, today: date, grace_days: int = 2):
        self.today, self.grace_days = today, grace_days

    def run(self, resources: list[dict], requests: list[dict], elsewhere: list[dict] | None = None) -> list[Finding]:
        reqs = {r["number"].strip().upper(): r for r in requests}
        groups: dict[str, list[dict]] = {}
        out: list[Finding] = []
        for res in resources:
            rid = tag(res.get("tags"), "request-id").upper()
            if rid == "PLATFORM":
                continue
            if not rid:
                out.append(Finding(res["name"], [res["name"]], {
                    "no_request_tag": f"{res['type'].split('/')[-1]} {res['name']} has no request-id tag"}))
                continue
            groups.setdefault(rid, []).append(res)

        for rid, members in sorted(groups.items()):
            f = Finding(rid, sorted(m["name"] for m in members))
            req = reqs.get(rid)
            primary = next((m for m in members if m["type"].lower() in PRIMARY), None)
            exps = {tag(m.get("tags"), "expires-on") for m in members}
            exp = parse_day(tag((primary or members[0]).get("tags"), "expires-on"))
            if not exp:
                f.problems["no_expiry_tag"] = "no valid expires-on tag"
            if req is None:
                f.problems["unknown_request"] = f"{rid} is not an SKR Cloud request in ServiceNow"
            elif req.get("u_cloud_approval") != "approved":
                f.problems["not_approved"] = f"{rid} is '{req.get('u_cloud_approval') or 'not approved'}'"
            elif (req.get("u_provisioning_state") or "") in CLOSED:
                f.problems["request_closed"] = f"{rid} is '{req['u_provisioning_state']}' but its resources exist"
            elif not req.get("u_provisioning_state"):
                f.problems["outside_worker"] = (f"{rid} is approved but was not built by the worker, which would "
                                                f"build it again")
            if exp and self.today > exp + timedelta(days=self.grace_days):
                f.problems["expired"] = (f"expired {exp.isoformat()}, grace ended "
                                         f"{(exp + timedelta(days=self.grace_days)).isoformat()}")
            if req is not None and not f.problems.keys() & {"not_approved", "request_closed"}:
                diffs = self._differences(req, primary, exp, exps)
                if diffs:
                    f.problems["differs_from_request"] = "; ".join(diffs)
            if f.problems:
                out.append(f)

        present = set(groups)
        for rid, req in sorted(reqs.items()):
            if req.get("u_provisioning_state") == "succeeded" and req.get("u_expiry_state") != "deleted" \
                    and rid not in present:
                out.append(Finding(rid, [], {"missing": f"{rid} says built, but nothing in the sandbox carries it"}))
        for res in elsewhere or []:
            rid = tag(res.get("tags"), "request-id") or "(no request id)"
            out.append(Finding(res["name"], [res["name"]], {"outside_sandbox": (
                f"{res['type'].split('/')[-1]} {res['name']} (request {rid}) is in {res.get('resource_group')}, "
                f"outside the sandbox")}))
        return out

    @staticmethod
    def _differences(req: dict, primary: dict | None, exp: date | None, exps: set) -> list[str]:
        v, diffs = final_values(req), []
        item = req.get("item", "")
        if primary is not None:
            kind = PRIMARY[primary["type"].lower()]
            if (kind == "VM") != ("VM" in item):
                diffs.append(f"a {kind} carries a request for '{item}'")
            elif kind == "VM" and v.get("vm_size") and primary.get("size") != v["vm_size"]:
                diffs.append(f"size {primary.get('size')}, approved {v['vm_size']}")
            elif kind == "storage account" and v.get("redundancy") and primary.get("sku") != v["redundancy"]:
                diffs.append(f"redundancy {primary.get('sku')}, approved {v['redundancy']}")
        want = parse_day(v.get("expires_on", ""))
        if exp and want and exp != want:
            diffs.append(f"expires-on {exp.isoformat()}, request says {want.isoformat()}")
        if len(exps) > 1:
            diffs.append("its resources carry different expires-on tags: " + ", ".join(sorted(exps)))
        return diffs


def prediction(f: Finding) -> dict:
    return {"key": f.key, "problems": sorted(f.problems)}


def report(findings: list[Finding], n_resources: int, n_requests: int, today: date, source: str) -> str:
    lines = [f"# Sandbox drift report ({today.isoformat()})", "",
             f"Source: {source}. {n_resources} resource(s), {n_requests} SKR Cloud request(s). "
             f"Report only: nothing was changed.", ""]
    if not findings:
        return "\n".join(lines + ["No drift: every resource belongs to an approved, built request.", ""])
    lines += [f"{len(findings)} finding(s):", "", "| Request / resource | Resources | Problems |", "|---|---|---|"]
    for f in sorted(findings, key=lambda f: min(SEVERITY_ORDER.index(c) for c in f.problems)):
        probs = "<br>".join(f"**{c}**: {why}" for c, why in f.problems.items())
        lines.append(f"| {f.key} | {', '.join(f.resources) or '(none)'} | {probs} |")
    return "\n".join(lines) + "\n"


def plain_report(findings: list[Finding], n_resources: int, n_requests: int, today: date, source: str) -> str:
    """The same report as plain text, for ServiceNow fields (which show Markdown as typed)."""
    lines = [f"Sandbox drift report ({today.isoformat()})",
             f"Source: {source}. {n_resources} resource(s), {n_requests} SKR Cloud request(s). Report only: nothing "
             f"was changed.", ""]
    if not findings:
        return "\n".join(lines + ["No drift."])
    lines.append(f"{len(findings)} finding(s):")
    for f in sorted(findings, key=lambda f: min(SEVERITY_ORDER.index(c) for c in f.problems)):
        lines.append(f"- {f.key} ({', '.join(f.resources) or 'no resources'})")
        lines += [f"    {c}: {why}" for c, why in f.problems.items()]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=["local", "live"], default="local")
    ap.add_argument("--out", default="runs/drift")
    ap.add_argument("--as-of", type=date.fromisoformat, help="judge expiry as of this day (default: today; "
                    "offline: the inventory's date)")
    ap.add_argument("--grace-days", type=int, default=2)
    ap.add_argument("--resource-group", default="rg-skr-prov-sandbox")
    ap.add_argument("--write", action="store_true", help="live only: open or update one incident with the report")
    a = ap.parse_args()
    from pathlib import Path

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.source == "live":
        from .connectors.azure_inventory import sandbox_resources
        from .connectors.servicenow import ServiceNowRequests

        sn = ServiceNowRequests(write=a.write)
        from .connectors.azure_inventory import tagged_elsewhere

        resources, requests = sandbox_resources(a.resource_group), sn.all_requests()
        elsewhere = tagged_elsewhere(a.resource_group)
        today, source = a.as_of or date.today(), f"Azure {a.resource_group} + ServiceNow, live"
    else:
        from .connectors.local import local_inventory

        inv = local_inventory()
        resources, requests, elsewhere = inv["resources"], inv["requests"], inv.get("elsewhere", [])
        today, source = a.as_of or date.fromisoformat(inv["as_of"]), "synthetic inventory"
    findings = DriftAgent(today, a.grace_days).run(resources, requests, elsewhere)
    text = report(findings, len(resources), len(requests), today, source)
    (out / "predictions.json").write_text(json.dumps([prediction(f) for f in findings], indent=1))
    (out / "findings.json").write_text(json.dumps([vars(f) for f in findings], indent=1))
    (out / "report.md").write_text(text)
    print(text)
    if a.source == "live":
        res = sn.report_drift(plain_report(findings, len(resources), len(requests), today, source), len(findings))
        print(res)
    print(f"Wrote {out}/ predictions.json, findings.json, report.md")


if __name__ == "__main__":
    main()
