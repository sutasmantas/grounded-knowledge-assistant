import type {
  ConnectorDescriptor,
  DocumentRecord,
  GenerationTrace,
  HealthResponse,
  IngestionJobRecord,
  QueryResponse,
  RetrievalProfile,
  RetrievalTrace,
  SourceResult,
} from "./types";
import { browserQuery, browserRequest, inBrowserWorkspace } from "./browser";

/** The identity headers Atlas expects from a trusted gateway. The demo sends
 *  the default tenant; a real deployment replaces this with its own boundary. */
export interface AccessIdentity {
  tenant: string;
  principal: string;
  groups?: string[];
}

export const DEFAULT_IDENTITY: AccessIdentity = {
  tenant: "demo",
  principal: "demo-user",
};

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

function identityHeaders(identity: AccessIdentity): Record<string, string> {
  const headers: Record<string, string> = {
    "X-Atlas-Tenant": identity.tenant,
    "X-Atlas-Principal": identity.principal,
  };
  if (identity.groups?.length) {
    headers["X-Atlas-Groups"] = identity.groups.join(",");
  }
  return headers;
}

async function request<T>(
  path: string,
  identity: AccessIdentity,
  init?: RequestInit,
): Promise<T> {
  if (inBrowserWorkspace()) {
    return browserRequest<T>(path, init);
  }
  // FormData sets its own multipart boundary; forcing a Content-Type breaks it.
  const isJsonBody = init?.body !== undefined && !(init.body instanceof FormData);
  const response = await fetch(path, {
    ...init,
    headers: {
      ...(isJsonBody ? { "Content-Type": "application/json" } : {}),
      ...identityHeaders(identity),
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    // Surface the API's own message. Atlas distinguishes 422 (the document or
    // request is at fault) from 503 (the server's parser install is at fault),
    // and the shell must not collapse that difference.
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") {
        detail = body.detail;
      }
    } catch {
      // A non-JSON error body is still reportable via the status line.
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export interface QueryInput {
  question: string;
  collections?: string[];
  topK?: number;
  retrievalProfile?: RetrievalProfile;
}

export interface LocalFolderSyncInput {
  root: string;
  subpath?: string;
  collection: string;
  instanceId?: string;
  recursive?: boolean;
}

export interface UrlSyncInput {
  urls: string[];
  collection: string;
  instanceId?: string;
}

export interface StreamHandlers {
  onSources: (sources: SourceResult[], retrieval: RetrievalTrace, streamed: boolean) => void;
  onDelta: (text: string) => void;
  onTrace: (
    generation: GenerationTrace,
    latencyMs: number,
    generationMode: string,
    retracted: boolean,
  ) => void;
  /** Atlas judged the finished answer ungrounded after it was displayed. A
   *  client that ignores this shows an answer the server has disowned. */
  onRetracted: (detail: string) => void;
  onError: (detail: string) => void;
}

/** Consume the `text/event-stream` from `POST /api/query/stream`.
 *
 *  Hand-parsed rather than using `EventSource`, which cannot issue a POST or
 *  carry the identity headers Atlas expects. */
export async function streamQuery(
  input: QueryInput,
  handlers: StreamHandlers,
  identity: AccessIdentity = DEFAULT_IDENTITY,
  signal?: AbortSignal,
): Promise<void> {
  if (inBrowserWorkspace()) {
    const result = browserQuery(input.question, input.retrievalProfile);
    handlers.onSources(result.sources, result.retrieval, true);
    if (result.answer) {
      for (const chunk of result.answer.match(/.{1,24}(?:\s|$)/g) ?? [result.answer]) {
        handlers.onDelta(chunk);
        await new Promise((resolve) => window.setTimeout(resolve, 24));
      }
    }
    handlers.onTrace(result.generation, result.latency_ms, result.generation_mode, false);
    return;
  }
  const response = await fetch("/api/query/stream", {
    method: "POST",
    signal: signal ?? null,
    headers: { "Content-Type": "application/json", ...identityHeaders(identity) },
    body: JSON.stringify({
      question: input.question,
      collections: input.collections ?? [],
      top_k: input.topK ?? null,
      retrieval_profile: input.retrievalProfile ?? null,
    }),
  });
  if (!response.ok || !response.body) {
    throw new ApiError(response.status, `${response.status} ${response.statusText}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const dispatch = (block: string) => {
    let name = "";
    let raw = "{}";
    for (const line of block.split("\n")) {
      if (line.startsWith("event: ")) name = line.slice(7).trim();
      else if (line.startsWith("data: ")) raw = line.slice(6);
    }
    if (!name) return;
    const data = JSON.parse(raw) as Record<string, unknown>;
    switch (name) {
      case "sources":
        handlers.onSources(
          data["sources"] as SourceResult[],
          data["retrieval"] as RetrievalTrace,
          Boolean(data["streamed"]),
        );
        break;
      case "delta":
        handlers.onDelta(String(data["text"] ?? ""));
        break;
      case "retracted":
        handlers.onRetracted(String(data["detail"] ?? "The answer was retracted."));
        break;
      case "trace":
        handlers.onTrace(
          data["generation"] as GenerationTrace,
          Number(data["latency_ms"] ?? 0),
          String(data["generation_mode"] ?? ""),
          Boolean(data["retracted"]),
        );
        break;
      case "error":
        handlers.onError(String(data["detail"] ?? "The request failed."));
        break;
      default:
        break;
    }
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      dispatch(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf("\n\n");
    }
  }
  if (buffer.trim()) dispatch(buffer);
}

export const api = {
  health: (identity = DEFAULT_IDENTITY) =>
    request<HealthResponse>("/api/health", identity),

  documents: (identity = DEFAULT_IDENTITY) =>
    request<DocumentRecord[]>("/api/documents", identity),

  connectors: (identity = DEFAULT_IDENTITY) =>
    request<ConnectorDescriptor[]>("/api/connectors", identity),

  ingestionJobs: (identity = DEFAULT_IDENTITY) =>
    request<IngestionJobRecord[]>("/api/ingestion-jobs", identity),

  documentVersions: (documentId: string, identity = DEFAULT_IDENTITY) =>
    request<DocumentRecord[]>(
      `/api/documents/${encodeURIComponent(documentId)}/versions`,
      identity,
    ),

  uploadDocument: (
    file: File,
    collection: string,
    identity = DEFAULT_IDENTITY,
  ) => {
    const body = new FormData();
    body.append("file", file);
    body.append("collection", collection);
    return request<DocumentRecord>("/api/documents", identity, {
      method: "POST",
      body,
    });
  },

  reindexDocument: (
    documentId: string,
    file: File,
    identity = DEFAULT_IDENTITY,
  ) => {
    const body = new FormData();
    body.append("file", file);
    return request<DocumentRecord>(
      `/api/documents/${encodeURIComponent(documentId)}`,
      identity,
      { method: "PUT", body },
    );
  },

  deleteDocument: (documentId: string, identity = DEFAULT_IDENTITY) =>
    request<void>(`/api/documents/${encodeURIComponent(documentId)}`, identity, {
      method: "DELETE",
    }),

  enqueueUpload: (file: File, collection: string, identity = DEFAULT_IDENTITY) => {
    const body = new FormData();
    body.append("file", file);
    body.append("collection", collection);
    return request<IngestionJobRecord>("/api/ingestion-jobs", identity, {
      method: "POST",
      body,
    });
  },

  ingestionJob: (jobId: string, identity = DEFAULT_IDENTITY) =>
    request<IngestionJobRecord>(
      `/api/ingestion-jobs/${encodeURIComponent(jobId)}`,
      identity,
    ),

  syncLocalFolder: (input: LocalFolderSyncInput, identity = DEFAULT_IDENTITY) =>
    request<IngestionJobRecord>("/api/connectors/local-folder/sync", identity, {
      method: "POST",
      body: JSON.stringify({
        root: input.root,
        subpath: input.subpath ?? "",
        collection: input.collection,
        instance_id: input.instanceId ?? null,
        recursive: input.recursive ?? true,
      }),
    }),

  syncUrls: (input: UrlSyncInput, identity = DEFAULT_IDENTITY) =>
    request<IngestionJobRecord>("/api/connectors/url/sync", identity, {
      method: "POST",
      body: JSON.stringify({
        urls: input.urls,
        collection: input.collection,
        instance_id: input.instanceId ?? null,
      }),
    }),

  query: (input: QueryInput, identity = DEFAULT_IDENTITY) =>
    request<QueryResponse>("/api/query", identity, {
      method: "POST",
      body: JSON.stringify({
        question: input.question,
        collections: input.collections ?? [],
        top_k: input.topK ?? null,
        retrieval_profile: input.retrievalProfile ?? null,
      }),
    }),
};
