#!/usr/bin/env bash
# Upload and publish the runbook code in infra/runbooks/ to the Automation account (Bicep creates them empty).
# Re-run after editing a .ps1.
#   infra/publish-runbooks.sh [resource-group] [automation-account]
set -euo pipefail
RG="${1:-rg-skr-prov-platform}"
AA="${2:-aa-skr-prov}"
API="2023-11-01"
DIR="$(cd "$(dirname "$0")" && pwd)/runbooks"
SUB="$(az account show --query id -o tsv)"
BASE="https://management.azure.com/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Automation/automationAccounts/$AA/runbooks"

for f in "$DIR"/RB-*.ps1; do
  name="$(basename "$f" .ps1)"
  az rest --method put --url "$BASE/$name/draft/content?api-version=$API" \
    --headers "Content-Type=text/powershell" --body @"$f" -o none
  az rest --method post --url "$BASE/$name/publish?api-version=$API" -o none
  echo "$name: $(az rest --method get --url "$BASE/$name?api-version=$API" --query properties.state -o tsv)"
done
