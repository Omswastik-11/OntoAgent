"""FastMCP Server providing operational tools for OntoAgent.

Purpose:
    Exposes create_refund_ticket, notify_seller_templated, and list_refund_tickets.
    Re-verifies HMAC approval tokens, checks single-use jti in ops.used_tokens,
    re-validates amounts and business invariants independently, and records audit logs.
    Connects as ontoagent_ops (restricted to ops.* write permissions).
"""

from decimal import Decimal, InvalidOperation
import json
import logging
import os
from typing import Any, Dict, List, Optional
import uuid
import psycopg

from mcp_server.auth import verify_approval_token

logger = logging.getLogger("mcp_server")

# Maximum refund per order cap
MAX_REFUND_PER_ORDER = Decimal("1000.00")
ALLOWED_REASON_CODES = {"LATE_7", "LATE_15", "UNDELIVERED_10"}
ALLOWED_TEMPLATES = {"sla_warning", "sla_probation", "late_handoff_notice"}


def get_ops_db_url() -> str:
    """Return database URL with ontoagent_ops credentials."""
    return os.getenv(
        "POSTGRES_OPS_URL",
        "postgresql://ontoagent_ops:ops_secret@localhost:5432/ontoagent",
    )


# Initialize official MCPServer if available
try:
    from mcp.server.mcpserver import MCPServer
    mcp = MCPServer("ontoagent_ops_server")
except Exception:
    class DummyMCPServer:
        def tool(self):
            def decorator(f):
                return f
            return decorator
    mcp = DummyMCPServer()


