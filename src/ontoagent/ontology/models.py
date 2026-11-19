"""Typed Pydantic models for the OntoAgent ontology.

Purpose:
    Represents entities, properties, metrics, glossary, and relationships parsed from ontology.yaml.
"""

from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class PropertyDef(BaseModel):
    """Definition of an individual property or database column."""
    type: str
    nullable: bool = False
    sensitivity: Optional[str] = None  # 'pii', 'free_text', or None
    values: Optional[List[str]] = None
    unit: Optional[str] = None
    description: Optional[str] = None


class EntityDef(BaseModel):
    """Definition of a business entity mapped to SQL and graph layers."""
    description: str
    sql_table: Optional[str] = None
    graph_label: Optional[str] = None
    key: Optional[str] = None
    grain: Optional[str] = None
    properties: Dict[str, PropertyDef] = Field(default_factory=dict)


class RelationshipDef(BaseModel):
    """Definition of a relationship between entities."""
    name: str
    from_: Union[str, List[str]] = Field(alias="from")
    to: str
    cardinality: str
    properties: Optional[List[str]] = None
    description: Optional[str] = None
    derived: bool = False


class MetricDef(BaseModel):
    """Definition of a canonical business metric."""
    description: str
    sql: Optional[str] = None
    table: Optional[str] = None
    default_time_dimension: Optional[str] = None


class GlossaryEntry(BaseModel):
    """Mapping of natural language business terms to canonical SQL predicates."""
    term: Union[str, List[str]]
    resolves_to: str
    applies_to: Optional[List[str]] = None
    note: Optional[str] = None


class Ontology(BaseModel):
    """Root model for the loaded business domain ontology."""
    version: int
    as_of_date: str
    entities: Dict[str, EntityDef]
    relationships: List[RelationshipDef] = Field(default_factory=list)
    metrics: Dict[str, MetricDef] = Field(default_factory=dict)
    glossary: List[GlossaryEntry] = Field(default_factory=list)
    join_pitfalls: List[str] = Field(default_factory=list)
