"""Project guide, roles explanation, database overview, and query playbook for OntoAgent UI.

Purpose:
    Provides structured, interactive documentation explaining system roles (Analyst vs Ops Manager),
    multi-modal database architecture (Postgres, Neo4j, Vector/RAG), sample queries playbook,
    and step-by-step navigation instructions.
"""

from typing import Dict, List

# Sample queries catalog categorized by modality and specialist
QUERY_CATALOG: Dict[str, List[Dict[str, str]]] = {
    "📊 SQL & Analytics (PostgreSQL)": [
        {
            "query": "Compare the average review score of late versus on-time delivered orders.",
            "role": "Analyst or Operations Manager",
            "specialist": "SQL Specialist (analytics star schema)",
            "description": "Computes customer satisfaction delta between orders delivered on schedule versus those delayed past the estimated date.",
            "tables": "fct_orders, fct_reviews",
        },
        {
            "query": "What is the late delivery rate and average delay days by Brazilian state?",
            "role": "Analyst or Operations Manager",
            "specialist": "SQL Specialist",
            "description": "Aggregates delivery performance metrics grouped by customer state (dim_state_region), highlighting regional logistical bottlenecks.",
            "tables": "fct_orders, dim_state_region",
        },
        {
            "query": "Calculate total GMV and average order value for the top 5 product categories in 2018.",
            "role": "Analyst or Operations Manager",
            "specialist": "SQL Specialist",
            "description": "Performs multi-table join between orders, order items, and products to aggregate financial GMV and AOV across product categories.",
            "tables": "fct_orders, fct_order_items, dim_product",
        },
        {
            "query": "Which sellers in São Paulo (SP) have the highest carrier handoff delay?",
            "role": "Analyst or Operations Manager",
            "specialist": "SQL Specialist",
            "description": "Calculates handoff_late_rate and days between order approval and carrier handoff for sellers located in SP.",
            "tables": "fct_order_items, dim_seller",
        },
    ],
    "🕸️ Knowledge Graph (Neo4j)": [
        {
            "query": "Find sellers who share products across multiple categories and have orders with negative reviews.",
            "role": "Analyst or Operations Manager",
            "specialist": "Graph Specialist (Cypher Traversal)",
            "description": "Traverses (:Seller)-[:SOLD]->(:OrderItem)-[:IN_CATEGORY]->(:Category) and (:OrderItem)-[:HAS_REVIEW]->(:Review) to spot cross-category sellers with low satisfaction.",
            "tables": "Neo4j Knowledge Graph",
        },
        {
            "query": "Which customers have placed orders fulfilled by more than two distinct sellers in the same order?",
            "role": "Analyst or Operations Manager",
            "specialist": "Graph Specialist",
            "description": "Multi-hop graph query detecting multi-seller split-fulfillment orders: (:Customer)-[:PLACED]->(:Order)-[:CONTAINS]->(:OrderItem)-[:FULFILLS]->(:Seller).",
            "tables": "Neo4j Knowledge Graph",
        },
        {
            "query": "Trace the supply chain fulfillment path from customer to seller for order 00010242fe8c59d54245f47053e114ff.",
            "role": "Analyst or Operations Manager",
            "specialist": "Graph Specialist",
            "description": "Extracts the complete graph subgraph linking customer location, order nodes, carrier shipment, and seller warehouse.",
            "tables": "Neo4j Knowledge Graph",
        },
    ],
    "📜 Policy, SLA & Compliance (RAG)": [
        {
            "query": "What are the refund eligibility rules for late electronics deliveries?",
            "role": "Analyst or Operations Manager",
            "specialist": "Policy RAG Specialist (Vector Store)",
            "description": "Retrieves specific policy clauses regarding delayed electronics shipments, packaging standards, and return acceptance windows.",
            "tables": "Vector Knowledge Base",
        },
        {
            "query": "What is the approved customer communication template for delayed orders?",
            "role": "Analyst or Operations Manager",
            "specialist": "Policy RAG Specialist",
            "description": "Surfaces official communication boundaries and pre-approved customer notification templates (late_apology).",
            "tables": "Policy Store",
        },
        {
            "query": "Explain the difference between Tier LATE_7 and Tier LATE_15 compensation rules.",
            "role": "Analyst or Operations Manager",
            "specialist": "Policy RAG Specialist",
            "description": "Summarizes the compensation policy matrix: 20% refund for 7-14 day delays vs 50% refund for 15+ day delays.",
            "tables": "Policy Store",
        },
    ],
    "🛡️ Actions & Human-in-the-Loop (HITL)": [
        {
            "query": "Identify delivered orders delayed by more than 15 days in Rio de Janeiro and propose late compensation vouchers.",
            "role": "Operations Manager (Action-Authorized)",
            "specialist": "Action Proposer + Deterministic Policy Engine",
            "description": "Finds candidate delayed orders, applies Tier LATE_15 policy (50% item price, capped at R$ 1,000), halts at Human-in-the-Loop gate, and awaits operator approval.",
            "tables": "fct_orders, Policy Engine, FastMCP",
        },
        {
            "query": "Identify undelivered orders delayed over 10 days past estimate and propose compensation batch.",
            "role": "Operations Manager (Action-Authorized)",
            "specialist": "Action Proposer + Policy Engine",
            "description": "Applies Tier UNDELIVERED_10 (100% item price + 100% freight) and stages batch for one-click operator confirmation.",
            "tables": "fct_orders, Policy Engine, FastMCP",
        },
        {
            "query": "Please issue a full refund for order e481f51cbdc50e4277241dd3877479c2.",
            "role": "Analyst (Read-Only) — Test Security Rejection",
            "specialist": "RBAC Security Guardrail",
            "description": "Demonstrates privilege enforcement: when submitted as Analyst, the system automatically rejects write execution with an authorization error.",
            "tables": "RBAC Layer",
        },
    ],
    "🗄️ Schema & Architecture Inquiries": [
        {
            "query": "Summarize the database schema and describe the relationship between orders and order items.",
            "role": "Analyst or Operations Manager",
            "specialist": "Schema Synthesis Context",
            "description": "Outputs a high-level overview of the relational star schema, key constraints, table grains, and one-to-many relationship dynamics.",
            "tables": "analytics schema",
        },
        {
            "query": "What canonical business metrics are defined in the ontology and how is late_rate computed?",
            "role": "Analyst or Operations Manager",
            "specialist": "Ontology & Metrics Catalog",
            "description": "Explains the exact mathematical formulation of late_rate, handoff_late_rate, and gmv defined in the canonical ontology.",
            "tables": "ontology.yaml",
        },
    ],
}

