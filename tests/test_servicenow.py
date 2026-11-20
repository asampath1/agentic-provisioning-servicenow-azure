"""The live connector with a stand-in HTTP session: reads pending requests, writes only when asked."""
from types import SimpleNamespace

from agents.connectors.servicenow import ServiceNowRequests


class Session:
    def __init__(self):
        self.auth, self.headers, self.patches = None, {}, []

    def get(self, url, params, timeout):
        if url.endswith("/sc_req_item"):
            assert "u_cloud_approval=requested" in params["sysparm_query"]
            rows = [{"sys_id": "s1", "number": "RITM0010009", "opened_at": "2026-11-20 10:00:00",
                     "requested_for.user_name": "synth.ajay.garcia", "cat_item.name": "Azure Linux test VM"}]
        else:
            rows = [{"sc_item_option.item_option_new.name": "vm_size", "sc_item_option.value": "Standard_B2ats_v2"},
                    {"sc_item_option.item_option_new.name": "purpose", "sc_item_option.value": "Try things."}]
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"result": rows})

    def patch(self, url, json, timeout):
        self.patches.append((url, json))
        return SimpleNamespace(status_code=200)


def connector(monkeypatch, write):
    for k, v in {"SN_INSTANCE": "dev000000", "SN_USER": "u", "SN_PASSWORD": "p"}.items():
        monkeypatch.setenv(k, v)
    return ServiceNowRequests(write=write, session=Session())


def test_reads_variables(monkeypatch):
    req = connector(monkeypatch, False).pending()[0]
    assert req["key"] == "RITM0010009" and req["variables"]["vm_size"] == "Standard_B2ats_v2"


def test_dry_run_writes_nothing(monkeypatch):
    c = connector(monkeypatch, False)
    c.write(c.pending()[0], {"u_ai_recommendation": "approve"}, "note")
    assert c.s.patches == [] and c.writes[0]["sent"] is False


def test_write_sets_only_ai_fields_and_note(monkeypatch):
    c = connector(monkeypatch, True)
    c.write(c.pending()[0], {"u_ai_recommendation": "approve", "u_ai_monthly_cost": "6.18", "u_ai_changes": ""}, "note")
    (url, body), = c.s.patches
    assert url.endswith("/sc_req_item/s1")
    assert set(body) == {"u_ai_recommendation", "u_ai_monthly_cost", "u_ai_changes", "work_notes"}
