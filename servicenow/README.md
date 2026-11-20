# ServiceNow side (P2)

`catalog.py` puts the SKR Cloud catalog on the PDI from `catalog_definition.py`. It is idempotent: each record is
found by its name, created if missing and updated if different. It is read-only unless you pass `--apply`.

```bash
cd servicenow
export SN_INSTANCE=dev467960 SN_USER=svc.aiops.loader
export SN_PASSWORD="$(az keyvault secret show --vault-name kvskrprovstuyjwu6 -n snow-password --query value -o tsv)"
python3 catalog.py --offline     # what it would create (no API calls)
python3 catalog.py               # compare the instance with the definition (read-only)
python3 catalog.py --apply       # create / update
python3 catalog.py --remove --apply   # take it all off again (the request fields stay)
```

## What it creates

| Record | Details |
|---|---|
| Category **SKR Cloud (Azure)** | in the Service Catalog |
| Item **Azure Linux test VM** | purpose, size, SSH public key, expiry date, justification. Built from Template Spec `vm-linux-test` |
| Item **Azure storage account** | purpose, redundancy, data classification, expiry date, justification. Built from Template Spec `storage-account` |
| Group **SKR Cloud Platform** | the approvers (the PDI `admin` for the demo) |
| Request fields | `u_cloud_approval` (the approval gate), `u_ai_recommendation`, `u_ai_monthly_cost` (validation agent, P3); `u_provisioning_state`, `u_azure_resource_id` (worker, P4) |
| 4 business rules | the approval flow below; source in [`scripts/`](scripts/) |

The size and redundancy lists include options the sandbox policy does not allow (D-series VMs, ZRS / GRS
storage), marked "needs justification". People do ask for them; the validation agent should catch them before a
person approves, and Azure Policy denies them anyway. A test checks the lists against the Bicep `@allowed` values.

## Approval flow

```
order the item -> RITM, approval = requested, one approval per member of SKR Cloud Platform,
                  except whoever opened the request or is getting it (separation of duties)
              -> validation agent (P3) writes a work note + AI recommendation
              -> a person approves or rejects (first decision counts; the others become "no longer required")
              -> approved: stage Fulfillment; the worker in Azure picks it up (P4)
                 rejected: Closed Incomplete
```

**The gate is `u_cloud_approval`, not the item's own approval field.** On this PDI the out-of-box "Service Catalog
Request" flow auto-approves any request under $1000 and copies that onto its items: my first test request showed
Approved two seconds after it was ordered, before anyone had decided (the audit trail shows user `system`). So
only a person's decision on an approval record sets `u_cloud_approval`, a "hold" rule keeps the item's approval
field in line with it, and the worker builds only when `u_cloud_approval = approved`.

I used business rules rather than a Flow Designer flow because a flow cannot be created cleanly over the API, and
the PDI must be rebuildable from this repo. The PDI's approval engine for requested items is off, so nothing else
creates approvals for these items. The rules contain no Azure call: ServiceNow never connects to Azure.
