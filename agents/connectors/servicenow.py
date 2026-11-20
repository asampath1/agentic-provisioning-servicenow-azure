"""Live source: SKR Cloud requests waiting for approval on the ServiceNow PDI.

Reads requested items in the "SKR Cloud (Azure)" category with u_cloud_approval = requested and no AI
recommendation yet, plus their catalog variables. Writes (only with write=True) a work note and the AI fields
u_ai_recommendation / u_ai_monthly_cost. It never approves, rejects or changes the request itself.

Credentials: SN_INSTANCE, SN_USER, SN_PASSWORD (in Azure, the worker reads them from Key Vault).
"""
from __future__ import annotations

import os

CATEGORY = "SKR Cloud (Azure)"


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

    def write(self, req: dict, fields: dict, note: str) -> None:
        rec = {"request": req["key"], "fields": fields, "work_note": note, "sent": False}
        if self.write_enabled:
            r = self.s.patch(f"{self.base}/api/now/table/sc_req_item/{req['sys_id']}", timeout=60,
                             json=dict(fields, work_notes=note))
            rec.update(sent=r.status_code < 300, status=r.status_code)
        self.writes.append(rec)