# Quick starter examples for the Chatbot tab
COPILOT_STARTER_EXAMPLES = [
    "Compare the average review score of late versus on-time delivered orders.",
    "What is the late delivery rate and average delay days by Brazilian state?",
    "Find sellers who share products across multiple categories and have orders with negative reviews.",
    "What are the refund eligibility rules for late electronics deliveries?",
    "Identify delivered orders delayed by more than 15 days in Rio de Janeiro and propose late compensation vouchers.",
    "Summarize the database schema and describe the relationship between orders and order items.",
]


def get_roles_markdown() -> str:
    """Generate comprehensive documentation on user personas, permissions, and guardrails."""
    return """OntoAgent implements **Role-Based Access Control (RBAC)** and **Deterministic Execution Boundaries** to guarantee that autonomous AI agents cannot execute unauthorized state modifications or financial transfers.

---

### 1. 🔍 Data Analyst (`analyst`)
- **Badge**: `Analyst (Read-Only)`
- **Access Level**: **Strict Read-Only**
- **Authorized Operations**:
  - Analytical SQL queries against PostgreSQL `analytics` schema via read-only user (`ontoagent_ro`).
  - Knowledge graph multi-hop traversals via Neo4j Cypher read queries.
  - Policy & SLA document search via pgvector semantic embeddings.
  - Schema, entity, and metric inspections.
- **Enforced Restrictions**:
  - **Zero Action Privileges**: Any prompt requesting refunds, voucher creation, ticket generation, or status mutation is rejected at the LangGraph supervisor node.
  - **Try it out**: Switch persona to `Analyst` and prompt: *"Issue a refund of R$ 100 for order 12345"*. The system will refuse execution with `Action Denied: Insufficient Role Privileges`.

---

### 2. 🛡️ Operations Manager (`ops_manager`)
- **Badge**: `Operations Manager (Action-Authorized)`
- **Access Level**: **Analytical + Propose Actions (Human-in-the-Loop)**
- **Authorized Operations**:
  - All read-only analytical queries available to the Analyst.
  - Proposing compensation batches for delayed or unfulfilled orders based on deterministic SLA policies.
  - Reviewing candidate orders, compensation amounts, and reason codes.
  - Approving or rejecting proposed action batches via the Human-in-the-Loop gate.
- **Safety Workflow**:
  1. **Candidate Identification**: The agent identifies eligible orders using SQL queries.
  2. **Deterministic Calculation**: Refund calculations are **never delegated to LLM hallucination**; the deterministic policy engine computes amounts strictly per SLA tiers (`LATE_7`, `LATE_15`, `UNDELIVERED_10`).
  3. **Hard Financial Ceilings**:
     - Maximum **R$ 1,000.00** per order cap.
     - Maximum **R$ 10,000.00** / **25 orders** per batch ceiling.
  4. **LangGraph Interrupt Gate**: Graph execution pauses at `human_approval`. No write occurs until the operator clicks **Approve Batch**.
  5. **HMAC-Signed JTI Token**: Approving the batch mints a single-use HMAC token that the FastMCP action server verifies and consumes, preventing replay attacks.
"""


