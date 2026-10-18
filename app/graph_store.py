from __future__ import annotations
from typing import Any
from app.config import FALKORDB_HOST, FALKORDB_PORT, FALKORDB_GRAPH

class GraphStore:
    """Small wrapper around FalkorDB. All query text is developer-authored."""
    def __init__(self, host: str = FALKORDB_HOST, port: int = FALKORDB_PORT, graph_name: str = FALKORDB_GRAPH):
        from falkordb import FalkorDB
        self.client = FalkorDB(host=host, port=port)
        self.graph = self.client.select_graph(graph_name)

    def query(self, cypher: str, params: dict[str, Any] | None = None, read_only: bool = False) -> list[list[Any]]:
        result = self.graph.ro_query(cypher, params or {}) if read_only else self.graph.query(cypher, params or {})
        return result.result_set

    def ping(self) -> bool:
        try:
            self.query("RETURN 1", read_only=True)
            return True
        except Exception:
            return False

def get_store() -> GraphStore:
    return GraphStore()
