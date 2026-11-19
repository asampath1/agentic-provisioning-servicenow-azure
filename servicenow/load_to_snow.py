#!/usr/bin/env python3
"""
Load data/load_plan.json into a ServiceNow instance via the REST Table API,
and remove it again with --cleanup.

Credentials come from environment variables (never hard-code them):
  SN_INSTANCE   e.g. dev123456            (or full https://dev123456.service-now.com)
  SN_USER       e.g. admin
  SN_PASSWORD   your PDI admin password

Usage:
  python3 load_to_snow.py --check            # test the credentials only (one read call)
  python3 load_to_snow.py --dry-run          # resolve every reference offline, call nothing
  python3 load_to_snow.py                    # load everything
  python3 load_to_snow.py --only users,groups,group_members
  python3 load_to_snow.py --cleanup          # delete everything recorded in data/manifest.json
  python3 load_to_snow.py --relink           # (re)write incident problem/change links; on instances
                                             # without incident.problem_id / caused_by, adds u_ fields
  python3 load_to_snow.py --setup            # add the AI fields to change_request (u_ai_risk, ...)
  python3 load_to_snow.py --verify-states    # compare each loaded change's state/type with the plan

Change-management dataset notes:
  * Records that already exist on the instance (from the v1.0 incident dataset: groups, CIs, services,
    relationships, KB articles, problems, and any user with the same user_name) are REUSED, not duplicated.
    They are marked "reused" in the manifest and --cleanup leaves them alone.
  * The Change model's business rules force new changes to state New and type normal, and block jumping to
    Closed / Review over the API. After the load, data/fix_change_states.js sets the planned state and type
    for this dataset's changes; run it once in System Definition > Scripts - Background, then --verify-states.
  * Schedule spans are written in IST (the schedules' time zone); the CSVs keep UTC.

How references work: a value "@user:synth.arjun.iyer" means "the sys_id of the record
created with that _key"; "@lookup:table:field=value" is queried once from the instance.
Created sys_ids are saved to data/manifest.json after every record, so a failed run can
be resumed (already-created keys are skipped) and cleanup knows exactly what to delete.
"""
import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

try:
    import requests
except ImportError:  # dry-run still works without requests
    requests = None


class AuthError(SystemExit):
    """Raised on 401/403 so the load stops at once instead of failing every record."""


AUTH_HELP = """
ServiceNow rejected the credentials ({status}) for user '{user}' on {base}.
Check:
  1. SN_USER / SN_PASSWORD are the *instance* admin login (the one shown under
     developer.servicenow.com > Manage instance password), not your developer.servicenow.com account.
  2. The password reached Python intact. Shells expand $ ! ` inside double quotes, so set it in
     single quotes:   export SN_PASSWORD='p@ss$word!'     (PowerShell: $env:SN_PASSWORD='p@ss$word!')
     Password seen by the loader: {pw_len} characters{pw_ws}.
  3. The instance is awake: log in once at {base} in a browser (PDIs hibernate).
  4. The account is not locked out after the failed attempts (log in as admin in the browser to check).
Then run:  python3 load_to_snow.py --check
"""


