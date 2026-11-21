#!/usr/bin/env python3
"""Create or update the SKR Cloud catalog on a ServiceNow PDI (P2). Idempotent: every record is found by its name
first, created if missing, updated if different. Nothing is written without --apply.

Credentials: SN_INSTANCE, SN_USER, SN_PASSWORD (the API user, e.g. svc.aiops.loader), as for load_to_snow.py.

  python3 catalog.py --offline     # print what would be created; no API calls, no credentials
  python3 catalog.py               # read-only: compare the instance with the definition
  python3 catalog.py --apply       # create / update everything
  python3 catalog.py --remove      # delete what this script created (items, variables, rules, group, category)
"""
import argparse
import sys

from catalog_definition import (APPROVER_GROUP, APPROVERS, BUSINESS_RULES, CATALOG, CATEGORY, ITEMS, RITM_FIELDS,
                                TAG, script)
from load_to_snow import Snow


class Catalog:
    def __init__(self, sn, apply: bool):
        self.sn, self.apply = sn, apply
        self.counts = {"create": 0, "update": 0, "ok": 0}

    def find(self, table, query, fields="sys_id"):
        rows = self.sn._get(table, query, fields)
        return rows[0] if rows else None

    def upsert(self, table, query, body, label):
        """Find by query; create if missing; patch the fields that differ."""
        fields = ",".join(["sys_id", *body])
        row = self.find(table, query, fields)
        if not row:
            self.counts["create"] += 1
            print(f"  + {label}")
            if not self.apply:
                return f"(new {table})"
            sys_id, err = self.sn.insert(table, body)
            if not sys_id:
                sys.exit(f"Could not create {label}: {err}")
            return sys_id
        val = lambda x: x.get("value", "") if isinstance(x, dict) else x      # references come back as {link, value}
        diff = {k: v for k, v in body.items() if str(val(row.get(k, ""))) != str(v)}
        if diff:
            self.counts["update"] += 1
            print(f"  ~ {label}: {', '.join(sorted(diff))}")
            if self.apply:
                err = self.sn.patch(table, row["sys_id"], diff)
                if err:
                    sys.exit(f"Could not update {label}: {err}")
        else:
            self.counts["ok"] += 1
        return row["sys_id"]

    def run(self):
        sn = self.sn
        print("== approver group")
        group = self.upsert("sys_user_group", f"name={APPROVER_GROUP['name']}", APPROVER_GROUP,
                            f"group {APPROVER_GROUP['name']}")
        for user in APPROVERS:
            u = self.find("sys_user", f"user_name={user}")
            if not u:
                print(f"  ! user {user} not found: skipped")
                continue
            if group.startswith("(new"):
                self.counts["create"] += 1
                print(f"  + member {user}")
            else:
                self.upsert("sys_user_grmember", f"group={group}^user={u['sys_id']}",
                            {"group": group, "user": u["sys_id"]}, f"member {user}")

        print("== request fields (sc_req_item)")
        for element, label, length in RITM_FIELDS:
            if self.find("sys_dictionary", f"name=sc_req_item^element={element}"):
                self.counts["ok"] += 1
                continue
            self.counts["create"] += 1
            print(f"  + sc_req_item.{element} ({label})")
            if self.apply:
                r = sn._req("POST", f"{sn.base}/api/now/table/sys_dictionary", json={
                    "name": "sc_req_item", "element": element, "column_label": label, "internal_type": "string",
                    "max_length": str(length), "active": "true"})
                if r.status_code >= 300:
                    sys.exit(f"Could not create sc_req_item.{element}: HTTP {r.status_code} {r.text[:300]}")

        print("== category and items")
        cat = self.find("sc_catalog", f"title={CATALOG}")
        if not cat:
            sys.exit(f"Catalog '{CATALOG}' not found on this instance.")
        category = self.upsert("sc_category", f"title={CATEGORY['title']}^sc_catalog={cat['sys_id']}",
                               dict(CATEGORY, sc_catalog=cat["sys_id"], active="true"), f"category {CATEGORY['title']}")
        for item in ITEMS:
            body = {k: item[k] for k in ("name", "short_description", "description")}
            body.update(category=category, sc_catalogs=cat["sys_id"], active="true", no_quantity="true",
                        meta=f"{TAG} template-spec:{item['template_spec']}")
            item_id = self.upsert("sc_cat_item", f"name={item['name']}", body, f"item {item['name']}")
            for order, var in enumerate(item["variables"], 1):
                vbody = {k: v for k, v in var.items() if k != "choices"}
                vbody.update(cat_item=item_id, order=str(order * 100), active="true")
                label = f"variable {item['name']} / {var['name']}"
                if item_id.startswith("(new"):
                    self.counts["create"] += 1 + len(var.get("choices", []))
                    print(f"  + {label}" + (f" ({len(var['choices'])} choices)" if var.get("choices") else ""))
                    continue
                vid = self.upsert("item_option_new", f"cat_item={item_id}^name={var['name']}", vbody, label)
                for corder, (value, text) in enumerate(var.get("choices", []), 1):
                    if vid.startswith("(new"):
                        self.counts["create"] += 1
                        continue
                    self.upsert("question_choice", f"question={vid}^value={value}",
                                {"question": vid, "value": value, "text": text, "order": str(corder * 100)},
                                f"choice {var['name']}={value}")

        print("== business rules")
        for rule in BUSINESS_RULES:
            body = {k: rule[k] for k in ("name", "collection", "when", "order", "action_insert", "action_update")}
            body.update(script=script(rule), active="true", advanced="true",
                        description=f"Approval flow for the SKR Cloud (Azure) catalog items. {TAG}")
            self.upsert("sys_script", f"name={rule['name']}^collection={rule['collection']}", body,
                        f"rule {rule['name']}")

        c = self.counts
        verb = "Done" if self.apply else "Plan (read-only; add --apply to write)"
        done = ("created", "updated") if self.apply else ("to create", "to update")
        print(f"\n{verb}: {c['create']} {done[0]}, {c['update']} {done[1]}, {c['ok']} already right.")

    def remove(self):
        """Delete in reverse dependency order. The sc_req_item fields are kept (they may hold request data)."""
        sn = self.sn
        for rule in BUSINESS_RULES:
            self._delete("sys_script", f"name={rule['name']}^collection={rule['collection']}", f"rule {rule['name']}")
        for item in ITEMS:
            it = self.find("sc_cat_item", f"name={item['name']}")
            if not it:
                continue
            for v in sn._get("item_option_new", f"cat_item={it['sys_id']}", "sys_id,name"):
                for ch in sn._get("question_choice", f"question={v['sys_id']}", "sys_id"):
                    self._delete("question_choice", f"sys_id={ch['sys_id']}", None)
                self._delete("item_option_new", f"sys_id={v['sys_id']}", f"variable {v['name']}")
            self._delete("sc_cat_item", f"sys_id={it['sys_id']}", f"item {item['name']}")
        self._delete("sc_category", f"title={CATEGORY['title']}", f"category {CATEGORY['title']}")
        g = self.find("sys_user_group", f"name={APPROVER_GROUP['name']}")
        if g:
            for m in sn._get("sys_user_grmember", f"group={g['sys_id']}", "sys_id"):
                self._delete("sys_user_grmember", f"sys_id={m['sys_id']}", None)
            self._delete("sys_user_group", f"sys_id={g['sys_id']}", f"group {APPROVER_GROUP['name']}")
        print("Done." if self.apply else "Plan only; add --apply to delete.")

    def _delete(self, table, query, label):
        row = self.find(table, query)
        if not row:
            return
        if label:
            print(f"  - {label}")
        if self.apply and not self.sn.delete(table, row["sys_id"]):
            print(f"  ! could not delete {label or table}")


def offline():
    print(f"Approver group '{APPROVER_GROUP['name']}' with {', '.join(APPROVERS)}")
    print(f"Request fields: {', '.join(e for e, _, _ in RITM_FIELDS)}")
    print(f"Category '{CATEGORY['title']}' in {CATALOG}")
    for item in ITEMS:
        print(f"Item '{item['name']}' (Template Spec {item['template_spec']})")
        for v in item["variables"]:
            ch = f"  [{', '.join(c for c, _ in v['choices'])}]" if v.get("choices") else ""
            print(f"    {v['name']:20} {v['question_text']}{ch}")
    print("Business rules: " + "; ".join(f"{r['name']} ({r['collection']}, {r['when']})" for r in BUSINESS_RULES))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write to the instance (default: read-only plan)")
    ap.add_argument("--remove", action="store_true", help="delete what this script created (with --apply)")
    ap.add_argument("--offline", action="store_true", help="print the definition; no API calls")
    a = ap.parse_args()
    if a.offline:
        offline()
        sys.exit(0)
    sn = Snow(False)
    sn.check()
    cat = Catalog(sn, a.apply)
    cat.remove() if a.remove else cat.run()
