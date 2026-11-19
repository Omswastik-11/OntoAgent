"""Configuration module for OntoAgent.

Purpose:
    Centralized, validated settings loaded from environment variables and .env.
    Includes feature flags for ablation experiments (E0 to E5).
"""

from typing import Dict, Tuple
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Features(BaseModel):
    """Ablation and behavior toggles for evaluation experiments."""
    ontology_prompt: bool = True
    few_shot: bool = True
    value_linking: bool = True
    sql_repair_loop: bool = True
    hybrid_retrieval: bool = True
    scan_untrusted: bool = True
    output_guard: bool = True
    llm_injection_judge: bool = False


class Settings(BaseSettings):
    """Global configuration settings for OntoAgent runtime."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # LLM Settings
    google_api_key: str = Field(default="", validation_alias="GOOGLE_API_KEY")
    gemini_api_key: str = Field(default="", validation_alias="GEMINI_API_KEY")
    groq_api_key: str = Field(default="", validation_alias="GROQ_API_KEY")
    llm_model: str = Field(default="openai/gpt-oss-120b", validation_alias="LLM_MODEL")
    llm_fallback_model: str = Field(default="openai/gpt-oss-20b", validation_alias="LLM_FALLBACK_MODEL")
    judge_model: str = Field(default="openai/gpt-oss-120b", validation_alias="JUDGE_MODEL")
    llm_temperature: float = Field(default=0.0, validation_alias="LLM_TEMPERATURE")
    llm_rpm_limit: int = Field(default=10, validation_alias="LLM_RPM_LIMIT")

    # Data Stores
    postgres_admin_url: str = Field(
        default="postgresql://ontoagent_admin:admin_secret@localhost:5432/ontoagent",
        validation_alias="POSTGRES_ADMIN_URL"
    )
    postgres_ro_url: str = Field(
        default="postgresql://ontoagent_ro:ro_secret@localhost:5432/ontoagent",
        validation_alias="POSTGRES_RO_URL"
    )
    postgres_kb_url: str = Field(
        default="postgresql://ontoagent_kb:kb_secret@localhost:5432/ontoagent",
        validation_alias="POSTGRES_KB_URL"
    )
    postgres_app_url: str = Field(
        default="postgresql://ontoagent_app:app_secret@localhost:5432/ontoagent",
        validation_alias="POSTGRES_APP_URL"
    )
    postgres_ops_url: str = Field(
        default="postgresql://ontoagent_ops:ops_secret@localhost:5432/ontoagent",
        validation_alias="POSTGRES_OPS_URL"
    )
    neo4j_uri: str = Field(default="bolt://localhost:7687", validation_alias="NEO4J_URI")
    neo4j_user: str = Field(default="neo4j", validation_alias="NEO4J_USER")
    neo4j_password: str = Field(default="ontoagent_neo4j_password", validation_alias="NEO4J_PASSWORD")

    # Embeddings
    embedding_model: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        validation_alias="EMBEDDING_MODEL"
    )
    embedding_dim: int = Field(default=384, validation_alias="EMBEDDING_DIM")

    # Domain
    as_of_date: str = Field(default="2018-09-01", validation_alias="AS_OF_DATE")
    dataset: str = Field(default="sample", validation_alias="DATASET")

    # Security & Guardrails
    approval_hmac_secret: str = Field(
        default="c8e7b1a2d3f4e5a6b7c8d9e0f1a2b3c4",
        validation_alias="APPROVAL_HMAC_SECRET"
    )
    pseudonym_secret: str = Field(
        default="f1e2d3c4b5a60718293a4b5c6d7e8f90",
        validation_alias="PSEUDONYM_SECRET"
    )
    max_refund_per_order: float = Field(default=1000.0, validation_alias="MAX_REFUND_PER_ORDER")
    sql_max_repairs: int = Field(default=2, validation_alias="SQL_MAX_REPAIRS")
    red_team_mode: bool = Field(default=True, validation_alias="RED_TEAM_MODE")

    # MCP
    mcp_transport: str = Field(default="stdio", validation_alias="MCP_TRANSPORT")
    mcp_url: str = Field(default="http://localhost:8000/mcp", validation_alias="MCP_URL")

    # API and Runtime
    api_keys: str = Field(
        default="analyst-demo-key:analyst:alice,ops-demo-key:ops_manager:omar",
        validation_alias="API_KEYS"
    )
    checkpointer: str = Field(default="memory", validation_alias="CHECKPOINTER")
    log_payloads: bool = Field(default=False, validation_alias="LOG_PAYLOADS")

    # Observability
    langsmith_tracing: bool = Field(default=False, validation_alias="LANGSMITH_TRACING")
    langsmith_api_key: str = Field(default="", validation_alias="LANGSMITH_API_KEY")

    # Feature Toggles
    features: Features = Field(default_factory=Features)

    def parse_api_keys(self) -> Dict[str, Tuple[str, str]]:
        """Parse API_KEYS string into mapping: key -> (role, actor_id)."""
        mapping: Dict[str, Tuple[str, str]] = {}
        for entry in self.api_keys.split(","):
            entry = entry.strip()
            if not entry:
                continue
            parts = entry.split(":")
            if len(parts) == 3:
                mapping[parts[0]] = (parts[1], parts[2])
        return mapping


def get_settings() -> Settings:
    """Singleton getter for application settings."""
    return Settings()
