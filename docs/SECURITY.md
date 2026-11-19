# OntoAgent Security Architecture & Threat Model

## 1. Overview & Security Philosophy

OntoAgent is built around a non-negotiable principle: **defense-in-depth with fail-closed invariants**. LLMs are treated as inherently untrusted reasoning engines that must never possess direct authority to mutate state, bypass schema boundaries, or execute unvalidated code.

Every query, traversal, policy lookup, and tool invocation passes through independent code-level validators and security gates.

---

## 2. Threat Model Matrix (T1 – T12)

| Threat ID | Threat Name | Attack Vector / Scenario | OntoAgent Defense & Mitigation | Tested In |
|---|---|---|---|---|
| **T1** | SQL Injection via LLM | Prompt injection attempts to force `DROP TABLE`, `UPDATE`, or access unauthorized tables (`ops.*`, `raw.*`). | `sqlglot` AST validation restricts statements strictly to `SELECT` on `analytics.*` tables only. Multi-statement queries and administrative commands are rejected. | `tests/unit/test_sql_validator.py`, `tests/adversarial/` |
| **T2** | Cypher Injection & Mutation | Adversarial input aims to execute `DETACH DELETE`, `SET`, or `REMOVE` in Neo4j. | Regex and AST Cypher validator enforces read-only operations (`MATCH`, `RETURN`). Disallows mutation keywords and caps traversal bounds. | `tests/unit/test_cypher_validator.py` |
| **T3** | Direct Prompt Injection | User input includes jailbreak phrases ("Ignore previous instructions", "Reveal system prompt", "You are now DAN"). | Input guard detects known jailbreak signatures, truncates oversized payloads (> 2000 chars), and flags `PROMPT_INJECTION` to abort turn. | `tests/unit/test_input_guard.py` |
| **T4** | Indirect Prompt Injection (RAG) | Poisoned policy documents containing hidden instructions injected into LLM context. | RAG specialist runs injection scanning during ingestion. Retrieved chunks are isolated within strict `<untrusted_data>` XML delimiters. | `tests/unit/test_sanitizer.py`, `tests/adversarial/` |
| **T5** | Denial of Service (Heavy Queries) | Queries with Cartesian joins or unbounded scans designed to exhaust database CPU/memory. | AST validators automatically enforce `LIMIT` clauses. Database connection roles have statement timeouts (`5s`) and read-only transaction defaults. | `tests/unit/test_sql_validator.py` |
| **T6** | PII Exfiltration | Attacker queries customer personal data (CPF, email, phone number) for extraction. | Brazilian CPF, phone, email, and credit card regex patterns automatically mask data into numbered placeholders (`[CPF_1]`, `[EMAIL_1]`). | `tests/unit/test_pii.py` |
| **T7** | Privilege Escalation (RBAC) | `analyst` user attempts to trigger refund actions or view sensitive restricted metrics. | Role-based policy enforcement (`policies/rbac.yaml`). The action planner rejects any actor without `ops_manager` credentials before drafting proposals. | `tests/unit/test_action_pipeline.py` |
| **T8** | Unauthorized Action Execution | Unapproved or automated execution of financial refunds or seller sanctions. | Human-in-the-Loop (HITL) gate: LangGraph pauses via `interrupt()`. Execution cannot resume without an authenticated human operator decision. | `tests/unit/test_action_pipeline.py`, `tests/unit/test_api.py` |
| **T9** | Approval Token Replay | Malicious actor captures a valid approval token and replays it to issue duplicate refunds. | Every approval token carries a unique `jti`. The MCP server writes used tokens to `ops.used_tokens` and verifies single-use in a serial transaction. | `tests/unit/test_action_pipeline.py` |
| **T10** | Approval Token Tampering | Attacker alters the refund amount or order ID in transit while using a valid signature. | Tokens encode an HMAC-SHA256 signature binding `thread_id`, `tool_name`, `approver`, and a canonical SHA-256 hash of all tool arguments. | `tests/unit/test_approval_token.py` |
| **T11** | Fabricated / Hallucinated Outputs | LLM generates plausible-sounding numbers or metrics without database backing. | Numeric grounding verification: synthesizer answers must be supported by specialist result sets. If databases are unreachable, execution fails closed. | `tests/unit/test_eval_runner.py` |
| **T12** | Data Exfiltration via Messaging | Free-form messages sent to sellers containing sensitive customer or internal data. | External communications are strictly constrained to pre-approved, deterministic templates (`policies/refund_policy.yaml`). | `tests/unit/test_action_pipeline.py` |

---

## 3. Cryptographic Token Invariants

Operational side-effects require an HMAC-SHA256 signed token minted at approval time:

```python
Token Payload = {
    "jti": UUIDv4,
    "thread_id": str,
    "tool": str,
    "args_hash": SHA256(canonical_json(args)),
    "approver": str,
    "iat": int,
    "exp": int (iat + 900s)
}
Token = base64url(payload) + "." + HMAC_SHA256(secret, payload)
```

### Verification Pipeline in FastMCP Server:
1. **Signature Integrity**: Verifies HMAC signature using `APPROVAL_HMAC_SECRET`.
2. **Expiry Verification**: Rejects tokens older than 15 minutes (`exp < now()`).
3. **Replay Defense**: Checks `ops.used_tokens` for `jti`. Rejects if already recorded.
4. **Argument Binding**: Computes `SHA256(args)` and asserts exact match against `args_hash`.
5. **Business Bounds**: Enforces hard caps (≤ R$ 1,000.00/order; valid reason codes: `LATE_7`, `LATE_15`, `UNDELIVERED_10`).
6. **Atomic Commit**: Records used token in `ops.used_tokens`, writes ticket to `ops.refund_tickets`, and writes audit event to `ops.audit_log` within a single database transaction.

---

## 4. Database User Isolation

| Role Name | Allowed Schemas | Permissions | Enforced Invariants |
|---|---|---|---|
| `ontoagent_ro` | `analytics` | `SELECT` | `statement_timeout = '5s'`, `default_transaction_read_only = on` |
| `ontoagent_kb` | `kb` | `SELECT` | Read-only vector and text search on policy chunks |
| `ontoagent_app` | `analytics`, `ops` | `SELECT` on `analytics.*`, `SELECT` on `ops.refund_tickets`, `INSERT` on `ops.audit_log` | API checkpointer and read-only status verification |
| `ontoagent_ops` | `ops` | `SELECT, INSERT` on `ops.*` | Dedicated to MCP server; strictly isolated from `raw.*` and `analytics.*` write access |
| `ontoagent_admin` | All | Full DDL/DML | Used only by migration and offline data loading scripts (`load_postgres.py`) |
