// Sandbox resource group: where requested resources land.
// Azure Policy here applies to EVERY deployment, from ServiceNow or the portal: same rules on both paths.

param location string
param tags object
param workerPrincipalId string
param allowedVmSizes array
param allowedStorageSkus array

// Shared network for requested VMs (no public IPs; requested VMs only get a NIC on this subnet).
// It is platform-owned, so it carries request-id "platform" and never expires; the drift agent ignores it.
resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' = {
  name: 'vnet-skr-sandbox'
  location: location
  tags: union(tags, { 'request-id': 'platform', 'expires-on': 'never' })
  properties: {
    addressSpace: {
      addressPrefixes: ['10.60.0.0/16']
    }
    subnets: [
      {
        name: 'snet-requests'
        properties: {
          addressPrefix: '10.60.1.0/24'
        }
      }
    ]
  }
}

// ---------------------------------------------------------------- Azure Policy (built-in definitions)
var policies = [
  {
    name: 'skr-allowed-vm-sizes'
    displayName: 'SKR sandbox: allowed VM sizes'
    definitionId: 'cccc23c7-8427-4f53-ad12-b6a63eb452b3' // Allowed virtual machine size SKUs
    parameters: { listOfAllowedSKUs: { value: allowedVmSizes } }
  }
  {
    name: 'skr-allowed-locations'
    displayName: 'SKR sandbox: allowed region'
    definitionId: 'e56962a6-4747-49cd-b67b-bf8b01975c4c' // Allowed locations
    parameters: { listOfAllowedLocations: { value: [location] } }
  }
  {
    name: 'skr-require-request-id'
    displayName: 'SKR sandbox: every resource needs a request-id tag'
    definitionId: '871b6d14-10aa-478d-b590-94f262ecfa99' // Require a tag on resources (deny)
    parameters: { tagName: { value: 'request-id' } }
  }
  {
    name: 'skr-require-expires-on'
    displayName: 'SKR sandbox: every resource needs an expires-on tag'
    definitionId: '871b6d14-10aa-478d-b590-94f262ecfa99'
    parameters: { tagName: { value: 'expires-on' } }
  }
  {
    name: 'skr-allowed-storage-skus'
    displayName: 'SKR sandbox: allowed storage SKUs'
    definitionId: '7433c107-6db4-4ad1-b57a-a76dce0154a1' // Storage accounts should be limited by allowed SKUs
    parameters: { effect: { value: 'Deny' }, listOfAllowedSKUs: { value: allowedStorageSkus } }
  }
  {
    name: 'skr-storage-https-only'
    displayName: 'SKR sandbox: storage requires secure transfer'
    definitionId: '404c3081-a854-4457-ae30-26a93ef643f9' // Secure transfer to storage accounts should be enabled
    parameters: { effect: { value: 'Deny' } }
  }
  {
    name: 'skr-storage-no-public-blobs'
    displayName: 'SKR sandbox: no public blob access'
    definitionId: '4fa4b6c0-31ca-4c0d-b10d-24b96f62a751' // Storage account public access should be disallowed
    parameters: { effect: { value: 'Deny' } }
  }
  {
    name: 'skr-storage-no-shared-key'
    displayName: 'SKR sandbox: no storage shared keys (Entra ID only)'
    definitionId: '8c6a50c6-9ffd-4ae7-986f-5fa6111f9a54' // Storage accounts should prevent shared key access
    parameters: { effect: { value: 'Deny' } }
  }
]

resource assignments 'Microsoft.Authorization/policyAssignments@2024-04-01' = [for p in policies: {
  name: p.name
  properties: {
    displayName: p.displayName
    policyDefinitionId: tenantResourceId('Microsoft.Authorization/policyDefinitions', p.definitionId)
    parameters: p.parameters
    enforcementMode: 'Default'
    nonComplianceMessages: [
      {
        message: '${p.displayName}. Request resources through the SKR ServiceNow catalog.'
      }
    ]
  }
}]

// ---------------------------------------------------------------- worker permissions (this RG only)
// Enough to deploy the two Template Specs and delete what they created: nothing outside this resource group,
// no role assignments, no policy changes, no other resource types.
resource workerRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' = {
  name: guid(resourceGroup().id, 'skr-provisioning-worker')
  properties: {
    roleName: 'SKR Provisioning Worker (${resourceGroup().name})'
    description: 'Deploys the SKR Template Specs into the sandbox and deletes expired requests. Nothing else.'
    type: 'CustomRole'
    assignableScopes: [resourceGroup().id]
    permissions: [
      {
        actions: [
          'Microsoft.Resources/subscriptions/resourceGroups/read'
          'Microsoft.Resources/deployments/*'
          'Microsoft.Resources/tags/read'
          'Microsoft.Compute/virtualMachines/*'
          'Microsoft.Compute/disks/*'
          'Microsoft.Network/networkInterfaces/*'
          'Microsoft.Network/virtualNetworks/read'
          'Microsoft.Network/virtualNetworks/subnets/read'
          'Microsoft.Network/virtualNetworks/subnets/join/action'
          'Microsoft.DevTestLab/schedules/*'
          'Microsoft.Storage/storageAccounts/*'
        ]
        notActions: [
          'Microsoft.Storage/storageAccounts/listKeys/action'
          'Microsoft.Storage/storageAccounts/regeneratekey/action'
          'Microsoft.Network/virtualNetworks/write'
          'Microsoft.Network/virtualNetworks/delete'
        ]
      }
    ]
  }
}

resource workerAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, workerPrincipalId, workerRole.id)
  properties: {
    roleDefinitionId: workerRole.id
    principalId: workerPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output subnetId string = vnet.properties.subnets[0].id
