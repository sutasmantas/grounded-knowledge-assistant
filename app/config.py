from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_prefix="ATLAS_",
        extra="ignore",
    )

    app_name: str = "Atlas Knowledge"
    data_dir: Path = PROJECT_ROOT / "data" / "runtime"
    sample_documents_dir: Path = PROJECT_ROOT / "data" / "sample_documents"
    qdrant_mode: Literal["embedded", "server"] = "embedded"
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    qdrant_timeout_seconds: int = Field(default=5, ge=1, le=120)
    auth_mode: Literal["headers", "oidc"] = "headers"
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    oidc_algorithms: list[str] = Field(default_factory=lambda: ["RS256"])
    oidc_tenant_claim: str = "tenant_id"
    oidc_principal_claim: str = "sub"
    oidc_groups_claim: str = "groups"
    oidc_roles_claim: str = "roles"
    oidc_jwks_cache_seconds: int = Field(default=300, ge=1, le=86400)
    oidc_jwks_timeout_seconds: int = Field(default=5, ge=1, le=60)
    oidc_clock_skew_seconds: int = Field(default=30, ge=0, le=300)
    embedding_provider: Literal[
        "hash",
        "fastembed",
        "sentence-transformers",
        "openai-compatible",
    ] = "fastembed"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dimensions: int | None = Field(default=None, ge=1, le=4096)
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_api_key: str = ""
    retrieval_profile: Literal["dense", "sparse", "hybrid", "hybrid-reranked"] = (
        "sparse"
    )
    reranker_provider: Literal["lexical", "cross-encoder", "colbert"] = "cross-encoder"
    reranker_model: str = "BAAI/bge-reranker-base"
    retrieval_candidate_k: int = Field(default=24, ge=8, le=100)
    generation_provider: Literal["extractive", "openai-compatible"] = "extractive"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_max_tokens: int = Field(default=256, ge=32, le=2048)
    llm_require_citations: bool = True
    max_upload_mb: int = Field(default=10, ge=1, le=50)
    pdf_min_characters_per_page: int = Field(default=24, ge=1, le=2000)
    connector_local_roots: dict[str, Path] = Field(default_factory=dict)
    connector_max_items: int = Field(default=500, ge=1, le=10000)
    connector_max_document_mb: int = Field(default=10, ge=1, le=50)
    connector_url_timeout_seconds: float = Field(default=10.0, ge=0.5, le=120)
    connector_url_max_redirects: int = Field(default=3, ge=0, le=10)
    connector_url_allow_private_networks: bool = False
    connector_deletion_policy: Literal["archive", "delete"] = "archive"
    ingestion_worker_enabled: bool = True
    ingestion_worker_poll_seconds: float = Field(default=0.5, ge=0.05, le=10)
    ingestion_job_max_attempts: int = Field(default=3, ge=1, le=10)
    otel_exporter_otlp_endpoint: str = ""
    otel_service_name: str = "atlas-knowledge"
    structured_logs: bool = True
    request_body_limit_mb: int = Field(default=12, ge=1, le=100)
    top_k: int = Field(default=5, ge=1, le=12)
    min_score: float = Field(default=0.08, ge=-1, le=1)
    semantic_evidence_floor: float = Field(default=0.50, ge=-1, le=1)
    score_ratio: float = Field(default=0.9, ge=0, le=1)
    chunk_size: int = Field(default=950, ge=300, le=2400)
    chunk_overlap: int = Field(default=140, ge=0, le=500)
    chunking_profile: Literal[
        "fixed",
        "heading-aware",
        "parent-child",
        "docling-hybrid",
    ] = "fixed"

    @model_validator(mode="after")
    def validate_provider_configuration(self) -> Settings:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        if self.request_body_limit_mb <= self.max_upload_mb:
            raise ValueError(
                "request_body_limit_mb must exceed max_upload_mb for multipart overhead"
            )
        if self.qdrant_mode == "server" and not self.qdrant_url:
            raise ValueError("ATLAS_QDRANT_URL is required in server mode")
        if self.qdrant_mode == "embedded" and self.qdrant_url:
            raise ValueError(
                "ATLAS_QDRANT_URL must be empty in embedded mode; set "
                "ATLAS_QDRANT_MODE=server explicitly"
            )
        if self.auth_mode == "oidc":
            required = {
                "ATLAS_OIDC_ISSUER": self.oidc_issuer,
                "ATLAS_OIDC_AUDIENCE": self.oidc_audience,
                "ATLAS_OIDC_JWKS_URL": self.oidc_jwks_url,
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise ValueError(f"Missing settings for OIDC mode: {missing}")
            parsed_jwks = urlparse(self.oidc_jwks_url)
            local_hosts = {"localhost", "127.0.0.1", "::1"}
            if not parsed_jwks.hostname or (
                parsed_jwks.scheme != "https" and parsed_jwks.hostname not in local_hosts
            ):
                raise ValueError(
                    "ATLAS_OIDC_JWKS_URL must use HTTPS except for a loopback test server"
                )
            claim_names = {
                self.oidc_tenant_claim,
                self.oidc_principal_claim,
                self.oidc_groups_claim,
                self.oidc_roles_claim,
            }
            if "" in claim_names or len(claim_names) != 4:
                raise ValueError("OIDC tenant, principal, group and role claims must be distinct")
            allowed_algorithms = {
                "RS256",
                "RS384",
                "RS512",
                "PS256",
                "PS384",
                "PS512",
                "ES256",
                "ES384",
                "ES512",
                "EdDSA",
            }
            if not self.oidc_algorithms or not set(self.oidc_algorithms) <= allowed_algorithms:
                raise ValueError(
                    "ATLAS_OIDC_ALGORITHMS must contain only approved asymmetric algorithms"
                )
        if self.generation_provider == "openai-compatible":
            missing = [
                name
                for name, value in {
                    "ATLAS_LLM_BASE_URL": self.llm_base_url,
                    "ATLAS_LLM_MODEL": self.llm_model,
                }.items()
                if not value
            ]
            if missing:
                raise ValueError(f"Missing settings for openai-compatible provider: {missing}")
        if self.embedding_provider == "openai-compatible" and not self.embedding_api_key:
            raise ValueError(
                "ATLAS_EMBEDDING_API_KEY is required for openai-compatible embeddings"
            )
        return self

    @property
    def connector_max_bytes(self) -> int:
        return self.connector_max_document_mb * 1024 * 1024

    @property
    def sqlite_path(self) -> Path:
        return self.data_dir / "atlas.sqlite3"

    @property
    def qdrant_path(self) -> Path:
        return self.data_dir / "qdrant"

    @property
    def ingestion_jobs_path(self) -> Path:
        return self.data_dir / "ingestion_jobs.sqlite3"

    @property
    def ingestion_job_inputs_dir(self) -> Path:
        return self.data_dir / "ingestion_job_inputs"
