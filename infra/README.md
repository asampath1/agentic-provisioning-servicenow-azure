# Infrastructure (P1)

| Path | What |
|---|---|
| `main.bicep` | Subscription-scope: the two resource groups, plus the modules below |
| `modules/platform.bicep` | Key Vault (RBAC), the provisioning worker (Automation account, system-assigned managed identity), role assignments |
| `modules/sandbox.bicep` | VNet for requested VMs, **8 Azure Policy assignments**, and the worker's custom role (this resource group only) |
| `templates/*.bicep` | The request templates, published as **Template Specs** by `publish-template-specs.sh` |

## Resource groups

- **`rg-skr-prov-platform`** (Central India; the Automation account is in Japan West, because free trials can create
  Automation only in six regions, one account per region, and Southeast Asia is still held by v1's deleted account)
  - Key Vault: `snow-instance`, `snow-user` and `snow-password` for the ServiceNow API user, added by hand
  - Template Specs: `vm-linux-test` and `storage-account`, versioned
  - Automation account `aa-skr-prov`: the worker
- **`rg-skr-prov-sandbox`** (Central India): requested resources land here. Policy applies to every deployment,
  from ServiceNow or the portal.

## Who can do what

| Identity | Permissions |
|---|---|
| Worker (Automation managed identity) | Read secrets in the vault; read Template Specs; in the sandbox only: deployments, VMs, disks, NICs, storage accounts, auto-shutdown schedules, and joining the subnet. It **cannot** list storage keys, change the VNet, assign roles or change policy |
| Admin (you) | Write secrets in the vault (Key Vault Secrets Officer), plus your subscription rights |
| ServiceNow | **Nothing in Azure.** The worker pulls from ServiceNow; ServiceNow holds no Azure credentials |

## Policy on the sandbox (built-in definitions, deny)

1. Allowed VM sizes: `Standard_B2ats_v2`, `Standard_B2als_v2`
2. Allowed region: Central India
3. `request-id` tag required
4. `expires-on` tag required
5. Storage SKU: `Standard_LRS`
6. Storage: secure transfer only
7. Storage: no public blob access
8. Storage: no shared keys (Entra ID only)

## Commands

```bash
# preview (read-only)
az deployment sub what-if --location centralindia -f infra/main.bicep \
  -p adminObjectId=$(az ad signed-in-user show --query id -o tsv)

# deploy (only after reviewing the preview)
az deployment sub create --location centralindia --name skr-prov-p1 -f infra/main.bicep \
  -p adminObjectId=$(az ad signed-in-user show --query id -o tsv)
infra/publish-template-specs.sh

# add the ServiceNow login to Key Vault (typed by you; never stored in files)
KV=$(az deployment sub show -n skr-prov-p1 --query properties.outputs.keyVaultName.value -o tsv)
az keyvault secret set --vault-name $KV --name snow-instance --value dev467960
az keyvault secret set --vault-name $KV --name snow-user --value svc.aiops.loader
printf 'ServiceNow password: '; stty -echo; read -r p; stty echo; echo      # not echoed, works in zsh and bash
az keyvault secret set --vault-name $KV --name snow-password --value "$p" -o none; unset p
```

## Teardown (before the trial ends on 15 Dec 2026)

```bash
az group delete -n rg-skr-prov-sandbox --yes      # requested resources, VNet, policy assignments
az group delete -n rg-skr-prov-platform --yes     # Key Vault, Template Specs, Automation account
az keyvault purge --name <vault name>             # soft-deleted vault (7-day retention)
az role definition list --custom-role-only true --query "[?contains(roleName,'SKR Provisioning')].name" -o tsv \
  | xargs -I{} az role definition delete --name {}
```

## Provisioning worker (P4)

`runbooks/RB-Provision-Requests.ps1` runs in the Automation account `aa-skr-prov` (PowerShell 7.2, system-assigned
managed identity). It pulls approved SKR Cloud requests from ServiceNow and builds them:

1. Picks requested items with `u_cloud_approval = approved` and no provisioning state.
2. Builds only if the validation agent recommended approve or approve with changes; otherwise marks it `blocked`.
3. Applies the agent's changes (`u_ai_changes`), re-checks every value against the policy, claims the item
   (`deploying`), deploys the Template Spec version into `rg-skr-prov-sandbox`.
4. Writes back `succeeded` / `failed`, the resource ID and a work note, closes the item, and records a change
   (model Change Registration).

The ServiceNow login comes from Key Vault; nothing secret is in the script or in ServiceNow.

```bash
infra/publish-runbooks.sh                                   # upload + publish after editing the .ps1
az automation runbook start -g rg-skr-prov-platform --automation-account-name aa-skr-prov \
  -n RB-Provision-Requests                                  # build now (add --parameters DryRun=true to preview)
az automation runbook start ... --parameters RetryFailed=true   # also retry builds that failed
pwsh infra/runbooks/RB-Provision-Requests.ps1 -DryRun       # preview from a laptop (SN_* variables set)
```

First real run (2026-11-20, RITM0010005): Azure refused the first attempt with **AllocationFailed** (no B2ats_v2
capacity in Central India at that moment); the worker marked the request `failed` with Azure's message, and the
retry built `vm-test-ritm0010005` a few minutes later. There is no schedule yet; it is started by hand until the demo.
