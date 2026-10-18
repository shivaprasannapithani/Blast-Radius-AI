
"""Fixed graph tools. The model never supplies Cypher or arbitrary query text."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from app.graph_store import get_store, GraphStore


class UnknownService(ValueError):
    pass


class IncidentTools:
    def __init__(self, store: GraphStore | None = None):
        self.store = store or get_store()

    def resolve_service(self, name: str) -> str:
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise UnknownService("A valid service name is required.")

        rows = self.store.query(
            "MATCH (s:Service {name:$name}) RETURN s.name",
            {"name": name.strip()},
            read_only=True,
        )

        if not rows:
            raise UnknownService(
                f"Unknown service '{name}'. No graph query was run for this service."
            )

        return rows[0][0]

    def list_services(self) -> dict:
        rows = self.store.query(
            "MATCH (s:Service) RETURN s.name, s.tier ORDER BY s.name",
            read_only=True,
        )

        return {
            "services": [
                {"name": row[0], "tier": row[1]}
                for row in rows
            ]
        }

    def blast_radius(self, service: str, depth: int = 3) -> dict:
        service = self.resolve_service(service)
        depth = max(1, min(int(depth), 5))

        # Dependency direction:
        # consumer -> provider
        #
        # When a provider fails, traverse incoming dependency paths
        # to discover consumers that could be affected.
        rows = self.store.query(
            f"""
            MATCH p=(consumer:Service)-[:DEPENDS_ON*1..{depth}]->(
                target:Service {{name:$name}}
            )
            RETURN DISTINCT
                consumer.name,
                consumer.tier,
                length(p),
                [n IN nodes(p) | n.name]
            ORDER BY length(p), consumer.name
            """,
            {"name": service},
            read_only=True,
        )

        # The graph can contain multiple valid paths to one service.
        # Keep only the shortest path for each unique impacted service.
        unique_impacted = {}

        for row in rows:
            name = row[0]

            if name not in unique_impacted:
                unique_impacted[name] = {
                    "service": name,
                    "tier": row[1],
                    "hops": row[2],
                    "path": row[3],
                }

        impacted = list(unique_impacted.values())

        return {
            "outcome": (
                "answered_with_path"
                if impacted
                else "not_in_graph"
            ),
            "failed_service": service,
            "depth": depth,
            "impacted_count": len(impacted),
            "impacted_services": impacted,
            "note": (
                "No upstream consumers were found in the modeled graph; "
                "this does not prove there is no real-world impact."
                if not impacted
                else None
            ),
        }

    def who_to_wake(self, service: str, depth: int = 3) -> dict:
        service = self.resolve_service(service)
        impact = self.blast_radius(service, depth)

        # Include the failed service itself and all unique impacted services.
        names = [
            service,
            *[
                item["service"]
                for item in impact["impacted_services"]
            ],
        ]

        rows = self.store.query(
            """
            MATCH (t:Team)-[:OWNS]->(s:Service)
            WHERE s.name IN $names
            OPTIONAL MATCH (p:Person)-[:MEMBER_OF]->(t)
            RETURN s.name, t.name, collect(p.name)
            ORDER BY s.name
            """,
            {"names": names},
            read_only=True,
        )

        owners = [
            {
                "service": row[0],
                "team": row[1],
                "responders": row[2],
            }
            for row in rows
        ]

        return {
            "failed_service": service,
            "owners": owners,
            "impact": impact,
        }

    def recent_changes(
        self,
        service: str,
        hours: int = 24,
        depth: int = 3,
    ) -> dict:
        service = self.resolve_service(service)
        hours = max(1, min(int(hours), 168))

        impact = self.blast_radius(service, depth)

        names = [
            service,
            *[
                item["service"]
                for item in impact["impacted_services"]
            ],
        ]

        rows = self.store.query(
            """
            MATCH (c:Change)-[:TOUCHED]->(s:Service)
            WHERE s.name IN $names
            RETURN c.sha, c.at, c.author, c.summary, s.name
            ORDER BY c.at DESC
            """,
            {"names": names},
            read_only=True,
        )

        # Seed timestamps are ISO-8601 UTC.
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        changes = []

        for row in rows:
            try:
                timestamp = datetime.fromisoformat(
                    str(row[1]).replace("Z", "+00:00")
                )

                # Treat timestamps without a timezone as UTC.
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)

                if timestamp < cutoff:
                    continue

            except (ValueError, TypeError):
                # Preserve records with unparseable timestamps rather
                # than silently dropping them.
                pass

            changes.append(
                {
                    "sha": row[0],
                    "at": row[1],
                    "author": row[2],
                    "summary": row[3],
                    "service": row[4],
                }
            )

        return {
            "failed_service": service,
            "window_hours": hours,
            "changes": changes,
            "impact_services_checked": names,
            "note": (
                "Changes are correlations in the time window, "
                "not proof of causation."
            ),
        }

    def path_between(self, source: str, target: str) -> dict:
        source = self.resolve_service(source)
        target = self.resolve_service(target)

        rows = self.store.query(
            """
            MATCH p=(a:Service {name:$source})-[:DEPENDS_ON*1..5]->
                     (b:Service {name:$target})
            RETURN [n IN nodes(p) | n.name] AS path,
                   length(p) AS hops
            ORDER BY hops
            LIMIT 1
            """,
            {"source": source, "target": target},
            read_only=True,
        )

        if not rows:
            return {
                "outcome": "not_in_graph",
                "source": source,
                "target": target,
                "path": None,
                "note": (
                    "No directed dependency path exists in the graph. "
                    "This may indicate a missing edge or no modeled connection."
                ),
            }

        return {
            "outcome": "answered_with_path",
            "source": source,
            "target": target,
            "path": rows[0][0],
            "hops": rows[0][1],
        }

    def recall(self, service: str, limit: int = 5) -> dict:
        service = self.resolve_service(service)
        limit = max(1, min(int(limit), 10))

        rows = self.store.query(
            """
            MATCH (f:Finding)-[:ABOUT]->(s:Service {name:$name})
            RETURN f.text, f.at, f.session
            ORDER BY f.at DESC
            LIMIT $limit
            """,
            {"name": service, "limit": limit},
            read_only=True,
        )

        return {
            "service": service,
            "findings": [
                {
                    "text": row[0],
                    "at": row[1],
                    "session": row[2],
                }
                for row in rows
            ],
            "outcome": (
                "answered_from_memory"
                if rows
                else "not_in_graph"
            ),
        }

    def save_finding(
        self,
        service: str,
        text: str,
        session: str = "manual",
    ) -> dict:
        service = self.resolve_service(service)

        if not isinstance(text, str) or not text.strip() or len(text) > 2000:
            raise ValueError("Finding must contain 1-2000 characters.")

        now = datetime.now(timezone.utc).isoformat()
        session = session[:100]

        self.store.query(
            """
            MATCH (s:Service {name:$name})
            CREATE (f:Finding {
                text:$text,
                at:$at,
                session:$session
            })-[:ABOUT]->(s)
            """,
            {
                "name": service,
                "text": text.strip(),
                "at": now,
                "session": session,
            },
        )

        return {
            "saved": True,
            "service": service,
            "at": now,
            "session": session,
        }
