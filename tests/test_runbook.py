"""Runs the worker runbook's decision logic in PowerShell (skipped when pwsh is not installed)."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = (ROOT / "infra/runbooks/RB-Provision-Requests.ps1").read_text()


@pytest.mark.skipif(not shutil.which("pwsh"), reason="pwsh not installed")
def test_runbook_logic():
    r = subprocess.run(["pwsh", "-NoProfile", "-File", str(ROOT / "tests/runbook_checks.ps1")],
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
