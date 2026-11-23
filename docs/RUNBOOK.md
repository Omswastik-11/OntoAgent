# OntoAgent Operational Runbook

## 1. System Requirements & Architecture Stack

| Component | Technology | Default Port / Connection | Notes |
|---|---|---|---|
| Orchestration API | FastAPI / Uvicorn | `http://localhost:8000` | REST API with API key authentication |
| Web Console | Gradio 6 | `http://localhost:7860` | Operational UI with persona switcher & HITL approval |
| Analytical Relational DB | PostgreSQL 16 + pgvector | `localhost:5432` | Schemas: `raw`, `analytics`, `kb`, `ops` |
| Graph Topology DB | Neo4j Community 5.x | `bolt://localhost:7687` | Property graph: Customer, Seller, Order, Product |
| MCP Execution Server | FastMCP / MCPServer | Subprocess (stdio) / In-Process | Restricted to `ops.*` table writes |

---

## 2. Quick Deployment & Initialization

### 2.1 Start Containerized Services
```bash
# Launch PostgreSQL and Neo4j via Docker Compose
docker compose up -d

# Verify container health
docker compose ps
```

### 2.2 Ingest and Build Data Pipeline
Run the consolidated data build pipeline to load raw CSVs, compute analytics models, mint synthetic PII, and populate the Neo4j graph:
```bash
# On Linux / macOS:
make data-build

# On Windows (PowerShell / CMD):
.\make.bat data-build
```

### 2.3 Verification & Quality Gate
Run the canonical verification suite before accepting production traffic:
```bash
# Full verification (Services, Schemas, Unit Tests, Adversarial, e2e smoke):
python scripts/verify.py

# Or fast offline verification:
python scripts/verify.py --fast
```

---

## 3. Starting Services

### 3.1 REST API Server
```bash
uvicorn ontoagent.api.main:app --host 0.0.0.0 --port 8000 --workers 2
```

### 3.2 Gradio Web Console
```bash
python -m ontoagent.ui.app
```
Access the console at [http://localhost:7860](http://localhost:7860).

### 3.3 Cloud Platform Deployment (Railway, Render, Supabase)
For cloud-hosted infrastructure without managing physical VMs:
1. **Managed PostgreSQL**: Provision a free instance on **Supabase** with the `pgvector` extension enabled.
2. **Managed Graph**: Provision a free **Neo4j AuraDB** cloud instance (`neo4j+s://...`).
3. **Application Hosting (Railway / Render)**: Connect the GitHub repository `Omswastik-11/OntoAgent`. The platform automatically builds and executes the root `Dockerfile`. Set the following environment variables in your platform dashboard:
   - `PORT`: `7860` (or platform default)
   - `GEMINI_API_KEY`: `<your_api_key>`
   - `ONTOAGENT_POSTGRES_HOST`: `db.<project-ref>.supabase.co`
   - `ONTOAGENT_POSTGRES_PASSWORD`: `<supabase_password>`
   - `ONTOAGENT_NEO4J_URI`: `neo4j+s://<aura_instance>.databases.neo4j.io`
   - `ONTOAGENT_NEO4J_PASSWORD`: `<aura_password>`
4. **Live Interview Sharing**: Run `python -m ontoagent.ui.app --share` to generate an instant 72-hour public HTTPS tunnel for remote demonstrations.

---

## 4. Health Checks & Diagnostics

### 4.1 Automated Health Endpoint
```bash
curl -s http://localhost:8000/v1/health | jq .
```
Expected response:
```json
{
  "status": "ok",
  "components": {
    "postgres": {"status": "connected", "latency_ms": 2.4},
    "neo4j": {"status": "connected", "latency_ms": 3.1},
    "llm": {"status": "ready", "detail": "gemini-1.5-flash"},
    "mcp": {"status": "ready"}
  },
  "as_of_date": "2018-09-01",
  "version": "0.1.0"
}
```

### 4.2 Database Connectivity Verification
```bash
# Check PostgreSQL connection
python -c "import psycopg; conn = psycopg.connect('postgresql://ontoagent_ro:ro_secret@localhost:5432/ontoagent'); print('PG OK'); conn.close()"

# Check Neo4j connection
python -c "from neo4j import GraphDatabase; d = GraphDatabase.driver('bolt://localhost:7687', auth=('neo4j', 'ontoagent_neo4j_password')); d.verify_connectivity(); print('Neo4j OK'); d.close()"
```

---

## 5. Common Incident Scenarios & Remediation

### Scenario A: PostgreSQL Unreachable (`postgres: unreachable`)
- **Symptoms**: `/v1/health` reports `"status": "degraded"`. SQL queries fail with database connection errors.
- **Root Cause**: Docker container stopped or port conflict on 5432.
- **Remediation**:
  ```bash
  docker compose restart postgres
  docker logs ontoagent_postgres --tail 50
  ```

### Scenario B: Neo4j Authentication or Bolt Connection Refused
- **Symptoms**: Graph specialist fails with Bolt handshake error.
- **Root Cause**: Neo4j container still initializing or password mismatch.
- **Remediation**:
  1. Inspect container logs: `docker logs ontoagent_neo4j --tail 50`.
  2. Verify credentials match `.env`:
     `NEO4J_URI=bolt://localhost:7687`
     `NEO4J_USER=neo4j`
     `NEO4J_PASSWORD=ontoagent_neo4j_password`
  3. Re-run graph ingestion: `python -m ontoagent.data.load_neo4j`.

### Scenario C: Action Approval Returns `400 Bad Request` or `403 Forbidden`
- **Symptoms**: Operator approval rejected at `/v1/threads/{thread_id}/approval`.
- **Root Cause**:
  - `403 Forbidden`: Authenticated user does not have `ops_manager` role (e.g. attempting approval with an `analyst` API key).
  - `400 Bad Request`: Thread ID is not currently in an interrupted state waiting for human approval.
- **Remediation**: Verify request header carries `X-API-Key: sk-ops-test` (or valid Ops Manager API key).

### Scenario D: Approval Token Expired (`INVALID_TOKEN` / `TOKEN_EXPIRED`)
- **Symptoms**: MCP executor reports tool failure with `INVALID_TOKEN`.
- **Root Cause**: LangGraph interrupt was resumed > 15 minutes after the approval token was minted.
- **Remediation**: Tokens intentionally expire in 900 seconds (15m) to prevent stale action execution. Re-run the turn to obtain a fresh proposal and approve promptly.

### Scenario E: Token Replay Rejected (`TOKEN_REPLAYED`)
- **Symptoms**: Tool execution rejected with `TOKEN_REPLAYED`.
- **Root Cause**: Re-submitting an already executed approval payload or replaying a consumed `jti`.
- **Remediation**: Invariant enforcement is working correctly. Do not reuse thread tokens across distinct operations.

---

## 6. Offline / Disaster Recovery Mode

If live databases or external LLM API endpoints are temporarily unavailable:
1. **Offline Smoke Testing**:
   ```bash
   export ONTOAGENT_FAKE_LLM=1
   export ONTOAGENT_INPROCESS_MCP=1
   pytest tests/unit/
   ```
2. **Offline Evaluation Benchmark**:
   ```bash
   python -m evals.eval_runner --suite all --model-provider fake
   ```
