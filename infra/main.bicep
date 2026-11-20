// P1: the platform for self-service provisioning (subscription scope).
//
//   rg-skr-prov-platform  Key Vault (ServiceNow API login), Template Specs, the provisioning worker
//                         (Automation account with a system-assigned managed identity)
//   rg-skr-prov-sandbox   where requested resources land; Azure Policy enforces sizes, tags, region and
//                         storage security here, whether a deployment comes from ServiceNow or the portal
//
// No secrets in this template. The ServiceNow password is added to Key Vault afterwards, by hand (see README).
//
//   az deployment sub what-if --location centralindia -f infra/main.bicep -p adminObjectId=<your object id>
targetScope = 'subscription'

@description('Region for the resource groups, Key Vault, Template Specs and requested resources.')
param location string = 'centralindia'

// Free trials may create Automation accounts only in eastus, eastus2, westus, northeurope, southeastasia and japanwest,
// one per region; southeastasia is still held by the deleted v1 account, so Japan West.
@description('Region for the Automation account (the worker).')
param automationLocation string = 'japanwest'

@description('Object ID of the admin who may write Key Vault secrets (az ad signed-in-user show --query id -o tsv).')
param adminObjectId string

param platformRgName string = 'rg-skr-prov-platform'
param sandboxRgName string = 'rg-skr-prov-sandbox'

@description('VM sizes requesters may choose (the trial is limited to small, non-zonal B-series).')
param allowedVmSizes array = ['Standard_B2ats_v2', 'Standard_B2als_v2']

@description('Storage SKUs requesters may choose.')
param allowedStorageSkus array = ['Standard_LRS']

var tags = {
  project: 'skr-provisioning'
  'data-classification': 'synthetic'
  'managed-by': 'bicep'
}

resource platformRg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: platformRgName
  location: location
  tags: tags
}

resource sandboxRg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: sandboxRgName
  location: location
  tags: tags
}

module platform 'modules/platform.bicep' = {
  name: 'skr-prov-platform'
  scope: platformRg
  params: {
    location: location
    automationLocation: automationLocation
    adminObjectId: adminObjectId
    tags: tags
  }
}

module sandbox 'modules/sandbox.bicep' = {
  name: 'skr-prov-sandbox'
  scope: sandboxRg
  params: {
    location: location
    tags: tags
    workerPrincipalId: platform.outputs.workerPrincipalId
    allowedVmSizes: allowedVmSizes
    allowedStorageSkus: allowedStorageSkus
  }
}

output keyVaultName string = platform.outputs.keyVaultName
output automationAccountName string = platform.outputs.automationAccountName
output workerPrincipalId string = platform.outputs.workerPrincipalId
output sandboxSubnetId string = sandbox.outputs.subnetId
