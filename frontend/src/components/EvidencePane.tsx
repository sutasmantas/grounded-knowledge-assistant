import type { SourceResult } from "../api/types";

interface Props {
  sources: SourceResult[];
  activeCitation: number | null;
  onCitationSelect: (rank: number) => void;
  /** Narrow viewports present this as a bottom sheet rather than a column, so
   *  it must not permanently occupy space the answer needs. */
  sheetOpen: boolean;
  onCloseSheet: () => void;
}

const FLAG_LABELS: Record<string, string> = {
  instruction_override: "Embedded instruction",
  secret_exfiltration: "Secret extraction attempt",
  remote_content: "Remote content reference",
};

export function EvidencePane({
  sources,
  activeCitation,
  onCitationSelect,
  sheetOpen,
  onCloseSheet,
}: Props) {
  const className = `evidence${sheetOpen ? " evidence--open" : ""}`;

  if (sources.length === 0) {
    return (
      <aside className={className} aria-label="Evidence">
        <h2 className="evidence__heading">Evidence</h2>
        <p className="evidence__empty">
          Sources appear here once a question returns supporting passages.
        </p>
      </aside>
    );
  }

  return (
    <aside className={className} aria-label="Evidence">
      <h2 className="evidence__heading">
        Evidence <span className="evidence__count">{sources.length}</span>
        <button
          type="button"
          className="button button--quiet evidence__close"
          onClick={onCloseSheet}
        >
          Close
        </button>
      </h2>
      <ol className="evidence__list">
        {sources.map((source) => {
          const active = activeCitation === source.rank;
          return (
            <li key={source.chunk_id}>
              <article
                className={`source${active ? " source--active" : ""}`}
                id={`source-${source.rank}`}
              >
                <header className="source__header">
                  <button
                    type="button"
                    className="source__rank"
                    onClick={() => onCitationSelect(source.rank)}
                    aria-label={`Highlight source ${source.rank}`}
                  >
                    {source.rank}
                  </button>
                  <span className="source__title">{source.title}</span>
                  <span className="source__score">{source.score.toFixed(3)}</span>
                </header>

                <p className="source__passage">{source.passage}</p>

                <dl className="source__meta">
                  <div>
                    <dt>Source</dt>
                    <dd className="source__uri">{source.source_uri || "—"}</dd>
                  </div>
                  <div>
                    <dt>Version</dt>
                    <dd>v{source.document_version}</dd>
                  </div>
                  <div>
                    <dt>Checksum</dt>
                    <dd className="source__checksum">
                      {source.document_sha256.slice(0, 12) || "—"}
                    </dd>
                  </div>
                  {source.page !== null ? (
                    <div>
                      <dt>Page</dt>
                      <dd>{source.page}</dd>
                    </div>
                  ) : null}
                </dl>

                {source.security_flags.length > 0 ? (
                  <ul className="source__flags">
                    {source.security_flags.map((flag) => (
                      <li key={flag} className="flag">
                        {FLAG_LABELS[flag] ?? flag}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </article>
            </li>
          );
        })}
      </ol>
    </aside>
  );
}
