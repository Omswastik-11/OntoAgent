"""Ontology loading functions.

Purpose:
    Loads and parses ontology.yaml and category_groups.yaml into validated Pydantic models.
"""

from pathlib import Path
from typing import Dict, List, Optional
import yaml

from ontoagent.ontology.models import Ontology


def load_ontology(path: Optional[Path] = None) -> Ontology:
    """Load and validate ontology.yaml from path or default workspace location."""
    if path is None:
        path = Path("ontology/ontology.yaml")

    if not path.is_absolute():
        # Resolve relative to repo root
        path = Path.cwd() / path

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return Ontology.model_validate(data)


def load_category_groups(path: Optional[Path] = None) -> Dict[str, List[str]]:
    """Load category to group mappings from category_groups.yaml."""
    if path is None:
        path = Path("ontology/category_groups.yaml")

    if not path.is_absolute():
        path = Path.cwd() / path

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return data or {}