def get_database_architecture_markdown() -> str:
    """Generate documentation explaining the multi-modal database stack."""
    return """OntoAgent unifies three distinct storage paradigms to handle complex enterprise e-commerce operational intelligence:

```text
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                         USER QUERY                                          │
└──────────────────────────────────────────────┬──────────────────────────────────────────────┘
                                               │
                                               ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                         LANGGRAPH SUPERVISOR (Routing & Subtask Plan)                       │
└──────────────┬───────────────────────────────┼───────────────────────────────┬──────────────┘
               │                               │                               │
               ▼                               ▼                               ▼
┌───────────────────────────────┐ ┌───────────────────────────┐ ┌─────────────────────────────┐
│       📊 SQL Specialist       │ │    🕸️ Graph Specialist     │ │    📜 Policy Specialist     │
│   PostgreSQL 16 Analytics DB  │ │  Neo4j 5.x Knowledge Graph│ │  pgvector Knowledge Base    │
│   Star Schema (8 Fact/Dims)   │ │  Multi-Hop Supply Chain   │ │  SLAs & Communication Rules │
└───────────────────────────────┘ └───────────────────────────┘ └─────────────────────────────┘
                                               │
                                               ▼ (When Action Proposed)
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                 DETERMINISTIC POLICY ENGINE (SLA Rules, Tiers & Financial Caps)             │
└──────────────────────────────────────────────┬──────────────────────────────────────────────┘
                                               │
                                               ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│               🛡️ HUMAN-IN-THE-LOOP APPROVAL GATE (LangGraph Execution Pause)                │
│                   Operator reviews proposed order batch and compensation sum                │
└──────────────────────────────────────────────┬──────────────────────────────────────────────┘
                                               │ (On "Approve Batch")
                                               ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                 FastMCP ACTION SERVER (Cryptographic Single-Use HMAC Token)                 │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

### 1. 📊 PostgreSQL 16 Data Warehouse (`analytics` schema)
- **Role**: Relational analytics, high-volume aggregations, filtering, and metric computation.
- **Connection Security**: Enforced read-only user (`ontoagent_ro`) with explicit `SET TRANSACTION READ ONLY`. AST-level SQL validation blocks all mutating operations (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`).
- **Core Tables**:
  - `analytics.fct_orders`: Grain: 1 row per order (order status, timestamps, carrier handoff, delay flag, delivery date).
  - `analytics.fct_order_items`: Grain: 1 row per order item (price, freight, seller, product).
  - `analytics.dim_seller`: Seller metadata, zip code, state, regional cluster.
  - `analytics.dim_product`: Product dimensions, weight, Brazilian category name.
  - `analytics.fct_reviews`: Customer satisfaction scores (1-5), review comments, timestamps.
  - `analytics.fct_payments`: Payment method (credit card, boleto, voucher), installments, sequential value.
  - `analytics.dim_customer`: Customer unique identifier, zip prefix, city, state.
  - `analytics.dim_state_region`: Brazilian geographical hierarchy (UF, Region, logistics zone).

---

### 2. 🕸️ Neo4j 5.x Knowledge Graph
- **Role**: Multi-hop relationship traversals, supply chain network analysis, co-purchasing, and fraud/cluster detection.
- **Node Labels**: `(:Customer)`, `(:Order)`, `(:OrderItem)`, `(:Product)`, `(:Seller)`, `(:Review)`, `(:Category)`, `(:StateRegion)`.
- **Key Relationships**:
  - `(:Customer)-[:PLACED]->(:Order)`
  - `(:Order)-[:CONTAINS]->(:OrderItem)`
  - `(:OrderItem)-[:SOLD]->(:Product)`
  - `(:OrderItem)-[:FULFILLS]->(:Seller)`
  - `(:Order)-[:HAS_REVIEW]->(:Review)`
  - `(:Product)-[:IN_CATEGORY]->(:Category)`
  - `(:Seller)-[:LOCATED_IN]->(:StateRegion)`

---

### 3. 📜 Vector Knowledge Base (pgvector / Chroma)
- **Role**: Semantic policy retrieval, SLA rules, customer communication templates, and seller probation criteria.
- **Retrieved Chunks**:
  - Official Customer Communication Boundaries & Approved Templates (`late_apology`).
  - Electronics Category Special Handling & Returns SLA.
  - Automated Delay Compensation Matrix (`Tier LATE_7`, `Tier LATE_15`, `Tier UNDELIVERED_10`).
  - Seller Probation & Delivery Reliability Guardrails.
"""


