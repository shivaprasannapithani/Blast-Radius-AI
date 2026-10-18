# Blast Radius AI — Graph-Based Incident Investigation Agent

**Blast Radius AI** is a graph-powered incident investigation agent built with Python, FastAPI, Streamlit, and FalkorDB. It helps engineers investigate service failures by identifying potentially impacted services, tracing dependency paths, locating responsible teams, correlating recent changes, and retrieving previous investigation findings.

The project uses graph relationships to connect service dependencies, ownership information, code changes, and investigation memory in a unified model.

## Problem Statement

Modern applications consist of interconnected services. When a service fails, engineers need to determine which downstream-facing consumers may be affected, understand dependency paths, identify responsible teams, and investigate recent changes.

Manual investigation can require checking multiple services, repositories, ownership records, and incident notes.

Blast Radius AI uses FalkorDB to represent these relationships as a graph and provides investigation tools that help engineers explore potential impact and supporting evidence.

## Key Features

- **Blast-radius analysis:** Identifies potentially impacted services through multi-hop dependency traversal.
- **Dependency path discovery:** Finds directed paths between services.
- **Ownership and responder lookup:** Maps affected services to owning teams and team members.
- **Recent change correlation:** Retrieves changes associated with the failed service and its impacted services within a configurable time window.
- **Investigation memory:** Saves and recalls service-specific findings from previous investigations.
- **Graph-grounded responses:** Uses application-defined tools to retrieve information from FalkorDB instead of generating arbitrary Cypher from user prompts.
- **API access:** Exposes backend functionality through FastAPI.
- **Interactive interface:** Provides a Streamlit UI for investigating service incidents.

## Technology Stack

| Technology | Purpose |
|---|---|
| Python | Application logic and investigation tools |
| FalkorDB | Graph storage and relationship traversal |
| Cypher | Graph queries and dependency analysis |
| FastAPI | Backend API |
| Streamlit | Interactive user interface |
| Docker Compose | Local graph database setup |
| Pytest | Automated testing, where configured |

## Architecture

```text
                 User
                  |
                  v
          Streamlit Interface
                  |
                  v
           FastAPI Backend
                  |
                  v
        Investigation Agent
                  |
                  v
           Incident Tools
                  |
                  v
             GraphStore
                  |
                  v
               FalkorDB
                  |
       +----------+----------+
       |          |          |
    Service     Team       Change
  Dependencies Ownership   History
       |
    Findings and Investigation Memory
```

The Streamlit interface provides the user-facing workflow. FastAPI exposes backend endpoints, while the investigation tools execute developer-defined Cypher queries through the `GraphStore` wrapper.

FalkorDB stores the relationships used for dependency traversal, ownership lookup, change correlation, and investigation memory.

## Graph Data Model

Blast Radius AI uses FalkorDB as its graph database to represent service dependencies, ownership, recent changes, incidents, and investigation findings.

### Node types

| Node | Purpose |
|---|---|
| `Service` | Represents a service, including its name and tier. |
| `Team` | Represents the team responsible for services. |
| `Person` | Represents an engineer who belongs to a team. |
| `Change` | Represents a code or configuration change, including its author, timestamp, and summary. |
| `Finding` | Stores investigation notes and lessons learned for future recall. |
| `Incident` | Represents an incident in the seeded graph data. The documented investigation queries do not directly query this node type. |

### Relationships

| Relationship | Direction | Purpose |
|---|---|---|
| `DEPENDS_ON` | Consumer → Provider | Models service dependencies and supports blast-radius analysis. |
| `OWNS` | Team → Service | Connects teams to the services they own. |
| `MEMBER_OF` | Person → Team | Connects engineers to their teams. |
| `TOUCHED` | Change → Service | Associates changes with affected services. |
| `ABOUT` | Finding → Service | Links saved investigation findings to a service. |

### Example dependency

```text
web-frontend → checkout-api → payments-api
```

This means `web-frontend` depends on `checkout-api`, which depends on `payments-api`.

If `payments-api` fails, the graph traversal identifies upstream consumers that may be affected by that provider failure.

## Cypher Queries and Graph Algorithms

The application uses developer-defined Cypher queries through a Python `GraphStore` wrapper. User prompts do not generate arbitrary Cypher. Service names and other values are passed as query parameters.

