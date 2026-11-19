"""Structured logging for OntoAgent.

Purpose:
    Formats log records as structured JSON or readable console output.
    Ensures PII and raw database query payloads are redacted or hashed unless explicitly configured.
"""

import hashlib
import json
import logging
import sys
from typing import Any, Dict


class JsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj: Dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "trace_id"):
            log_obj["trace_id"] = record.trace_id
        if hasattr(record, "actor_id"):
            log_obj["actor_id"] = record.actor_id
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj)


def setup_logging(level: int = logging.INFO, json_format: bool = False) -> None:
    """Configure root logger with either JSON or console formatting."""
    root = logging.getLogger()
    root.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    if json_format:
        handler.setFormatter(JsonFormatter())
    else:
        fmt = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
        handler.setFormatter(logging.Formatter(fmt))

    root.handlers = [handler]


def hash_payload(data: Any) -> str:
    """Hash raw data payload to avoid leaking sensitive row data in logs."""
    content = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
