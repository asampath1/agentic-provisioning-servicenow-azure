# agentic-provisioning-servicenow-azure

Self-service Azure provisioning from a ServiceNow catalog. An AI agent checks each request against policy and cost
before a person approves it. One versioned **Template Spec** builds the resource, whether it is deployed from
ServiceNow or from the Azure portal, and **Azure Policy** applies the same rules to both. Secrets stay in **Key
Vault**. Expired resources are cleaned up, and anything created outside the process is reported.

> **Disclaimer:** *ShopKart Retails (SKR)* is a fictional company. All people, requests and records are synthetic.
> No client or employer data is used.

> **Status: complete (live Azure parts until the trial ends, 15 December 2026).** One VM went from a ServiceNow
> request to its deletion, live: validated, approved, built from a Template Spec, reminded, confirmed by the owner,
> deleted, every step recorded ([live demo](docs/live-demo.md)). Validation agent: 0 of 17 wrong approvals with
> Claude reading the text, 4 of 17 with rules only ([results](evaluation/README.md)). Drift agent: 0 of 19 missed on
> a synthetic inventory, and a live portal deployment with a made-up request id caught. Plain-language summary:
> [docs/overview.md](docs/overview.md). Design: [docs/design.md](docs/design.md). Infrastructure:
> [infra/README.md](infra/README.md).

Part of a series on agentic IT operations with ServiceNow:
[incident triage and auto-remediation](https://github.com/asampath1/agentic-aiops-servicenow-azure) ·
[change management](https://github.com/asampath1/agentic-change-management-servicenow) ·
request fulfilment (this repo).