class Snow:
    def __init__(self, dry):
        self.dry = dry
        if dry:
            return
        inst = os.environ.get("SN_INSTANCE", "").strip()
        user, pw = (os.environ.get("SN_USER") or "").strip(), os.environ.get("SN_PASSWORD") or ""
        if not (inst and user and pw):
            sys.exit("Set SN_INSTANCE, SN_USER and SN_PASSWORD environment variables first.")
        if requests is None:
            sys.exit("pip install requests")
        if inst.startswith("http"):
            self.base = f"https://{urlparse(inst).netloc}"     # drop any path such as /now/nav/ui
        else:
            self.base = f"https://{inst.removesuffix('.service-now.com')}.service-now.com"
        self.user, self.pw = user, pw
        self.s = requests.Session()
        self.s.auth = (user, pw)
        self.s.headers.update({"Accept": "application/json", "Content-Type": "application/json"})

    def _req(self, method, url, **kw):
        for attempt in range(5):
            r = self.s.request(method, url, timeout=60, **kw)
            if r.status_code in (429, 502, 503, 504):
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code == 401:
                self._auth_fail(r)
            return r
        return r

    def _auth_fail(self, r):
        ws = " (has leading/trailing whitespace!)" if self.pw != self.pw.strip() else ""
        raise AuthError(AUTH_HELP.format(status=f"HTTP {r.status_code}", user=self.user, base=self.base,
                                         pw_len=len(self.pw), pw_ws=ws) + f"\nServer said: {r.text[:200]}")

    def check(self):
        """One read call that proves the login works and has the roles the load needs."""
        if self.dry:
            return
        try:
            r = self._req("GET", f"{self.base}/api/now/table/sys_user",
                          params={"sysparm_query": f"user_name={self.user}", "sysparm_fields": "sys_id,user_name",
                                  "sysparm_limit": 1})
        except requests.RequestException as e:
            sys.exit(f"Cannot reach {self.base}: {e}\nCheck SN_INSTANCE (e.g. dev123456) and that the PDI is awake.")
        if r.status_code == 403:
            self._auth_fail(r)
        if r.status_code >= 300 or "json" not in r.headers.get("Content-Type", ""):
            sys.exit(f"Unexpected response from {self.base} (HTTP {r.status_code}). Is the PDI awake? "
                     f"Log in once in a browser, then retry.\n{r.text[:200]}")
        print(f"Connected to {self.base} as {self.user}.")

    def query_one(self, table, field, value):
        if self.dry:
            return f"dry-{table}-{value}"[:32]
        r = self._req("GET", f"{self.base}/api/now/table/{table}",
                      params={"sysparm_query": f"{field}={value}", "sysparm_fields": "sys_id", "sysparm_limit": 1})
        r.raise_for_status()
        res = r.json()["result"]
        return res[0]["sys_id"] if res else None

    def _get(self, table, query, fields):
        r = self._req("GET", f"{self.base}/api/now/table/{table}",
                      params={"sysparm_query": query, "sysparm_fields": fields, "sysparm_limit": 200})
        return r.json().get("result", []) if r.status_code < 300 else []

    def close_code_map(self):
        """Map the generator's close codes onto this instance's choices.

        Releases differ: the field may be labelled "Close code" or "Resolution code", the stored values
        may be "Solution provided" or "Solved (Permanently)", and some releases add a separate mandatory
        resolution-code field. Returns {field: {our_value: instance_value}} for every such field.
        """
        if self.dry:
            return {}
        fields = {"close_code"}
        for d in self._get("sys_dictionary", "name=incident^column_labelINResolution code,Close code", "element"):
            if d.get("element"):
                fields.add(d["element"])
        wanted = {"Solution provided": ("solution provided", "solved permanently", "solved", "resolved"),
                  "Workaround provided": ("workaround provided", "solved work around", "workaround"),
                  "Resolved by change": ("resolved by change", "solution provided", "solved permanently", "solved")}
        norm = lambda x: " ".join("".join(c if c.isalnum() else " " for c in (x or "").lower()).split())  # noqa: E731
        out = {}
        for f in sorted(fields):
            choices = [(c["value"], c["label"]) for c in
                       self._get("sys_choice", f"name=incident^element={f}^inactive=false", "value,label")]
            if not choices:
                continue
            m = {}
            for ours, prefs in wanted.items():
                pick = None
                for p in prefs:
                    pick = next((v for v, lbl in choices if norm(v) == p or norm(lbl) == p), None) or \
                        next((v for v, lbl in choices if p in norm(v) or p in norm(lbl)), None)
                    if pick:
                        break
                m[ours] = pick or choices[0][0]
            out[f] = m
            print(f"  close codes for incident.{f}: " + ", ".join(f"{k} -> {v}" for k, v in m.items()))
        return out

    # Standard incident reference fields -> (custom fallback, referenced table, label).
    REF_FIELDS = {"problem_id": ("u_problem_id", "problem", "Problem (SYNTH-SKR)"),
                  "caused_by": ("u_caused_by", "change_request", "Caused by Change (SYNTH-SKR)")}

    def incident_ref_fields(self, create=False):
        """Return {standard field: field to write on this instance}, or None for a field with nowhere to go.

        Some PDIs have no incident.problem_id / incident.caused_by: writes to them are dropped silently.
        With create=True the custom u_ reference fields are added to the incident table (a schema change).
        """
        if self.dry:
            return {f: f for f in self.REF_FIELDS}
        out = {}
        for std, (custom, ref, label) in self.REF_FIELDS.items():
            if self._get("sys_dictionary", f"nameINincident,task^element={std}", "element"):
                out[std] = std
            elif self._get("sys_dictionary", f"name=incident^element={custom}", "element"):
                out[std] = custom
            elif create:
                r = self._req("POST", f"{self.base}/api/now/table/sys_dictionary", json={
                    "name": "incident", "element": custom, "column_label": label,
                    "internal_type": "reference", "reference": ref, "active": "true"})
                ok = r.status_code < 300 and self._get("sys_dictionary", f"name=incident^element={custom}", "element")
                if not ok:
                    sys.exit(f"Could not create incident.{custom}: HTTP {r.status_code} {r.text[:300]}")
                print(f"  + created field incident.{custom} (reference to {ref}); incident.{std} does not exist here")
                out[std] = custom
            else:
                out[std] = None
        return out

    def insert(self, table, body):
        if self.dry:
            return uuid.uuid4().hex, None
        r = self._req("POST", f"{self.base}/api/now/table/{table}", json=body,
                      params={"sysparm_fields": "sys_id,number", "sysparm_input_display_value": "false"})
        if r.status_code >= 300:
            return None, f"{r.status_code} {r.text[:300]}"
        res = r.json()["result"]
        return res["sys_id"], res.get("number")

    def patch(self, table, sys_id, body):
        if self.dry:
            return None
        r = self._req("PATCH", f"{self.base}/api/now/table/{table}/{sys_id}", json=body)
        return None if r.status_code < 300 else f"{r.status_code} {r.text[:200]}"

    def delete(self, table, sys_id):
        if self.dry:
            return True
        r = self._req("DELETE", f"{self.base}/api/now/table/{table}/{sys_id}")
        return r.status_code in (200, 204, 404)


