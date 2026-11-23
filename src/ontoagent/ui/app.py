"""Gradio interactive operations console for OntoAgent.

Purpose:
    Provides an enterprise web UI featuring persona switching (Analyst vs Ops Manager),
    grounded multi-turn conversational querying, collapsible trace drawer (SQL/Cypher/RAG),
    and interactive human-in-the-loop action approval/narrowing.
"""

import argparse
import json
import os
import socket
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Windows 11 Smart App Control (SAC) / WDAC Code Integrity compatibility
try:
    import numpy.random  # noqa: F401
except (ImportError, OSError) as _err:
    if "Application Control" in str(_err) or "DLL load failed" in str(_err):
        import types
        try:
            import numpy
            _stub = types.ModuleType("numpy.random")
            _stub.Generator = type("Generator", (), {})
            _stub.BitGenerator = type("BitGenerator", (), {})
            _stub.RandomState = type("RandomState", (), {})
            _stub.default_rng = lambda *a, **kw: _stub.Generator()
            sys.modules["numpy.random"] = _stub
            numpy.random = _stub
        except Exception:
            pass

import gradio as gr
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from ontoagent.config import get_settings
from ontoagent.graph.builder import build_graph
from ontoagent.llm import extract_text_content

# Role configuration
ROLES = {
    "Analyst": {
        "role": "analyst",
        "actor_id": "analyst_console",
        "api_key": "sk-analyst-test",
        "badge": "Analyst (Read-Only)",
    },
    "Operations Manager": {
        "role": "ops_manager",
        "actor_id": "ops_manager_console",
        "api_key": "sk-ops-test",
        "badge": "Operations Manager (Action-Authorized)",
    },
}

# Graph singleton
_GRAPH = None


def get_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH


async def submit_query(
    user_message: str,
    persona_label: str,
    thread_id_state: str,
    chat_history: Optional[List[Dict[str, str]]],
) -> Tuple[List[Dict[str, str]], str, str, str, str, Dict[str, Any], bool]:
    """Execute user query through graph and update conversation and traces."""
    history = list(chat_history) if chat_history else []
    if not user_message or not user_message.strip():
        return history, "", "", "", "", {}, False

    graph = get_graph()
    settings = get_settings()
    persona = ROLES.get(persona_label, ROLES["Analyst"])
    thread_id = thread_id_state or f"web_{uuid.uuid4().hex[:10]}"
    print(f"\n[OntoAgent UI] User ({persona_label}): {user_message}", flush=True)

    config = {"configurable": {"thread_id": thread_id}}

    try:
        res = await graph.ainvoke(
            {
                "messages": [HumanMessage(content=user_message.strip())],
                "user_role": persona["role"],
                "actor_id": persona["actor_id"],
                "time_context": {"as_of": settings.as_of_date, "thread_id": thread_id},
            },
            config=config,
        )
    except Exception as e:
        err_msg = f"System Error: {str(e)}"
        print(f"[OntoAgent UI] Error: {err_msg}", flush=True)
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": err_msg})
        return history, thread_id, "", "", "", {}, False

    raw_answer = res.get("final_text") or res.get("answer") or "No output generated."
    answer = extract_text_content(raw_answer)
    citations = res.get("citations") or []
    if citations:
        answer += "\n\n**Citations**:\n" + "\n".join(f"- `{c}`" for c in citations)

    # Check for approval interrupt
    state_snap = graph.get_state(config)
    is_interrupted = bool(state_snap and state_snap.next and "human_approval" in state_snap.next)
    proposed = res.get("proposed_action") or {}

    if is_interrupted and proposed:
        batch_items = proposed.get("items", [])
        total_val = proposed.get("total", "0.00")
        action_tool = proposed.get("tool", "create_refund_ticket")
        batch_id = proposed.get("action_id") or proposed.get("batch_id")
        banner = (
            f"\n\n---\n"
            f"### 🛡️ Human-in-the-Loop Approval Required\n"
            f"Execution is paused at the **Human-in-the-Loop Approval Gate**:\n"
            f"- **Action / Tool**: `{action_tool}`\n"
            f"- **Batch ID**: `{batch_id}`\n"
            f"- **Candidate Orders**: `{len(batch_items)}` eligible order(s)\n"
            f"- **Total Compensation**: `R$ {total_val}` (computed by deterministic policy engine)\n\n"
            f"👉 **Review the batch in the approval drawer below and click `Approve Batch` to execute via FastMCP, or `Reject Batch` to abort.**"
        )
        answer += banner

    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": answer})

    # Extract traces
    sql_results = res.get("sql_results") or []
    sql_text = "\n\n".join(f"```sql\n{sr.get('sql')}\n```\nRows: {sr.get('row_count', 0)}" for sr in sql_results if sr.get("sql")) or "No SQL queries generated."
    try:
        print(f"[OntoAgent UI] SQL ({len(sql_results)}): {sql_text[:120]}...", flush=True)
        print(f"[OntoAgent UI] Answer: {answer[:120]}...\n", flush=True)
    except Exception:
        pass
    
    graph_res = res.get("graph_result") or {}
    cypher_text = f"```cypher\n{graph_res.get('cypher')}\n```" if graph_res.get("cypher") else "No Cypher queries generated."
    
    rag_res = res.get("rag_result") or {}
    rag_chunks = rag_res.get("chunks") or []
    rag_text = "\n\n".join(f"**{c.get('citation_anchor')}**\n{c.get('content')}" for c in rag_chunks) or "No policy documentation retrieved."

    approval_status_md = ""
    if is_interrupted and proposed:
        approval_status_md = (
            f"### Proposed Action: {proposed.get('tool', 'Refund Batch')}\n"
            f"- **Batch ID**: `{proposed.get('batch_id')}`\n"
            f"- **Candidate Orders**: {len(proposed.get('items', []))}\n"
            f"- **Total Amount**: R$ {proposed.get('total', '0.00')}\n"
            f"- **Action Required**: Operations Manager review and approval required."
        )

    return (
        history,
        thread_id,
        sql_text,
        cypher_text,
        rag_text,
        proposed,
        is_interrupted,
    )


