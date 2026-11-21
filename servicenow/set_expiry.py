#!/usr/bin/env python3
"""Change the expiry date of a built SKR Cloud request in ServiceNow (the catalog variable expires_on), with a work
note and a comment to the requester. The Azure `expires-on` tag is changed separately (az tag update, see
servicenow/README.md); the expiry worker reads the tag, and the drift agent reports the two if they differ.

Read-only unless --apply. Credentials: SN_INSTANCE, SN_USER, SN_PASSWORD.

  python3 set_expiry.py RITM0010005 2026-11-23 --reason "shortened for the P5 expiry demo"
  python3 set_expiry.py RITM0010005 2026-11-23 --reason "..." --apply
"""
import argparse
from datetime import date

from load_to_snow import Snow

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("number")
ap.add_argument("expires_on", type=date.fromisoformat)
ap.add_argument("--reason", required=True)
ap.add_argument("--apply", action="store_true")
a = ap.parse_args()
sn = Snow(False)
sn.check()
rows = sn._get("sc_req_item", f"number={a.number}^cat_item.category.title=SKR Cloud (Azure)", "sys_id,number")
if not rows:
    raise SystemExit(f"{a.number}: not an SKR Cloud request")
ritm = rows[0]
opts = sn._get("sc_item_option_mtom", f"request_item={ritm['sys_id']}^sc_item_option.item_option_new.name=expires_on",
               "sc_item_option,sc_item_option.value")
if len(opts) != 1:
    raise SystemExit(f"{a.number}: expected one expires_on variable, found {len(opts)}")
opt = opts[0]
opt_id = opt["sc_item_option"]["value"] if isinstance(opt["sc_item_option"], dict) else opt["sc_item_option"]
old, new = opt["sc_item_option.value"], a.expires_on.isoformat()
print(f"  {a.number}: expires_on {old} -> {new}" + ("" if a.apply else "  [plan]"))
if a.apply:
    for table, sys_id, body in (
            ("sc_item_option", opt_id, {"value": new}),
            ("sc_req_item", ritm["sys_id"], {"work_notes": f"Expiry date changed from {old} to {new}: {a.reason}.",
                                             "comments": f"The expiry date of this request is now {new}."})):
        err = sn.patch(table, sys_id, body)
        if err:
            raise SystemExit(f"    x {table}: {err}")
print("Done." if a.apply else "Plan only; add --apply.")
