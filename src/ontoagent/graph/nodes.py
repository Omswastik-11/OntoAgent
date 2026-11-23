"""Core LangGraph node implementations for OntoAgent.

Purpose:
    Turn initialization, input safety guard, supervisor intent decomposition,
    specialist delegation wrappers, grounded synthesis, deterministic action planning,
    human-in-the-loop approval interrupt/resume, and final turn closure.
    Enforces explicit error propagation, degraded modes, and strict anti-fabrication.
"""

from decimal import Decimal
import hashlib
import json
import logging
import re
import time
from typing import Any, Dict, List
import unicodedata
import uuid

import psycopg

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.types import interrupt

from ontoagent.actions.mcp_client import McpClient
from ontoagent.actions.planner import plan_refund_action
from ontoagent.agents.graph.graph import run_graph_subgraph
from ontoagent.agents.rag.graph import run_rag_subgraph
from ontoagent.agents.sql.graph import run_sql_subgraph
from ontoagent.config import get_settings
from ontoagent.graph.models import RoutePlan, Subtask
from ontoagent.graph.state import RESET, AgentState
from ontoagent.guards.approval_token import mint_approval_token
from ontoagent.guards.sanitize import scan_untrusted_text
from ontoagent.llm import extract_text_content, get_llm
from ontoagent.ontology.time import resolve_time_expression

logger = logging.getLogger(__name__)


def init_turn(state: AgentState) -> Dict[str, Any]:
    """Extract question, resolve relative dates, and reset per-turn fields."""
    messages = state.get("messages", [])
    question = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage) or getattr(msg, "type", "") == "human":
            question = msg.content if isinstance(msg.content, str) else str(msg.content)
            break

    settings = get_settings()
    time_fact = resolve_time_expression(question, as_of_str=settings.as_of_date)
    time_ctx = {
        "as_of": settings.as_of_date,
        "resolved_range": time_fact.model_dump() if time_fact else None,
    }

    # Reset per-turn fields using sentinel RESET for accumulating lists
    return {
        "question": question,
        "time_context": time_ctx,
        "risk_flags": [RESET],
        "plan": None,
        "sql_results": None,
        "graph_result": None,
        "rag_result": None,
        "draft_answer": None,
        "answer": None,
        "citations": [],
        "proposed_action": None,
        "approval": None,
        "action_outcome": None,
        "action_result": None,
        "final_text": None,
        "errors": [RESET],
        "events": [RESET, {"ts": time.time(), "type": "turn_init", "detail": {"as_of": settings.as_of_date}}],
    }


def input_guard(state: AgentState) -> Dict[str, Any]:
    """Validate query length, empty input, and scan for prompt injection heuristics."""
    question = state.get("question", "")

    # Empty question must route to clarify, not supervisor
    if not question or not question.strip():
        return {
            "question": "",
            "errors": ["Empty question received."],
            "risk_flags": ["EMPTY_QUESTION"],
            "plan": {
                "decision": "clarify",
                "clarification_question": "Please provide a valid question or operational request.",
                "subtasks": [],
                "wants_action": False,
                "rationale": "Empty question provided.",
            },
            "final_text": "Please provide a valid question or operational request.",
        }

    # Length cap (2000 chars)
    if len(question) > 2000:
        return {
            "errors": ["Question exceeds maximum permitted length (2000 characters)."],
            "risk_flags": ["QUERY_TOO_LONG"],
            "plan": {
                "decision": "refuse",
                "refusal_reason": "Your query is too long. Please restrict requests to under 2,000 characters.",
                "subtasks": [],
                "wants_action": False,
                "rationale": "Query exceeds 2000 characters.",
            },
            "final_text": "Your query is too long. Please restrict requests to under 2,000 characters.",
        }

    # Unicode normalization
    normalized = unicodedata.normalize("NFKC", question)

    # Injection scan heuristics (soft flags)
    scan_res = scan_untrusted_text(normalized)
    risk_flags = []
    if scan_res.flagged:
        risk_flags.append("USER_INJECTION_PATTERN")
        if scan_res.score >= 0.8:
            risk_flags.append("USER_INJECTION_HARD")

    events = [{"ts": time.time(), "type": "input_guard_pass", "detail": {"scan_score": scan_res.score}}]

    return {
        "question": normalized,
        "risk_flags": risk_flags,
        "events": events,
    }


