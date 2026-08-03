import type {
  ConnectorDescriptor,
  DocumentRecord,
  IngestionJobRecord,
  QueryResponse,
  RetrievalProfile,
  SourceResult,
} from "./types";

const now = "2026-08-03T10:00:00Z";

function document(id: string, filename: string, title: string, collection: string): DocumentRecord {
  return {
    id, source_id: id, source_uri: `kb://${collection.toLowerCase()}/${filename}`,
    version: 1, supersedes_document_id: null, filename, title, collection,
    mime_type: "text/markdown", size_bytes: 12480, sha256: `${id}f3b9c32b2a0e742a527aeec7f8e9d9fc47c0b33ab8d8e46e423d907d6a1`,
    chunk_count: 8, status: "indexed", created_at: now, tenant_id: "northstar",
    owner_principal_id: "knowledge-ops", visibility: "tenant",
    allowed_principals: [], allowed_groups: [], connector_name: "local-folder", connector_instance: "handbook",
  };
}

let documents: DocumentRecord[] = [
  document("billing", "billing-policy.md", "Billing and refund policy", "Commercial"),
  document("contracts", "enterprise-terms.md", "Enterprise contract terms", "Commercial"),
  document("security", "security-response.md", "Security incident response", "Trust"),
  document("approvals", "approval-matrix.md", "Commercial approval matrix", "Operations"),
];

const connectors: ConnectorDescriptor[] = [
  { name: "local-folder", description: "Incremental folder synchronization", configured_roots: ["handbook"], supported_formats: ["PDF", "DOCX", "HTML", "Markdown", "text"] },
  { name: "url", description: "Allowlisted public URL synchronization", configured_roots: [], supported_formats: ["HTML", "Markdown", "text"] },
];

const jobs = new Map<string, IngestionJobRecord>();

function source(rank: number, documentId: string, title: string, filename: string, collection: string, passage: string, score: number): SourceResult {
  return {
    rank, document_id: documentId, source_id: documentId, source_uri: `kb://${collection.toLowerCase()}/${filename}`,
    document_version: 1, document_sha256: documents.find((item) => item.id === documentId)?.sha256 ?? "sha256",
    chunk_id: `${documentId}-chunk-${rank}`, title, filename, collection, page: rank,
    passage, score, rerank_score: score + 0.03, security_flags: [],
  };
}

export function inBrowserWorkspace(): boolean {
  return window.location.hostname.endsWith("github.io") || new URLSearchParams(window.location.search).has("static");
}

export function browserQuery(question: string, profile: RetrievalProfile = "sparse"): QueryResponse {
  const lower = question.toLowerCase();
  if (lower.includes("bicycle") || lower.includes("derailleur")) {
    return {
      answer: "", sources: [],
      retrieval: { profile, candidate_limit: 24, candidates_considered: 0, fusion: profile.includes("hybrid") ? "reciprocal-rank" : null, reranker: profile.includes("reranked") ? "cross-encoder" : null, retrieval_ms: 7, rerank_ms: 0 },
      generation: { provider: "abstain", context_sources: 0, context_characters: 0, prompt_tokens: null, completion_tokens: null, total_tokens: null, generation_ms: 0 },
      generation_mode: "abstained", latency_ms: 9,
    };
  }
  let answer = "Enterprise customers may cancel only at renewal with the required notice. Mid-term exceptions require Commercial Operations approval and documented cause [1] [2].";
  let sources = [
    source(1, "contracts", "Enterprise contract terms", "enterprise-terms.md", "Commercial", "The subscription remains active through the committed term. Cancellation takes effect at renewal after 30 days' written notice.", 0.94),
    source(2, "approvals", "Commercial approval matrix", "approval-matrix.md", "Operations", "Any mid-term cancellation or refund exception requires approval from Commercial Operations and Finance.", 0.89),
  ];
  if (lower.includes("security") || lower.includes("incident")) {
    answer = "After a confirmed incident affecting customer data, the response team must notify affected customers, preserve the incident record, and apply the contractual service remedy after severity review [1] [2].";
    sources = [
      source(1, "security", "Security incident response", "security-response.md", "Trust", "Confirmed customer-data incidents trigger notification, evidence preservation and a severity review led by Security.", 0.96),
      source(2, "contracts", "Enterprise contract terms", "enterprise-terms.md", "Commercial", "Service remedies are determined by incident severity and the customer agreement's service-level schedule.", 0.86),
    ];
  } else if (lower.includes("refund")) {
    answer = "Annual plans are normally non-refundable after the cooling-off period. A documented service failure can be routed to Finance and Commercial Operations for an exception decision [1] [2].";
    sources = [
      source(1, "billing", "Billing and refund policy", "billing-policy.md", "Commercial", "Annual subscriptions are non-refundable after the cooling-off period unless a documented service failure applies.", 0.95),
      source(2, "approvals", "Commercial approval matrix", "approval-matrix.md", "Operations", "Refund exceptions require Finance and Commercial Operations approval before customer confirmation.", 0.91),
    ];
  }
  return {
    answer, sources,
    retrieval: { profile, candidate_limit: 24, candidates_considered: 11, fusion: profile.includes("hybrid") ? "reciprocal-rank" : null, reranker: profile.includes("reranked") ? "cross-encoder" : null, retrieval_ms: 18, rerank_ms: profile.includes("reranked") ? 12 : 0 },
    generation: { provider: "grounded-extractive", context_sources: 2, context_characters: 584, prompt_tokens: null, completion_tokens: null, total_tokens: null, generation_ms: 42 },
    generation_mode: "grounded", latency_ms: profile.includes("reranked") ? 78 : 61,
  };
}

