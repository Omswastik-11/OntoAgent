"""Few-shot example selection for SQL specialist prompts.

Purpose:
    Retrieves top-k relevant query examples from ontology/sql_examples.yaml
    using token-overlap scoring to guide SQL generation without data leakage.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
from rapidfuzz import fuzz

_CACHED_EXAMPLES: Optional[List[Dict[str, Any]]] = None


def load_sql_examples(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Load curated few-shot SQL examples from YAML file."""
    global _CACHED_EXAMPLES
    if _CACHED_EXAMPLES is not None and path is None:
        return _CACHED_EXAMPLES

    if path is None:
        path = Path("ontology/sql_examples.yaml")
    if not path.is_absolute():
        path = Path.cwd() / path

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    examples = data.get("examples", [])
    if path.name == "sql_examples.yaml":
        _CACHED_EXAMPLES = examples
    return examples


def select_few_shot_examples(
    instruction: str,
    k: int = 4,
    examples_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """Select top-k most relevant few-shot SQL examples based on token similarity.

    Args:
        instruction: Natural language instruction.
        k: Maximum number of examples to return (default 4).
        examples_path: Optional path override.

    Returns:
        List of selected example dictionaries sorted by descending relevance.
    """
    all_examples = load_sql_examples(examples_path)
    if not all_examples or not instruction:
        return all_examples[:k]

    scored = []
    for ex in all_examples:
        target_text = f"{ex.get('intent', '')} {ex.get('instruction', '')}"
        score = fuzz.token_set_ratio(instruction.lower(), target_text.lower())
        scored.append((score, ex))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in scored[:k]]


def format_few_shot_prompt(examples: List[Dict[str, Any]]) -> str:
    """Render selected few-shot examples into formatted prompt section."""
    if not examples:
        return ""

    lines = ["### FEW-SHOT EXAMPLES:"]
    for i, ex in enumerate(examples, 1):
        lines.append(f"Example {i}:")
        lines.append(f"Question: {ex.get('instruction')}")
        lines.append(f"SQL:\n```sql\n{ex.get('sql').strip()}\n```\n")

    return "\n".join(lines)
