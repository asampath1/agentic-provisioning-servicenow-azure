# Sandbox drift report (2026-11-25)

Source: synthetic inventory. 84 resource(s), 32 SKR Cloud request(s). Report only: nothing was changed.

19 finding(s):

| Request / resource | Resources | Problems |
|---|---|---|
| RITM9999001 | stportaltest01 | **unknown_request**: RITM9999001 is not an SKR Cloud request in ServiceNow |
| RITM9999002 | shutdown-computevm-vm-portal-test, vm-portal-test, vm-portal-test-nic, vm-portal-test-osdisk | **unknown_request**: RITM9999002 is not an SKR Cloud request in ServiceNow |
| RITM0010146 | shutdown-computevm-vm-test-ritm0010146, vm-test-ritm0010146, vm-test-ritm0010146-nic, vm-test-ritm0010146-osdisk | **not_approved**: RITM0010146 is 'requested' |
| RITM0010149 | stskrritm0010149 | **not_approved**: RITM0010149 is 'rejected' |
| RITM0010153 | shutdown-computevm-vm-test-ritm0010153, vm-test-ritm0010153, vm-test-ritm0010153-nic, vm-test-ritm0010153-osdisk | **request_closed**: RITM0010153 is 'cancelled' but its resources exist |
| RITM0010156 | stskrritm0010156 | **request_closed**: RITM0010156 is 'deleted' but its resources exist |
| stadhoctest01 | stadhoctest01 | **no_request_tag**: storageAccounts stadhoctest01 has no request-id tag |
| vm-old-demo-osdisk | vm-old-demo-osdisk | **no_request_tag**: disks vm-old-demo-osdisk has no request-id tag |
| RITM0010160 | shutdown-computevm-vm-test-ritm0010160, vm-test-ritm0010160, vm-test-ritm0010160-nic, vm-test-ritm0010160-osdisk | **outside_worker**: RITM0010160 is approved but was not built by the worker, which would build it again |
| RITM0010163 | shutdown-computevm-vm-test-ritm0010163, vm-test-ritm0010163, vm-test-ritm0010163-nic, vm-test-ritm0010163-osdisk | **expired**: expired 2026-11-20, grace ended 2026-11-22 |
| RITM0010167 | stskrritm0010167 | **expired**: expired 2026-11-22, grace ended 2026-11-24 |
| RITM0010169 | shutdown-computevm-vm-test-ritm0010169, vm-test-ritm0010169, vm-test-ritm0010169-nic, vm-test-ritm0010169-osdisk | **differs_from_request**: size Standard_B2als_v2, approved Standard_B2ats_v2 |
| RITM0010173 | shutdown-computevm-vm-test-ritm0010173, vm-test-ritm0010173, vm-test-ritm0010173-nic, vm-test-ritm0010173-osdisk | **differs_from_request**: size Standard_B2als_v2, approved Standard_B2ats_v2 |
| RITM0010176 | stskrritm0010176 | **differs_from_request**: expires-on 2027-01-11, request says 2026-12-12 |
| RITM0010179 | shutdown-computevm-vm-test-ritm0010179, vm-test-ritm0010179, vm-test-ritm0010179-nic, vm-test-ritm0010179-osdisk | **differs_from_request**: a VM carries a request for 'Azure storage account' |
| RITM0010183 | vm-test-ritm0010183, vm-test-ritm0010183-nic | **no_expiry_tag**: no valid expires-on tag |
| RITM0010186 | (none) | **missing**: RITM0010186 says built, but nothing in the sandbox carries it |
| RITM0010189 | (none) | **missing**: RITM0010189 says built, but nothing in the sandbox carries it |
| stskrportal0001 | stskrportal0001 | **outside_sandbox**: storageAccounts stskrportal0001 (request RITM9999003) is in rg-skr-prov-platform, outside the sandbox |
