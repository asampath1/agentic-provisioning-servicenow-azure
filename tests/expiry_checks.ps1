# Local checks for the expiry worker's decision logic (no Azure, no ServiceNow). Run by tests/test_runbook.py.
$env:SKR_RUNBOOK_TEST = '1'
. "$PSScriptRoot/../infra/runbooks/RB-Expire-Resources.ps1"
$fail = 0
function Check($name, $cond) { if (-not $cond) { Write-Output "FAIL $name"; $script:fail++ } }
function Act($today, $state = '', $reply = '', $rem = 1, $grace = 1) {
    return (Get-ExpiryAction ([datetime]'2026-11-23') ([datetime]$today) $rem $grace $state $reply)[0]
}

# the live demo dates: expires 23 Nov, reminder 1 day before, 1-day grace
Check 'quiet before the reminder' ((Act '2026-11-21') -eq 'none')
Check 'reminder on the 22nd' ((Act '2026-11-22') -eq 'remind')
Check 'reminder only once' ((Act '2026-11-22' 'reminded') -eq 'wait')
Check 'expire on the 23rd' ((Act '2026-11-23' 'reminded') -eq 'expire')
Check 'expire even without a reminder' ((Act '2026-11-23') -eq 'expire')
Check 'wait for the reply' ((Act '2026-11-23' 'expired' 'requested') -eq 'wait')
Check 'owner confirms: delete at once' ((Act '2026-11-23' 'expired' 'approved') -eq 'delete')
Check 'grace over: delete' ((Act '2026-11-24' 'expired' 'requested') -eq 'delete')
Check 'rejection does not extend' ((Act '2026-11-24' 'expired' 'rejected') -eq 'delete')
Check 'never delete without asking first' ((Act '2026-11-30' 'reminded') -eq 'expire')
Check 'deleted stays deleted' ((Act '2026-11-30' 'deleted') -eq 'none')
# the design defaults: reminder 3 days before, 2-day grace
Check 'default reminder 3 days before' ((Act '2026-11-20' '' '' 3 2) -eq 'remind')
Check 'default grace still running' ((Act '2026-11-24' 'expired' 'requested' 3 2) -eq 'wait')
Check 'default grace over' ((Act '2026-11-25' 'expired' 'requested' 3 2) -eq 'delete')

Check 'tag names ignore case' ((Get-Tag @{ 'Request-ID' = ' RITM0010005 ' } 'request-id') -eq 'RITM0010005')
Check 'missing tag is empty' ((Get-Tag @{ owner = 'x' } 'expires-on') -eq '')
Check 'bad date' ($null -eq (Get-ExpiryDate 'never'))
Check 'good date' ((Get-ExpiryDate '2026-11-23') -eq [datetime]'2026-11-23')
if ($fail) { exit 1 } else { Write-Output 'ALL OK' }
