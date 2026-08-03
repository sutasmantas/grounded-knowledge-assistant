import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import type {
  ConnectorDescriptor,
  DocumentRecord,
  IngestionJobRecord,
  SyncItemResult,
} from "../api/types";
import { DocumentLibrary } from "./DocumentLibrary";

const TERMINAL = new Set(["succeeded", "failed", "cancelled", "dead_letter"]);

const ACTION_TONE: Record<SyncItemResult["action"], string> = {
  created: "positive",
  updated: "positive",
  unchanged: "muted",
  archived: "warning",
  deleted: "warning",
  skipped_duplicate: "muted",
  failed: "danger",
};

function describe(error: unknown): string {
  if (error instanceof ApiError) {
    // 503 means the server's parser install is broken, not the request. Keep
    // that visible instead of implying the user did something wrong.
    return error.status === 503 ? `Server not ready: ${error.detail}` : error.detail;
  }
  return error instanceof Error ? error.message : "Unknown error";
}

interface Props {
  documents: DocumentRecord[];
  onIndexChanged: () => void;
}

export function SourcesView({ documents, onIndexChanged }: Props) {
  const [connectors, setConnectors] = useState<ConnectorDescriptor[]>([]);
  const [catalogueError, setCatalogueError] = useState<string | null>(null);

  const [root, setRoot] = useState("");
  const [subpath, setSubpath] = useState("");
  const [urls, setUrls] = useState("");
  const [collection, setCollection] = useState("General");

  const [job, setJob] = useState<IngestionJobRecord | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const catalogue = await api.connectors();
        if (cancelled) return;
        setConnectors(catalogue);
        const localRoots = catalogue.find((entry) => entry.name === "local-folder");
        if (localRoots?.configured_roots[0]) {
          setRoot(localRoots.configured_roots[0]);
        }
      } catch (error) {
        if (!cancelled) setCatalogueError(describe(error));
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const follow = useCallback(
    async (queued: IngestionJobRecord) => {
      setJob(queued);
      for (let attempt = 0; attempt < 120; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 500));
        try {
          const current = await api.ingestionJob(queued.id);
          setJob(current);
          if (TERMINAL.has(current.status)) {
            onIndexChanged();
            return;
          }
        } catch (error) {
          setSubmitError(describe(error));
          return;
        }
      }
    },
    [onIndexChanged],
  );

  const localConnector = connectors.find((entry) => entry.name === "local-folder");
  const roots = localConnector?.configured_roots ?? [];

  async function submitFolder() {
    setBusy(true);
    setSubmitError(null);
    try {
      const queued = await api.syncLocalFolder({ root, subpath, collection });
      await follow(queued);
    } catch (error) {
      setSubmitError(describe(error));
    } finally {
      setBusy(false);
    }
  }

  async function submitUrls() {
    const list = urls
      .split(/\s+/)
      .map((value) => value.trim())
      .filter(Boolean);
    if (list.length === 0) {
      setSubmitError("Enter at least one http or https URL.");
      return;
    }
    setBusy(true);
    setSubmitError(null);
    try {
      const queued = await api.syncUrls({ urls: list, collection });
      await follow(queued);
    } catch (error) {
      setSubmitError(describe(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="sources" aria-label="Sources">
      <header className="sources__intro">
        <h2>Connected sources</h2>
        <p>
          Synchronization is incremental: unchanged files are skipped by checksum,
          changed files create a new immutable version, and a file that disappears
          upstream follows the configured deletion policy.
        </p>
      </header>

      {catalogueError ? (
        <div className="notice notice--danger" role="alert">
          <strong>The connector catalogue is unavailable.</strong>
          <span>{catalogueError}</span>
        </div>
      ) : null}

      <div className="sources__grid">
        <form
          className="panel"
          onSubmit={(event) => {
            event.preventDefault();
            void submitFolder();
          }}
        >
          <h3 className="panel__heading">Local folder</h3>
          {roots.length === 0 ? (
            <p className="panel__empty">
              No roots are configured. An operator sets{" "}
              <code>ATLAS_CONNECTOR_LOCAL_ROOTS</code>; requests select a root by
              name and can never address an arbitrary path.
            </p>
          ) : (
            <>
              <label className="field">
                <span className="field__label">Root</span>
                <select
                  value={root}
                  onChange={(event) => setRoot(event.target.value)}
                  disabled={busy}
                >
                  {roots.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span className="field__label">Subpath (optional)</span>
                <input
                  type="text"
                  value={subpath}
                  placeholder="handbook/policies"
                  onChange={(event) => setSubpath(event.target.value)}
                  disabled={busy}
                />
              </label>
              <button
                type="submit"
                className="button button--primary"
                disabled={busy || !root}
              >
                {busy ? "Synchronizing…" : "Synchronize folder"}
              </button>
            </>
          )}
        </form>

        <form
          className="panel"
          onSubmit={(event) => {
            event.preventDefault();
            void submitUrls();
          }}
        >
          <h3 className="panel__heading">URLs</h3>
          <p className="panel__empty">
            Only http and https are accepted. Private, loopback and cloud metadata
            targets are refused before a job is created.
          </p>
          <label className="field">
            <span className="field__label">One URL per line</span>
            <textarea
              rows={3}
              value={urls}
              placeholder="https://example.com/handbook.md"
              onChange={(event) => setUrls(event.target.value)}
              disabled={busy}
            />
          </label>
          <button type="submit" className="button button--primary" disabled={busy}>
            {busy ? "Synchronizing…" : "Synchronize URLs"}
          </button>
        </form>

        <div className="panel">
          <h3 className="panel__heading">Collection</h3>
          <label className="field">
            <span className="field__label">Target collection</span>
            <input
              type="text"
              value={collection}
              onChange={(event) => setCollection(event.target.value)}
              disabled={busy}
            />
          </label>
          <p className="panel__empty">
            Supported formats:{" "}
            {(localConnector?.supported_formats ?? []).join(", ") || "—"}
          </p>
        </div>
      </div>

      {submitError ? (
        <div className="notice notice--danger" role="alert">
          <strong>The synchronization request was rejected.</strong>
          <span>{submitError}</span>
        </div>
      ) : null}

      {job ? (
        <section className="panel" aria-label="Synchronization job">
          <h3 className="panel__heading">
            Job {job.status}
            {job.attempts > 0 ? ` · attempt ${job.attempts} of ${job.max_attempts}` : ""}
          </h3>
          <div
            className="progress"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={job.progress}
          >
            <span className="progress__bar" style={{ width: `${job.progress}%` }} />
          </div>
          <p className="panel__stage">
            {job.stage}
            {job.error_message ? ` — ${job.error_message}` : ""}
          </p>

          {job.sync_report ? (
            <>
              <ul className="tally">
                {(
                  [
                    ["discovered", job.sync_report.discovered],
                    ["created", job.sync_report.created],
                    ["updated", job.sync_report.updated],
                    ["unchanged", job.sync_report.unchanged],
                    ["removed", job.sync_report.removed],
                    ["skipped", job.sync_report.skipped],
                    ["failed", job.sync_report.failed],
                  ] as const
                ).map(([label, value]) => (
                  <li key={label}>
                    <strong>{value}</strong>
                    <small>{label}</small>
                  </li>
                ))}
              </ul>
              <table className="table">
                <caption className="visually-hidden">Per-item synchronization result</caption>
                <thead>
                  <tr>
                    <th scope="col">Action</th>
                    <th scope="col">Source</th>
                    <th scope="col">Version</th>
                    <th scope="col">Parser</th>
                  </tr>
                </thead>
                <tbody>
                  {job.sync_report.items.map((item) => (
                    <tr key={`${item.source_id}-${item.action}`}>
                      <td>
                        <span className={`tag tag--${ACTION_TONE[item.action]}`}>
                          {item.action.replace("_", " ")}
                        </span>
                      </td>
                      <td className="table__uri">{item.source_uri}</td>
                      <td>{item.version === null ? "—" : `v${item.version}`}</td>
                      <td>{item.parser ?? item.error_type ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : null}
        </section>
      ) : null}

      <DocumentLibrary
        documents={documents}
        collection={collection}
        onIndexChanged={onIndexChanged}
      />
    </section>
  );
}
