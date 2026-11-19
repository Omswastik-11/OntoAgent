"""Domain exception hierarchy for OntoAgent.

Purpose:
    Consistent error handling without leaking stack traces across API boundaries.
"""

from typing import Optional


class OntoAgentError(Exception):
    """Base exception for all OntoAgent domain errors."""

    def __init__(self, message: str, code: str = "ONTOAGENT_ERROR"):
        super().__init__(message)
        self.message = message
        self.code = code


class ConfigError(OntoAgentError):
    """Raised when configuration, environment variables, or keys are invalid or missing."""

    def __init__(self, message: str, code: str = "CONFIG_ERROR"):
        super().__init__(message, code=code)


class SecurityViolationError(OntoAgentError):
    """Raised when security boundaries, injection guards, or RBAC rules are violated."""

    def __init__(self, message: str, code: str = "SECURITY_VIOLATION"):
        super().__init__(message, code=code)


class ValidationError(OntoAgentError):
    """Raised when queries, schemas, or models fail syntactic or structural checks."""

    def __init__(self, message: str, code: str = "VALIDATION_ERROR"):
        super().__init__(message, code=code)


class PolicyViolationError(OntoAgentError):
    """Raised when action parameters exceed business policy caps or thresholds."""

    def __init__(self, message: str, code: str = "POLICY_VIOLATION"):
        super().__init__(message, code=code)


class DatabaseExecutionError(OntoAgentError):
    """Raised when database statements time out or fail at execution time."""

    def __init__(self, message: str, code: str = "DATABASE_ERROR"):
        super().__init__(message, code=code)


class MCPExecutionError(OntoAgentError):
    """Raised when MCP tool execution or validation fails on the server."""

    def __init__(self, message: str, code: str = "MCP_ERROR"):
        super().__init__(message, code=code)