### 1. Validate a service

```cypher
MATCH (s:Service {name: $name})
RETURN s.name
```

**Purpose:** Confirms that a requested service exists before running service-specific investigation queries.

### 2. Find the blast radius

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

**Purpose:** Finds upstream consumers that may be affected by a failed service, returning their tiers, hop counts, and dependency paths.

The example uses three hops. The implementation supports a bounded traversal depth of one to five hops.

### 3. Find a dependency path

```cypher
MATCH p=(a:Service {name: $source})-[:DEPENDS_ON*1..5]->
         (b:Service {name: $target})
RETURN [n IN nodes(p) | n.name] AS path,
       length(p) AS hops
ORDER BY hops
LIMIT 1
```

**Purpose:** Finds a directed dependency path between two services and returns the shortest path among the results returned by the query.

### 4. Identify service owners and responders

```cypher
MATCH (t:Team)-[:OWNS]->(s:Service)
WHERE s.name IN $names
OPTIONAL MATCH (p:Person)-[:MEMBER_OF]->(t)
RETURN s.name, t.name, collect(p.name)
ORDER BY s.name
```

**Purpose:** Maps impacted services to their owning teams and team members, helping responders identify whom to contact.

### 5. Retrieve recent changes

```cypher
MATCH (c:Change)-[:TOUCHED]->(s:Service)
WHERE s.name IN $names
RETURN c.sha, c.at, c.author, c.summary, s.name
ORDER BY c.at DESC
```

**Purpose:** Retrieves changes associated with the failed service and its impacted services. The application filters results by the requested time window.

A recent change may be relevant evidence, but temporal correlation does not establish causation.

### 6. Recall previous investigation findings

```cypher
MATCH (f:Finding)-[:ABOUT]->(s:Service {name: $name})
RETURN f.text, f.at, f.session
ORDER BY f.at DESC
LIMIT $limit
```

**Purpose:** Retrieves saved investigation notes for a service so earlier observations and lessons can inform subsequent investigations.

### 7. Save an investigation finding

```cypher
MATCH (s:Service {name: $name})
CREATE (f:Finding {
    text: $text,
    at: $at,
    session: $session
})-[:ABOUT]->(s)
```

**Purpose:** Persists a timestamped finding associated with a service for later retrieval.

### Graph algorithms and investigation logic

The current implementation relies on bounded variable-length graph traversal, directed path search, and application-side deduplication of impacted services.

- **Blast-radius analysis:** Traverses dependency paths from consumers toward the failed provider.
- **Dependency-path analysis:** Searches directed paths up to five hops and requests the shortest result.
- **Impact deduplication:** Keeps the first result for each impacted service after sorting by path length.
- **Ownership resolution:** Joins impacted services to teams and responders.
- **Change correlation:** Filters associated changes by timestamp and investigation window.
- **Investigation memory:** Saves and retrieves findings linked to services.

These results depend on the relationships and metadata available in the graph. Missing edges and incomplete metadata can limit the accuracy of impact analysis.

## Example Investigation

Consider an investigation involving `payments-api`.

### Potentially impacted services

| Service | Tier | Hops | Dependency path |
|---|---|---:|---|
| `checkout-api` | tier-1 | 1 | `checkout-api → payments-api` |
| `refunds-worker` | tier-2 | 1 | `refunds-worker → payments-api` |
| `status-page` | tier-3 | 2 | `status-page → refunds-worker → payments-api` |
| `web-frontend` | tier-1 | 2 | `web-frontend → checkout-api → payments-api` |

These are potential impacts inferred from the dependency graph, not proof that every listed service experienced an outage.

### Ownership and changes

The investigation can retrieve owning teams and responders for affected services, along with recent associated changes such as a payments retry-policy update or a checkout timeout change.

It can also recall previously saved findings about payment failures and database connection pressure.

**Important:** Change correlation and saved findings help guide investigation, but they do not independently prove the root cause of an incident.

## Getting Started

Follow these instructions to run Blast Radius AI locally on Windows.

### Prerequisites

Install the following tools:

- Python 3.11 or 3.12
- Docker Desktop with Docker Compose
- Git
- Windows PowerShell or another compatible terminal

Verify the installations:

```powershell
python --version
docker --version
docker compose version
git --version
```

### 1. Clone the repository

