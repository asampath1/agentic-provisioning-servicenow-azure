<#
RB-Expire-Resources: the expiry worker (P5). SYNTH-SKR-PROV

Runs in the same Automation account as RB-Provision-Requests (managed identity for Azure, ServiceNow login from Key
Vault). Every VM and storage account in the sandbox carries `request-id` and `expires-on` tags; this runbook walks
them and, for each request, does at most one step per run:

  remind   expires-on - ReminderDays reached: a comment to the requester (they see it in the portal) + work note.
  expire   expires-on reached: an approval "delete <name>?" for the requester. Approving it confirms the deletion.
  delete   the requester approved, or the grace period (GraceDays after expires-on) ended with no approval.
           The resource is deleted (a VM takes its disk and NIC with it), the deletion is recorded as a change
           (model Change Registration), and the request item is closed (Closed Complete,
           u_provisioning_state = deleted). The item stays open until then: ServiceNow's rule "Moot Approvals
           Upon Cancellation" marks approvals on closed tasks not required, so the requester could not confirm.

Nothing is deleted before the requester was asked (step "expire"). A rejected approval does not extend the
resource: extensions are out of scope, so the reply explains that and the grace period still applies.
The step reached is kept in sc_req_item.u_expiry_state (reminded | expired | deleted), so reruns are safe.

Defaults follow the design (reminder 3 days before, 2-day grace). -AsOf runs the logic for another day (India time
by default); -DryRun prints the steps without writing to ServiceNow or Azure.
#>
param(
    [switch]$DryRun,
    [string]$AsOf = '',                 # yyyy-MM-dd; default today in India Standard Time
    [int]$ReminderDays = 3,
    [int]$GraceDays = 2,
    [string]$SandboxResourceGroup = 'rg-skr-prov-sandbox'
)

# ------------------------------------------------------------------ pure functions (tested locally)
function Get-ExpiryAction([datetime]$ExpiresOn, [datetime]$Today, [int]$ReminderDays, [int]$GraceDays,
                          [string]$ExpiryState, [string]$OwnerReply) {
    # Returns @(action, reason). action: none | remind | expire | delete | wait
    $e, $t = $ExpiresOn.Date, $Today.Date
    if ($ExpiryState -eq 'deleted') { return @('none', 'already deleted') }
    if ($t -ge $e) {
        if ($ExpiryState -ne 'expired') { return @('expire', 'expired: ask the requester to confirm the deletion') }
        if ($OwnerReply -eq 'approved') { return @('delete', 'the requester confirmed the deletion') }
        if ($t -ge $e.AddDays($GraceDays)) { return @('delete', "no confirmation within the $GraceDays-day grace period") }
        return @('wait', "waiting for the requester until $($e.AddDays($GraceDays).ToString('yyyy-MM-dd'))")
    }
    if ($t -ge $e.AddDays(-$ReminderDays)) {
        if ($ExpiryState -in @('reminded', 'expired')) { return @('wait', 'reminder already sent') }
        return @('remind', "expires in $(($e - $t).Days) day(s)")
    }
    return @('none', "expires $($e.ToString('yyyy-MM-dd'))")
}

function Get-Tag($Tags, [string]$Name) {
    # Tag names are case-insensitive in Azure; values are trimmed.
    if (-not $Tags) { return '' }
    foreach ($k in @($Tags.Keys)) { if ($k -ieq $Name) { return ([string]$Tags[$k]).Trim() } }
    return ''
}

function Get-ShortId([string]$Id) {
    # Resource ID without the subscription, for text people read (change records, notes, screenshots)
    return ($Id -replace '^/subscriptions/[^/]+/resourceGroups/', '')
}

function Get-ExpiryDate([string]$Value) {
    $d = [datetime]::MinValue
    if ([datetime]::TryParseExact($Value, 'yyyy-MM-dd', $null, 'None', [ref]$d)) { return $d }
    return $null
}

# ------------------------------------------------------------------ ServiceNow REST (same helpers as the provisioning worker)
function Invoke-Snow([string]$Method, [string]$Path, $Body = $null) {
    $p = @{ Method = $Method; Uri = "$script:SnBase$Path"; Headers = $script:SnHeaders; TimeoutSec = 60 }
    if ($Body) { $p.Body = ($Body | ConvertTo-Json -Depth 5 -Compress); $p.ContentType = 'application/json' }
    return Invoke-RestMethod @p
}

function Get-Snow([string]$Table, [string]$Query, [string]$Fields) {
    $q = [uri]::EscapeDataString($Query)
    return (Invoke-Snow GET "/api/now/table/$Table`?sysparm_query=$q&sysparm_fields=$Fields&sysparm_limit=50&sysparm_exclude_reference_link=true").result
}

