/** Types mirroring `app/schemas.py`. Kept hand-written and narrow on purpose:
 *  the shell should fail to compile when the API contract changes. */

export type RetrievalProfile = "dense" | "sparse" | "hybrid" | "hybrid-reranked";

export interface SourceResult {
  rank: number;
  document_id: string;
  source_id: string;
  source_uri: string;
  document_version: number;
  document_sha256: string;
  chunk_id: string;
  title: string;
  filename: string;
  collection: string;
  page: number | null;
  passage: string;
  score: number;
  rerank_score: number | null;
  security_flags: string[];
}

export interface RetrievalTrace {
  profile: RetrievalProfile;
  candidate_limit: number;
  candidates_considered: number;
  fusion: string | null;
  reranker: string | null;
  retrieval_ms: number;
  rerank_ms: number;
}

/** Token counts are null whenever the provider did not report usage, which
 *  includes the no-key extractive mode. The UI must render "not reported"
 *  rather than zero. */
export interface GenerationTrace {
  provider: string;
  context_sources: number;
  context_characters: number;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  generation_ms: number;
}

export interface QueryResponse {
  answer: string;
  sources: SourceResult[];
  retrieval: RetrievalTrace;
  generation: GenerationTrace;
  generation_mode: string;
  latency_ms: number;
}

export interface DocumentRecord {
  id: string;
  source_id: string;
  source_uri: string;
  version: number;
  supersedes_document_id: string | null;
  filename: string;
  title: string;
  collection: string;
  mime_type: string;
  size_bytes: number;
  sha256: string;
  chunk_count: number;
  status: string;
  created_at: string;
  tenant_id: string;
  owner_principal_id: string;
  visibility: "tenant" | "restricted";
  allowed_principals: string[];
  allowed_groups: string[];
  connector_name: string;
  connector_instance: string;
}

export interface HealthResponse {
  status: string;
  documents: number;
  embedding_provider: string;
  generation_provider: string;
  chunking_profile: string;
}

export interface ConnectorDescriptor {
  name: "local-folder" | "url";
  description: string;
  configured_roots: string[];
  supported_formats: string[];
}

export interface SyncItemResult {
  source_id: string;
  source_uri: string;
  action:
    | "created"
    | "updated"
    | "unchanged"
    | "archived"
    | "deleted"
    | "skipped_duplicate"
    | "failed";
  document_id: string | null;
  version: number | null;
  parser: string | null;
  error_type: string | null;
  error_message: string | null;
}

export interface SyncReport {
  connector: string;
  instance_id: string;
  collection: string;
  deletion_policy: "archive" | "delete";
  discovered: number;
  created: number;
  updated: number;
  unchanged: number;
  removed: number;
  skipped: number;
  failed: number;
  items: SyncItemResult[];
}

export interface IngestionJobRecord {
  id: string;
  kind: "upload" | "connector-sync";
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled" | "dead_letter";
  progress: number;
  stage: string;
  filename: string;
  collection: string;
  source_uri: string;
  attempts: number;
  max_attempts: number;
  cancel_requested: boolean;
  error_type: string | null;
  error_message: string | null;
  document_id: string | null;
  connector_name: string;
  connector_instance: string;
  sync_report: SyncReport | null;
}
