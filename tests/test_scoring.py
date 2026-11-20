from evaluation.score import score

T = [{"key": "a", "decision": "reject", "problems": ["private_key"], "changes": {}, "monthly_cost_usd": 10.0, "messy": False},
     {"key": "b", "decision": "approve_with_changes", "problems": ["size_not_allowed"],
      "changes": {"vm_size": "Standard_B2als_v2"}, "monthly_cost_usd": 20.0, "messy": True}]


def test_wrong_approval_and_changes():
    p = [{"key": "a", "decision": "approve", "problems": [], "changes": {}, "monthly_cost_usd": 10.5},
         {"key": "b", "decision": "approve_with_changes", "problems": ["size_not_allowed"],
          "changes": {"vm_size": "Standard_B2als_v2"}, "monthly_cost_usd": 30.0}]
    s = score(p, T)
    assert s["wrong_approvals"] == 1 and s["should_block"] == 1 and s["over_blocked"] == 0
    assert s["changes_exact"] == "1/1" and s["cost_within_10pct"] == "1/2" and s["messy_correct"] == "1/1"
    assert s["problems_precision"] == 1.0 and s["problems_recall"] == 0.5