async def supervisor(state: AgentState) -> Dict[str, Any]:
    """Analyze intent and produce structured subtask routing decomposition."""
    question = state.get("question", "")
    role = state.get("user_role", "analyst")
    time_ctx = state.get("time_context", {})
    as_of = time_ctx.get("as_of", "2018-09-01")

    prompt = f"""You are the OntoAgent Supervisor. Analyze this operational ecommerce question and plan the retrieval.
User Role: {role}
Current As-Of Date: {as_of}

User Question: {question}

Role Permissions:
- Analyst: Strictly READ-ONLY analytical and policy queries. If the user asks to create, modify, refund, compensate, cancel, or execute any operational action/write, you MUST set decision='refuse' and refusal_reason='Action planning and execution requires Operations Manager authorization. The Analyst role is strictly restricted to read-only analytical queries.'
- Operations Manager: Authorized to plan, initiate, and draft operational actions. When an action is requested (e.g. create/propose/draft refund or compensation batch), set wants_action=True, action_type='refund', and include a SQL subtask to fetch candidate delayed order IDs (e.g. 'Retrieve late orders including order_id, delay_days').

Routing rules:
1. SQL: Aggregates, counts, delay rates, averages, order values, list of delayed orders, metrics by category, seller, customer, or questions inquiring about the database schema, tables, entities, or columns.
2. RAG: Policies, refund rules, SLAs, escalation procedures, thresholds.
3. GRAPH: Multi-hop seller/customer/product network relationships, co-purchases, shared customers, and review clusters.
4. Decision: "answer" for valid questions/plans, "clarify" if completely ambiguous, "refuse" if unauthorized, destructive, or out-of-scope.
5. wants_action: Set to TRUE whenever the user asks to create, propose, draft, initiate, execute, or prepare a refund, compensation, ticket, or batch.

Subtask Guidelines:
- In the Subtask instruction field, keep the instruction concise and directly focused on the user's business question (e.g. "Find categories with highest number of late shipments").
- NEVER invent, assume, or fabricate fictional table names, columns, or schemas (e.g. DO NOT say "Assume there are tables orders, products, categories").

Return a valid RoutePlan."""

    llm = get_llm(temperature=0.0)
    structured_llm = llm.with_structured_output(RoutePlan)

    try:
        plan: RoutePlan = await structured_llm.ainvoke([
            SystemMessage(content="You are an expert query router decomposing operational retail analytics tasks."),
            HumanMessage(content=prompt),
        ])
        plan_dict = plan.model_dump()
        role = state.get("user_role", "analyst")
        risk_flags = state.get("risk_flags", [])

        WRITE_ACTION_TERMS = {
            "create", "modify", "refund", "compensate", "compensation",
            "cancel", "execute", "issue", "draft", "update", "delete", "write"
        }
        words = set(re.findall(r"\b[a-zA-Z]+\b", question.lower()))
        is_write_intent = bool(words & WRITE_ACTION_TERMS) or plan_dict.get("wants_action") or (plan_dict.get("action_type") not in ("none", "", None))

        if role != "ops_manager" and is_write_intent:
            plan_dict["decision"] = "refuse"
            plan_dict["subtasks"] = []
            plan_dict["wants_action"] = False
            plan_dict["refusal_reason"] = (
                "Action planning and execution requires Operations Manager authorization. "
                "The Analyst role is strictly restricted to read-only analytical queries."
            )
            plan_dict["rationale"] = "Analyst role is unauthorized to plan, create, modify, or execute operational actions."
        elif role == "ops_manager" and is_write_intent and "USER_INJECTION_HARD" not in risk_flags:
            plan_dict["wants_action"] = True
            if not plan_dict.get("subtasks"):
                plan_dict["subtasks"] = [{"specialist": "sql", "instruction": f"Retrieve candidate orders with order_id for: {question}"}]
        elif role != "ops_manager" or "USER_INJECTION_HARD" in risk_flags:
            plan_dict["wants_action"] = False
    except Exception as e:
        # Fallback handling: log error, append to state errors, degrade explicitly with SUPERVISOR_FALLBACK
        logger.warning("Supervisor LLM failed: %s; degrading to single SQL subtask fallback", str(e))
        plan_dict = {
            "decision": "answer",
            "subtasks": [{"specialist": "sql", "instruction": question}],
            "wants_action": False,
            "action_type": "none",
            "clarification_question": None,
            "refusal_reason": None,
            "rationale": "Supervisor fallback due to model error; default to SQL execution.",
        }
        return {
            "plan": plan_dict,
            "errors": [f"Supervisor LLM error: {str(e)}"],
            "risk_flags": ["SUPERVISOR_FALLBACK"],
            "events": [{"ts": time.time(), "type": "supervisor_degraded", "detail": {"error": str(e)}}],
        }

    return {
        "plan": plan_dict,
        "events": [{"ts": time.time(), "type": "supervisor_done", "detail": plan_dict}],
    }