function Update-Item([string]$SysId, [hashtable]$Fields, [string]$Note, [string]$Comment = '') {
    $body = @{} + $Fields
    if ($Note) { $body.work_notes = $Note }
    if ($Comment) { $body.comments = $Comment }
    if ($script:DryRun) { Write-Output "  [dry run] would update the item: $(($body.Keys | Sort-Object) -join ', ')"; return }
    Invoke-Snow PATCH "/api/now/table/sc_req_item/$SysId" $body | Out-Null
}

function New-ChangeRecord([string]$Number, [string]$What, [string]$Description, [datetime]$Start, [datetime]$End) {
    $model = (Get-Snow 'chg_model' 'name=Change Registration' 'sys_id') | Select-Object -First 1
    $body = @{
        short_description = $What; description = $Description; justification = "Expiry of catalog request $Number."
        correlation_id = 'SYNTH-SKR-PROV'; correlation_display = $Number
        start_date = $Start.ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ss')
        end_date = $End.ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ss')
    }
    if ($model) { $body.chg_model = $model.sys_id }
    $chg = (Invoke-Snow POST '/api/now/table/change_request' $body).result
    # Change Registration keeps its own short description and group (read-only), so the details go in the notes.
    $fix = @{ state = '3'; close_code = 'successful'; close_notes = $What; work_notes = $Description }
    try { Invoke-Snow PATCH "/api/now/table/change_request/$($chg.sys_id)" $fix | Out-Null }
    catch { Write-Output "  change $($chg.number): could not close: $($_.Exception.Message)" }
    return $chg.number
}

# ------------------------------------------------------------------ main
if ($env:SKR_RUNBOOK_TEST) { return }       # tests dot-source the functions above

$ErrorActionPreference = 'Stop'
$today = if ($AsOf) { Get-ExpiryDate $AsOf } else { (Get-Date).ToUniversalTime().AddHours(5.5).Date }
if (-not $today) { throw "AsOf '$AsOf' is not a yyyy-MM-dd date" }

Connect-AzAccount -Identity | Out-Null
$vault = Get-AutomationVariable -Name 'KeyVaultName'
$inst = Get-AzKeyVaultSecret -VaultName $vault -Name 'snow-instance' -AsPlainText
$user = Get-AzKeyVaultSecret -VaultName $vault -Name 'snow-user' -AsPlainText
$pw = Get-AzKeyVaultSecret -VaultName $vault -Name 'snow-password' -AsPlainText
$script:SnBase = "https://$($inst -replace '\.service-now\.com$', '').service-now.com"
$pair = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("${user}:${pw}"))
$script:SnHeaders = @{ Authorization = "Basic $pair"; Accept = 'application/json' }
$pw = $null; $pair = $null

# The requested resources: VMs and storage accounts (a VM's disk and NIC are deleted with it).
$resources = @()
foreach ($vm in @(Get-AzVM -ResourceGroupName $SandboxResourceGroup)) {
    $resources += @{ kind = 'VM'; name = $vm.Name; id = $vm.Id; tags = $vm.Tags }
}
foreach ($st in @(Get-AzStorageAccount -ResourceGroupName $SandboxResourceGroup)) {
    $resources += @{ kind = 'storage account'; name = $st.StorageAccountName; id = $st.Id; tags = $st.Tags }
}
Write-Output "As of $($today.ToString('yyyy-MM-dd')) (reminder $ReminderDays day(s) before, grace $GraceDays day(s)): $($resources.Count) resource(s) in $SandboxResourceGroup$(if ($DryRun) { ' [dry run]' })."

