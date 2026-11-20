# agentic-provisioning-servicenow-azure

Self-service Azure provisioning from a ServiceNow catalog. An AI agent checks each request against policy and cost
before a person approves it. One versioned **Template Spec** builds the resource, whether it is deployed from
ServiceNow or from the Azure portal, and **Azure Policy** applies the same rules to both. Secrets stay in **Key
Vault**. Expired resources are cleaned up, and anything created outside the process is reported.

> **Disclaimer:** *ShopKart Retails (SKR)* is a fictional company. All people, requests and records are synthetic.
> No client or employer data is used.

> **Status: in progress.** P1 (Azure platform: Key Vault, worker identity, Template Specs, Policy) deployed
> 2026-11-19. P2 (ServiceNow catalog items and approval flow, [details](servicenow/README.md)) and P3 (validation agent: 0 of
> 17 wrong approvals with Claude, [results](evaluation/README.md)) and P4 (the provisioning worker: first VM built from a
> ServiceNow request, [details](infra/README.md#provisioning-worker-p4)) done 2026-11-20. Design: [docs/design.md](docs/design.md). The live Azure parts must be finished before the Azure trial ends
> (15 December 2026). Infrastructure: [infra/README.md](infra/README.md).

Part of a series on agentic IT operations with ServiceNow:
[incident triage and auto-remediation](https://github.com/asampath1/agentic-aiops-servicenow-azure) ·
[change management](https://github.com/asampath1/agentic-change-management-servicenow) ·
request fulfilment (this repo).
