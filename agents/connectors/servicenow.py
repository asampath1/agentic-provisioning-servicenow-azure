"""Live source: SKR Cloud requests waiting for approval on the ServiceNow PDI.

Reads requested items in the "SKR Cloud (Azure)" category with u_cloud_approval = requested and no AI
recommendation yet, plus their catalog variables. Writes (only with write=True) a work note and the AI fields
u_ai_recommendation / u_ai_monthly_cost. It never approves, rejects or changes the request itself.

Credentials: SN_INSTANCE, SN_USER, SN_PASSWORD (in Azure, the worker reads them from Key Vault).
"""
from __future__ import annotations

import os

CATEGORY = "SKR Cloud (Azure)"
DRIFT_TAG = "SYNTH-SKR-PROV-DRIFT"


class ServiceNowRequests:
    def __init__(self, write: bool = False, session=None):
        import requests

        inst = os.environ["SN_INSTANCE"].strip()
        self.base = inst if inst.startswith("http") else f"https://{inst.removesuffix('.service-now.com')}.service-now.com"
        self.s = session or requests.Session()
        self.s.auth = (os.environ["SN_USER"].strip(), os.environ["SN_PASSWORD"])
        self.s.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
        self.write_enabled = write
        self.writes: list[dict] = []

    def _get(self, table: str, query: str, fields: str, limit: int = 200) -> list[dict]:
        r = self.s.get(f"{self.base}/api/now/table/{table}", timeout=60, params={
            "sysparm_query": query, "sysparm_fields": fields, "sysparm_limit": limit,
            "sysparm_display_value": "false", "sysparm_exclude_reference_link": "true"})
        r.raise_for_status()
        return r.json()["result"]

    def pending(self) -> list[dict]:
        rows = self._get("sc_req_item", f"cat_item.category.title={CATEGORY}^u_cloud_approval=requested"
                                        "^u_ai_recommendationISEMPTY^ORDERBYnumber",
                         "sys_id,number,opened_at,requested_for.user_name,cat_item.name")
        out = []
        for r in rows:
            opts = self._get("sc_item_option_mtom", f"request_item={r['sys_id']}",
                             "sc_item_option.item_option_new.name,sc_item_option.value")
            variables = {o["sc_item_option.item_option_new.name"]: o["sc_item_option.value"] for o in opts}
            out.append({"key": r["number"], "sys_id": r["sys_id"], "item": r["cat_item.name"],
                        "requested_for": r["requested_for.user_name"], "opened_at": r["opened_at"],
                        "variables": variables})
        return out

    def all_requests(self) -> list[dict]:
        """Every SKR Cloud request (any state), with its variables: the drift agent's view of ServiceNow."""
        rows = self._get("sc_req_item", f"cat_item.category.title={CATEGORY}^ORDERBYnumber",
                         "sys_id,number,cat_item.name,u_cloud_approval,u_provisioning_state,u_expiry_state,u_ai_changes",
                         limit=500)
        out = []
        for r in rows:
            opts = self._get("sc_item_option_mtom", f"request_item={r['sys_id']}",
                             "sc_item_option.item_option_new.name,sc_item_option.value")
            out.append({"number": r["number"], "item": r["cat_item.name"], "u_cloud_approval": r["u_cloud_approval"],
                        "u_provisioning_state": r["u_provisioning_state"], "u_expiry_state": r.get("u_expiry_state", ""),
                        "u_ai_changes": r["u_ai_changes"],
                        "variables": {o["sc_item_option.item_option_new.name"]: o["sc_item_option.value"] for o in opts}})
        return out

    def report_drift(self, text: str, n: int) -> str:
        """With write=True: one open incident carries the drift report (created once, then updated with work notes)."""
        if not n:
            return "No drift: no incident."
        if not self.write_enabled:
            return f"[dry run] would open or update the drift incident ({n} finding(s)); add --write."
        found = self._get("incident", f"correlation_id={DRIFT_TAG}^active=true", "sys_id,number", limit=1)
        if found:
            r = self.s.patch(f"{self.base}/api/now/table/incident/{found[0]['sys_id']}", timeout=60,
                             json={"work_notes": text})
            return f"Updated {found[0]['number']} (HTTP {r.status_code})."
        group = self._get("sys_user_group", "name=SKR Cloud Platform", "sys_id", limit=1)
        body = {"short_description": f"Azure sandbox drift: {n} finding(s) without a matching approved request",
                "description": text, "correlation_id": DRIFT_TAG, "impact": "3", "urgency": "3",
                "category": "software"}
        if group:
            body["assignment_group"] = group[0]["sys_id"]
        caller = self._get("sys_user", f"user_name={self.s.auth[0]}", "sys_id", limit=1)
        if caller:
            body["caller_id"] = caller[0]["sys_id"]      # the form makes Caller mandatory: the agent's API user
        r = self.s.post(f"{self.base}/api/now/table/incident", timeout=60, json=body)
        num = r.json().get("result", {}).get("number") if r.status_code < 300 else None
        return f"Opened {num}." if num else f"Incident not created: HTTP {r.status_code} {r.text[:200]}"

    def write(self, req: dict, fields: dict, note: str) -> None:
        rec = {"request": req["key"], "fields": fields, "work_note": note, "sent": False}
        if self.write_enabled:
            r = self.s.patch(f"{self.base}/api/now/table/sc_req_item/{req['sys_id']}", timeout=60,
                             json=dict(fields, work_notes=note))
            rec.update(sent=r.status_code < 300, status=r.status_code)
        self.writes.append(rec)