def _extract_instruction(st: Any) -> str:
    if isinstance(st, str):
        return st
    if isinstance(st, dict):
        return st.get("instruction", "")
    return getattr(st, "instruction", "")


def _extract_specialist(st: Any) -> str:
    if isinstance(st, str):
        return "sql"
    if isinstance(st, dict):
        return st.get("specialist", "")
    return getattr(st, "specialist", "")


async def sql_specialist_node(state: AgentState) -> Dict[str, Any]:
    """Execute SQL specialist subgraph for all SQL subtasks in the plan."""
    plan = state.get("plan") or {}
    subtasks = plan.get("subtasks", [])
    sql_instructions = [
        _extract_instruction(st)
        for st in subtasks
        if _extract_specialist(st) == "sql"
    ]

    question = state.get("question", "")
    cleaned_instructions = []
    for inst in sql_instructions:
        lower_inst = inst.lower()
        if any(h in lower_inst for h in ["assume there are tables", "assume tables", "assuming tables", "assuming that tables"]):
            cleaned_instructions.append(question if question else inst)
        else:
            cleaned_instructions.append(inst)

    if not cleaned_instructions:
        cleaned_instructions = [question]

    role = state.get("user_role", "analyst")
    time_ctx = state.get("time_context", {})
    as_of = time_ctx.get("as_of", "2018-09-01")

    subtask_objs = [
        Subtask(specialist="sql", instruction=inst) for inst in cleaned_instructions
    ]

    try:
        sql_results = await run_sql_subgraph(
            subtasks=subtask_objs,
            role=role,
            as_of=as_of,
        )
    except Exception as e:
        logger.error("SQL specialist error: %s", e)
        sql_results = [{
            "ok": False,
            "instruction": sql_instructions[0] if sql_instructions else "",
            "sql": None,
            "attempts": 1,
            "columns": [],
            "row_count": 0,
            "rows": [],
            "digest": {},
            "candidate_ids": [],
            "error_code": "SPECIALIST_FAILURE",
            "error": str(e),
            "elapsed_ms": 0,
        }]

    return {
        "sql_results": sql_results,
        "events": [{"ts": time.time(), "type": "sql_specialist_done", "detail": {"count": len(sql_results)}}],
    }


async def graph_specialist_node(state: AgentState) -> Dict[str, Any]:
    """Execute Graph specialist subgraph for network relationships and multi-hop patterns."""
    plan = state.get("plan") or {}
    subtasks = plan.get("subtasks", [])
    graph_instructions = [
        _extract_instruction(st)
        for st in subtasks
        if _extract_specialist(st) == "graph"
    ]
    instruction = graph_instructions[0] if graph_instructions else state.get("question", "")
    subtask_objs = [
        Subtask(specialist="graph", instruction=inst) for inst in (graph_instructions or [instruction])
    ]

    try:
        graph_res = await run_graph_subgraph(subtasks=subtask_objs)
    except Exception as e:
        logger.error("Graph specialist error: %s", e)
        graph_res = {
            "ok": False,
            "instruction": instruction,
            "cypher": None,
            "attempts": 1,
            "row_count": 0,
            "rows": [],
            "error_code": "SPECIALIST_FAILURE",
            "error": str(e),
            "elapsed_ms": 0,
        }

    return {
        "graph_result": graph_res,
        "events": [{"ts": time.time(), "type": "graph_specialist_done", "detail": {"rows": graph_res.get("row_count", 0)}}],
    }


