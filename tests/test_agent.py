from app.agent import IncidentAgent
from app.tools import UnknownService

class FakeTools:
    def resolve_service(self, name):
        if name != "payments-api": raise UnknownService(f"Unknown service '{name}'.")
        return name
    def list_services(self): return {"services":[{"name":"payments-api","tier":"tier-1"}]}
    def blast_radius(self, service, depth=3):
        return {"outcome":"answered_with_path","failed_service":service,"depth":depth,"impacted_count":1,
                "impacted_services":[{"service":"checkout-api","tier":"tier-1","hops":1,"path":["checkout-api","payments-api"]}],"note":None}
    def who_to_wake(self, service, depth=3): return {"owners":[{"service":"payments-api","team":"payments-team","responders":["Asha Rao"]}],"impact":self.blast_radius(service,depth)}
    def recent_changes(self, service, hours=24, depth=3): return {"changes":[{"at":"2026-10-18T07:42:00Z","sha":"chg-1042","service":"payments-api","summary":"Retry policy updated","author":"Asha Rao"}]}
    def recall(self, service): return {"findings":[{"text":"Check retry limits","at":"2026-10-10T09:30:00Z","session":"postmortem"}]}

def test_blast_radius_includes_path():
    result = IncidentAgent(FakeTools()).investigate("payments-api is down, what is affected?", depth=2)
    assert "checkout-api -> payments-api" in result["answer"]
    assert result["tool_results"][0]["result"]["impacted_count"] == 1

def test_unknown_service_stops_before_tools():
    import pytest
    with pytest.raises(UnknownService):
        IncidentAgent(FakeTools()).investigate("unknown-api is down", service="unknown-api")

def test_owner_and_change_tools_selected():
    result = IncidentAgent(FakeTools()).investigate("payments-api is down, who should respond and what changed?")
    tool_names = {x["tool"] for x in result["tool_results"]}
    assert "who_to_wake" in tool_names
    assert "recent_changes" in tool_names