```powershell
git clone https://github.com/shivaprasannapithani/Blast-Radius-AI.git
cd Blast-Radius-AI
```

### 2. Create and activate a virtual environment

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If Python 3.12 is not installed, install a supported version or select another compatible Python installation.

If PowerShell blocks activation, run the following in the current terminal:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a local `.env` file from the example:

```powershell
Copy-Item .env.example .env
```

Open `.env` and configure the variables required by the application. Check `.env.example` and `app/config.py` for the exact variable names and default values.

Never commit `.env` or API keys to the public repository. Keep `.env.example` free of secrets.

### 5. Start FalkorDB

Ensure Docker Desktop is running, then execute:

```powershell
docker compose up -d
```

Check the container status:

```powershell
docker compose ps
```

### 6. Seed the graph database

Populate FalkorDB with the sample graph data:

```powershell
python -m app.seed
```

The seed script initializes the sample data used for local demonstrations.

### 7. Start the FastAPI backend

In the first terminal, from the project directory with the virtual environment activated, run:

```powershell
uvicorn app.main:app --reload
```

Open the API documentation:

[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### 8. Start the Streamlit interface

Open a second PowerShell terminal in the project directory. Activate the virtual environment and run:

```powershell
.\.venv\Scripts\Activate.ps1
streamlit run ui.py
```

Open the application:

[http://localhost:8501](http://localhost:8501)

Keep both the FastAPI and Streamlit processes running while using the application.

### 9. Try a sample investigation

Once the application is running, investigate `payments-api`.

Example questions:

- Which services could be impacted if `payments-api` fails?
- What is the dependency path between `checkout-api` and `payments-api`?
- Which team owns the affected services?
- What recent changes are associated with the affected services?
- What findings were previously recorded for `payments-api`?

The available questions depend on the tools and workflows exposed by the current application.

### 10. Run tests

If the project includes pytest tests, execute:

```powershell
python -m pytest -v
```

Review the test results and resolve failures before submitting.

## Troubleshooting

### FalkorDB connection error

- Ensure Docker Desktop is running.
- Run `docker compose ps` and check the container status.
- Verify that the configured FalkorDB host, port, and graph name match the Docker Compose configuration and application settings.

### Missing Python packages

- Confirm that the virtual environment is active.
- Run `python -m pip install -r requirements.txt` again.

### The graph contains no services

- Run `python -m app.seed`.
- Confirm that the seed script and application connect to the same FalkorDB instance and graph name.

### The Streamlit interface cannot reach the backend

- Confirm FastAPI is running at `http://127.0.0.1:8000`.
- Check the backend URL configuration used by `ui.py`.

### Port already in use

Stop the process occupying the required port or update the relevant configuration consistently before restarting the application.

## Stopping the Application

Stop the FastAPI and Streamlit processes using `Ctrl+C` in their respective terminals.

To stop the FalkorDB container:

```powershell
docker compose down
```

This stops and removes the Compose containers and network. Named volumes are normally retained unless explicitly removed.

## Limitations

- Analysis depends on the completeness and accuracy of the graph data.
- Missing dependency edges can cause affected services to be overlooked.
- Recent changes are investigative leads, not definitive root-cause evidence.
- Saved findings provide historical context but may require verification against current system behavior.
- The current project is intended as an incident investigation aid, not a replacement for production monitoring, alerting, or human incident-response judgment.

## Future Improvements

Potential future improvements include:

- Integrating live service inventories and monitoring alerts.
- Adding incident timelines and richer incident relationships.
- Incorporating deployment and telemetry data.
- Improving graph visualization and investigation summaries.
- Adding more automated integration tests.
- Supporting additional incident-management integrations.

## Demo Video

**Demo video:** Add the public or unlisted video URL here after recording and uploading the working project demonstration.

The demo should show the running application, a blast-radius investigation, dependency paths, ownership lookup, recent changes, and saved finding retrieval.

## Hackathon Submission

- **Project:** Blast Radius AI
- **Primary track:** Agents That Act on Connected Data
- **Source code:** [GitHub Repository](https://github.com/shivaprasannapithani/Blast-Radius-AI)
- **Demo video:** Add the video URL above when available.

## License

Add the license you choose for this project. If the repository already contains a license file, keep this section consistent with that license.
