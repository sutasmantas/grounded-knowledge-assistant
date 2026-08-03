from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.access import DocumentVisibility

RetrievalProfile = Literal["dense", "sparse", "hybrid", "hybrid-reranked"]
IngestionJobStatus = Literal[
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "dead_letter",
]
IngestionJobKind = Literal["upload", "connector-sync"]
ConnectorName = Literal["local-folder", "url"]
DeletionPolicy = Literal["archive", "delete"]


class HealthResponse(BaseModel):
    status: str
    documents: int
    embedding_provider: str
    generation_provider: str
    chunking_profile: str


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, Literal["ok", "unavailable"]]


class DocumentRecord(BaseModel):
    id: str
    source_id: str
    source_uri: str
    version: int
    supersedes_document_id: str | None
    filename: str
    title: str
    collection: str
    mime_type: str
    size_bytes: int
    sha256: str
    chunk_count: int
    status: str
    created_at: datetime
    tenant_id: str
    owner_principal_id: str
    visibility: DocumentVisibility
    allowed_principals: tuple[str, ...] = ()
    allowed_groups: tuple[str, ...] = ()
    connector_name: str = ""
    connector_instance: str = ""


class SyncItemResult(BaseModel):
    source_id: str
    source_uri: str
    action: Literal[
        "created",
        "updated",
        "unchanged",
        "archived",
        "deleted",
        "skipped_duplicate",
        "failed",
    ]
    document_id: str | None = None
    version: int | None = None
    parser: str | None = None
    error_type: str | None = None
    error_message: str | None = None


class SyncReport(BaseModel):
    connector: str
    instance_id: str
    collection: str
    deletion_policy: DeletionPolicy
    discovered: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    skipped: int = 0
    failed: int = 0
    items: list[SyncItemResult] = Field(default_factory=list)


class ConnectorDescriptor(BaseModel):
    name: ConnectorName
    description: str
    configured_roots: list[str] = Field(default_factory=list)
    supported_formats: list[str] = Field(default_factory=list)


class LocalFolderSyncRequest(BaseModel):
    root: str = Field(min_length=1, max_length=128)
    subpath: str = Field(default="", max_length=512)
    collection: str = Field(default="General", min_length=1, max_length=120)
    instance_id: str | None = Field(default=None, max_length=128)
    recursive: bool = True
    visibility: DocumentVisibility = "tenant"
    allowed_principals: list[str] = Field(default_factory=list, max_length=50)
    allowed_groups: list[str] = Field(default_factory=list, max_length=50)


class UrlSyncRequest(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=100)
    collection: str = Field(default="General", min_length=1, max_length=120)
    instance_id: str | None = Field(default=None, max_length=128)
    visibility: DocumentVisibility = "tenant"
    allowed_principals: list[str] = Field(default_factory=list, max_length=50)
    allowed_groups: list[str] = Field(default_factory=list, max_length=50)


class IngestionJobRecord(BaseModel):
    id: str
    kind: IngestionJobKind = "upload"
    status: IngestionJobStatus
    progress: int = Field(ge=0, le=100)
    stage: str
    filename: str
    collection: str
    source_uri: str
    mime_type: str
    attempts: int
    max_attempts: int
    cancel_requested: bool
    error_type: str | None
    error_message: str | None
    document_id: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    tenant_id: str
    owner_principal_id: str
    visibility: DocumentVisibility
    allowed_principals: tuple[str, ...] = ()
    allowed_groups: tuple[str, ...] = ()
    connector_name: str = ""
    connector_instance: str = ""
    sync_report: SyncReport | None = None


class QueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    collections: list[str] = Field(default_factory=list)
    top_k: int | None = Field(default=None, ge=1, le=12)
    retrieval_profile: RetrievalProfile | None = None


class QueryComparisonRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    collections: list[str] = Field(default_factory=list)
    top_k: int | None = Field(default=None, ge=1, le=12)
    profiles: list[RetrievalProfile] = Field(
        default_factory=lambda: ["sparse", "hybrid"],
        min_length=2,
        max_length=4,
    )

    @field_validator("profiles")
    @classmethod
    def profiles_must_be_unique(
        cls,
        profiles: list[RetrievalProfile],
    ) -> list[RetrievalProfile]:
        if len(profiles) != len(set(profiles)):
            raise ValueError("Comparison profiles must be unique")
        return profiles


class SourceResult(BaseModel):
    rank: int
    document_id: str
    source_id: str
    source_uri: str
    document_version: int
    document_sha256: str
    chunk_id: str
    title: str
    filename: str
    collection: str
    page: int | None
    passage: str
    score: float
    rerank_score: float | None = None
    security_flags: tuple[str, ...] = ()


class RetrievalTrace(BaseModel):
    profile: RetrievalProfile
    candidate_limit: int
    candidates_considered: int
    fusion: str | None
    reranker: str | None
    retrieval_ms: int
    rerank_ms: int


class GenerationTrace(BaseModel):
    """What generation actually cost.

    Token counts are `null` whenever the provider did not report usage, which
    includes the local extractive mode. They are never estimated.
    """

    provider: str
    context_sources: int
    context_characters: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    generation_ms: int = 0


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceResult]
    retrieval: RetrievalTrace
    generation: GenerationTrace
    generation_mode: str
    latency_ms: int


class QueryComparisonResponse(BaseModel):
    question: str
    collections: list[str]
    results: list[QueryResponse]