foreach ($r in $resources) {
    $num = Get-Tag $r.tags 'request-id'
    $exp = Get-ExpiryDate (Get-Tag $r.tags 'expires-on')
    if (-not $num -or -not $exp) { Write-Output "$($r.name): no request-id / expires-on tag, left to the drift report"; continue }
    $it = (Get-Snow 'sc_req_item' "number=$num" 'sys_id,number,u_expiry_state,requested_for,requested_for.user_name') | Select-Object -First 1
    if (-not $it) { Write-Output "$($r.name): request $num not found in ServiceNow, left to the drift report"; continue }

    $reply = ''
    if ($it.u_expiry_state -eq 'expired') {
        $ap = (Get-Snow 'sysapproval_approver' "sysapproval=$($it.sys_id)^approver=$($it.requested_for)^ORDERBYDESCsys_created_on" 'sys_id,state') | Select-Object -First 1
        if ($ap) { $reply = $ap.state }
    }
    $action, $why = Get-ExpiryAction $exp $today $ReminderDays $GraceDays $it.u_expiry_state $reply
    Write-Output "$num $($r.name): $action ($why)"
    $expStr = $exp.ToString('yyyy-MM-dd')
    $graceEnd = $exp.AddDays($GraceDays).ToString('yyyy-MM-dd')

    switch ($action) {
        'remind' {
            Update-Item $it.sys_id @{ u_expiry_state = 'reminded' } "Expiry reminder sent ($why)." (
                "Your $($r.kind) $($r.name) expires on $expStr. On that day you will get an approval to confirm its " +
                "deletion; with no reply it is deleted on $graceEnd. Copy anything you need before then. Extensions " +
                "are not offered: order a new one if you still need it.")
        }
        'expire' {
            if ($DryRun) { Write-Output "  [dry run] would ask $($it.'requested_for.user_name') to approve the deletion" }
            else {
                $ap = (Invoke-Snow POST '/api/now/table/sysapproval_approver' @{
                    sysapproval = $it.sys_id; source_table = 'sc_req_item'; document_id = $it.sys_id
                    approver = $it.requested_for; state = 'requested'
                    comments = "Delete $($r.kind) $($r.name)? It expired on $expStr. Approve to delete it now; with no reply it is deleted on $graceEnd." }).result
                $ap = (Get-Snow 'sysapproval_approver' "sys_id=$($ap.sys_id)" 'sys_id,state') | Select-Object -First 1   # read back: rules run after insert
                if ($ap.state -ne 'requested') {
                    # e.g. the requester has no approval rights (approver_user): ServiceNow marks it not required
                    Write-Output "  approval was set to '$($ap.state)' by ServiceNow: the requester cannot confirm"
                    Update-Item $it.sys_id @{} ("The deletion approval for $($it.'requested_for.user_name') was set to " +
                        "'$($ap.state)' by ServiceNow (no approval rights?), so they cannot confirm. Without a " +
                        "confirmation the resource is deleted on $graceEnd.")
                }
            }
            Update-Item $it.sys_id @{ u_expiry_state = 'expired' } "Expired on $expStr. Deletion approval sent to $($it.'requested_for.user_name'); grace period ends $graceEnd." (
                "Your $($r.kind) $($r.name) expired today. Please approve its deletion in My Approvals; with no reply " +
                "it is deleted on $graceEnd.")
        }
        'delete' {
            if ($DryRun) { Write-Output "  [dry run] would delete $($r.id) and record a change"; continue }
            $start = Get-Date
            try {
                if ($r.kind -eq 'VM') {
                    Remove-AzVM -ResourceGroupName $SandboxResourceGroup -Name $r.name -Force | Out-Null   # disk + NIC: deleteOption Delete
                    $sched = (Get-AzContext).Subscription.Id
                    $sched = "/subscriptions/$sched/resourceGroups/$SandboxResourceGroup/providers/Microsoft.DevTestLab/schedules/shutdown-computevm-$($r.name)"
                    try { Remove-AzResource -ResourceId $sched -Force | Out-Null } catch { Write-Output "  auto-shutdown schedule: $($_.Exception.Message)" }
                } else {
                    Remove-AzStorageAccount -ResourceGroupName $SandboxResourceGroup -Name $r.name -Force
                }
                $what = "Deleted expired $($r.kind) $($r.name) for $num (SKR Cloud expiry)"
                $desc = "Automated deletion by the SKR expiry worker.`nRequest: $num`nResource: $(Get-ShortId $r.id)`nExpired: $expStr`nReason: $why."
                $chg = $null
                try { $chg = New-ChangeRecord $num $what $desc $start (Get-Date) }
                catch { Write-Output "  change record failed: $($_.Exception.Message)" }
                Update-Item $it.sys_id @{ u_expiry_state = 'deleted'; u_provisioning_state = 'deleted'; state = '3' } (
                    "Deleted $($r.name) ($why)." + $(if ($chg) { " Recorded as $chg." } else { '' })) (
                    "Your $($r.kind) $($r.name) has been deleted ($why).")
                Write-Output "  deleted$(if ($chg) { " ($chg)" })"
            } catch {
                $msg = $_.Exception.Message
                if ($msg.Length -gt 600) { $msg = $msg.Substring(0, 600) + '...' }
                Update-Item $it.sys_id @{} "Deletion of $($r.name) failed, will retry on the next run: $msg"
                Write-Output "  FAILED: $msg"
            }
        }
    }
}