def get_navigation_guide_markdown() -> str:
    """Generate step-by-step UI navigation and user flow guide."""
    return """Follow this operational workflow to test and navigate the OntoAgent platform:

```text
[ Step 1: Select Persona ] ──▶ [ Step 2: Submit Query / Examples ] ──▶ [ Step 3: Inspect Trace Drawer ]
 (Analyst vs Ops Manager)        (Input Box or Starter Queries)           (SQL, Cypher & Policy RAG)
                                                                                       │
                                                  ┌────────────────────────────────────┴────────────────────────────────────┐
                                                  ▼                                                                         ▼
                                        [ Analytical Query ]                                                      [ Operational Action ]
                                                  │                                                                         │
                                     Synthesized Direct Response                                                LangGraph Pauses Execution
                                       with Factual Citations                                                               │
                                                                                                                 [ Step 4: Review Approval Card ]
                                                                                                                  (Candidate count & R$ total)
                                                                                                                            │
                                                                                                                 [ Step 5: Click Approve / Reject ]
                                                                                                                  (Mints HMAC Token for FastMCP)
```

---

### Step 1: Choose Your Active Persona
- Located at the top of the **💬 Copilot Chat** tab.
- **Analyst**: Use for analytical reporting, exploratory questions, and graph traversals. (Safe mode; write actions are blocked).
- **Operations Manager**: Use when evaluating operational remediation, creating compensation vouchers, or executing policies.

### Step 2: Ask Questions or Test Queries
- Type your question in the input box, or click any pre-configured query from the **Starter Queries** right below the chat box.
- The **LangGraph Supervisor** automatically parses the user intent and fans out to the appropriate specialist agent (SQL, Graph, RAG, or Policy Proposer).

### Step 3: Inspect the Real-Time Trace Drawer
- On the right side of the **Copilot Chat** tab, you can expand the three collapsible drawers:
  - **Generated SQL Query**: Inspect the exact sanitized PostgreSQL query executed.
  - **Graph Cypher Pattern**: Inspect the generated Neo4j graph traversal match pattern.
  - **Retrieved Policy Documents**: Inspect the retrieved RAG policy passages and citations.

### Step 4: Test Human-in-the-Loop Actions
- Switch persona dropdown to **Operations Manager**.
- Submit an operational remediation query such as:
  > *"Identify delivered orders delayed by more than 15 days in Rio de Janeiro and propose late compensation vouchers."*
- Notice how execution pauses: an **Approval Card** appears below the chat with candidate count and total compensation amount.
- Click **Approve Batch** to mint an HMAC token and execute via FastMCP, or **Reject Batch** to safely dismiss the proposal.

### Step 5: Explore the Schema & Policies Tabs
- **🗄️ Database Schema**: Use the search bar to find any table, column, business metric, or graph relationship.
- **📜 SLA Policies**: Review the business rules, delay tiers, financial ceilings, and cryptographic validation specs.
"""


def get_playbook_markdown(category_name: str) -> str:
    """Generate query playbook table and descriptions for a selected category."""
    items = QUERY_CATALOG.get(category_name, [])
    if not items:
        return "No queries found for this category."

    lines = [
        f"**Category: {category_name}**",
        "",
        "Copy any query below and test it in the **💬 Copilot Chat** tab:",
        "",
    ]

    for idx, item in enumerate(items, 1):
        lines.extend([
            f"### {idx}. {item['query']}",
            f"- **Target Specialist**: {item['specialist']}",
            f"- **Required Role**: `{item['role']}`",
            f"- **Data Source**: `{item['tables']}`",
            f"- **Business Purpose**: {item['description']}",
            f"> 💬 **Query to Run**:\n> ```{item['query']}```",
            "",
        ])

    return "\n".join(lines)
