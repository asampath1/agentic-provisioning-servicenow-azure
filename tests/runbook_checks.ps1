# Local checks for the worker's decision logic (no Azure, no ServiceNow). Run by tests/test_runbook.py.
$env:SKR_RUNBOOK_TEST = '1'
. "$PSScriptRoot/../infra/runbooks/RB-Provision-Requests.ps1"
$fail = 0
function With($h, $o) { $r = @{} + $h; foreach ($k in $o.Keys) { $r[$k] = $o[$k] }; return $r }
function Check($name, $cond) { if (-not $cond) { Write-Output "FAIL $name"; $script:fail++ } }

Check 'approve builds' ((Get-BuildDecision 'approve') -eq 'build')
Check 'changes build' ((Get-BuildDecision 'approve_with_changes') -eq 'build')
Check 'reject blocked' ((Get-BuildDecision 'reject') -eq 'block')
Check 'need_info blocked' ((Get-BuildDecision 'need_info') -eq 'block')
Check 'not validated waits' ((Get-BuildDecision '') -eq 'wait')

$today = [datetime]'2026-11-20'
$key = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBr9xyz me@pc'
$vm = @{ purpose = 'Load test with generated data'; vm_size = 'Standard_D4s_v5'; expires_on = '2026-12-31'; ssh_public_key = $key }
$merged = Merge-Changes $vm '{"vm_size": "Standard_B2als_v2", "expires_on": "2026-12-20"}'
Check 'changes applied' ($merged.vm_size -eq 'Standard_B2als_v2' -and $merged.expires_on -eq '2026-12-20')
Check 'original untouched' ($vm.vm_size -eq 'Standard_D4s_v5')
Check 'merged passes policy' ((Test-Policy 'Azure Linux test VM' $merged $today).Count -eq 0)
Check 'unmerged fails policy' ((Test-Policy 'Azure Linux test VM' $vm $today).Count -eq 2)
Check 'private key blocked' ((Test-Policy 'Azure Linux test VM' (With $merged @{ ssh_public_key = "-----BEGIN OPENSSH PRIVATE KEY-----" }) $today).Count -eq 1)
Check 'past expiry blocked' ((Test-Policy 'Azure Linux test VM' (With $merged @{ expires_on = '2026-11-19' }) $today).Count -eq 1)
$st = @{ purpose = 'fixtures'; redundancy = 'Standard_GRS'; data_classification = 'synthetic'; expires_on = '2026-12-01' }
Check 'GRS blocked' ((Test-Policy 'Azure storage account' $st $today).Count -eq 1)
Check 'GRS changed to LRS passes' ((Test-Policy 'Azure storage account' (Merge-Changes $st '{"redundancy": "Standard_LRS"}') $today).Count -eq 0)
Check 'internal data blocked' ((Test-Policy 'Azure storage account' (With $st @{ redundancy = 'Standard_LRS'; data_classification = 'internal' }) $today).Count -eq 1)

$plan = Get-DeploymentPlan 'Azure Linux test VM' 'RITM0010005' 'synth.aditya.banerjee' $merged
Check 'vm spec' ($plan.spec -eq 'vm-linux-test' -and $plan.name -eq 'vm-test-ritm0010005' -and $plan.deployment -eq 'skr-ritm0010005')
Check 'vm params' ($plan.parameters.requestId -eq 'RITM0010005' -and $plan.parameters.vmSize -eq 'Standard_B2als_v2' -and $plan.parameters.owner -eq 'synth.aditya.banerjee')
Check 'vm param names' ((@($plan.parameters.Keys) | Sort-Object) -join ',' -eq 'expiresOn,owner,purpose,requestId,sshPublicKey,vmName,vmSize')
$long = Get-DeploymentPlan 'Azure storage account' 'RITM0010005' 'x' (With $st @{ purpose = ('a' * 200); redundancy = 'Standard_LRS' })
Check 'storage name' ($long.name -eq 'stskrritm0010005' -and $long.parameters.skuName -eq 'Standard_LRS')
Check 'purpose capped at 120' ($long.parameters.purpose.Length -eq 120)
if ($fail) { exit 1 } else { Write-Output 'ALL OK' }