async def rag_specialist_node(state: AgentState) -> Dict[str, Any]:
    """Execute RAG specialist subgraph for policy document retrieval."""
    plan = state.get("plan") or {}
    subtasks = plan.get("subtasks", [])
    rag_instructions = [
        _extract_instruction(st)
        for st in subtasks
        if _extract_specialist(st) == "rag"
    ]

    instruction = rag_instructions[0] if rag_instructions else state.get("question", "")
    subtask_objs = [
        Subtask(specialist="rag", instruction=inst) for inst in (rag_instructions or [instruction])
    ]

    try:
        rag_res = await run_rag_subgraph(subtasks=subtask_objs)
    except Exception as e:
        logger.error("RAG specialist error: %s", e)
        rag_res = {
            "ok": False,
            "instruction": instruction,
            "chunks": [],
            "citations": [],
            "quarantined_count": 0,
            "error_code": "SPECIALIST_FAILURE",
            "error": str(e),
            "elapsed_ms": 0,
        }

    return {
        "rag_result": rag_res,
        "citations": rag_res.get("citations", []),
        "events": [{"ts": time.time(), "type": "rag_specialist_done", "detail": {"chunks": len(rag_res.get("chunks", []))}}],
    }


async def synthesizer(state: AgentState) -> Dict[str, Any]:
    """Synthesize specialist findings into a grounded, citation-backed response."""
    question = state.get("question", "")
    time_ctx = state.get("time_context", {})
    as_of = time_ctx.get("as_of", "2018-09-01")
    sql_results = state.get("sql_results") or []
    graph_res = state.get("graph_result") or {}
    rag_result = state.get("rag_result") or {}

    context_parts = []
    findings = []
    has_fixture_data = False

    for i, sr in enumerate(sql_results):
        sql_text = sr.get("sql", "None")
        rows = sr.get("rows", [])
        if any(r.get("_fixture") for r in rows if isinstance(r, dict)):
            has_fixture_data = True
        context_parts.append(f"SQL Query {i+1}:\n```sql\n{sql_text}\n```\nRows ({sr.get('row_count', 0)} total):\n{json.dumps(rows[:10], default=str)}")
        for r in rows[:5]:
            findings.append(str(r))

    graph_cypher = graph_res.get("cypher")
    graph_rows = graph_res.get("rows", [])
    if graph_cypher:
        if any(r.get("_fixture") for r in graph_rows if isinstance(r, dict)):
            has_fixture_data = True
        context_parts.append(f"Graph Cypher Query:\n```cypher\n{graph_cypher}\n```\nRows ({len(graph_rows)} total):\n{json.dumps(graph_rows[:10], default=str)}")
        for r in graph_rows[:5]:
            findings.append(str(r))

    chunks = rag_result.get("chunks", [])
    if chunks:
        chunk_texts = [
            c.get("content", str(c)) if isinstance(c, dict) else getattr(c, "content", str(c))
            for c in chunks
        ]
        context_parts.append("Retrieved Policy Documentation:\n" + "\n\n".join(chunk_texts))

    # Check if question is asking about database schema, tables, or ontology structure
    q_lower = question.lower()
    schema_keywords = {"schema", "tables", "entities", "columns", "database structure", "data model", "db schema"}
    if any(k in q_lower for k in schema_keywords):
        try:
            from ontoagent.ontology.loader import load_ontology
            onto = load_ontology()
            schema_summary = [
                "Domain Ontology & Database Schema Overview:",
                "Relational Tables (PostgreSQL analytics schema):",
            ]
            for ent_name, ent in onto.entities.items():
                if ent.sql_table:
                    cols = ", ".join(f"{col} ({p.type})" for col, p in list(ent.properties.items())[:6])
                    schema_summary.append(
                        f"- `{ent.sql_table}` ({ent_name}): {ent.description} [Grain: {ent.grain or '1 row'}, Key: {ent.key or '-'}]. Key columns: {cols}"
                    )
            schema_summary.append("\nNeo4j Knowledge Graph:")
            schema_summary.append("- Nodes: Customer, Order, Product, Seller, Review")
            schema_summary.append("- Relationships: (:Customer)-[:PLACED]->(:Order), (:Order)-[:CONTAINS]->(:Product), (:Seller)-[:FULFILLS]->(:Order)")
            schema_summary.append("\nCanonical Metrics: late_rate, handoff_late_rate, gmv, avg_review_score")
            context_parts.append("\n".join(schema_summary))
        except Exception as e:
            logger.warning("Could not append schema context: %s", e)

    data_context = "\n\n".join(context_parts) if context_parts else "No specialist data retrieved."

    plan = state.get("plan") or {}
    wants_action = plan.get("wants_action", False)
    role = state.get("user_role", "analyst")

    if wants_action and role == "ops_manager":
        prompt = f"""You are OntoAgent, an intelligent enterprise operations agent assisting the Operations Manager.
Current As-Of Date: {as_of}
User Request: {question}

Operational Data Context:
<untrusted_data>
{data_context}
</untrusted_data>

The user requested an operational action (propose/draft refund or compensation batch).
State clearly that you have analyzed the delayed orders and drafted a compensation proposal batch according to policy, which has been submitted to the Human Approval Gate for review and confirmation.

Format your response in exactly these sections:
**Answer**: Direct agentic confirmation that eligible delayed orders have been identified and a proposed refund batch has been submitted to the Human Approval Gate for operator review.
**Findings**: Key metrics, count of delayed orders, delay days, or categories identified.
**How I got this**: The data query logic and SLA policy thresholds evaluated.
**Caveats**: As-of date limitations and confirmation that no payments are executed until approved by the operator.
"""
    else:
        prompt = f"""You are the OntoAgent Synthesizer. Synthesize a strictly grounded operational answer.
As-Of Date: {as_of}
User Question: {question}

Data Context:
<untrusted_data>
{data_context}
</untrusted_data>

Format your response in exactly these sections:
**Answer**: Direct 1-3 sentence summary.
**Findings**: Exact figures and bullet points from the data.
**How I got this**: The query logic and policy citations.
**Caveats**: As-of date limitations and data gaps.
"""

    llm = get_llm(temperature=0.0)
    flags_to_add = []
    errors_to_add = []

    try:
        resp = await llm.ainvoke([
            SystemMessage(content="You are OntoAgent, an enterprise operations agent. Ground all findings strictly in data and policies. Never fabricate facts."),
            HumanMessage(content=prompt),
        ])
        final_answer = extract_text_content(resp.content if hasattr(resp, "content") else resp)
        if has_fixture_data and "FIXTURE DATA" not in final_answer:
            final_answer = "**FIXTURE DATA**\n\n" + final_answer
    except Exception as e:
        # Fallback handling: log error, append to state errors, degrade explicitly with SYNTHESIZER_FALLBACK
        logger.warning("Synthesizer LLM failed: %s; degrading to fallback summary", str(e))
        errors_to_add.append(f"Synthesizer LLM error: {str(e)}")
        flags_to_add.append("SYNTHESIZER_FALLBACK")

        fixture_header = "**FIXTURE DATA**: " if has_fixture_data else ""
        if findings:
            final_answer = (
                f"{fixture_header}**Answer**: Analysis completed for historical data as of {as_of}.\n\n"
                f"**Findings**:\n" + "\n".join(findings[:5]) + "\n\n"
                f"**How I got this**: Executed relational SQL/graph queries against the operational database.\n\n"
                f"**Caveats**: Evaluation performed against configured as-of date {as_of}."
            )
        else:
            final_answer = (
                f"**Answer**: No data could be retrieved for the specified question as of {as_of}.\n\n"
                f"**Caveats**: No matching query results or documentation found."
            )

    return {
        "draft_answer": final_answer,
        "answer": final_answer,
        "final_text": final_answer,
        "risk_flags": flags_to_add,
        "errors": errors_to_add,
        "events": [{"ts": time.time(), "type": "synthesizer_done", "detail": {"answer_length": len(final_answer)}}],
    }


