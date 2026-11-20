# Synthetic requests (P3 evaluation set)

`generate_requests.py` writes 40 catalog requests (`data/requests.json`, what the agent sees) and their right
answers (`data/ground_truth.json`, read only by the scorer). Seed 11; requests dated 16-20 November 2026.

| Decision | Requests | Examples |
|---|---|---|
| approve | 14 | allowed size or LRS, clear purpose, expiry within 30 days, valid public key, test data |
| approve with changes | 9 | D-series VM, ZRS / GRS storage, expiry 45-120 days |
| needs information | 7 | vague purpose ("test", "for work"), malformed SSH key, expiry in the past |
| reject | 10 | private key pasted, internal or confidential data, production use or real data |

Every answer follows from [`docs/request-policy.md`](../docs/request-policy.md). Four rejects are the **messy subset**:
their only problem is production use or real data, worded without the policy's own words ("shoppers will hit this
box for the Black Friday checkout"). Costs use `data/prices.json`, a dated snapshot of the Azure retail prices for
Central India.

All people and requests are synthetic. SSH keys are random bytes in the right format, not real keys.
