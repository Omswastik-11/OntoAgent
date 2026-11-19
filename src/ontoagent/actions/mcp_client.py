"""MCP Client adapter for invoking operational tools on the FastMCP/MCPServer.

Purpose:
    Provides an async client interface to dispatch create_refund_ticket,
    notify_seller_templated, and list_refund_tickets to the MCPServer.
    Supports official MCP stdio subprocess transport with an in-process fallback
    for fast unit testing and constrained execution environments.
"""

import json
import logging
import os
import sys
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class McpClient:
    """Async client interface for OntoAgent MCP server tools.

    Modes:
        - stdio: Spawns mcp_server.server as a subprocess communicating over JSON-RPC.
        - inprocess: Directly imports and executes tools (enabled via ONTOAGENT_INPROCESS_MCP=1).
    """

    def __init__(self, in_process: Optional[bool] = None):
        if in_process is not None:
            self.in_process = in_process
        else:
            self.in_process = os.getenv("ONTOAGENT_INPROCESS_MCP", "0") == "1"

    async def call_tool(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Invoke MCP tool and return standardized execution result."""
        if self.in_process:
            return await self._call_tool_inprocess(tool_name, args)

        try:
            return await self._call_tool_stdio(tool_name, args)
        except Exception as e:
            logger.warning(
                f"MCP stdio transport failed ({e}); falling back to in-process execution."
            )
            return await self._call_tool_inprocess(tool_name, args)

    async def _call_tool_stdio(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatch tool call to MCPServer subprocess via stdio transport."""
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        # Ensure PYTHONPATH includes project root for module resolution
        env = os.environ.copy()
        pythonpath = os.getcwd()
        if "PYTHONPATH" in env:
            pythonpath = f"{pythonpath}{os.pathsep}{env['PYTHONPATH']}"
        env["PYTHONPATH"] = pythonpath

        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "mcp_server.server"],
            env=env,
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments=args)

                is_err = getattr(result, "is_error", False) or getattr(result, "isError", False)
                if is_err:
                    err_msg = ""
                    if result.content:
                        first = result.content[0]
                        err_msg = getattr(first, "text", str(first))
                    return {
                        "ok": False,
                        "error_code": "MCP_TOOL_ERROR",
                        "message": err_msg or "Tool reported error",
                    }

                if result.content:
                    first = result.content[0]
                    if hasattr(first, "text") and first.text:
                        try:
                            parsed = json.loads(first.text)
                            if isinstance(parsed, dict):
                                return parsed
                            return {"ok": True, "result": parsed}
                        except Exception:
                            return {"ok": True, "raw": first.text}

                return {"ok": True}

    async def _call_tool_inprocess(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """In-process execution fallback for unit tests and local isolation."""
        from mcp_server.server import (
            create_refund_ticket,
            list_refund_tickets,
            notify_seller_templated,
        )

        try:
            if tool_name == "create_refund_ticket":
                return await create_refund_ticket(
                    order_id=args["order_id"],
                    amount=args["amount"],
                    reason_code=args["reason_code"],
                    policy_ref=args["policy_ref"],
                    idempotency_key=args["idempotency_key"],
                    requested_by=args["requested_by"],
                    approval_token=args["approval_token"],
                )

            elif tool_name == "notify_seller_templated":
                return await notify_seller_templated(
                    seller_id=args["seller_id"],
                    template_id=args["template_id"],
                    params=args["params"],
                    idempotency_key=args["idempotency_key"],
                    requested_by=args["requested_by"],
                    approval_token=args["approval_token"],
                )

            elif tool_name == "list_refund_tickets":
                tickets = await list_refund_tickets(order_id=args["order_id"])
                return {"ok": True, "tickets": tickets}

            else:
                return {
                    "ok": False,
                    "error_code": "UNKNOWN_TOOL",
                    "message": f"Tool '{tool_name}' is not recognized",
                }

        except Exception as e:
            logger.error(f"In-process MCP tool {tool_name} failed: {e}")
            return {
                "ok": False,
                "error_code": "CLIENT_DISPATCH_ERROR",
                "message": str(e),
            }