def action_planner_node(state: AgentState) -> Dict[str, Any]:
    """Execute deterministic action planner to build ProposedAction for eligible refunds."""
    role = state.get("user_role", "analyst")
    risk_flags = state.get("risk_flags", [])

    # Collect candidate order IDs from SQL results or previous turn
    candidate_ids = []
    for sr in state.get("sql_results") or []:
        candidate_ids.extend(sr.get("candidate_ids", []))
    if not candidate_ids:
        candidate_ids = list(state.get("last_candidate_order_ids") or [])

    # If still empty, check if specific order IDs are mentioned in the question
    if not candidate_ids:
        q = state.get("question", "")
        extracted = re.findall(r"\b(?:order_[0-9a-zA-Z_]+|[0-9a-f]{32})\b", q, re.I)
        if extracted:
            candidate_ids.extend(extracted)

    # If still empty and role is ops_manager, query candidate late orders from database
    if not candidate_ids and role == "ops_manager":
        try:
            settings = get_settings()
            with psycopg.connect(settings.postgres_ro_url, connect_timeout=3) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT order_id FROM analytics.fct_orders WHERE is_late = TRUE AND is_delivered ORDER BY delay_days DESC LIMIT 25;"
                    )
                    candidate_ids = [str(r[0]) for r in cur.fetchall()]
        except Exception as e:
            logger.warning(f"Could not retrieve default candidate orders for action planning: {e}")

    # Dedup preserving order
    seen = set()
    deduped_ids = [oid for oid in candidate_ids if not (oid in seen or seen.add(oid))]

    thread_id = state.get("time_context", {}).get("thread_id", "")

    proposed = plan_refund_action(
        candidate_order_ids=deduped_ids,
        user_role=role,
        risk_flags=risk_flags,
        thread_id=thread_id,
    )

    return {
        "proposed_action": proposed,
        "events": [
            {
                "ts": time.time(),
                "type": "action_planner_done",
                "detail": {
                    "eligible_items": len(proposed.get("items", [])),
                    "total": proposed.get("total", "0.00"),
                },
            }
        ],
    }