function job(kind: "upload" | "connector-sync", filename: string, collection: string, sourceUri: string): IngestionJobRecord {
  const id = `job-${Date.now()}`;
  const record: IngestionJobRecord = {
    id, kind, status: "succeeded", progress: 100, stage: "Index updated", filename, collection,
    source_uri: sourceUri, attempts: 1, max_attempts: 3, cancel_requested: false,
    error_type: null, error_message: null, document_id: null, connector_name: kind === "upload" ? "upload" : "browser",
    connector_instance: "workspace", sync_report: kind === "connector-sync" ? {
      connector: "browser", instance_id: "workspace", collection, deletion_policy: "archive",
      discovered: 2, created: 1, updated: 0, unchanged: 1, removed: 0, skipped: 0, failed: 0,
      items: [
        { source_id: "synced-1", source_uri: sourceUri, action: "created", document_id: "synced-1", version: 1, parser: "markdown", error_type: null, error_message: null },
        { source_id: "synced-2", source_uri: `${sourceUri}/existing`, action: "unchanged", document_id: "billing", version: 1, parser: "markdown", error_type: null, error_message: null },
      ],
    } : null,
  };
  jobs.set(id, record);
  return record;
}

export async function browserRequest<T>(path: string, init?: RequestInit): Promise<T> {
  await new Promise((resolve) => window.setTimeout(resolve, 70));
  if (path === "/api/health") return { status: "ok", documents: documents.length, embedding_provider: "hybrid index", generation_provider: "grounded answer", chunking_profile: "structure-aware" } as T;
  if (path === "/api/documents" && (!init?.method || init.method === "GET")) return structuredClone(documents) as T;
  if (path === "/api/connectors") return structuredClone(connectors) as T;
  if (path === "/api/ingestion-jobs") return [...jobs.values()] as T;
  if (path === "/api/query" && init?.body) {
    const payload = JSON.parse(String(init.body)) as { question: string; retrieval_profile?: RetrievalProfile };
    return browserQuery(payload.question, payload.retrieval_profile) as T;
  }
  if (path === "/api/documents" && init?.method === "POST") {
    const created = document(`upload-${Date.now()}`, "uploaded-document.pdf", "Uploaded document", "General");
    documents = [created, ...documents];
    return structuredClone(created) as T;
  }
  const deleteMatch = path.match(/^\/api\/documents\/([^/]+)$/);
  if (deleteMatch && init?.method === "DELETE") {
    documents = documents.filter((item) => item.id !== deleteMatch[1]);
    return undefined as T;
  }
  if (path === "/api/ingestion-jobs" && init?.method === "POST") return job("upload", "uploaded-document.pdf", "General", "upload://document") as T;
  const jobMatch = path.match(/^\/api\/ingestion-jobs\/(.+)$/);
  if (jobMatch) {
    const current = jobs.get(jobMatch[1]!);
    if (!current) throw new Error("Synchronization job not found");
    return structuredClone(current) as T;
  }
  if (path.startsWith("/api/connectors/") && init?.method === "POST") {
    const payload = JSON.parse(String(init.body ?? "{}")) as { collection?: string; root?: string; urls?: string[] };
    return job("connector-sync", "source sync", payload.collection ?? "General", payload.urls?.[0] ?? `folder://${payload.root ?? "handbook"}`) as T;
  }
  if (path.endsWith("/versions")) return structuredClone(documents.filter((item) => path.includes(item.id))) as T;
  throw new Error(`Unknown browser-workspace route: ${path}`);
}