async def execute_approval_decision(
    approved: bool,
    persona_label: str,
    thread_id_state: str,
    proposed_state: Dict[str, Any],
    chat_history: Optional[List[Dict[str, str]]],
) -> Tuple[List[Dict[str, str]], str, Dict[str, Any], bool]:
    """Execute or reject pending action batch upon human decision."""
    history = list(chat_history) if chat_history else []
    persona = ROLES.get(persona_label, ROLES["Analyst"])
    if persona["role"] != "ops_manager":
        history.append({"role": "assistant", "content": "Error: Only Operations Manager persona is authorized to approve actions."})
        return history, "Approval rejected: unauthorized persona.", {}, False

    if not thread_id_state:
        return history, "No active thread for approval.", {}, False

    graph = get_graph()
    config = {"configurable": {"thread_id": thread_id_state}}

    resume_payload = {
        "approved": approved,
        "narrow_order_ids": None,
        "reason": "Approved from web console" if approved else "Rejected from web console",
        "actor_id": persona["actor_id"],
    }

    try:
        res = await graph.ainvoke(Command(resume=resume_payload), config=config)
        action_res = res.get("action_result") or res.get("action_outcome") or {}
        if approved:
            status_text = (
                f"**Action Executed Successfully**\n\n"
                f"- Tool: `{action_res.get('tool')}`\n"
                f"- Created Tickets: {len(action_res.get('created_tickets', []))}\n"
                f"- Total Approved: R$ {action_res.get('total_amount', '0.00')}\n"
                f"- Token JTI: `{action_res.get('consumed_jti')}` (Audit Verified)"
            )
        else:
            status_text = "**Action Batch Cancelled by Operator.**"
        history.append({"role": "assistant", "content": status_text})
        return history, status_text, {}, False
    except Exception as e:
        err = f"Approval execution failed: {str(e)}"
        history.append({"role": "assistant", "content": err})
        return history, err, proposed_state, True


