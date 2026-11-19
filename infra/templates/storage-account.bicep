// Template Spec "storage-account": a locked-down storage account for one approved request.
// HTTPS and TLS 1.2 only, no public blob access, no shared keys (Entra ID access only), tagged with the request.

@description('ServiceNow request item number, e.g. RITM0010002.')
param requestId string

@description('Expiry date, YYYY-MM-DD.')
param expiresOn string

param owner string

@maxLength(120)
param purpose string

@description('Globally unique, 3-24 lowercase letters and digits, e.g. stskrritm0010002.')
@minLength(3)
@maxLength(24)
param storageName string

@allowed(['Standard_LRS'])
param skuName string = 'Standard_LRS'

param location string = resourceGroup().location

resource st 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  tags: {
    'request-id': requestId
    'expires-on': expiresOn
    owner: owner
    purpose: purpose
    'managed-by': 'skr-provisioning'
  }
  sku: {
    name: skuName
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
  }
}

output storageId string = st.id
output blobEndpoint string = st.properties.primaryEndpoints.blob
