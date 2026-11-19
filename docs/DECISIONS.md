# Architecture Decision Records (ADRs)

## ADR-001: Separation of Relational (PostgreSQL) and Graph (Neo4j) Workloads
- **Context:** Enterprise operations data consists of high-volume transaction records (orders, payments, line items) that require aggregation, alongside multi-hop networks (sellers, orders, customers, reviews) that reveal relational risk clusters.
- **Decision:** Use PostgreSQL 16 (with pgvector) for quantitative reporting, analytical queries, and vector storage, and Neo4j 5 for graph traversal and cluster analysis.
- **Alternatives Considered:** Storing everything in PostgreSQL via recursive CTEs; storing everything in Neo4j.
- **Consequences:** Clean separation of concerns; analytical queries stay fast and scalable in Postgres, while relationship queries stay expressive and efficient in Cypher.

## ADR-002: Role-Based Connection Segregation in PostgreSQL
- **Context:** Specialists and API callers have differing privilege requirements. Giving agents blanket read/write privileges risks data loss or accidental mutation.
- **Decision:** Establish dedicated PostgreSQL roles: `ontoagent_ro` (read-only for analytical schemas), `ontoagent_kb` (read-only for vector knowledge base), `ontoagent_app` (read-only for application data, append-only for audit), `ontoagent_ops` (restricted write access for ticket operations), and `ontoagent_admin` (schema migrations).
- **Alternatives Considered:** Single service user with application-level RBAC filtering.
- **Consequences:** Security boundary enforced at the database kernel level; SQL injection attacks cannot escape table/schema boundaries or perform unauthorized DML/DDL.

## ADR-003: Pure-AST SQL & Cypher Validation Before Execution
- **Context:** LLM-generated queries may contain syntax errors, prohibited statements (DDL, mutation), or unauthorized table/column references.
- **Decision:** Parse and validate all SQL via `sqlglot` and Cypher via regex AST keyword analysis before sending statements to the database engine.
- **Alternatives Considered:** Relying solely on database user permissions or post-execution error handling.
- **Consequences:** Eliminates attack vectors before they reach the database; prevents query errors from leaking database internals.

## ADR-004: Anti-Fabrication Invariant (Grounding & Fail-Closed Synthesis)
- **Context:** Hallucinated metrics or fabricated rows destroy trust in enterprise operations copilots.
- **Decision:** Specialists fail closed when data is unavailable or queries fail. Numbers presented in final syntheses must be directly traceable to query results or retrieved policy documents.
- **Alternatives Considered:** Providing synthetic estimates or fallback estimations when queries return empty or fail.
- **Consequences:** Grounded, trustworthy answers; system admits when data is unavailable rather than inventing figures.

## ADR-005: HMAC-SHA256 Cryptographic Approval Tokens
- **Context:** Human-in-the-loop action proposals must not be tampered with between approval review and MCP execution.
- **Decision:** Mint stateless HMAC-SHA256 tokens binding thread ID, tool name, exact argument digest, approver identity, and expiration timestamp.
- **Alternatives Considered:** Database-persisted approval session flags or JWT tokens.
- **Consequences:** Zero external state needed for token verification; replay attacks, argument modification, and unauthorized tool calls are cryptographically blocked.

## ADR-006: Explicit Delimiter Encapsulation for Untrusted Text
- **Context:** Free-text review comments and knowledge base chunks may contain indirect prompt injection attacks designed to hijack agent behavior.
- **Decision:** Wrap untrusted text in strict XML-style `<untrusted_data>` boundaries and strip literal closing tags before inclusion in prompts.
- **Alternatives Considered:** Naive string interpolation or markdown quoting.
- **Consequences:** Clear semantic separation between system instructions and external user/data payloads.

## ADR-007: LangGraph State Machine Orchestration
- **Context:** Complex operations workflows require parallel specialist delegation, state checkpointing, human-in-the-loop interrupts, and conditional error routing.
- **Decision:** Use LangGraph `StateGraph` with explicit state models, parallel fan-out conditional edges, and memory-backed checkpoints.
- **Alternatives Considered:** Sequential LangChain chains, AutoGen, or custom async loops.
- **Consequences:** Fully inspectable, deterministic control flow; easy pause/resume for approval; clear event tracing.

