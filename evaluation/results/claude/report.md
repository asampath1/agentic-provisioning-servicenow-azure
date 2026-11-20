# Validation scores (40 requests)

| Metric | Result |
|---|---|
| **Wrong approvals** (should be rejected or sent back, recommended for approval) | **0 of 17** |
| Over-blocking (fine or fixable, but rejected or sent back) | 0 |
| Decision accuracy / macro F1 | 100% / 1.0 |
| Problems found (precision / recall) | 0.933 / 1.0 |
| Approve-with-changes: exact changes | 9/9 |
| Cost estimate within 10% | 40/40 (mean error 0.0%) |
| Messy subset (production or real data in other words): decision right | 4/4 |

Decision confusion (rows = truth, columns = predicted):

| truth \ predicted | approve | approve_with_changes | need_info | reject |
|---|---|---|---|---|
| approve | 14 | 0 | 0 | 0 |
| approve_with_changes | 0 | 9 | 0 | 0 |
| need_info | 0 | 0 | 7 | 0 |
| reject | 0 | 0 | 0 | 10 |
