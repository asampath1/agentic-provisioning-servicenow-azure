// Template Spec "vm-linux-test": a small Linux test VM for one approved request.
// The SAME published version is deployed by the ServiceNow worker and from the Azure portal (admins).
// No public IP, SSH key only (no password), auto-shutdown at 22:00 IST, every resource tagged with the request.

@description('ServiceNow request item number, e.g. RITM0010001 (admins deploying from the portal must use one too).')
param requestId string

@description('Expiry date, YYYY-MM-DD (at most 30 days ahead; checked by the validation agent).')
param expiresOn string

@description('Requester user name.')
param owner string

@description('Why the VM is needed (one line).')
@maxLength(120)
param purpose string

@description('VM name, e.g. vm-test-ritm0010001.')
@minLength(3)
@maxLength(40)
param vmName string

@allowed(['Standard_B2ats_v2', 'Standard_B2als_v2'])
param vmSize string = 'Standard_B2ats_v2'

@description('The requester\'s SSH public key (ssh-ed25519 or ssh-rsa). No passwords are ever set.')
param sshPublicKey string

param adminUsername string = 'skradmin'
param vnetName string = 'vnet-skr-sandbox'
param subnetName string = 'snet-requests'
param location string = resourceGroup().location

var tags = {
  'request-id': requestId
  'expires-on': expiresOn
  owner: owner
  purpose: purpose
  'managed-by': 'skr-provisioning'
}

resource subnet 'Microsoft.Network/virtualNetworks/subnets@2023-11-01' existing = {
  name: '${vnetName}/${subnetName}'
}

resource nic 'Microsoft.Network/networkInterfaces@2023-11-01' = {
  name: '${vmName}-nic'
  location: location
  tags: tags
  properties: {
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          privateIPAllocationMethod: 'Dynamic'
          subnet: {
            id: subnet.id
          }
        }
      }
    ]
  }
}

resource vm 'Microsoft.Compute/virtualMachines@2024-03-01' = {
  name: vmName
  location: location
  tags: tags
  properties: {
    hardwareProfile: {
      vmSize: vmSize
    }
    osProfile: {
      computerName: take(replace(vmName, '_', '-'), 15)
      adminUsername: adminUsername
      linuxConfiguration: {
        disablePasswordAuthentication: true
        ssh: {
          publicKeys: [
            {
              path: '/home/${adminUsername}/.ssh/authorized_keys'
              keyData: sshPublicKey
            }
          ]
        }
      }
    }
    storageProfile: {
      imageReference: {
        publisher: 'Canonical'
        offer: '0001-com-ubuntu-server-jammy'
        sku: '22_04-lts-gen2'
        version: 'latest'
      }
      osDisk: {
        name: '${vmName}-osdisk'
        createOption: 'FromImage'
        deleteOption: 'Delete' // deleting the VM removes its disk too (clean expiry)
        managedDisk: {
          storageAccountType: 'Standard_LRS'
        }
      }
    }
    networkProfile: {
      networkInterfaces: [
        {
          id: nic.id
          properties: {
            deleteOption: 'Delete'
          }
        }
      ]
    }
    diagnosticsProfile: {
      bootDiagnostics: {
        enabled: true
      }
    }
  }
}

resource shutdown 'Microsoft.DevTestLab/schedules@2018-09-15' = {
  name: 'shutdown-computevm-${vmName}'
  location: location
  tags: tags
  properties: {
    status: 'Enabled'
    taskType: 'ComputeVmShutdownTask'
    dailyRecurrence: {
      time: '2200'
    }
    timeZoneId: 'India Standard Time'
    targetResourceId: vm.id
  }
}

output vmId string = vm.id
output privateIp string = nic.properties.ipConfigurations[0].properties.privateIPAddress