IST = timedelta(hours=5, minutes=30)
TAG = "SYNTH-SKR-CHG"
AI_FIELDS = (("u_ai_risk", "AI risk"), ("u_ai_recommendation", "AI recommendation"),
             ("u_ai_close_code", "AI suggested close code"))
CI_TABLES = ("cmdb_ci_win_server", "cmdb_ci_linux_server", "cmdb_ci_appl", "cmdb_ci_db_mssql_instance",
             "cmdb_ci_ip_firewall")


def reuse_query(table, body):
    """Encoded query that finds an existing copy of this record (v1.0 data), or None if it is always new."""
    if table == "sys_user":
        return f"user_name={body['user_name']}"
    if table == "sys_user_group" or table == "cmdb_ci_service":
        return f"name={body['name']}"
    if table in CI_TABLES:
        return f"name={body['name']}"
    if table == "sys_user_grmember":
        return f"group={body.get('group')}^user={body.get('user')}"
    if table == "cmdb_rel_ci":
        return f"parent={body.get('parent')}^child={body.get('child')}^type={body.get('type')}"
    if table == "kb_knowledge":
        return f"short_description={body['short_description']}^metaLIKESYNTH-SKR"
    if table == "problem":
        return f"short_description={body['short_description']}^correlation_idSTARTSWITHSYNTH-SKR"
    return None


def to_ist_span(body):
    """cmn_schedule_span: our UTC 'YYYY-MM-DD HH:MM:SS' -> IST 'YYYYMMDDTHHMMSS'; weekday digits follow."""
    s = datetime.strptime(body["start_date_time"], "%Y-%m-%d %H:%M:%S")
    e = datetime.strptime(body["end_date_time"], "%Y-%m-%d %H:%M:%S")
    shift = ((s + IST).date() - s.date()).days
    out = dict(body, start_date_time=(s + IST).strftime("%Y%m%dT%H%M%S"), end_date_time=(e + IST).strftime("%Y%m%dT%H%M%S"))
    if body.get("days_of_week"):
        out["days_of_week"] = "".join(sorted(str((int(d) - 1 + shift) % 7 + 1) for d in body["days_of_week"]))
    return out


