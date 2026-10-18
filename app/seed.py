"""Seed a realistic demo graph. Safe to rerun: clears only the configured demo graph."""
from app.graph_store import get_store

def seed_demo() -> dict:
    store = get_store()
    # The graph is intentionally reset so the demo dataset remains predictable.
    store.query("MATCH (n) DETACH DELETE n")
    services = [
        ("web-frontend", "tier-1"), ("checkout-api", "tier-1"), ("payments-api", "tier-1"),
        ("orders-db", "tier-1"), ("inventory-api", "tier-1"), ("shipping-worker", "tier-2"),
        ("notification-service", "tier-2"), ("refunds-worker", "tier-2"), ("status-page", "tier-3"),
        ("auth-service", "tier-1"),
    ]
    for name, tier in services:
        store.query("CREATE (:Service {name: $name, tier: $tier})", {"name": name, "tier": tier})
    # Direction: consumer -[:DEPENDS_ON]-> provider. A provider outage impacts reverse traversal.
    dependencies = [
        ("web-frontend", "checkout-api", "sync", 1),
        ("checkout-api", "payments-api", "sync", 1),
        ("checkout-api", "inventory-api", "sync", 1),
        ("payments-api", "orders-db", "sync", 1),
        ("inventory-api", "orders-db", "sync", 1),
        ("shipping-worker", "orders-db", "async", 2),
        ("notification-service", "shipping-worker", "async", 2),
        ("refunds-worker", "payments-api", "async", 2),
        ("status-page", "refunds-worker", "sync", 1),
        ("checkout-api", "auth-service", "sync", 1),
        ("web-frontend", "auth-service", "sync", 1),
    ]
    for consumer, provider, kind, weight in dependencies:
        store.query("MATCH (a:Service {name:$consumer}), (b:Service {name:$provider}) CREATE (a)-[:DEPENDS_ON {kind:$kind, weight:$weight}]->(b)",
                    {"consumer": consumer, "provider": provider, "kind": kind, "weight": weight})
    teams = [("payments-team", "payments-api"), ("commerce-team", "checkout-api"),
             ("platform-team", "orders-db"), ("inventory-team", "inventory-api"),
             ("fulfillment-team", "shipping-worker"), ("identity-team", "auth-service"),
             ("web-team", "web-frontend"), ("messaging-team", "notification-service"),
             ("payments-team", "refunds-worker"), ("platform-team", "status-page")]
    for team, service in teams:
        store.query("MERGE (t:Team {name:$team}) MERGE (s:Service {name:$service}) MERGE (t)-[:OWNS]->(s)",
                    {"team": team, "service": service})
    people = [("Asha Rao", "payments-team"), ("Rohan Iyer", "commerce-team"),
              ("Meera Nair", "platform-team"), ("Dev Shah", "inventory-team"),
              ("Kavya Das", "fulfillment-team"), ("Arjun Menon", "identity-team"),
              ("Nina Joseph", "web-team"), ("Ishaan Roy", "messaging-team")]
    for person, team in people:
        store.query("MERGE (p:Person {name:$person}) MERGE (t:Team {name:$team}) MERGE (p)-[:MEMBER_OF]->(t) MERGE (p)-[:ONCALL_FOR {from_at:0, to_at:4102444800}]->(t)",
                    {"person": person, "team": team})
    changes = [
        ("chg-1042", "payments-api", "2026-10-18T07:42:00Z", "Asha Rao", "Retry policy updated"),
        ("chg-1038", "checkout-api", "2026-10-18T06:55:00Z", "Rohan Iyer", "Checkout timeout increased"),
        ("chg-1029", "orders-db", "2026-10-17T22:10:00Z", "Meera Nair", "Connection pool configuration changed"),
        ("chg-1021", "auth-service", "2026-10-17T18:30:00Z", "Arjun Menon", "Token cache refreshed"),
        ("chg-1004", "inventory-api", "2026-10-16T14:00:00Z", "Dev Shah", "Inventory query optimization"),
    ]
    for sha, service, at, author, summary in changes:
        store.query("MATCH (s:Service {name:$service}) CREATE (c:Change {sha:$sha, at:$at, author:$author, summary:$summary})-[:TOUCHED]->(s)",
                    {"sha": sha, "service": service, "at": at, "author": author, "summary": summary})
    store.query("MATCH (s:Service {name:'payments-api'}) CREATE (i:Incident {id:'INC-2048', at:'2026-10-18T08:00:00Z', summary:'Elevated payment failures after retry policy change'})-[:AFFECTED]->(s)")
    store.query("MATCH (s:Service {name:'payments-api'}) CREATE (f:Finding {text:'Previous incident: retry storms increased database connection pressure; verify retry limits and pool saturation.', at:'2026-10-10T09:30:00Z', session:'postmortem-INC-1991'})-[:ABOUT]->(s)")
    return {"services": len(services), "dependencies": len(dependencies), "teams": len(set(t for t, _ in teams)), "people": len(people), "changes": len(changes), "incidents": 1, "findings": 1}

if __name__ == "__main__":
    print("Seed complete:", seed_demo())
