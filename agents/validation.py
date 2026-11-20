"""Validation agent: checks a catalog request against docs/request-policy.md and recommends.

Every check maps to a numbered policy rule. The agent recommends; a person from the SKR Cloud Platform team decides.
Outcomes, strongest first: reject > need_info > approve_with_changes > approve.

Text checks (rule 4 vague purpose, rule 7 production use or real data) are regular expressions written from the
policy's own wording. They are the weak spot: a request can describe production use or real data in other words.
"""
from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .pricing import Prices

ALLOWED_SIZES = ("Standard_B2ats_v2", "Standard_B2als_v2")
FALLBACK_SIZE = "Standard_B2als_v2"          # rule 1: the largest allowed size
ALLOWED_REDUNDANCY = ("Standard_LRS",)
MAX_DAYS = 30
SEVERITY = {"reject": 3, "need_info": 2, "approve_with_changes": 1, "approve": 0}
OUTCOME = {"size_not_allowed": "approve_with_changes", "redundancy_not_allowed": "approve_with_changes",
           "expiry_too_long": "approve_with_changes", "expiry_invalid": "need_info", "purpose_vague": "need_info",
           "ssh_key_invalid": "need_info", "private_key": "reject", "data_not_allowed": "reject",
           "production_or_real_data": "reject"}
RULE = {"size_not_allowed": 1, "redundancy_not_allowed": 2, "expiry_too_long": 3, "expiry_invalid": 3,
        "purpose_vague": 4, "ssh_key_invalid": 5, "private_key": 5, "data_not_allowed": 6,
        "production_or_real_data": 7}

PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----|PuTTY-User-Key-File", re.I)
PUBLIC_KEY = re.compile(r"^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(?:256|384|521))\s+([A-Za-z0-9+/]+={0,2})(?:\s+\S.*)?$")
# rule 7, in the policy's words
PRODUCTION = re.compile(r"\bproduction\b|\bprod\b|\blive (?:traffic|customers?|data|service)\b|\bgo-?live\b", re.I)
REAL_DATA = re.compile(r"\b(?:real|actual) (?:customer|company|personal|user)?\s*data\b|\bcustomer data\b|"
                       r"\bpersonal data\b|\bPII\b|\bconfidential\b", re.I)


@dataclass
class Validation:
    key: str
    item: str
    decision: str
    problems: dict = field(default_factory=dict)        # code -> explanation
    changes: dict = field(default_factory=dict)         # variable -> recommended value
    monthly_cost_usd: float | None = None               # as requested
    recommended_cost_usd: float | None = None           # with the changes
    evidence: dict = field(default_factory=dict)        # code -> quoted text (text checks)
    note: str = ""


def check_ssh_key(text: str) -> tuple[str | None, str]:
    t = (text or "").strip()
    if PRIVATE_KEY.search(t):
        return "private_key", "this is a PRIVATE key. Treat that key pair as exposed: create a new one and send only the .pub line"
    m = PUBLIC_KEY.match(t)
    if not m:
        return "ssh_key_invalid", "not a public key line (expected 'ssh-ed25519 AAAA... name')"
    try:
        blob = base64.b64decode(m.group(2), validate=True)
    except (binascii.Error, ValueError):
        return "ssh_key_invalid", "the key data is not valid base64"
    if len(blob) < 20 or m.group(1).encode() not in blob[:40]:
        return "ssh_key_invalid", "the key data does not match its type"
    return None, ""


