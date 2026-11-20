# Validation agent

```bash
python -m agents --out runs/latest                      # the 40 synthetic requests, offline
python -m agents --live-prices --out runs/live          # with today's Azure retail prices
python -m agents --reasoner claude --out runs/claude    # Claude reads the free text for rule 7 (ANTHROPIC_API_KEY)
python -m agents --source servicenow --out runs/pdi     # live PDI requests waiting for approval, dry run
python -m agents --source servicenow --write            # posts the work note and AI fields
```

| Module | Does |
|---|---|
| `validation.py` | One check per rule in [`docs/request-policy.md`](../docs/request-policy.md); the strongest outcome wins (reject > needs information > approve with changes > approve); a work note listing every problem with its rule number, the changes and the cost |
| `pricing.py` | Monthly cost: VM hourly price x 730 h + OS disk; storage per GB-month x 100 GB. Dated snapshot by default, live Azure Retail Prices API with `--live-prices` |
| `text_reader.py` | Optional: Claude reads purpose and justification for rule 7 and must quote the request as evidence; quotes not in the text are rejected; cached; API errors fall back to the regexes |
| `connectors/local.py`, `connectors/servicenow.py` | The synthetic set, or live requested items in the SKR Cloud (Azure) category with `u_cloud_approval = requested` and no AI recommendation yet |

**Guardrails.** The agent only recommends. On ServiceNow it writes a work note and `u_ai_recommendation` /
`u_ai_monthly_cost`, never the approval or the request state, and only with `--write`. A private key pasted into a
request is flagged for rejection and the note tells the requester to replace that key pair.
