"""What P2 puts on the ServiceNow PDI: two catalog items, their variables, an approver group, request fields and
the approval business rules. ``catalog.py`` creates or updates exactly this, idempotently.

The variable names and choices line up with the Template Spec parameters (``infra/templates/*.bicep``). The form
deliberately offers a few options the sandbox policy does NOT allow (bigger VM sizes, geo-redundant storage): real
catalogs get such requests, and catching them before approval is the validation agent's job (P3). Azure Policy
would deny them anyway.
"""
from pathlib import Path

TAG = "SYNTH-SKR-PROV"
SCRIPTS = Path(__file__).parent / "scripts"

APPROVER_GROUP = {"name": "SKR Cloud Platform",
                  "description": f"Approves Azure self-service requests from the SKR Cloud catalog. {TAG}"}
APPROVERS = ["admin"]          # the PDI admin, so the demo can approve; add the cloud team in a real setup

CATALOG = "Service Catalog"
CATEGORY = {"title": "SKR Cloud (Azure)",
            "description": f"Self-service Azure resources for test and development. Every request is checked "
                           f"against policy and cost, then approved by the cloud platform team. {TAG}"}

# item_option_new.type values
SINGLE_LINE, MULTI_LINE, SELECT, DATE = "6", "2", "5", "9"

EXPIRY_HELP = "At most 30 days from today. The resource is deleted after this date (you get a reminder 3 days before)."
COMMON_TOP = [
    {"name": "purpose", "question_text": "What is it for?", "type": SINGLE_LINE, "mandatory": "true",
     "help_text": "One line, for example: load test of the orders API before the December release."},
]
COMMON_BOTTOM = [
    {"name": "expires_on", "question_text": "Delete after (expiry date)", "type": DATE, "mandatory": "true",
     "help_text": EXPIRY_HELP},
    {"name": "justification", "question_text": "Justification (needed for sizes or options marked so)",
     "type": MULTI_LINE, "mandatory": "false"},
]

ITEMS = [
    {
        "name": "Azure Linux test VM",
        "short_description": "A small Ubuntu VM in the SKR sandbox, with no public IP and SSH key login only.",
        "description": ("Ubuntu 22.04 in the SKR sandbox network (no public IP), SSH key login only, shut down "
                        "every night at 22:00 IST, deleted on the expiry date. Built from the vm-linux-test "
                        "Template Spec."),
        "template_spec": "vm-linux-test",
        "variables": COMMON_TOP + [
            {"name": "vm_size", "question_text": "Size", "type": SELECT, "mandatory": "true",
             "default_value": "Standard_B2ats_v2",
             "choices": [("Standard_B2ats_v2", "B2ats v2: 2 vCPU, 1 GiB (smallest, cheapest)"),
                         ("Standard_B2als_v2", "B2als v2: 2 vCPU, 4 GiB"),
                         ("Standard_D2s_v5", "D2s v5: 2 vCPU, 8 GiB (needs justification)"),
                         ("Standard_D4s_v5", "D4s v5: 4 vCPU, 16 GiB (needs justification)")]},
            {"name": "ssh_public_key", "question_text": "Your SSH public key", "type": MULTI_LINE,
             "mandatory": "true", "help_text": "One line starting with ssh-ed25519 or ssh-rsa. Never a private key."},
        ] + COMMON_BOTTOM,
    },
    {
        "name": "Azure storage account",
        "short_description": "A private storage account in the SKR sandbox (HTTPS only, Entra ID access, no keys).",
        "description": ("StorageV2 in the SKR sandbox: HTTPS and TLS 1.2 only, no public blob access, no shared "
                        "keys (Entra ID access only), deleted on the expiry date. Built from the storage-account "
                        "Template Spec. For test data only."),
        "template_spec": "storage-account",
        "variables": COMMON_TOP + [
            {"name": "redundancy", "question_text": "Redundancy", "type": SELECT, "mandatory": "true",
             "default_value": "Standard_LRS",
             "choices": [("Standard_LRS", "Locally redundant (LRS), cheapest"),
                         ("Standard_ZRS", "Zone redundant (ZRS) (needs justification)"),
                         ("Standard_GRS", "Geo redundant (GRS) (needs justification)")]},
            {"name": "data_classification", "question_text": "What data will it hold?", "type": SELECT,
             "mandatory": "true", "default_value": "synthetic",
             "choices": [("synthetic", "Synthetic or test data only"),
                         ("internal", "Internal company data"),
                         ("confidential", "Confidential or personal data")]},
        ] + COMMON_BOTTOM,
    },
]

# Fields on the requested item (sc_req_item) for the AI agent (P3) and the provisioning worker (P4).
RITM_FIELDS = [
    ("u_cloud_approval", "Cloud approval", 20),          # requested | approved | rejected: the worker's gate
    ("u_ai_recommendation", "AI recommendation", 40),     # approve | approve_with_changes | reject | need_info
    ("u_ai_monthly_cost", "AI monthly cost estimate (USD)", 20),
    ("u_ai_changes", "AI recommended changes (JSON)", 255),  # e.g. {"vm_size": "Standard_B2als_v2"}; the worker applies them
    ("u_provisioning_state", "Provisioning state", 40),   # deploying | succeeded | failed | deleted
    ("u_azure_resource_id", "Azure resource ID", 255),
]

BUSINESS_RULES = [
    {"name": "SKR Cloud: request approval", "collection": "sc_req_item", "when": "before", "order": "100",
     "action_insert": "true", "action_update": "false", "script_file": "ritm_request_approval.js"},
    {"name": "SKR Cloud: create approvals", "collection": "sc_req_item", "when": "after", "order": "100",
     "action_insert": "true", "action_update": "false", "script_file": "ritm_create_approvals.js"},
    {"name": "SKR Cloud: approval decided", "collection": "sysapproval_approver", "when": "after", "order": "100",
     "action_insert": "false", "action_update": "true", "script_file": "approval_decided.js"},
    {"name": "SKR Cloud: hold approval", "collection": "sc_req_item", "when": "before", "order": "1000",
     "action_insert": "false", "action_update": "true", "script_file": "ritm_hold_approval.js"},
]


def script(rule: dict) -> str:
    return (SCRIPTS / rule["script_file"]).read_text()
