"""Unit tests for ontology loading, validation, and role-based prompt rendering."""

import pytest
from ontoagent.errors import ValidationError
from ontoagent.ontology.loader import load_ontology
from ontoagent.ontology.models import EntityDef, Ontology, RelationshipDef
from ontoagent.ontology.prompt_builder import render_cypher_schema_prompt, render_sql_schema_prompt
from ontoagent.ontology.validate import validate_ontology


def test_ontology_loads_successfully(ontology):
    assert ontology.version == 1
    assert "Order" in ontology.entities
    assert "OrderItem" in ontology.entities
    assert "Customer" in ontology.entities
    assert len(ontology.relationships) >= 8
    assert len(ontology.metrics) >= 4


def test_ontology_validation_passes(ontology):
    errors = validate_ontology(ontology, strict=False)
    assert errors == []


def test_validation_catches_invalid_relationship():
    broken_onto = Ontology(
        version=1,
        as_of_date="2018-09-01",
        entities={
            "Order": EntityDef(description="Order entity")
        },
        relationships=[
            RelationshipDef(
                name="PLACED",
                **{"from": "GhostCustomer", "to": "Order", "cardinality": "one_to_many"}
            )
        ]
    )
    with pytest.raises(ValidationError):
        validate_ontology(broken_onto, strict=True)


def test_sql_prompt_analyst_filtering(ontology):
    prompt = render_sql_schema_prompt(ontology, role="analyst")
    # Analyst CANNOT see dim_customer
    assert "analytics.dim_customer" not in prompt
    # Analyst CANNOT see review comment text
    assert "comment_title" not in prompt
    assert "comment_message" not in prompt
    # Analyst CAN see orders and sellers
    assert "analytics.fct_orders" in prompt
    assert "analytics.dim_seller" in prompt


def test_sql_prompt_ops_manager_filtering(ontology):
    prompt = render_sql_schema_prompt(ontology, role="ops_manager")
    # Ops manager CAN see dim_customer
    assert "analytics.dim_customer" in prompt
    # But denied raw PII columns are filtered out
    assert "email" not in prompt
    assert "phone" not in prompt
    assert "cpf" not in prompt


def test_cypher_prompt_generation(ontology):
    cypher_prompt = render_cypher_schema_prompt(ontology, role="analyst")
    assert "(:Order" in cypher_prompt
    assert "(:Seller" in cypher_prompt
    assert "-[:FULFILLS]->" in cypher_prompt
