## Graph Data Model

Blast Radius AI uses **FalkorDB as its graph database** to represent service dependencies, ownership, recent changes, incidents, and investigation findings.

### Node types

| Node | Purpose |
|---|---|
| `Service` | Represents a service, including its name and tier. |
| `Team` | Represents the team responsible for services. |
| `Person` | Represents an engineer who belongs to a team. |
| `Change` | Represents a code or configuration change, including its author, timestamp, and summary. |
| `Finding` | Stores investigation notes and lessons learned for future recall. |

### Relationships

| Relationship | Direction | Purpose |
|---|---|---|
| `DEPENDS_ON` | Consumer → Provider | Models service dependencies and supports blast-radius analysis. |
| `OWNS` | Team → Service | Connects teams to the services they own. |
| `MEMBER_OF` | Person → Team | Connects engineers to their teams. |
| `TOUCHED` | Change → Service | Associates changes with affected services. |
| `ABOUT` | Finding → Service | Links saved investigation findings to a service. |

### Example dependency

A dependency chain such as:

`web-frontend → checkout-api → payments-api`

means that `web-frontend` depends on `checkout-api`, which depends on `payments-api`. If `payments-api` fails, the graph can be traversed in reverse dependency direction to identify potentially impacted consumers.

## Cypher Queries and Graph Algorithms

The application uses developer-defined Cypher queries through a Python `GraphStore` wrapper. User prompts do not generate arbitrary Cypher. Service names and other values are passed as query parameters.

### 1. Find the blast radius

```cypher
MATCH p=(consumer:Service)-[:DEPENDS_ON*1..3]->
         (target:Service {name: $name})
RETURN DISTINCT
    consumer.name,
    consumer.tier,
    length(p),
    [n IN nodes(p) | n.name]
ORDER BY length(p), consumer.name
```

**Purpose:** Finds upstream consumers that may be affected by a failed service, returning their tiers, hop counts, and dependency paths. The actual implementation allows a bounded depth of 1–5 hops.

### 2. Find a dependency path

```cypher
MATCH p=(a:Service {name: $source})-[:DEPENDS_ON*1..5]->
         (b:Service {name: $target})
RETURN [n IN nodes(p) | n.name] AS path,
       length(p) AS hops
ORDER BY hops
LIMIT 1
```

**Purpose:** Finds a directed dependency path between two services and returns the shortest path found by the query.

### 3. Identify service owners and responders

```cypher
MATCH (t:Team)-[:OWNS]->(s:Service)
WHERE s.name IN $names
OPTIONAL MATCH (p:Person)-[:MEMBER_OF]->(t)
RETURN s.name, t.name, collect(p.name)
ORDER BY s.name
```

**Purpose:** Maps impacted services to their owning teams and team members, helping responders identify whom to contact.

### 4. Retrieve recent changes

```cypher
MATCH (c:Change)-[:TOUCHED]->(s:Service)
WHERE s.name IN $names
RETURN c.sha, c.at, c.author, c.summary, s.name
ORDER BY c.at DESC
```

**Purpose:** Retrieves changes associated with the failed service and its impacted services. The application filters results by a configurable time window. Temporal correlation does not establish causation.

### 5. Recall previous investigation findings

```cypher
MATCH (f:Finding)-[:ABOUT]->(s:Service {name: $name})
RETURN f.text, f.at, f.session
ORDER BY f.at DESC
LIMIT $limit
```

**Purpose:** Retrieves saved investigation notes for a service so earlier observations and lessons can inform subsequent investigations.

### 6. Save an investigation finding

```cypher
MATCH (s:Service {name: $name})
CREATE (f:Finding {
    text: $text,
    at: $at,
    session: $session
})-[:ABOUT]->(s)
```

**Purpose:** Persists a timestamped finding associated with a service for later retrieval.

## Graph Algorithms and Investigation Logic

The current implementation relies on **bounded variable-length graph traversal**, directed path search, and application-side shortest-path selection for unique impacted services.

- **Blast-radius analysis:** Traverses incoming dependency paths toward the failed provider.
- **Dependency-path analysis:** Searches directed paths up to five hops and requests the shortest result.
- **Impact deduplication:** Keeps the first result for each impacted service after sorting by path length.
- **Ownership resolution:** Joins impacted services to teams and responders.
- **Change correlation:** Filters associated changes by timestamp and investigation window.
- **Investigation memory:** Saves and retrieves findings linked to services.

These results describe the relationships represented in the graph. Missing graph edges, incomplete metadata, and temporal correlations can limit conclusions about real-world impact or root cause.