def load(args):
    data_dir = Path(args.data)
    plan = json.loads((data_dir / "load_plan.json").read_text())
    man_path = data_dir / ("manifest.dryrun.json" if args.dry_run else "manifest.json")
    manifest = json.loads(man_path.read_text()) if man_path.exists() and not args.dry_run else {"records": {}}
    created = manifest["records"]           # _key -> {table, sys_id, number}
    lookups = {}
    sn = Snow(args.dry_run)
    sn.check()
    only = set(args.only.split(",")) if args.only else None
    errors = reused = 0
    close_map = None
    ref_map = None
    intended = manifest.setdefault("intended_change_state", {})

    def resolve(v):
        if not (isinstance(v, str) and v.startswith("@")):
            return v
        if v.startswith("@lookup:"):
            if v not in lookups:
                _, table, cond = v.split(":", 2)
                field, value = cond.split("=", 1)
                lookups[v] = sn.query_one(table, field, value)
                if not lookups[v]:
                    print(f"  ! lookup not found: {table} {field}={value} (field left empty)")
            return lookups[v]
        key = v[1:]
        if key not in created:
            raise KeyError(f"unresolved reference {v}")
        return created[key]["sys_id"]

    for stage in plan["stages"]:
        if only and stage["stage"] not in only:
            continue
        recs = stage["records"]
        print(f"== {stage['stage']} ({len(recs)})")
        done = 0
        for rec in recs:
            key, table = rec["_key"], rec["_table"]
            if key in created:
                continue
            try:
                body = {k: resolve(v) for k, v in rec.items() if not k.startswith("_")}
            except KeyError as e:
                # A record it depends on failed earlier: skip this one, keep going, re-run later to resume.
                errors += 1
                print(f"  x {key}: skipped, {e.args[0]} (that record was not created)")
                continue
            body = {k: v for k, v in body.items() if v not in (None, "")}
            q = reuse_query(table, body)
            if q and not args.dry_run:
                found = sn._get("cmdb_ci" if table in CI_TABLES else table, q, "sys_id")
                if found:
                    created[key] = {"table": table, "sys_id": found[0]["sys_id"], "number": None, "reused": True}
                    reused += 1
                    continue
            if table == "cmn_schedule_span":
                body = to_ist_span(body)
            if table == "change_request":
                intended[key] = {"state": rec.get("state"), "type": rec.get("type")}
            if table == "incident" and any(f in body for f in Snow.REF_FIELDS):
                if ref_map is None:
                    ref_map = sn.incident_ref_fields()
                    missing = [f for f, t in ref_map.items() if not t]
                    if missing:
                        print(f"  ! incident has no {', '.join(missing)} field: run --relink after the load")
                for std, target in ref_map.items():
                    if std in body and target != std:
                        v = body.pop(std)
                        if target:
                            body[target] = v
            if table == "incident" and body.get("close_code"):
                if close_map is None:
                    close_map = sn.close_code_map()
                ours = body["close_code"]
                for field, m in close_map.items():
                    if ours in m:
                        body[field] = m[ours]
            sys_id, info = sn.insert(table, body)
            if not sys_id and rec.get("_retry_drop"):
                for f in rec["_retry_drop"]:
                    body.pop(f, None)
                sys_id, info = sn.insert(table, body)
            if not sys_id:
                errors += 1
                print(f"  x {key}: {info}")
                continue
            created[key] = {"table": table, "sys_id": sys_id, "number": info}
            if rec.get("_post_patch"):
                err = sn.patch(table, sys_id, rec["_post_patch"])
                if err:
                    print(f"  ~ {key}: timestamp patch failed ({err})")
            done += 1
            if not args.dry_run:
                man_path.write_text(json.dumps(manifest, indent=1))
            if done % 25 == 0:
                print(f"  ... {done}")
            if args.delay:
                time.sleep(args.delay)
        print(f"  created {done}")
    man_path.write_text(json.dumps(manifest, indent=1))
    suffix = ".dryrun" if args.dry_run else ""
    write_loaded_truth(data_dir, created, suffix)
    js = fix_states_script(created, intended)
    (data_dir / f"fix_change_states{suffix}.js").write_text(js)
    print(f"\nDone. {len(created)} records in manifest ({reused} reused from earlier loads), {errors} errors. "
          f"Manifest: {man_path}")
    print(f"Next: run data/fix_change_states{suffix}.js in System Definition > Scripts - Background, then "
          f"python3 load_to_snow.py --verify-states")
    return errors


