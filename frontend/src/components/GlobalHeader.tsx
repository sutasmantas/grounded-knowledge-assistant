import type { HealthResponse } from "../api/types";

export type View = "research" | "sources";

interface Props {
  health: HealthResponse | null;
  healthError: string | null;
  onToggleRail: () => void;
  railCollapsed: boolean;
  view: View;
  onViewChange: (view: View) => void;
}

/** Compact global header: workspace, retrieval scope, index health, provider.
 *  Deliberately not a navigation sidebar — the research view has no permanent
 *  left navigation. */
export function GlobalHeader({
  health,
  healthError,
  onToggleRail,
  railCollapsed,
  view,
  onViewChange,
}: Props) {
  const state = healthError ? "error" : health ? "ok" : "loading";
  const label =
    state === "error" ? "Index unavailable" : state === "ok" ? "Index healthy" : "Connecting";

  return (
    <header className="header">
      <button
        type="button"
        className="header__rail-toggle"
        onClick={onToggleRail}
        aria-expanded={!railCollapsed}
        aria-controls="query-rail"
      >
        <span aria-hidden="true">{railCollapsed ? "»" : "«"}</span>
        <span className="visually-hidden">
          {railCollapsed ? "Show the query rail" : "Hide the query rail"}
        </span>
      </button>

      <div className="header__brand">
        <span className="header__mark" aria-hidden="true">
          A
        </span>
        <span className="header__names">
          <strong>Atlas</strong>
          <small>Retrieval workbench</small>
        </span>
      </div>

      {/* Compact top-level switch, not a persistent navigation sidebar. */}
      <nav className="header__views" aria-label="Views">
        {(["research", "sources"] as const).map((candidate) => (
          <button
            key={candidate}
            type="button"
            className={`view-tab${view === candidate ? " view-tab--active" : ""}`}
            aria-current={view === candidate ? "page" : undefined}
            onClick={() => onViewChange(candidate)}
          >
            {candidate === "research" ? "Research" : "Sources"}
          </button>
        ))}
      </nav>

      <span className="header__scope" title="Retrieval scope">
        Northstar policy workspace
      </span>

      <span className={`chip chip--${state}`}>
        <span className="chip__dot" aria-hidden="true" />
        <span>
          {label}
          {health ? ` · ${health.documents} documents` : ""}
        </span>
      </span>

      {health ? (
        <span className="header__providers">
          {health.embedding_provider} · {health.generation_provider}
        </span>
      ) : null}
    </header>
  );
}