## ADR-008: FastMCP for Action Execution
- **Context:** External operational actions (creating refund tickets, sending seller notifications) must follow standard tool-use protocols with audit logging.
- **Decision:** Use FastMCP with streamable HTTP and stdio transport, verifying approval tokens and business policy caps server-side.
- **Alternatives Considered:** Direct REST API calls or ad-hoc database mutations in agent nodes.
- **Consequences:** Interoperable tool-use architecture conforming to Model Context Protocol standards.

## ADR-009: PII Redaction and Deterministic Pseudonymization
- **Context:** Customer personal identifying information (names, emails, phones, CPF) must never be passed to LLMs or displayed to unauthorized roles.
- **Decision:** Mask PII attributes at the database retrieval layer and deterministically pseudonymize customer IDs using HMAC-SHA256.
- **Alternatives Considered:** Masking in the UI layer only.
- **Consequences:** Zero PII leakage to LLM providers or intermediate logs; consistent multi-turn reasoning without real-world identity exposure.

## ADR-010: Free, Local Embeddings via Sentence-Transformers
- **Context:** RAG retrieval over operational policies requires embedding generation for vector search.
- **Decision:** Use `sentence-transformers/all-MiniLM-L6-v2` generating 384-dimensional dense vectors locally.
- **Alternatives Considered:** OpenAI `text-embedding-3-small` or cloud endpoints.
- **Consequences:** Completely free, offline-capable, deterministic, and fast vector generation with zero external dependencies.

## ADR-011: Strict MemorySaver Default Checkpointer
- **Context:** Checkpoint persistence across turns is required for multi-turn conversational context and approval interrupts.
- **Decision:** Use LangGraph's `MemorySaver` as the default checkpointer, supporting optional PostgreSQL checkpointer via configuration.
- **Alternatives Considered:** Mandatory PostgreSQL checkpointer for all environments.
- **Consequences:** Fast, dependency-free local testing and CI workflows with straightforward migration to production persistent stores.

## ADR-012: Deterministic Synthetic PII Generation via Faker and Hash Seeding
- **Context:** To demonstrate and test PII redaction and pseudonymization without leaking real customer data, realistic Brazilian identifiers are required.
- **Decision:** Deterministically generate synthetic CPF, phone numbers, and emails using `Faker('pt_BR')` seeded by the SHA-256 hash of `customer_unique_id`.
- **Alternatives Considered:** Hardcoded dummy values or random unseeded values.
- **Consequences:** Customer identity attributes remain constant across test runs and database rebuilds while real personal data is never stored.

## ADR-013: Plain SQL Parameterized Order Facts Fetcher in Action Planner
- **Context:** The action planner must calculate compensation eligibility for candidate orders.
- **Decision:** Use a fixed, parameterized SQL query in code (`fetch_order_facts`) rather than allowing the LLM to query or filter candidate rows.
- **Alternatives Considered:** Allowing the LLM to inspect raw rows and output amounts.
- **Consequences:** Ensures zero mathematical hallucination; compensation amounts and eligibility are computed strictly by deterministic Python policy code.

## ADR-014: Single Source of Truth for Policy Numbers (YAML & Markdown Synchronization)
- **Context:** Discrepancies between human-readable policy documentation and programmatic decision logic create compliance vulnerabilities.
- **Decision:** Maintain policy thresholds in `policies/refund_policy.yaml` and enforce consistency with `policies/docs/refund_policy.md` via automated unit tests.
- **Alternatives Considered:** Hardcoding numbers in Python files and markdown separately.
- **Consequences:** Any drift between documentation and code immediately breaks unit testing and fails CI.

## ADR-015: Cross-Platform Verification Runner (make.bat and scripts/verify.py)
- **Context:** The specification prescribes a single verification command `make verify`. Windows environments often lack GNU `make`.
- **Decision:** Implement `scripts/verify.py` as the canonical verification engine, callable via `Makefile` on POSIX systems and `make.bat` or `python scripts/verify.py` on Windows.
- **Alternatives Considered:** Forcing Windows users to install Chocolatey or WSL to acquire `make`.
- **Consequences:** Seamless one-command verification across Windows, Linux, macOS, and GitHub Actions CI without platform prerequisites.

