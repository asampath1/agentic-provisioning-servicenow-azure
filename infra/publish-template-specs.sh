#!/usr/bin/env bash
# Publish the request templates as versioned Template Specs in the platform resource group.
# The ServiceNow worker and the Azure portal (admins) both deploy these exact versions.
#
#   infra/publish-template-specs.sh            # publish version 1.0 of both
#   VERSION=1.1 infra/publish-template-specs.sh
set -euo pipefail
cd "$(dirname "$0")"
RG=${RG:-rg-skr-prov-platform}
LOCATION=${LOCATION:-centralindia}
VERSION=${VERSION:-1.0}

publish() {
  local name=$1 file=$2 desc=$3
  echo "== $name $VERSION"
  az ts create --resource-group "$RG" --location "$LOCATION" --name "$name" --version "$VERSION" \
    --template-file "$file" --display-name "$name" --description "$desc" \
    --version-description "Published $(date -u +%Y-%m-%d) from $(git rev-parse --short HEAD 2>/dev/null || echo local)" \
    --tags project=skr-provisioning managed-by=publish-template-specs --yes -o none
  az ts show --resource-group "$RG" --name "$name" --version "$VERSION" --query id -o tsv
}

publish vm-linux-test templates/vm-linux-test.bicep \
  "SKR catalog: small Linux test VM (no public IP, SSH key only, auto-shutdown 22:00 IST)"
publish storage-account templates/storage-account.bicep \
  "SKR catalog: locked-down storage account (HTTPS/TLS1.2, no public blobs, no shared keys)"