def write_loaded_truth(data_dir, created, suffix=""):
    """The answer key with local keys replaced by the instance's CHG/INC numbers (for scoring live runs)."""
    gt_path = data_dir / "ground_truth.json"
    if not gt_path.exists():
        return
    gt = json.loads(gt_path.read_text())
    num = lambda k: (created.get(k) or {}).get("number") or k          # noqa: E731
    for a in gt["assess"]:
        a["local_key"], a["key"] = a["key"], num(a["key"])
        for c in a["conflicts"]:
            c["local_key"], c["key"] = c["key"], num(c["key"])
    for v in gt["verify"]:
        v["local_key"], v["key"] = v["key"], num(v["key"])
        v["caused_incidents"] = [num(i) for i in v["caused_incidents"]]
        for d in v["distractor_incidents"]:
            d["local_key"], d["key"] = d["key"], num(d["key"])
    (data_dir / f"ground_truth.loaded{suffix}.json").write_text(json.dumps(gt, indent=1))


def fix_states_script(created, intended):
    want = {created[k]["sys_id"]: [v["state"], v["type"]] for k, v in intended.items() if k in created}
    return f"""// Generated by load_to_snow.py for the {TAG} change dataset.
// The Change model's business rules force inserted changes to New / normal and block jumping to Closed or Review
// over the API. This sets the planned state and type on THIS dataset's changes only, without running business rules.
// Run once in System Definition > Scripts - Background.
var want = {json.dumps(want)};
var fixed = 0, ok = 0;
var gr = new GlideRecord('change_request');
gr.addQuery('correlation_id', '{TAG}');
gr.query();
while (gr.next()) {{
  var w = want[gr.getUniqueValue()];
  if (!w) continue;
  if (gr.getValue('state') == w[0] && gr.getValue('type') == w[1]) {{ ok++; continue; }}
  gr.setWorkflow(false);      // skip business rules (state model, approvals, notifications)
  gr.autoSysFields(false);
  gr.setValue('state', w[0]);
  gr.setValue('type', w[1]);
  gr.update();
  fixed++;
}}
gs.info('{TAG}: fixed ' + fixed + ' change(s), ' + ok + ' already right, ' + Object.keys(want).length + ' planned');
"""


def setup(args):
    """Add the AI output fields to change_request (a schema change on the instance)."""
    sn = Snow(args.dry_run)
    sn.check()
    for element, label in AI_FIELDS:
        if not args.dry_run and sn._get("sys_dictionary", f"name=change_request^element={element}", "element"):
            print(f"  = change_request.{element} exists")
            continue
        if args.dry_run:
            print(f"  would create change_request.{element} ({label})")
            continue
        r = sn._req("POST", f"{sn.base}/api/now/table/sys_dictionary", json={
            "name": "change_request", "element": element, "column_label": label, "internal_type": "string",
            "max_length": "40", "active": "true"})
        if r.status_code >= 300:
            sys.exit(f"Could not create change_request.{element}: HTTP {r.status_code} {r.text[:300]}")
        print(f"  + created change_request.{element} ({label})")


def verify_states(args):
    data_dir = Path(args.data)
    manifest = json.loads((data_dir / "manifest.json").read_text())
    created, intended = manifest["records"], manifest.get("intended_change_state", {})
    sn = Snow(False)
    sn.check()
    rows = {}
    for page in range(0, 2000, 200):
        r = sn._req("GET", f"{sn.base}/api/now/table/change_request",
                    params={"sysparm_query": f"correlation_id={TAG}", "sysparm_fields": "sys_id,number,state,type",
                            "sysparm_limit": 200, "sysparm_offset": page})
        batch = r.json().get("result", [])
        rows.update({x["sys_id"]: x for x in batch})
        if len(batch) < 200:
            break
    bad = []
    for k, want in intended.items():
        got = rows.get((created.get(k) or {}).get("sys_id"))
        if not got or got["state"] != want["state"] or got["type"] != want["type"]:
            bad.append((k, want, got and {"state": got["state"], "type": got["type"], "number": got["number"]}))
    print(f"{len(intended) - len(bad)} of {len(intended)} changes have the planned state and type.")
    for k, want, got in bad[:20]:
        print(f"  x {k}: want {want}, instance has {got}")
    return len(bad)


