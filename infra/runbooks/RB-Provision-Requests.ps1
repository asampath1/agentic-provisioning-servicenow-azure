<#
RB-Provision-Requests: the provisioning worker (P4). SYNTH-SKR-PROV

Pull model: ServiceNow never calls Azure. This runbook (Azure Automation, PowerShell 7.2, system-assigned managed
identity) asks ServiceNow for approved SKR Cloud requests and builds them from the published Template Spec.

For each requested item in the "SKR Cloud (Azure)" category with u_cloud_approval = approved and no provisioning
state yet:
  1. The validation agent must have recommended approve or approve_with_changes. A person's approval of a request
     the agent flagged reject / need_info is NOT built: the item is marked "blocked" with a note.
  2. The agent's changes (u_ai_changes) are applied, then every value is checked against the sandbox policy again.
  3. The item is claimed (u_provisioning_state = deploying), then the Template Spec version is deployed into the
     sandbox resource group with the managed identity. Azure Policy checks the same rules again.
  4. The result goes back to the item (state, resource ID, work note) and the build is recorded as a change
     (model "Change Registration": a record of an automated change).

Credentials: the ServiceNow API login comes from Key Vault (Automation variable KeyVaultName). No secret is in this
script or in ServiceNow. -DryRun reads ServiceNow and prints what it would deploy, without writing anything. -RetryFailed also retries items
whose last build failed (same deployment name, so Azure updates the half-built resources instead of duplicating).
#>
param(
    [switch]$DryRun,
    [switch]$RetryFailed,          # also pick up items whose last build failed (e.g. Azure had no capacity)
    [int]$MaxItems = 5,
    [string]$SandboxResourceGroup = 'rg-skr-prov-sandbox',
    [string]$PlatformResourceGroup = 'rg-skr-prov-platform',
    [string]$TemplateSpecVersion = '1.0'
)

$Category = 'SKR Cloud (Azure)'
$AllowedSizes = @('Standard_B2ats_v2', 'Standard_B2als_v2')
$AllowedRedundancy = @('Standard_LRS')
$MaxDays = 30

# ------------------------------------------------------------------ pure functions (tested locally)
function Get-BuildDecision([string]$Recommendation) {
    switch ($Recommendation) {
        'approve' { return 'build' }
        'approve_with_changes' { return 'build' }
        '' { return 'wait' }            # not validated yet: the validation agent runs first
        default { return 'block' }      # reject / need_info: never built, even if a person approved
    }
}

function Merge-Changes([hashtable]$Variables, [string]$ChangesJson) {
    $out = @{} + $Variables
    if ($ChangesJson) {
        $changes = $ChangesJson | ConvertFrom-Json -AsHashtable
        foreach ($k in $changes.Keys) { $out[$k] = $changes[$k] }
    }
    return $out
}

function Test-Policy([string]$Item, [hashtable]$V, [datetime]$Today) {
    # Returns a list of problems; empty means the values may be deployed. Mirrors docs/request-policy.md.
    $problems = @()
    $exp = [datetime]::MinValue
    if (-not [datetime]::TryParseExact($V['expires_on'], 'yyyy-MM-dd', $null, 'None', [ref]$exp)) {
        $problems += "expiry date '$($V['expires_on'])' is not a date"
    } elseif ($exp.Date -le $Today.Date -or $exp.Date -gt $Today.Date.AddDays($MaxDays)) {
        $problems += "expiry date $($V['expires_on']) is not within $MaxDays days from today"
    }
    if ($Item -like '*VM*') {
        if ($AllowedSizes -notcontains $V['vm_size']) { $problems += "size $($V['vm_size']) is not allowed" }
        if ($V['ssh_public_key'] -notmatch '^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp\d+) [A-Za-z0-9+/]+=*( .*)?$' -or
            $V['ssh_public_key'] -match 'PRIVATE KEY') { $problems += 'the SSH key is not a public key line' }
    } else {
        if ($AllowedRedundancy -notcontains $V['redundancy']) { $problems += "redundancy $($V['redundancy']) is not allowed" }
        if ($V['data_classification'] -ne 'synthetic') { $problems += 'data classification is not synthetic' }
    }
    return , $problems
}

