"""Environment introspection script for third-party libraries.

Purpose:
    Introspects installed versions and signatures of critical dependencies
    (langgraph, sqlglot, pydantic, psycopg, neo4j, etc.) to catch version drift in seconds.
"""

import importlib
import inspect
import sys
from typing import List, Tuple


def check_module_symbol(module_name: str, symbol_name: str) -> Tuple[bool, str]:
    """Verify that a symbol exists in a module and report its details."""
    try:
        mod = importlib.import_module(module_name)
    except ImportError as e:
        return False, f"Module '{module_name}' could not be imported: {str(e)}"

    if not hasattr(mod, symbol_name):
        return False, f"Symbol '{symbol_name}' missing from module '{module_name}'"

    target = getattr(mod, symbol_name)
    version = getattr(mod, "__version__", "unknown")
    if inspect.isclass(target) or inspect.isfunction(target):
        return True, f"Found {target.__name__} in {module_name} (version {version})"
    return True, f"Found attribute {symbol_name} in {module_name} (version {version})"


def main() -> int:
    checks = [
        ("pydantic", "BaseModel"),
        ("sqlglot", "parse"),
        ("sqlglot.expressions", "Select"),
        ("langchain_core.messages", "AIMessage"),
        ("langchain_core.language_models.chat_models", "BaseChatModel"),
        ("langgraph.graph", "StateGraph"),
        ("langgraph.checkpoint.memory", "MemorySaver"),
        ("rapidfuzz.fuzz", "ratio"),
        ("faker", "Faker"),
    ]

    # Optional checks depending on installed environment
    optional_checks = [
        ("neo4j", "AsyncGraphDatabase"),
        ("psycopg", "AsyncConnection"),
        ("sentence_transformers", "SentenceTransformer"),
        ("fastmcp", "FastMCP"),
    ]

    print("=" * 65)
    print(" OntoAgent Environment API Introspection (scripts/check_env.py)")
    print("=" * 65)
    print(f"Python Version: {sys.version.split()[0]} ({sys.platform})")
    print("-" * 65)

    all_passed = True
    for mod_name, sym_name in checks:
        passed, msg = check_module_symbol(mod_name, sym_name)
        status = "PASS" if passed else "FAIL"
        print(f"[{status:4s}] {mod_name}.{sym_name:20s} -> {msg}")
        if not passed:
            all_passed = False

    for mod_name, sym_name in optional_checks:
        passed, msg = check_module_symbol(mod_name, sym_name)
        status = "PASS" if passed else "WARN"
        print(f"[{status:4s}] {mod_name}.{sym_name:20s} -> {msg}")

    print("=" * 65)
    if all_passed:
        print("ALL CORE ENVIRONMENT CHECKS PASSED.")
        return 0
    else:
        print("CRITICAL: Some required dependencies are missing or incompatible.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
