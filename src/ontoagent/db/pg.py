"""PostgreSQL connection management and execution.

Purpose:
    Provides sync and async database client helpers with strict read-only execution,
    query timeouts, and row cap limits.
    Uses asyncio.to_thread with sync psycopg to guarantee 100% compatibility across
    all platforms including Windows ProactorEventLoop and Linux.
"""

import asyncio
from typing import Any, Dict, List, Optional, Tuple

from ontoagent.config import get_settings
from ontoagent.errors import DatabaseExecutionError


def _sync_execute_ro_query(
    conn_url: str,
    sql: str,
    params: Optional[Tuple[Any, ...]],
    max_rows: int,
    timeout_s: float,
) -> List[Dict[str, Any]]:
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(conn_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SET LOCAL statement_timeout = '{int(timeout_s * 1000)}ms'")
            cur.execute(sql, params)
            rows = cur.fetchmany(max_rows + 1)
            if len(rows) > max_rows:
                rows = rows[:max_rows]
            return [dict(r) for r in rows]


async def execute_ro_query(
    sql: str,
    params: Optional[Tuple[Any, ...]] = None,
    max_rows: int = 1000,
    timeout_s: float = 5.0,
) -> List[Dict[str, Any]]:
    """Execute read-only query using ontoagent_ro role.

    Args:
        sql: Rewritten SQL query string.
        params: Optional SQL parameter tuple.
        max_rows: Maximum rows to fetch before aborting.
        timeout_s: Execution timeout limit.

    Returns:
        List of row dictionaries.

    Raises:
        DatabaseExecutionError on connection, timeout, or execution failure.
    """
    settings = get_settings()
    conn_url = settings.postgres_ro_url

    try:
        return await asyncio.to_thread(
            _sync_execute_ro_query,
            conn_url,
            sql,
            params,
            max_rows,
            timeout_s,
        )
    except Exception as e:
        raise DatabaseExecutionError(f"PostgreSQL read execution failed: {str(e)}")


def execute_admin_script(sql: str) -> None:
    """Execute DDL or loader SQL script using ontoagent_admin role."""
    settings = get_settings()
    conn_url = settings.postgres_admin_url

    try:
        import psycopg
        with psycopg.connect(conn_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
    except Exception as e:
        raise DatabaseExecutionError(f"PostgreSQL admin script failed: {str(e)}")