def human_approval_node(state: AgentState) -> Dict[str, Any]:
    """LangGraph interrupt node: pauses execution for human approval and narrowing."""
    proposed = state.get("proposed_action") or {}
    items = proposed.get("items", [])
    risk_flags = state.get("risk_flags", [])

    # Interrupt execution; wait for human decision
    resume_val = interrupt({
        "type": "approval_request",
        "action": proposed,
        "risk_flags": risk_flags,
        "expires_in_s": 900,
    })

    # Parse and validate resume response supporting both schemas
    if not isinstance(resume_val, dict):
        decision = "approve" if resume_val is True else "reject"
        approver = state.get("actor_id", "unknown")
        selected_ids = None
        note = ""
    else:
        decision = "approve" if (resume_val.get("decision") == "approve" or resume_val.get("approved") is True) else "reject"
        approver = resume_val.get("approver") or resume_val.get("actor_id") or state.get("actor_id", "unknown")
        selected_ids = (
            resume_val.get("selected_order_ids")
            if resume_val.get("selected_order_ids") is not None
            else resume_val.get("narrow_order_ids")
        )
        note = resume_val.get("note") or resume_val.get("reason") or ""

    # Approvers may ONLY narrow (deselect items). Cannot add items or raise amounts.
    if selected_ids is not None:
        selected_set = set(selected_ids)
        narrowed_items = [it for it in items if it.get("order_id") in selected_set]
    else:
        narrowed_items = items

    narrowed_total = sum(Decimal(str(it.get("amount", 0))) for it in narrowed_items)

    return {
        "approval": {
            "decision": decision,
            "approver": approver,
            "selected_order_ids": [it.get("order_id") for it in narrowed_items],
            "note": note,
        },
        "proposed_action": {
            **proposed,
            "items": narrowed_items,
            "total": f"{narrowed_total:.2f}",
        },
        "events": [
            {
                "ts": time.time(),
                "type": "human_approval_resolved",
                "detail": {
                    "decision": decision,
                    "approver": approver,
                    "selected_count": len(narrowed_items),
                    "narrowed_total": f"{narrowed_total:.2f}",
                },
            }
        ],
    }


