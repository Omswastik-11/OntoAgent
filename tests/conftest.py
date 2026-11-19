"""Pytest configuration and shared fixtures for OntoAgent."""

import sys
from pathlib import Path
import pytest

# Ensure src/ is in python path
src_dir = Path(__file__).resolve().parent.parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from ontoagent.ontology.loader import load_ontology
from ontoagent.ontology.models import Ontology


@pytest.fixture(scope="session")
def ontology() -> Ontology:
    """Fixture providing loaded and validated ontology."""
    return load_ontology()
