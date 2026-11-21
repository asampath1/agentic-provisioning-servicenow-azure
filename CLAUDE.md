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
- Azure: `az login --use-device-code` works from this shell; free trial, region Central India; Automation accounts: trials
  allow only eastus/eastus2/westus/northeurope/southeastasia/japanwest, one per region (this project: japanwest); B2ats_v2 / B2als_v2 VM sizes work (non-zonal). If `az` hangs, check IPv6.
- `servicenow/catalog.py` (P2) creates the catalog items, approver group, request fields and approval business
  rules from `catalog_definition.py`; read-only unless `--apply`. It reuses the `Snow` client from `load_to_snow.py`.
- Tests: `.venv/bin/python -m pytest -q` (the repo has its own .venv: requests, pytest, anthropic).
- P3: `python -m agents --out runs/latest && python -m evaluation.score runs/latest` (validation agent, policy in
  `docs/request-policy.md`); `--reasoner claude` reads rule 7 text with Claude; `--source servicenow [--write]`.
  P4 worker: `infra/runbooks/RB-Provision-Requests.ps1` (publish with `infra/publish-runbooks.sh`, start with
  `az automation runbook start ... [--parameters DryRun=true|RetryFailed=true]`); local logic checks in
  `tests/runbook_checks.ps1` (pwsh). Change Registration keeps short_description/assignment_group read-only.
  After any generator change: `cd synthetic-data && python3 generate_requests.py` (test_dataset checks freshness).
- P5: expiry worker `infra/runbooks/RB-Expire-Resources.ps1` (remind -> deletion approval for the requester ->
  delete + change; state in `u_expiry_state`; `-AsOf`, `-ReminderDays` 3, `-GraceDays` 2; checks in
  `tests/expiry_checks.ps1`). Drift agent `python -m agents.drift [--source live [--write]]`, scored by
  `python -m evaluation.score_drift runs/drift` against `drift_truth.json` (agents never read it); regenerate with
  `cd synthetic-data && python3 generate_inventory.py`. `servicenow/set_expiry.py` changes a request's expiry.