async def mcp_executor_node(state: AgentState) -> Dict[str, Any]:
    """Execute approved operational actions through FastMCP client with HMAC token gates."""
    proposed = state.get("proposed_action") or {}
    items = proposed.get("items", [])
    approval = state.get("approval") or {}
    approver = approval.get("approver") or state.get("actor_id", "ops_manager")
    action_id = proposed.get("action_id", str(uuid.uuid4()))
    thread_id = state.get("time_context", {}).get("thread_id", "default_thread")

    client = McpClient()
    results = []

    for item in items:
        order_id = item["order_id"]
        amount = str(item["amount"])
        reason_code = item["reason_code"]
        policy_ref = item["policy_ref"]

        # Deterministic idempotency key
        raw_key = f"{thread_id}:{action_id}:{order_id}"
        idempotency_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

        tool_args = {
            "order_id": order_id,
            "amount": amount,
            "reason_code": reason_code,
            "policy_ref": policy_ref,
            "idempotency_key": idempotency_key,
            "requested_by": approver,
        }

        # Mint cryptographic HMAC approval token
        token = mint_approval_token(
            thread_id=thread_id,
            tool="create_refund_ticket",
            args=tool_args,
            approver=approver,
            expires_in_s=900,
        )

        call_payload = {**tool_args, "approval_token": token}
        res = await client.call_tool("create_refund_ticket", call_payload)
        results.append({
            "order_id": order_id,
            "amount": amount,
            "result": res,
        })

    created_tickets = [
        r["result"]["ticket_id"]
        for r in results
        if isinstance(r.get("result"), dict) and r["result"].get("ok") and r["result"].get("ticket_id")
    ]
    total_amount = sum(
        Decimal(str(r.get("amount", 0)))
        for r in results
        if isinstance(r.get("result"), dict) and r["result"].get("ok")
    )

    outcome = {
        "action_id": action_id,
        "tool": "create_refund_ticket",
        "total_attempted": len(items),
        "created_tickets": created_tickets,
        "total_amount": f"{total_amount:.2f}",
        "results": results,
        "status": "completed",
    }

    return {
        "action_outcome": outcome,
        "action_result": outcome,
        "events": [
            {
                "ts": time.time(),
                "type": "mcp_executor_done",
                "detail": {
                    "action_id": action_id,
                    "count": len(items),
                    "created_count": len(created_tickets),
                    "total_amount": f"{total_amount:.2f}",
                },
            }
        ],
    }


def clarify_node(state: AgentState) -> Dict[str, Any]:
    """Handle requests requiring additional clarification."""
    plan = state.get("plan") or {}
    clarification = plan.get("clarification_question") or "Could you please specify more details for your request?"
    return {"final_text": clarification}


def refuse_node(state: AgentState) -> Dict[str, Any]:
    """Handle out-of-scope or destructive requests with safe refusal."""
    plan = state.get("plan") or {}
    reason = plan.get("refusal_reason") or "I cannot fulfill this request as it is out of scope or violates safety policies."
    return {"final_text": reason}


def finalize_node(state: AgentState) -> Dict[str, Any]:
    """Wrap output into AIMessage and record turn conclusion."""
    text = state.get("final_text") or state.get("answer") or "Turn completed."

    # If action outcome exists, append summary
    outcome = state.get("action_result") or state.get("action_outcome")
    if outcome:
        res_list = outcome.get("results", [])
        created_count = len(outcome.get("created_tickets", []))
        total_amt = outcome.get("total_amount", "0.00")
        text += f"\n\n**Action Outcome**: Executed {len(res_list)} action(s) ({created_count} tickets created, R$ {total_amt})."
    elif state.get("approval") and state.get("approval", {}).get("decision") == "reject":
        text += "\n\n**Action Outcome**: Proposed actions were rejected by the approver."

    ai_msg = AIMessage(content=text)

    # Collect candidate IDs from SQL results for follow-up turns
    candidates = []
    for sr in state.get("sql_results") or []:
        candidates.extend(sr.get("candidate_ids", []))

    return {
        "messages": [ai_msg],
        "final_text": text,
        "last_candidate_order_ids": candidates[:500],
        "events": [{"ts": time.time(), "type": "turn_finalized", "detail": {"candidates": len(candidates)}}],
    }