@mcp.tool()
async def list_refund_tickets(order_id: str) -> List[Dict[str, Any]]:
    """Read-only. Returns existing tickets for a given order."""
    tickets = []
    db_url = get_ops_db_url()
    try:
        with psycopg.connect(db_url, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT ticket_id, order_id, amount, reason_code, policy_ref, status, created_at
                    FROM ops.refund_tickets
                    WHERE order_id = %s
                    ORDER BY created_at DESC;
                    """,
                    (order_id,),
                )
                for row in cur.fetchall():
                    tickets.append({
                        "ticket_id": str(row[0]),
                        "order_id": str(row[1]),
                        "amount": str(row[2]),
                        "reason_code": str(row[3]),
                        "policy_ref": str(row[4]),
                        "status": str(row[5]),
                        "created_at": row[6].isoformat() if hasattr(row[6], "isoformat") else str(row[6]),
                    })
    except Exception as e:
        logger.error(f"Error querying ops.refund_tickets for order {order_id}: {e}")
    return tickets


@mcp.tool()
async def create_refund_ticket(
    order_id: str,
    amount: str,
    reason_code: str,
    policy_ref: str,
    idempotency_key: str,
    requested_by: str,
    approval_token: str,
) -> Dict[str, Any]:
    """Create a refund ticket.

    Re-verifies token, checks single use of jti, re-validates amount,
    and inserts ticket atomically with audit logging.
    """
    # 1. Verify approval token
    expected_args = {
        "order_id": order_id,
        "amount": amount,
        "reason_code": reason_code,
        "policy_ref": policy_ref,
        "idempotency_key": idempotency_key,
        "requested_by": requested_by,
    }
    valid, reason, payload = verify_approval_token(approval_token, "create_refund_ticket", expected_args)
    if not valid:
        logger.warning(f"Rejecting create_refund_ticket: invalid token ({reason})")
        return {"ok": False, "error_code": "INVALID_TOKEN", "message": reason}

    jti = payload.get("jti")
    thread_id = payload.get("thread_id", "")
    approver = payload.get("approver", requested_by)

    # 2. Validate amount representation and bounds
    try:
        dec_amount = Decimal(amount)
    except (InvalidOperation, TypeError):
        return {"ok": False, "error_code": "INVALID_AMOUNT", "message": "Amount must be a valid numeric string"}

    if dec_amount <= Decimal("0.00"):
        return {"ok": False, "error_code": "INVALID_AMOUNT", "message": "Amount must be greater than zero"}

    if dec_amount.as_tuple().exponent < -2:
        return {"ok": False, "error_code": "INVALID_AMOUNT", "message": "Amount cannot exceed 2 decimal places"}

    if dec_amount > MAX_REFUND_PER_ORDER:
        return {
            "ok": False,
            "error_code": "AMOUNT_EXCEEDS_CAP",
            "message": f"Amount R${dec_amount:.2f} exceeds MAX_REFUND_PER_ORDER R${MAX_REFUND_PER_ORDER:.2f}",
        }

    # 3. Validate reason code
    if reason_code not in ALLOWED_REASON_CODES:
        return {
            "ok": False,
            "error_code": "INVALID_REASON_CODE",
            "message": f"Reason code '{reason_code}' is not in allowed set: {ALLOWED_REASON_CODES}",
        }

    # 4. Database checks and atomic transaction
    db_url = get_ops_db_url()
    try:
        with psycopg.connect(db_url, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                # 4a. Check single-use jti
                cur.execute("SELECT 1 FROM ops.used_tokens WHERE jti = %s;", (jti,))
                if cur.fetchone():
                    return {
                        "ok": False,
                        "error_code": "TOKEN_REPLAYED",
                        "message": f"Approval token jti '{jti}' has already been consumed",
                    }

                # 4b. Check order validity and payment_total in analytics.fct_orders
                cur.execute(
                    "SELECT order_status, payment_total FROM analytics.fct_orders WHERE order_id = %s;",
                    (order_id,),
                )
                row = cur.fetchone()
                if row:
                    status, payment_total = row
                    if status == "canceled":
                        return {"ok": False, "error_code": "ORDER_CANCELED", "message": "Cannot refund canceled order"}
                    if dec_amount > Decimal(str(payment_total)):
                        return {
                            "ok": False,
                            "error_code": "AMOUNT_EXCEEDS_PAYMENT",
                            "message": f"Amount R${dec_amount:.2f} exceeds payment total R${payment_total:.2f}",
                        }

                # 4c. Check idempotency
                cur.execute(
                    "SELECT ticket_id, amount, status FROM ops.refund_tickets WHERE idempotency_key = %s;",
                    (idempotency_key,),
                )
                existing = cur.fetchone()
                if existing:
                    ticket_id, ex_amount, ex_status = existing
                    return {
                        "ok": True,
                        "ticket_id": str(ticket_id),
                        "status": ex_status,
                        "amount": str(ex_amount),
                        "created": False,
                    }

                # 4d. Atomic execution: insert used_tokens, refund_tickets, audit_log
                cur.execute(
                    """
                    INSERT INTO ops.used_tokens (jti, thread_id, tool, approver)
                    VALUES (%s, %s, %s, %s);
                    """,
                    (jti, thread_id, "create_refund_ticket", approver),
                )

                cur.execute(
                    """
                    INSERT INTO ops.refund_tickets (
                        order_id, amount, reason_code, policy_ref, idempotency_key, requested_by, status
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, 'created')
                    RETURNING ticket_id;
                    """,
                    (order_id, dec_amount, reason_code, policy_ref, idempotency_key, requested_by),
                )
                ticket_id = cur.fetchone()[0]

                # Insert audit log
                audit_payload = {
                    "tool": "create_refund_ticket",
                    "order_id": order_id,
                    "amount": str(dec_amount),
                    "reason_code": reason_code,
                    "policy_ref": policy_ref,
                    "ticket_id": str(ticket_id),
                    "jti": jti,
                }
                cur.execute(
                    """
                    INSERT INTO ops.audit_log (event_type, actor_id, thread_id, payload)
                    VALUES (%s, %s, %s, %s);
                    """,
                    ("mcp_tool_create_refund_ticket", requested_by, thread_id, json.dumps(audit_payload)),
                )

                conn.commit()

                return {
                    "ok": True,
                    "ticket_id": str(ticket_id),
                    "status": "created",
                    "amount": f"{dec_amount:.2f}",
                    "created": True,
                }
    except Exception as e:
        logger.error(f"Database error in create_refund_ticket: {e}")
        return {"ok": False, "error_code": "DB_EXECUTION_ERROR", "message": str(e)}


@mcp.tool()
async def notify_seller_templated(
    seller_id: str,
    template_id: str,
    params: Dict[str, str],
    idempotency_key: str,
    requested_by: str,
    approval_token: str,
) -> Dict[str, Any]:
    """Queue a templated seller notification.

    Re-verifies token, checks single use of jti, validates template and parameters,
    and inserts notification atomically with audit logging.
    """
    # 1. Verify approval token
    expected_args = {
        "seller_id": seller_id,
        "template_id": template_id,
        "params": params,
        "idempotency_key": idempotency_key,
        "requested_by": requested_by,
    }
    valid, reason, payload = verify_approval_token(approval_token, "notify_seller_templated", expected_args)
    if not valid:
        return {"ok": False, "error_code": "INVALID_TOKEN", "message": reason}

    jti = payload.get("jti")
    thread_id = payload.get("thread_id", "")
    approver = payload.get("approver", requested_by)

    # 2. Validate template_id
    if template_id not in ALLOWED_TEMPLATES:
        return {
            "ok": False,
            "error_code": "INVALID_TEMPLATE",
            "message": f"Template '{template_id}' is not permitted. Allowed: {ALLOWED_TEMPLATES}",
        }

    # 3. Validate params: string keys and values, length <= 80, no URLs
    if not isinstance(params, dict):
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "Params must be a dictionary"}

    for k, v in params.items():
        if not isinstance(k, str) or not isinstance(v, str):
            return {"ok": False, "error_code": "INVALID_PARAMS", "message": "Param keys and values must be strings"}
        if len(v) > 80:
            return {"ok": False, "error_code": "PARAM_TOO_LONG", "message": f"Param '{k}' exceeds 80 characters"}
        if "http://" in v.lower() or "https://" in v.lower():
            return {"ok": False, "error_code": "URL_NOT_PERMITTED", "message": f"Param '{k}' contains forbidden URL"}

    # 4. Atomic database transaction
    db_url = get_ops_db_url()
    try:
        with psycopg.connect(db_url, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                # 4a. Check single-use jti
                cur.execute("SELECT 1 FROM ops.used_tokens WHERE jti = %s;", (jti,))
                if cur.fetchone():
                    return {
                        "ok": False,
                        "error_code": "TOKEN_REPLAYED",
                        "message": f"Approval token jti '{jti}' has already been consumed",
                    }

                # 4b. Check idempotency
                cur.execute(
                    "SELECT notification_id, status FROM ops.seller_notifications WHERE idempotency_key = %s;",
                    (idempotency_key,),
                )
                existing = cur.fetchone()
                if existing:
                    nid, st = existing
                    return {"ok": True, "notification_id": str(nid), "status": st, "created": False}

                # 4c. Atomic execution: insert used_tokens, seller_notifications, audit_log
                cur.execute(
                    """
                    INSERT INTO ops.used_tokens (jti, thread_id, tool, approver)
                    VALUES (%s, %s, %s, %s);
                    """,
                    (jti, thread_id, "notify_seller_templated", approver),
                )

                cur.execute(
                    """
                    INSERT INTO ops.seller_notifications (
                        seller_id, template_id, params, idempotency_key, requested_by, status
                    )
                    VALUES (%s, %s, %s, %s, %s, 'queued')
                    RETURNING notification_id;
                    """,
                    (seller_id, template_id, json.dumps(params), idempotency_key, requested_by),
                )
                notification_id = cur.fetchone()[0]

                audit_payload = {
                    "tool": "notify_seller_templated",
                    "seller_id": seller_id,
                    "template_id": template_id,
                    "notification_id": str(notification_id),
                    "jti": jti,
                }
                cur.execute(
                    """
                    INSERT INTO ops.audit_log (event_type, actor_id, thread_id, payload)
                    VALUES (%s, %s, %s, %s);
                    """,
                    ("mcp_tool_notify_seller", requested_by, thread_id, json.dumps(audit_payload)),
                )

                conn.commit()

                return {
                    "ok": True,
                    "notification_id": str(notification_id),
                    "status": "queued",
                    "created": True,
                }
    except Exception as e:
        logger.error(f"Database error in notify_seller_templated: {e}")
        return {"ok": False, "error_code": "DB_EXECUTION_ERROR", "message": str(e)}


if __name__ == "__main__":
    mcp.run(transport="stdio")