function Get-DeploymentPlan([string]$Item, [string]$Number, [string]$Owner, [hashtable]$V) {
    $id = $Number.ToLower()                                   # ritm0010005
    $purpose = ($V['purpose'] -replace '\s+', ' ').Trim()
    if ($purpose.Length -gt 120) { $purpose = $purpose.Substring(0, 117) + '...' }
    $common = @{ requestId = $Number; expiresOn = $V['expires_on']; owner = $Owner; purpose = $purpose }
    if ($Item -like '*VM*') {
        return @{ spec = 'vm-linux-test'; name = "vm-test-$id"; deployment = "skr-$id"
                  parameters = $common + @{ vmName = "vm-test-$id"; vmSize = $V['vm_size']
                                            sshPublicKey = $V['ssh_public_key'].Trim() } }
    }
    $st = ('stskr' + ($id -replace '[^a-z0-9]', ''))
    if ($st.Length -gt 24) { $st = $st.Substring(0, 24) }
    return @{ spec = 'storage-account'; name = $st; deployment = "skr-$id"
              parameters = $common + @{ storageName = $st; skuName = $V['redundancy'] } }
}

# ------------------------------------------------------------------ ServiceNow REST (basic auth from Key Vault)
function Invoke-Snow([string]$Method, [string]$Path, $Body = $null) {
    $p = @{ Method = $Method; Uri = "$script:SnBase$Path"; Headers = $script:SnHeaders; TimeoutSec = 60 }
    if ($Body) { $p.Body = ($Body | ConvertTo-Json -Depth 5 -Compress); $p.ContentType = 'application/json' }
    return Invoke-RestMethod @p
}

function Get-Snow([string]$Table, [string]$Query, [string]$Fields) {
    $q = [uri]::EscapeDataString($Query)
    return (Invoke-Snow GET "/api/now/table/$Table`?sysparm_query=$q&sysparm_fields=$Fields&sysparm_limit=50&sysparm_exclude_reference_link=true").result
}

function Update-Item([string]$SysId, [hashtable]$Fields, [string]$Note) {
    $body = @{} + $Fields
    if ($Note) { $body.work_notes = $Note }
    if ($script:DryRun) { Write-Output "  [dry run] would update $SysId : $(($body.Keys | Sort-Object) -join ', ')"; return }
    Invoke-Snow PATCH "/api/now/table/sc_req_item/$SysId" $body | Out-Null
}

function New-ChangeRecord([hashtable]$Req, [hashtable]$Plan, [string]$ResourceId, [datetime]$Start, [datetime]$End) {
    $model = (Get-Snow 'chg_model' 'name=Change Registration' 'sys_id') | Select-Object -First 1
    $group = (Get-Snow 'sys_user_group' 'name=SKR Cloud Platform' 'sys_id') | Select-Object -First 1
    $body = @{
        short_description = "Provisioned $($Plan.name) for $($Req.number) (SKR Cloud self-service)"
        description = "Automated build by the SKR provisioning worker from Template Spec $($Plan.spec) $TemplateSpecVersion.`nRequest: $($Req.number)`nResource: $ResourceId"
        justification = "Approved catalog request $($Req.number)."
        correlation_id = 'SYNTH-SKR-PROV'; correlation_display = $Req.number
        start_date = $Start.ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ss')
        end_date = $End.ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ss')
        close_code = 'successful'; close_notes = "Deployed $($Plan.deployment) into $SandboxResourceGroup."
    }
    if ($model) { $body.chg_model = $model.sys_id }
    if ($group) { $body.assignment_group = $group.sys_id }
    $chg = (Invoke-Snow POST '/api/now/table/change_request' $body).result
    # The Change Registration model applies its own template on insert ("Automated : Change", group Change
    # Management, state Review) and keeps short description and group read-only. So the details go in the close
    # notes and work notes, the request number in correlation_display, and the change is closed: the work is done.
    $fix = @{ state = '3'; close_code = 'successful'
              close_notes = "$($Plan.name) for $($Req.number) deployed from Template Spec $($Plan.spec) $TemplateSpecVersion into $SandboxResourceGroup."
              work_notes = $body.description }
    try { Invoke-Snow PATCH "/api/now/table/change_request/$($chg.sys_id)" $fix | Out-Null }
    catch { Write-Output "  change $($chg.number): could not close: $($_.Exception.Message)" }
    return $chg.number
}

# ------------------------------------------------------------------ main
if ($env:SKR_RUNBOOK_TEST) { return }       # tests dot-source the functions above

$ErrorActionPreference = 'Stop'
$today = (Get-Date).ToUniversalTime()
if ($env:SN_PASSWORD -and $DryRun) {
    # local dry run from a laptop: ServiceNow login from the environment, no Azure calls
    $inst, $user, $pw = $env:SN_INSTANCE, $env:SN_USER, $env:SN_PASSWORD
    $sub = '<subscription>'
} else {
    Connect-AzAccount -Identity | Out-Null
    $vault = Get-AutomationVariable -Name 'KeyVaultName'
    $inst = Get-AzKeyVaultSecret -VaultName $vault -Name 'snow-instance' -AsPlainText
    $user = Get-AzKeyVaultSecret -VaultName $vault -Name 'snow-user' -AsPlainText
    $pw = Get-AzKeyVaultSecret -VaultName $vault -Name 'snow-password' -AsPlainText
    $sub = (Get-AzContext).Subscription.Id
}
$script:SnBase = "https://$($inst -replace '\.service-now\.com$', '').service-now.com"
$pair = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("${user}:${pw}"))
$script:SnHeaders = @{ Authorization = "Basic $pair"; Accept = 'application/json' }
$pw = $null; $pair = $null

