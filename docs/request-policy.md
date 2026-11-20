# SKR Cloud sandbox: request policy

This is the policy the validation agent applies to every request from the **SKR Cloud (Azure)** catalog, before a
person from the SKR Cloud Platform team approves it. The agent recommends; the person decides.

## What the sandbox is for

Short-lived **test and development** resources with **synthetic or test data only**. It is not for production
workloads, live customer traffic, or real company, customer or personal data.

## Rules

| # | Rule | If broken |
|---|---|---|
| 1 | VM size is **Standard_B2ats_v2** or **Standard_B2als_v2** | Approve with changes: the largest allowed size (B2als v2) |
| 2 | Storage redundancy is **Standard_LRS** | Approve with changes: LRS |
| 3 | Expiry date is in the future and **at most 30 days** after the request | Too far: approve with changes (30 days). In the past or missing: needs information |
| 4 | The purpose says what the resource is for, in more than a few words | Needs information |
| 5 | The SSH key is a **public** key (`ssh-ed25519` or `ssh-rsa` followed by the key) | Malformed: needs information. A **private** key: reject, and the requester must replace that key pair, because the private key is now in a ticket |
| 6 | Data classification is **synthetic / test data only** | Internal or confidential data: reject |
| 7 | Nothing in the request suggests production use, live customer traffic, or real customer or personal data | Reject |

When several rules are broken, the strongest outcome wins: **reject**, then **needs information**, then **approve
with changes**. The recommendation lists every problem found, not just the first.

## Cost estimate

Each recommendation includes a monthly cost estimate from the Azure retail price list for Central India
(pay-as-you-go, USD):
- **VM:** hourly price x 730 hours (an upper bound: the VM shuts down at 22:00 IST and stays off until started), plus
  the OS disk (Standard HDD S4).
- **Storage account:** the hot-tier price per GB-month for the requested redundancy, for 100 GB.

The estimate is for the configuration as requested. When the recommendation changes it, the note gives both.
