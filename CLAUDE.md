# Project context for Claude

Portfolio project: ServiceNow catalog requests -> AI validation -> human approval -> Azure provisioning from one
versioned Template Spec, with expiry clean-up and drift detection. Fictional retailer ShopKart Retails (SKR); all data
synthetic. Design: `docs/design.md` (agreed 2026-11-19). Sibling repos `../agentic-aiops-servicenow-azure` (frozen
v1.0, never edit) and `../agentic-change-management-servicenow`.

## Hard rules
- PULL model: ServiceNow holds NO Azure credentials. The Azure worker uses a managed identity for Azure and reads
  the ServiceNow API login from Key Vault. No secrets in code, templates, parameters files or the repo.
- Nothing is provisioned without an approved request; deletions are recorded as standard changes.
- Every Azure resource carries `request-id` and `expires-on` tags; Policy enforces allowed sizes, tags and region.
- ServiceNow and Azure writes are dry-run unless explicitly requested (`--write` / an explicit deploy step).
- Agents never read the evaluation answer key; never inspect per-item answers to tune or debug agents.
- Azure trial ends mid-December 2026: live Azure work by ~10 Dec, then tear everything down
  (resource group, Template Specs, policy assignment, custom role).
- Docs in the first person singular ("I"): solo project. The user commits and pushes; don't commit unless asked.

## Environment (from the earlier projects)
- ServiceNow PDI dev467960; API user `svc.aiops.loader`. Live ServiceNow commands run in the user's VS Code
  terminal (this shell's SN_PASSWORD is stale); I read the files they write.
- Azure: `az login --use-device-code` works from this shell; free trial, region Central India; Automation accounts
  had to go in Southeast Asia; B2ats_v2 / B2als_v2 VM sizes work (non-zonal). If `az` hangs, check IPv6.
- `servicenow/load_to_snow.py` is the loader from the change-management project (reuses existing records by name,
  dry-run mode); it will be extended for catalog items.