## ADR-016: Fail-Closed SQL Execution and Explicit Offline Fixture Protocol
- **Context:** In offline scenarios without live database services, returning hardcoded mock rows violates the core promise of zero data fabrication.
- **Decision:** Enforce fail-closed SQL execution returning SqlStepResult(ok=False, error_code="DB_UNAVAILABLE") unless ONTOAGENT_OFFLINE_FIXTURES=1 is explicitly set in the environment. When enabled, fixture rows are explicitly marked with `_fixture: true` and the synthesizer prominently prefixes the response with 'FIXTURE DATA'.
- **Alternatives Considered:** Silently substituting fake rows or fallback count queries.
- **Consequences:** Enforces complete honesty and eliminates fabricated numbers from the system.

## ADR-017: Deterministic Action Pipeline, MCPServer Selection, and Two-Tier Approval Gate
- **Context:** Enterprise operations workflows require an action path where operational actions are proposed, approved by humans, and executed via FastMCP. Official `mcp` SDK v2.0 renamed `FastMCP` to `MCPServer`, and allowing models to compute compensation amounts or execute mutations directly poses critical hallucination and tool-abuse risks (Threats T1, T7, T8, T12).
- **Decision:** Implement pure deterministic compensation calculation in `policy_engine.py` using `Decimal` arithmetic with zero LLM math. Adopt `mcp.server.mcpserver.MCPServer` in `mcp_server/server.py` with full server-side re-validation and independent auth. Enforce a two-tier gate: LangGraph `interrupt()` for human approval (narrowing only) followed by single-use HMAC-SHA256 token verification and atomic `jti` tracking in PostgreSQL `ops.used_tokens`.
- **Alternatives Considered:** Permitting LLMs to choose compensation values or trusting client-supplied amounts.
- **Consequences:** Guaranteed mathematical accuracy, single-use token replay protection, and hard role isolation restricting action planning exclusively to `ops_manager`.

## ADR-018: REST API Architecture, State Management, and Gradio Operational Interface
- **Context:** Enterprise deployment requires a robust REST API and interactive web console enabling analysts and operations managers to inspect the ontology, execute grounded conversational analytics, review SQL/Cypher/RAG traces, and approve or narrow operational actions with role-governed authorization.
- **Decision:** Build FastAPI service (`src/ontoagent/api/main.py`) exposing `/v1/health`, `/v1/ontology`, `/v1/chat`, `/v1/threads/{thread_id}/approval`, and `/v1/threads/{thread_id}`. Map `X-API-Key` headers to `UserIdentity(actor_id, role)`. Enforce hard role gates returning HTTP 403 Forbidden when non-`ops_manager` users attempt approval. Implement Gradio console (`src/ontoagent/ui/app.py`) with persona switching, conversational history, collapsible trace accordion, automatic available port discovery, and interactive human-in-the-loop approval controls. For PostgreSQL execution, adopt `asyncio.to_thread` wrapping synchronous `psycopg.connect` in `src/ontoagent/db/pg.py` to guarantee complete compatibility across all async event loops on Windows (including default `ProactorEventLoop`) and POSIX.
- **Alternatives Considered:** Building monolithic UI without REST abstraction, forcing `WindowsSelectorEventLoopPolicy` (incompatible with AnyIO/Tornado runners), or skipping human interrupt controls.
- **Consequences:** Clean separation of concerns, secure role isolation across API and UI, cross-platform socket stability on Windows, and strict compliance with enterprise security policies.

## ADR-019: LLM Provider Alignment and Benchmark Provenance Isolation
- **Context:** The upstream Google GenAI endpoint deprecated `gemini-1.5-flash` for new API keys (returning HTTP 404), while Groq does not serve Google Gemini models (causing `gemini-1.5-pro` on Groq to fail with model not found). Upgrading models changes latency and generation characteristics, raising potential drift against historical benchmark reports.
- **Decision:** Configure modern defaults (`LLM_MODEL=gemini-3.5-flash` and `LLM_FALLBACK_MODEL=openai/gpt-oss-120b`). Preserve strict benchmark honesty: documentation in `docs/RESULTS.md` explicitly identifies `evals/reports/eval_20261026_140340.json` as the baseline Gemini 1.5 benchmark audit artifact, and decouples active runtime model upgrades from historical benchmark records. Offline CI unit tests remain 100% deterministic using `FakeChatModel`.
- **Alternatives Considered:** Silently altering historical benchmark numbers without a fresh run or leaving broken model endpoints in `.env`.
- **Consequences:** Full model availability in production environments without fabricating or confounding benchmark audit numbers.