def create_ui() -> gr.Blocks:
    """Build Gradio interface layout."""
    settings = get_settings()

    with gr.Blocks(title="OntoAgent Enterprise Copilot") as demo:
        gr.Markdown(
            f"""# OntoAgent: Operations Intelligence Copilot
**Ground Truth Analytics, Graph Topology & Policy Engine** | Engine: `{settings.llm_model}` | As-Of: `{settings.as_of_date}` | Red Team Mode: `{'Active' if settings.red_team_mode else 'Off'}`
"""
        )

        with gr.Row():
            with gr.Column(scale=3):
                with gr.Row():
                    persona_dropdown = gr.Dropdown(
                        label="Active Persona",
                        choices=["Analyst", "Operations Manager"],
                        value="Analyst",
                        interactive=True,
                    )
                    thread_id_box = gr.Textbox(
                        label="Thread ID",
                        value="",
                        interactive=False,
                    )

                chatbot = gr.Chatbot(
                    label="Operations Conversation",
                    height=500,
                )

                with gr.Row():
                    query_input = gr.Textbox(
                        label="Enter question or operational request",
                        placeholder="e.g. Compare the average review score of late versus on-time delivered orders.",
                        scale=4,
                    )
                    submit_btn = gr.Button("Send", variant="primary", scale=1)

                # Approval Box (hidden unless approval is requested)
                with gr.Group():
                    approval_markdown = gr.Markdown("No pending operational actions.")
                    with gr.Row():
                        approve_btn = gr.Button("Approve Batch", variant="primary", visible=False)
                        reject_btn = gr.Button("Reject Batch", variant="stop", visible=False)

            with gr.Column(scale=2):
                gr.Markdown("### Operational Trace Drawer")
                with gr.Accordion("Generated SQL Query", open=True):
                    sql_display = gr.Markdown("No SQL queries generated yet.")
                with gr.Accordion("Graph Cypher Pattern", open=False):
                    cypher_display = gr.Markdown("No Cypher queries generated yet.")
                with gr.Accordion("Retrieved Policy Documents", open=False):
                    rag_display = gr.Markdown("No policy documentation retrieved yet.")

        # Hidden state holders
        proposed_action_state = gr.State({})
        is_interrupted_state = gr.State(False)

        # Wire query submission
        async def on_submit(msg, persona, thread, history):
            hist, th, sql, cyp, rag, prop, is_int = await submit_query(msg, persona, thread, history)
            batch_items = prop.get("items", [])
            batch_id = prop.get("action_id") or prop.get("batch_id", "")
            app_text = (
                f"### 🛡️ Action Approval Required ({persona})\n"
                f"- **Tool**: `{prop.get('tool')}`\n"
                f"- **Batch ID**: `{batch_id}`\n"
                f"- **Orders Count**: {len(batch_items)} eligible\n"
                f"- **Total Compensation**: R$ {prop.get('total')}\n"
                f"- **Status**: Paused at LangGraph interrupt. FastMCP execution pending."
                if is_int else "No pending operational actions."
            )
            return (
                hist, th, sql, cyp, rag, prop, is_int,
                app_text,
                gr.update(visible=is_int),
                gr.update(visible=is_int),
                "",
            )

        submit_btn.click(
            fn=on_submit,
            inputs=[query_input, persona_dropdown, thread_id_box, chatbot],
            outputs=[
                chatbot, thread_id_box, sql_display, cypher_display, rag_display,
                proposed_action_state, is_interrupted_state,
                approval_markdown, approve_btn, reject_btn, query_input
            ],
        )
        query_input.submit(
            fn=on_submit,
            inputs=[query_input, persona_dropdown, thread_id_box, chatbot],
            outputs=[
                chatbot, thread_id_box, sql_display, cypher_display, rag_display,
                proposed_action_state, is_interrupted_state,
                approval_markdown, approve_btn, reject_btn, query_input
            ],
        )

        # Wire approve button
        async def on_approve(persona, thread, prop, history):
            hist, status_text, new_prop, new_int = await execute_approval_decision(True, persona, thread, prop, history)
            return (
                hist, status_text, new_prop, new_int,
                gr.update(visible=new_int),
                gr.update(visible=new_int),
            )

        approve_btn.click(
            fn=on_approve,
            inputs=[persona_dropdown, thread_id_box, proposed_action_state, chatbot],
            outputs=[chatbot, approval_markdown, proposed_action_state, is_interrupted_state, approve_btn, reject_btn],
        )

        # Wire reject button
        async def on_reject(persona, thread, prop, history):
            hist, status_text, new_prop, new_int = await execute_approval_decision(False, persona, thread, prop, history)
            return (
                hist, status_text, new_prop, new_int,
                gr.update(visible=new_int),
                gr.update(visible=new_int),
            )

        reject_btn.click(
            fn=on_reject,
            inputs=[persona_dropdown, thread_id_box, proposed_action_state, chatbot],
            outputs=[chatbot, approval_markdown, proposed_action_state, is_interrupted_state, approve_btn, reject_btn],
        )

    return demo


def find_available_port(start_port: int = 7860, max_attempts: int = 100) -> int:
    """Find the first available TCP port starting from start_port."""
    for p in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", p))
                return p
            except OSError:
                continue
    return start_port


def launch(host: str = "0.0.0.0", port: Optional[int] = None):
    """Launch Gradio application with CLI argument support and automatic port discovery."""
    parser = argparse.ArgumentParser(description="OntoAgent UI Console")
    parser.add_argument("--host", type=str, default=host, help="Host address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=port, help="Port to listen on (default: auto-find free port starting from 7860)")
    parser.add_argument("--share", action="store_true", default=False, help="Create a public Gradio share link")

    args, _ = parser.parse_known_args()
    target_host = args.host
    env_port = int(os.environ.get("GRADIO_SERVER_PORT", "0"))
    requested_port = args.port or (env_port if env_port > 0 else 7860)

    # Check if requested port is available, or find the next free port automatically
    actual_port = find_available_port(requested_port)
    if actual_port != requested_port and args.port:
        print(f"[OntoAgent UI] Port {requested_port} is busy. Automatically switched to available port: {actual_port}")
    elif actual_port != 7860 and not args.port:
        print(f"[OntoAgent UI] Port 7860 is busy. Automatically found available port: {actual_port}")

    ui = create_ui()
    ui.launch(server_name=target_host, server_port=actual_port, share=args.share)


if __name__ == "__main__":
    launch()