$stateFilter = if ($RetryFailed) { '^u_provisioning_stateISEMPTY^ORu_provisioning_state=failed' } else { '^u_provisioning_stateISEMPTY' }
$items = Get-Snow 'sc_req_item' ("cat_item.category.title=$Category^u_cloud_approval=approved" +
    "$stateFilter^active=true^ORDERBYnumber") `
    'sys_id,number,u_ai_recommendation,u_ai_changes,requested_for.user_name,cat_item.name'
Write-Output "Approved and not yet built: $(@($items).Count) item(s)$(if ($DryRun) { ' [dry run]' })."

foreach ($it in @($items) | Select-Object -First $MaxItems) {
    $num = $it.number
    $decision = Get-BuildDecision $it.u_ai_recommendation
    if ($decision -eq 'wait') { Write-Output "$num : not validated yet, skipped"; continue }
    if ($decision -eq 'block') {
        Write-Output "$num : blocked (validation agent: $($it.u_ai_recommendation))"
        Update-Item $it.sys_id @{ u_provisioning_state = 'blocked' } ("Not built: the validation agent recommended " +
            "'$($it.u_ai_recommendation)'. Fix the request and re-validate, or ask the SKR Cloud Platform team.")
        continue
    }
    $opts = Get-Snow 'sc_item_option_mtom' "request_item=$($it.sys_id)" 'sc_item_option.item_option_new.name,sc_item_option.value'
    $vars = @{}
    foreach ($o in @($opts)) { $vars[$o.'sc_item_option.item_option_new.name'] = [string]$o.'sc_item_option.value' }
    $final = Merge-Changes $vars $it.u_ai_changes
    $item = $it.'cat_item.name'
    $problems = Test-Policy $item $final $today
    if ($problems.Count) {
        Write-Output "$num : blocked by the policy check: $($problems -join '; ')"
        Update-Item $it.sys_id @{ u_provisioning_state = 'blocked' } ("Not built: " + ($problems -join '; ') + '.')
        continue
    }
    $plan = Get-DeploymentPlan $item $num $it.'requested_for.user_name' $final
    $specId = "/subscriptions/$sub/resourceGroups/$PlatformResourceGroup/providers/Microsoft.Resources/templateSpecs/$($plan.spec)/versions/$TemplateSpecVersion"
    if ($DryRun) {
        Write-Output "$num : would deploy $($plan.spec) $TemplateSpecVersion as $($plan.deployment): $($plan.parameters | ConvertTo-Json -Compress)"
        continue
    }
    Update-Item $it.sys_id @{ u_provisioning_state = 'deploying' } "Build started: $($plan.spec) $TemplateSpecVersion -> $($plan.name)."
    $start = Get-Date
    try {
        $dep = New-AzResourceGroupDeployment -Name $plan.deployment -ResourceGroupName $SandboxResourceGroup `
            -TemplateSpecId $specId -TemplateParameterObject $plan.parameters -ErrorAction Stop
        $rid = if ($dep.Outputs.vmId) { $dep.Outputs.vmId.Value } else { $dep.Outputs.storageId.Value }
        $detail = if ($dep.Outputs.privateIp) { "private IP $($dep.Outputs.privateIp.Value), SSH as skradmin with your key" } `
                  else { "blob endpoint $($dep.Outputs.blobEndpoint.Value), Entra ID access only" }
        $chg = $null
        try { $chg = New-ChangeRecord @{ number = $num } $plan $rid $start (Get-Date) }
        catch { Write-Output "$num : change record failed: $($_.Exception.Message)" }
        Update-Item $it.sys_id @{ u_provisioning_state = 'succeeded'; u_azure_resource_id = $rid; state = '3'; stage = 'complete' } (
            "Built $($plan.name) in $SandboxResourceGroup ($detail). Expires $($final['expires_on']): it is deleted " +
            "after that date." + $(if ($chg) { " Recorded as $chg." } else { '' }))
        Write-Output "$num : succeeded -> $rid $(if ($chg) { "($chg)" })"
    } catch {
        $msg = $_.Exception.Message
        if ($msg.Length -gt 600) { $msg = $msg.Substring(0, 600) + '...' }
        Update-Item $it.sys_id @{ u_provisioning_state = 'failed' } "Build failed: $msg"
        Write-Output "$num : FAILED: $msg"
    }
}
