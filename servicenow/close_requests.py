#!/usr/bin/env python3
"""Close SKR Cloud requests that must never be built (e.g. test requests), without building them.

Sets state Closed Incomplete and u_provisioning_state = cancelled, with a work note. Read-only unless --apply.
Credentials: SN_INSTANCE, SN_USER, SN_PASSWORD.

  python3 close_requests.py RITM0010001 RITM0010002 RITM0010003 RITM0010004 --reason "P2 approval-flow test"
  python3 close_requests.py ... --apply
"""
import argparse

from load_to_snow import Snow

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("numbers", nargs="+")
ap.add_argument("--reason", default="test request")
ap.add_argument("--apply", action="store_true")
a = ap.parse_args()
sn = Snow(False)
sn.check()
for n in a.numbers:
    rows = sn._get("sc_req_item", f"number={n}^cat_item.category.title=SKR Cloud (Azure)",
                   "sys_id,number,state,u_cloud_approval,u_provisioning_state")
    if not rows:
        print(f"  ! {n}: not an SKR Cloud request, skipped")
        continue
    r = rows[0]
    print(f"  {n}: state {r['state']}, approval gate '{r['u_cloud_approval']}', provisioning "
          f"'{r['u_provisioning_state']}' -> closed incomplete, cancelled" + ("" if a.apply else "  [plan]"))
    if a.apply:
        err = sn.patch("sc_req_item", r["sys_id"], {"state": "4", "u_provisioning_state": "cancelled",
                                                    "work_notes": f"Closed without building: {a.reason}."})
        if err:
            print(f"    x {err}")
print("Done." if a.apply else "Plan only; add --apply.")
