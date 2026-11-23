// Platform resource group guard (P6). SYNTH-SKR-PROV
// The portal's Template Spec form defaults to the Template Spec's own resource group, so a portal deployment can land
// here, where none of the sandbox policies apply (found in the P5 drift test). Requested resource types are denied in
// this group: they belong in the sandbox. Key Vault, Automation and Template Specs are not affected.
resource notHere 'Microsoft.Authorization/policyAssignments@2024-04-01' = {
  name: 'skr-platform-no-requested-resources'
  properties: {
    displayName: 'SKR platform: no VMs or storage accounts here (they belong in the sandbox)'
    policyDefinitionId: tenantResourceId('Microsoft.Authorization/policyDefinitions', '6c112d4e-5bc7-47ae-a041-ea2d9dccd749') // Not allowed resource types
    parameters: {
      listOfResourceTypesNotAllowed: {
        value: [
          'Microsoft.Compute/virtualMachines'
          'Microsoft.Compute/disks'
          'Microsoft.Network/networkInterfaces'
          'Microsoft.Storage/storageAccounts'
        ]
      }
    }
    enforcementMode: 'Default'
    nonComplianceMessages: [
      {
        message: 'Requested resources belong in rg-skr-prov-sandbox. Request them through the SKR ServiceNow catalog.'
      }
    ]
  }
}
