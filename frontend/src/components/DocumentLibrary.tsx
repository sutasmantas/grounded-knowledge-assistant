import { useState } from "react";

import { ApiError, api } from "../api/client";
import type { DocumentRecord } from "../api/types";

function describe(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 503) return `Server not ready: ${error.detail}`;
    if (error.status === 404) return "Not found, or not visible to this identity.";
    return error.detail;
  }
  return error instanceof Error ? error.message : "Unknown error";
}

interface Props {
  documents: DocumentRecord[];
  collection: string;
  onIndexChanged: () => void;
}

/** Upload, re-index, version history and deletion. These are the lifecycle
 *  controls Phase B built and no interface exposed, and they are also what make
 *  the error and version states reachable without inventing fixtures. */
export function DocumentLibrary({ documents, collection, onIndexChanged }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [versionsFor, setVersionsFor] = useState<string | null>(null);
  const [versions, setVersions] = useState<DocumentRecord[]>([]);

  async function run(label: string, work: () => Promise<string | null>) {
    setBusy(label);
    setError(null);
    setNotice(null);
    try {
      const message = await work();
      if (message) setNotice(message);
      onIndexChanged();
    } catch (caught) {
      setError(describe(caught));
    } finally {
      setBusy(null);
    }
  }

  function upload(files: FileList | null) {
    const file = files?.[0];
    if (!file) return;
    void run("upload", async () => {
      const document = await api.uploadDocument(file, collection);
      return `Indexed ${document.filename} as version ${document.version}.`;
    });
  }

  function replace(document: DocumentRecord, files: FileList | null) {
    const file = files?.[0];
    if (!file) return;
    void run(`replace-${document.id}`, async () => {
      const replaced = await api.reindexDocument(document.id, file);
      return `${replaced.filename} is now version ${replaced.version}; version ${document.version} is superseded.`;
    });
  }

  function remove(document: DocumentRecord) {
    void run(`delete-${document.id}`, async () => {
      await api.deleteDocument(document.id);
      setVersionsFor(null);
      return `Removed ${document.filename} and every version's vectors.`;
    });
  }

  async function showVersions(document: DocumentRecord) {
    if (versionsFor === document.id) {
      setVersionsFor(null);
      return;
    }
    setError(null);
    try {
      const history = await api.documentVersions(document.id);
      setVersions(history);
      setVersionsFor(document.id);
    } catch (caught) {
      setError(describe(caught));
    }
  }

  return (
    <section className="panel" aria-label="Document library">
      <h3 className="panel__heading">Document library ({documents.length})</h3>

      <label className="field">
        <span className="field__label">
          Upload a document (PDF, Markdown, text, DOCX, HTML or CSV)
        </span>
        <input
          type="file"
          onChange={(event) => upload(event.target.files)}
          disabled={busy !== null}
        />
      </label>

      {error ? (
        <div className="notice notice--danger" role="alert">
          <strong>That did not work.</strong>
          <span>{error}</span>
        </div>
      ) : null}

      {notice ? (
        <div className="notice notice--muted" role="status">
          <span>{notice}</span>
        </div>
      ) : null}

      {documents.length === 0 ? (
        <p className="panel__empty">Nothing is indexed yet.</p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Title</th>
              <th scope="col">Collection</th>
              <th scope="col">Version</th>
              <th scope="col">Source</th>
              <th scope="col">Chunks</th>
              <th scope="col">Actions</th>
            </tr>
          </thead>
          <tbody>
            {documents.map((document) => (
              <tr key={document.id}>
                <td>{document.title}</td>
                <td>{document.collection}</td>
                <td>
                  v{document.version}
                  {document.supersedes_document_id ? (
                    <span className="tag tag--muted"> replaced</span>
                  ) : null}
                </td>
                <td className="table__uri">{document.source_uri}</td>
                <td>{document.chunk_count}</td>
                <td className="table__actions">
                  <button
                    type="button"
                    className="button button--quiet"
                    onClick={() => void showVersions(document)}
                    aria-expanded={versionsFor === document.id}
                  >
                    History
                  </button>
                  <label className="button button--quiet">
                    Replace
                    <input
                      type="file"
                      className="visually-hidden"
                      onChange={(event) => replace(document, event.target.files)}
                      disabled={busy !== null}
                    />
                  </label>
                  <button
                    type="button"
                    className="button button--quiet"
                    onClick={() => remove(document)}
                    disabled={busy !== null}
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {versionsFor ? (
        <section aria-label="Version history">
          <h4 className="panel__heading">Version history</h4>
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Version</th>
                <th scope="col">Status</th>
                <th scope="col">Checksum</th>
                <th scope="col">Chunks</th>
              </tr>
            </thead>
            <tbody>
              {versions.map((version) => (
                <tr key={version.id}>
                  <td>v{version.version}</td>
                  <td>
                    <span
                      className={`tag tag--${
                        version.status === "indexed" ? "positive" : "muted"
                      }`}
                    >
                      {version.status}
                    </span>
                  </td>
                  <td className="table__uri">{version.sha256.slice(0, 12)}</td>
                  <td>{version.chunk_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}
    </section>
  );
}
