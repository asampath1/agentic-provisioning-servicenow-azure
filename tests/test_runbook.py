"""Runs the worker runbook's decision logic in PowerShell (skipped when pwsh is not installed)."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = (ROOT / "infra/runbooks/RB-Provision-Requests.ps1").read_text()


EXPIRY = (ROOT / "infra/runbooks/RB-Expire-Resources.ps1").read_text()


@pytest.mark.skipif(not shutil.which("pwsh"), reason="pwsh not installed")
@pytest.mark.parametrize("checks", ["runbook_checks.ps1", "expiry_checks.ps1"])
def test_runbook_logic(checks):
    r = subprocess.run(["pwsh", "-NoProfile", "-File", str(ROOT / "tests" / checks)],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and "ALL OK" in r.stdout, r.stdout + r.stderr


def test_parameter_names_match_the_template_specs():
    for spec, names in (("vm-linux-test", "requestId expiresOn owner purpose vmName vmSize sshPublicKey"),
                        ("storage-account", "requestId expiresOn owner purpose storageName skuName")):
        bicep = (ROOT / f"infra/templates/{spec}.bicep").read_text()
        declared = set(re.findall(r"^param (\w+)", bicep, re.M))
        assert set(names.split()) <= declared, spec


def test_no_secrets_and_only_its_own_items():
    assert not re.search(r"password\s*=\s*['\"]", RUNBOOK, re.I)
    assert "Get-AzKeyVaultSecret" in RUNBOOK and "Connect-AzAccount -Identity" in RUNBOOK
    assert "u_cloud_approval=approved" in RUNBOOK and "u_provisioning_stateISEMPTY" in RUNBOOK


def test_expiry_worker_secrets_and_scope():
    assert not re.search(r"password\s*=\s*['\"]", EXPIRY, re.I)
    assert "Get-AzKeyVaultSecret" in EXPIRY and "Connect-AzAccount -Identity" in EXPIRY
    # only the sandbox, and only what the worker role may delete
    assert re.search(r"\$SandboxResourceGroup = 'rg-skr-prov-sandbox'", EXPIRY)
    assert "Remove-AzResourceGroup" not in EXPIRY
    # defaults are the design's (reminder 3 days, 2-day grace); the demo passes 1 / 1
    assert "[int]$ReminderDays = 3" in EXPIRY and "[int]$GraceDays = 2" in EXPIRY


def test_both_runbooks_are_declared_in_bicep():
    bicep = (ROOT / "infra/modules/platform.bicep").read_text()
    for f in (ROOT / "infra/runbooks").glob("RB-*.ps1"):
        assert f"name: '{f.stem}'" in bicep, f.stem
