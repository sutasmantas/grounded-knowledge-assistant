import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, api, streamQuery } from "./api/client";
import type {
  DocumentRecord,
  GenerationTrace,
  HealthResponse,
  QueryResponse,
  RetrievalProfile,
  RetrievalTrace,
} from "./api/types";

const EMPTY_GENERATION: GenerationTrace = {
  provider: "",
  context_sources: 0,
  context_characters: 0,
  prompt_tokens: null,
  completion_tokens: null,
  total_tokens: null,
  generation_ms: 0,
};

const EMPTY_RETRIEVAL: RetrievalTrace = {
  profile: "sparse",
  candidate_limit: 0,
  candidates_considered: 0,
  fusion: null,
  reranker: null,
  retrieval_ms: 0,
  rerank_ms: 0,
};
import { AnswerCanvas } from "./components/AnswerCanvas";
import { EvidencePane } from "./components/EvidencePane";
import { GlobalHeader, type View } from "./components/GlobalHeader";
import { QueryRail } from "./components/QueryRail";
import { SourcesView } from "./components/SourcesView";
import { TraceDrawer } from "./components/TraceDrawer";

function message(error: unknown): string {
  if (error instanceof ApiError) {
    return error.detail;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Unknown error";
}

export function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);

  const [question, setQuestion] = useState("");
  const [profile, setProfile] = useState<RetrievalProfile>("sparse");
  const [selectedCollections, setSelectedCollections] = useState<string[]>([]);

  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [queryError, setQueryError] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(true);
  const [streamingAnswer, setStreamingAnswer] = useState<string | null>(null);
  const [retracted, setRetracted] = useState<string | null>(null);

  // Below 1200px the rail is a fixed overlay rather than a column, so leaving
  // it open on load would cover the canvas the user came for.
  const [railCollapsed, setRailCollapsed] = useState(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia("(max-width: 1200px)").matches,
  );
  const [traceOpen, setTraceOpen] = useState(false);
  const [activeCitation, setActiveCitation] = useState<number | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [view, setView] = useState<View>("research");

  const refreshIndex = useCallback(async () => {
    try {
      const [healthResponse, documentResponse] = await Promise.all([
        api.health(),
        api.documents(),
      ]);
      setHealth(healthResponse);
      setDocuments(documentResponse);
      setHealthError(null);
    } catch (error) {
      setHealthError(message(error));
    }
  }, []);

  useEffect(() => {
    void refreshIndex();
  }, [refreshIndex]);

  const collections = useMemo(
    () => [...new Set(documents.map((document) => document.collection))].sort(),
    [documents],
  );

  const runQuery = useCallback(
    async (asked: string) => {
      const trimmed = asked.trim();
      if (trimmed.length < 3) return;
      setBusy(true);
      setQueryError(null);
      setRetracted(null);
      setActiveCitation(null);
      setStreamingAnswer(null);
      const input = {
        question: trimmed,
        collections: selectedCollections,
        retrievalProfile: profile,
      };
      try {
        if (!streaming) {
          const response = await api.query(input);
          setResult(response);
          setRailCollapsed(true);
          return;
        }

        // Streaming: evidence is shown as soon as retrieval finishes, while
        // generation is still running.
        let partial = "";
        let carried: Partial<QueryResponse> = {};
        setResult(null);
        setRailCollapsed(true);
        await streamQuery(input, {
          onSources: (sources, retrieval) => {
            carried = { ...carried, sources, retrieval };
            setResult({
              answer: "",
              sources,
              retrieval,
              generation: EMPTY_GENERATION,
              generation_mode: "",
              latency_ms: 0,
            });
          },
          onDelta: (text) => {
            partial += text;
            setStreamingAnswer(partial);
          },
          onRetracted: (detail) => setRetracted(detail),
          onTrace: (generation, latencyMs, generationMode) => {
            setResult({
              answer: partial,
              sources: carried.sources ?? [],
              retrieval: carried.retrieval ?? EMPTY_RETRIEVAL,
              generation,
              generation_mode: generationMode,
              latency_ms: latencyMs,
            });
            setStreamingAnswer(null);
          },
          onError: (detail) => {
            setQueryError(detail);
            setStreamingAnswer(null);
          },
        });
      } catch (error) {
        setResult(null);
        setQueryError(message(error));
      } finally {
        setBusy(false);
      }
    },
    [profile, selectedCollections, streaming],
  );

  function handlePreparedCase(prepared: string) {
    setQuestion(prepared);
    void runQuery(prepared);
  }

  function handleCitationSelect(rank: number) {
    setActiveCitation((current) => (current === rank ? null : rank));
    setSheetOpen(true);
    document.getElementById(`source-${rank}`)?.scrollIntoView({
      behavior: "smooth",
      block: "nearest",
    });
  }

  return (
    <div className="shell">
      <GlobalHeader
        health={health}
        healthError={healthError}
        railCollapsed={railCollapsed}
        onToggleRail={() => setRailCollapsed((value) => !value)}
        view={view}
        onViewChange={setView}
      />

      {view === "sources" ? (
        <div className="single">
          <SourcesView documents={documents} onIndexChanged={() => void refreshIndex()} />
        </div>
      ) : (
      <div className={`workspace${railCollapsed ? " workspace--rail-collapsed" : ""}`}>
        <QueryRail
          collapsed={railCollapsed}
          workspace={{
            scope: "Northstar policy workspace",
            documents: health?.documents ?? null,
            embeddingProvider: health?.embedding_provider ?? null,
            generationProvider: health?.generation_provider ?? null,
          }}
          profile={profile}
          onProfileChange={setProfile}
          collections={collections}
          selectedCollections={selectedCollections}
          onCollectionsChange={setSelectedCollections}
          onPreparedCase={handlePreparedCase}
          busy={busy}
        />

        <main className="main">
          <AnswerCanvas
            question={question}
            onQuestionChange={setQuestion}
            onSubmit={() => void runQuery(question)}
            busy={busy}
            result={result}
            error={queryError}
            activeCitation={activeCitation}
            onCitationSelect={handleCitationSelect}
            onPreparedCase={handlePreparedCase}
            streamingAnswer={streamingAnswer}
            retracted={retracted}
            streaming={streaming}
            onStreamingChange={setStreaming}
          />

          {result ? (
            <button
              type="button"
              className="trace-toggle"
              onClick={() => setTraceOpen((value) => !value)}
              aria-expanded={traceOpen}
            >
              {result.retrieval.profile} · {result.latency_ms} ms ·{" "}
              {traceOpen ? "hide trace" : "show trace"}
            </button>
          ) : null}
        </main>

        <EvidencePane
          sources={result?.sources ?? []}
          activeCitation={activeCitation}
          onCitationSelect={handleCitationSelect}
          sheetOpen={sheetOpen}
          onCloseSheet={() => setSheetOpen(false)}
        />
      </div>
      )}

      <TraceDrawer
        open={traceOpen}
        onOpenChange={setTraceOpen}
        retrieval={result?.retrieval ?? null}
        generation={result?.generation ?? null}
        latencyMs={result?.latency_ms ?? null}
      />
    </div>
  );
}
