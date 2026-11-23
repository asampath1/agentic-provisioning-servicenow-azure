# What this project is about (no technical background needed)

## The problem

Developers and testers often need a cloud server or a storage space for a few days: to try a new version, run a
load test or train new joiners. In many companies they ask for it through a service portal such as **ServiceNow**,
and someone in the cloud team creates it by hand.

That is slow, and it goes wrong in familiar ways:

1. **Requests are not checked properly.** Someone asks for a large, expensive server "just in case", or for a test
   box that will quietly hold real customer data.
2. **Nobody knows what it costs** until the bill arrives.
3. **Things are never deleted.** The test server from three months ago is still running and still costing money.
4. **Things appear outside the process.** An admin creates something directly in the cloud console, and nobody
   knows who it belongs to or when it can go.

## What this project does

It automates the whole life of a test resource on **Microsoft Azure**, from the request in ServiceNow to its
deletion, with AI **agents** doing the checking and **people making every decision**:

| Step | Who does it | In everyday terms |
|---|---|---|
| Ask | the employee | Orders a "Linux test VM" or a "storage account" in the ServiceNow portal, with a purpose and an expiry date (at most 30 days) |
| Check | validation agent (AI) | Checks the request against the company's written cloud policy (7 rules) and estimates the monthly cost from Azure's public price list. Recommends: approve, approve with changes (e.g. a smaller size), ask for more information, or reject |
| Decide | a person in the cloud team | Approves or rejects. Nobody can approve their own request |
| Build | provisioning worker (automation in Azure) | Builds exactly what was approved, from one standard template, and records it as a change in ServiceNow |
| Remind and clean up | expiry worker | Reminds the owner before the expiry date, asks them to confirm the deletion, deletes the resource (after their OK, or after a short grace period) and records that too |
| Watch | drift agent (AI) | Compares what is really in Azure with the approved requests, and reports anything that has no approved request, is past its expiry, or differs from what was approved |

## The safety rules

- **The AI only recommends.** It writes a note on the request. A person approves.
- **The worker only builds what the AI and a person both accepted.** If a person approves something the agent
  flagged for rejection, it is not built.
- **Azure enforces the same rules again** (Azure Policy): allowed sizes, one region, required tags, no public
  storage. A request that slips through the checks is still refused by Azure.
- **No secret passwords in ServiceNow, and no Azure passwords at all.** ServiceNow never connects to Azure; the
  worker in Azure fetches approved requests and uses its own managed identity. The one ServiceNow password it needs
  is kept in Azure Key Vault.
- **Nothing is deleted without asking the owner first.**
- **The drift agent only reports.** It never deletes anything itself.

## What it demonstrates

**Checking requests.** I tested the validation agent on **40 requests** with known right answers, hidden from the
agent. The hardest ones describe production use or real data without using those words ("Shoppers will hit this
box for the Black Friday checkout").

| Question | Rules only | With Claude reading the text |
|---|---|---|
| Requests that should be rejected or sent back, but were recommended for approval | 4 of 17 | **0 of 17** |
| Recommendations matching the right answer | 90% | **100%** |
| Cost estimates within 10% | 40 of 40 | 40 of 40 |

Claude, a language model, does just one job here: it reads the free text of each request and must quote the exact
words that show a problem. Reading all 40 requests cost about four US cents.

**Finding drift.** On a synthetic Azure inventory with 19 planted problems (made-up request numbers, a server
resized after approval, an expiry date extended by hand, leftovers without an owner) and 16 clean look-alikes, the
drift agent found all 19 and raised no false alarms. I wrote the planted problems and the rules from the same
definitions, so this checks that the rules do what they say rather than proving they would find every real case.

**Live, end to end.** Two real servers went through the whole life on the ServiceNow system and Azure: ordered,
checked, approved, built, reminded, confirmed by the owner, deleted, each step recorded in ServiceNow
([screenshots](live-demo.md)). A third test, deploying straight from the Azure console with a made-up request
number, was caught by the drift agent, which opened a ticket for the cloud team.

## What I learned

The live runs found problems the offline tests could not. ServiceNow silently cancels approvals on closed requests,
so the owner could never confirm a deletion until the request stayed open while the server existed. The Azure
console deploys into a different place than expected by default, where the safety rules did not apply. Each is now
fixed and written up in the [live demo](live-demo.md).

## What is real and what is made up

- **Real:** the ServiceNow system (a free developer instance), the Azure subscription (a free trial), the templates,
  the policies, the agents, the automation and the scoring.
- **Made up:** the company. *ShopKart Retails* is a fictional retailer, and its employees and requests are
  synthetic. No client or employer data is used.

This is the third project in a series on AI agents for IT operations with ServiceNow, after
[incident triage](https://github.com/asampath1/agentic-aiops-servicenow-azure) and
[change management](https://github.com/asampath1/agentic-change-management-servicenow).
