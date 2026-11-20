// Platform resource group: Key Vault, the provisioning worker and (published separately) the Template Specs.

param location string
param automationLocation string
param adminObjectId string
param tags object

param automationAccountName string = 'aa-skr-prov'

// Key Vault names are global; 'kvskrprov' + 8 characters stays under the 24-character limit.
var keyVaultName = 'kvskrprov${take(uniqueString(resourceGroup().id), 8)}'

var roles = {
  keyVaultSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
  keyVaultSecretsOfficer: 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
  templateSpecReader: '392ae280-861d-42bd-9ea5-08ee6d83b80e'
}

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true // access by Entra ID roles only, no access policies
    softDeleteRetentionInDays: 7 // shortest allowed: the vault is torn down at the end of the trial
    publicNetworkAccess: 'Enabled'
  }
}

// The worker: polls ServiceNow for approved requests, deploys Template Specs into the sandbox.
// Its runbooks are published separately (P4). disableLocalAuth: no webhooks or shared keys.
resource aa 'Microsoft.Automation/automationAccounts@2023-11-01' = {
  name: automationAccountName
  location: automationLocation
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    sku: {
      name: 'Basic'
    }
    publicNetworkAccess: true
    disableLocalAuth: true
  }
}

resource kvVar 'Microsoft.Automation/automationAccounts/variables@2023-11-01' = {
  parent: aa
  name: 'KeyVaultName'
  properties: {
    value: '"${kv.name}"'
    isEncrypted: false
    description: 'Vault holding the ServiceNow API login (secret names: snow-instance, snow-user, snow-password).'
  }
}

// The worker's runbook (P4). Bicep creates it empty; infra/publish-runbooks.sh uploads and publishes the code.
// No schedule yet: it is started by hand (az automation runbook start) until the demo, then hourly.
resource provisionRunbook 'Microsoft.Automation/automationAccounts/runbooks@2023-11-01' = {
  parent: aa
  name: 'RB-Provision-Requests'
  location: automationLocation
  tags: tags
  properties: {
    runbookType: 'PowerShell72'
    logProgress: false
    logVerbose: false
    description: 'Builds approved SKR Cloud catalog requests from the Template Specs (pull model). SYNTH-SKR-PROV'
  }
}

// Worker may READ secrets in this vault (not write or delete them).
resource workerSecrets 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, aa.id, roles.keyVaultSecretsUser)
  scope: kv
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.keyVaultSecretsUser)
    principalId: aa.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// The admin (you) may write secrets; nobody else.
resource adminSecrets 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, adminObjectId, roles.keyVaultSecretsOfficer)
  scope: kv
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.keyVaultSecretsOfficer)
    principalId: adminObjectId
    principalType: 'User'
  }
}

// Worker may read the Template Specs published in this resource group (to deploy them into the sandbox).
resource workerTemplateSpecs 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, aa.id, roles.templateSpecReader)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.templateSpecReader)
    principalId: aa.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

output keyVaultName string = kv.name
output automationAccountName string = aa.name
output workerPrincipalId string = aa.identity.principalId