def relink(args):
    """Write incident -> problem / change links for incidents already loaded (listed in the manifest).

    For PDIs without incident.problem_id / incident.caused_by: creates u_problem_id / u_caused_by
    (unless --dry-run) and patches the links from the load plan into whichever fields exist.
    """
    data_dir = Path(args.data)
    plan = json.loads((data_dir / "load_plan.json").read_text())
    man_path = data_dir / "manifest.json"
    if not man_path.exists():
        sys.exit("No data/manifest.json - load the data first.")
    created = json.loads(man_path.read_text())["records"]
    sn = Snow(args.dry_run)
    sn.check()
    ref_map = sn.incident_ref_fields(create=not args.dry_run)
    print("Fields: " + ", ".join(f"{s} -> incident.{t}" for s, t in ref_map.items()))
    done = errors = 0
    for stage in plan["stages"]:
        for rec in stage["records"]:
            if rec["_table"] != "incident" or not any(rec.get(f) for f in ref_map):
                continue
            inc = created.get(rec["_key"])
            if not inc:
                print(f"  x {rec['_key']}: not in manifest (not loaded)")
                errors += 1
                continue
            body = {}
            for std, target in ref_map.items():
                v = rec.get(std)
                if v and target:
                    ref = created.get(v[1:])          # "@prb:PRB_X" -> manifest key "prb:PRB_X"
                    if not ref:
                        print(f"  x {rec['_key']}: {v} not in manifest")
                        errors += 1
                        continue
                    body[target] = ref["sys_id"]
            if not body:
                continue
            err = sn.patch("incident", inc["sys_id"], body)
            if err:
                print(f"  x {rec['_key']} ({inc.get('number')}): {err}")
                errors += 1
                continue
            done += 1
            if done % 25 == 0:
                print(f"  ... {done}")
    verb = "would patch" if args.dry_run else "patched"
    print(f"\nDone. {verb} {done} incidents, {errors} errors.")
    return errors


def cleanup(args):
    data_dir = Path(args.data)
    man_path = data_dir / "manifest.json"
    if not man_path.exists():
        sys.exit("No data/manifest.json - nothing to clean up.")
    manifest = json.loads(man_path.read_text())
    sn = Snow(args.dry_run)
    sn.check()
    # delete in reverse creation order (incidents first, users last)
    items = list(manifest["records"].items())[::-1]
    print(f"Deleting {len(items)} records ...")
    left = {}
    for i, (key, m) in enumerate(items, 1):
        if m.get("reused"):
            continue                       # belongs to an earlier load (v1.0); never delete it from here
        if not sn.delete(m["table"], m["sys_id"]):
            left[key] = m
        if i % 50 == 0:
            print(f"  ... {i}")
    manifest["records"] = dict(reversed(list(left.items())))
    man_path.write_text(json.dumps(manifest, indent=1))
    print(f"Done. {len(left)} records could not be deleted (kept in manifest).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="data")
    ap.add_argument("--dry-run", action="store_true", help="resolve references offline, no API calls")
    ap.add_argument("--only", help="comma-separated stages to load")
    ap.add_argument("--delay", type=float, default=0.0, help="seconds to sleep between records")
    ap.add_argument("--cleanup", action="store_true", help="delete everything listed in the manifest")
    ap.add_argument("--check", action="store_true", help="only test the connection and credentials")
    ap.add_argument("--setup", action="store_true", help="add the AI fields to change_request")
    ap.add_argument("--verify-states", action="store_true", help="compare loaded change states with the plan")
    ap.add_argument("--relink", action="store_true",
                    help="(re)write incident problem/change links; adds u_ fields if the instance lacks them")
    a = ap.parse_args()
    if a.check:
        Snow(False).check()
    elif a.setup:
        setup(a)
    elif a.verify_states:
        sys.exit(1 if verify_states(a) else 0)
    elif a.relink:
        sys.exit(1 if relink(a) else 0)
    elif a.cleanup:
        cleanup(a)
    else:
        sys.exit(1 if load(a) else 0)
