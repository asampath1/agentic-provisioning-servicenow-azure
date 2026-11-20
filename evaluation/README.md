# Evaluation

`score.py` compares a validation run with the answer key (`synthetic-data/data/ground_truth.json`). It is the only
code that reads the answer key; `tests/test_answer_key_isolation.py` checks that the agents never do.

```bash
python -m agents --out runs/latest && python -m evaluation.score runs/latest
```

## Metrics

| Metric | What it checks |
|---|---|
| **Wrong approvals** | Requests that should be rejected or sent back for information, recommended for approval (with or without changes). The safety metric; target 0 |
| Over-blocking | Fine or fixable requests that were rejected or sent back (wasted requester time) |
| Decision accuracy, macro F1 | Approve / approve with changes / needs information / reject |
| Problems found | Precision and recall of the policy problems listed (a request can have several) |
| Exact changes | For approve-with-changes: the recommended size, redundancy and expiry match exactly |
| Cost estimate | Within 10% of the expected monthly cost |
| Messy subset | The 4 requests whose only problem is production use or real data, worded without the policy's words |

## Heuristic baseline (no LLM)

| Metric | Result |
|---|---|
| **Wrong approvals** | **4 of 17** |
| Over-blocking | 0 |
| Decision accuracy / macro F1 | 90% / 0.91 |
| Problems found (precision / recall) | 1.0 / 0.86 |
| Exact changes | 9 of 9 |
| Cost within 10% | 40 of 40 |
| Messy subset | 0 of 4 |

What this shows:
- **The structured rules are solved.** Sizes, redundancy, expiry, data classification and SSH keys (including a
  pasted private key) are all right, and the changes and costs are exact.
- **All 4 wrong approvals are the messy requests.** "Shoppers will hit this box for the Black Friday checkout"
  describes production use without the words the policy regexes look for. Reading that is the job of the Claude
  reader (`--reasoner claude`).
- **The cost check is easy here.** The answer key's costs come from the same dated price snapshot the agent uses
  offline, so 40 of 40 shows the formula is applied right, not that the prices are current. `--live-prices` uses
  today's Azure retail prices.

## Claude reads the free text (rule 7)

One change from the baseline: Claude (`claude-opus-5-5`) reads each request's purpose, justification and data
classification for rule 7, and must quote the request as evidence. Everything else is the same code.

| Metric | Heuristic | Claude |
|---|---|---|
| **Wrong approvals** | **4 of 17** | **0 of 17** |
| Over-blocking | 0 | 0 |
| Decision accuracy / macro F1 | 90% / 0.91 | 100% / 1.0 |
| Problems found (precision / recall) | 1.0 / 0.86 | 0.93 / 1.0 |
| Messy subset | 0 of 4 | 4 of 4 |
| Cost | - | $0.04 (40 requests, 4 calls, 4,132 in / 1,285 out tokens) |

- **All 4 messy requests rejected**, each with a quote, for example "Our storefront points its DNS here while the
  main web tier is rebuilt next week". No quote was rejected and no call fell back to the regexes.
- **The lower precision is 2 extra flags**, on requests already rejected for their data classification ("Shared
  folder for the team's planning spreadsheets", internal; "Archive of signed supplier contracts", confidential).
  Claude also called these real company data, which is arguably right; the answer key lists only the
  classification problem. The decisions are unaffected. I worked this out by comparing the two runs' outputs.
- **Limits.** One run. I wrote both the messy phrasings and the rule-7 definition Claude gets, so the definition
  was not written blind to the test wording; I wrote it once, before the run, and did not change it after.

Results: [`results/heuristic/`](results/heuristic/report.md) and [`results/claude/`](results/claude/report.md)
(including each rule-7 quote, `claude_rule7.json`).