def parse_day(s: str) -> date | None:
    try:
        return datetime.strptime((s or "").strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


class ValidationAgent:
    name = "validation"

    def __init__(self, prices: Prices, reader=None):
        self.prices = prices
        self.reader = reader                 # optional text reader for rule 7 (default: the regexes above)

    def text_flags(self, req: dict) -> dict[str, str]:
        """Rule 7 evidence: {'production_or_real_data': quote} or {}."""
        v = req["variables"]
        if self.reader:
            got = self.reader.read(req)
            if got is not None:
                return got                    # None: Claude unavailable for this request, use the regexes
        text = " ".join([v.get("purpose", ""), v.get("justification", "")])
        m = PRODUCTION.search(text) or REAL_DATA.search(text)
        return {"production_or_real_data": m.group(0)} if m else {}

    def run(self, req: dict) -> Validation:
        v, item = req["variables"], req["item"]
        is_vm = "VM" in item
        problems, changes = {}, {}
        opened = parse_day(req.get("opened_at", "")) or date.today()

        purpose = (v.get("purpose") or "").strip()
        if len(purpose.split()) <= 3:
            problems["purpose_vague"] = f'purpose "{purpose}" does not say what it is for'

        exp = parse_day(v.get("expires_on", ""))
        if not exp or exp <= opened:
            problems["expiry_invalid"] = f'expiry date "{v.get("expires_on", "")}" is missing or not in the future'
        elif exp > opened + timedelta(days=MAX_DAYS):
            problems["expiry_too_long"] = f"{(exp - opened).days} days; the sandbox allows {MAX_DAYS}"
            changes["expires_on"] = (opened + timedelta(days=MAX_DAYS)).isoformat()

        if is_vm:
            size = v.get("vm_size", "")
            if size not in ALLOWED_SIZES:
                problems["size_not_allowed"] = f"{size} is not allowed in the sandbox"
                changes["vm_size"] = FALLBACK_SIZE
            code, why = check_ssh_key(v.get("ssh_public_key", ""))
            if code:
                problems[code] = why
            cost = self.prices.vm_monthly(size)
            rec_cost = self.prices.vm_monthly(changes.get("vm_size", size))
        else:
            sku = v.get("redundancy", "")
            if sku not in ALLOWED_REDUNDANCY:
                problems["redundancy_not_allowed"] = f"{sku} is not allowed in the sandbox"
                changes["redundancy"] = ALLOWED_REDUNDANCY[0]
            if v.get("data_classification", "synthetic") != "synthetic":
                problems["data_not_allowed"] = f"data classification '{v.get('data_classification')}': the sandbox holds test data only"
            cost = self.prices.storage_monthly(sku)
            rec_cost = self.prices.storage_monthly(changes.get("redundancy", sku))

        evidence = self.text_flags(req)
        for code, quote in evidence.items():
            problems[code] = f'the request says "{quote}": the sandbox is for test data and test traffic only'

        decision = max((OUTCOME[p] for p in problems), key=SEVERITY.get, default="approve")
        out = Validation(key=req["key"], item=item, decision=decision, problems=problems,
                         changes=changes if decision == "approve_with_changes" else {},
                         monthly_cost_usd=cost, recommended_cost_usd=rec_cost, evidence=evidence)
        out.note = self.work_note(out)
        return out

    @staticmethod
    def work_note(r: Validation) -> str:
        label = {"approve": "Approve", "approve_with_changes": "Approve with changes",
                 "need_info": "Needs information from the requester", "reject": "Reject"}[r.decision]
        lines = ["[AI request validation - recommendation only; the SKR Cloud Platform team decides]", "",
                 f"Recommendation: {label}."]
        if r.problems:
            lines.append("Problems (policy rule):")
            lines += [f"- Rule {RULE[c]}: {why}." for c, why in sorted(r.problems.items(), key=lambda t: RULE[t[0]])]
        else:
            lines.append("All 7 policy rules pass.")
        if r.changes:
            lines.append("Change before building: " + ", ".join(f"{k} -> {v}" for k, v in r.changes.items()) + ".")
        if r.monthly_cost_usd is not None:
            cost = f"Estimated cost: ${r.monthly_cost_usd:.2f} per month as requested"
            if r.changes and r.recommended_cost_usd != r.monthly_cost_usd:
                cost += f", ${r.recommended_cost_usd:.2f} with the changes"
            lines.append(cost + " (Azure retail prices, Central India).")
        return "\n".join(lines)


def prediction(r: Validation) -> dict:
    return {"key": r.key, "decision": r.decision, "problems": sorted(r.problems), "changes": r.changes,
            "monthly_cost_usd": r.monthly_cost_usd}
