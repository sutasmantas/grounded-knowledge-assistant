import type { RetrievalProfile } from "../api/types";

export interface PreparedCase {
  id: string;
  label: string;
  hint: string;
  question: string;
}

export const PREPARED_CASES: PreparedCase[] = [
  {
    id: "cancel",
    label: "Contract cancellation",
    hint: "Terms, notice and approvals",
    question:
      "Can enterprise customers cancel mid-contract, and what approval is required?",
  },
  {
    id: "security",
    label: "Security incident remedy",
    hint: "Cross-policy reasoning",
    question:
      "What remedies apply after a confirmed security incident affecting customer data?",
  },
  {
    id: "refund",
    label: "Annual plan refund",
    hint: "Eligibility and routing",
    question: "Is an annual plan refundable, and who approves the exception?",
  },
  {
    id: "unanswerable",
    label: "Deliberately unanswerable",
    hint: "Proves abstention",
    // Verified to return zero sources against the seeded corpus. Questions
    // that merely sound off-topic ("office parking policy") still match
    // lexically on "policy" and do not abstain.
    question: "How do I repair a bicycle derailleur?",
  },
];

const PROFILES: Array<{ value: RetrievalProfile; label: string }> = [
  { value: "sparse", label: "Sparse lexical · measured default" },
  { value: "hybrid", label: "Hybrid · dense + lexical" },
  { value: "hybrid-reranked", label: "Hybrid + late reranking" },
  { value: "dense", label: "Dense baseline" },
];

export interface WorkspaceSummary {
  scope: string;
  documents: number | null;
  embeddingProvider: string | null;
  generationProvider: string | null;
}

interface Props {
  collapsed: boolean;
  workspace: WorkspaceSummary;
  profile: RetrievalProfile;
  onProfileChange: (profile: RetrievalProfile) => void;
  collections: string[];
  selectedCollections: string[];
  onCollectionsChange: (collections: string[]) => void;
  onPreparedCase: (question: string) => void;
  busy: boolean;
}

export function QueryRail({
  collapsed,
  workspace,
  profile,
  onProfileChange,
  collections,
  selectedCollections,
  onCollectionsChange,
  onPreparedCase,
  busy,
}: Props) {
  function toggleCollection(name: string) {
    onCollectionsChange(
      selectedCollections.includes(name)
        ? selectedCollections.filter((item) => item !== name)
        : [...selectedCollections, name],
    );
  }

  return (
    <aside
      id="query-rail"
      className={`rail${collapsed ? " rail--collapsed" : ""}`}
      aria-label="Query setup"
      hidden={collapsed}
    >
      {/* The header drops scope and provider mode below 720px. They belong
        * somewhere reachable rather than nowhere, so the rail carries them at
        * every width. */}
      <section className="rail__section">
        <h2 className="rail__heading">Workspace</h2>
        <dl className="rail__summary">
          <div>
            <dt>Scope</dt>
            <dd>{workspace.scope}</dd>
          </div>
          <div>
            <dt>Indexed</dt>
            <dd>
              {workspace.documents === null
                ? "unknown"
                : `${workspace.documents} documents`}
            </dd>
          </div>
          <div>
            <dt>Providers</dt>
            <dd className="rail__providers">
              {workspace.embeddingProvider && workspace.generationProvider
                ? `${workspace.embeddingProvider} · ${workspace.generationProvider}`
                : "connecting"}
            </dd>
          </div>
        </dl>
      </section>

      <section className="rail__section">
        <h2 className="rail__heading">Prepared cases</h2>
        <p className="rail__copy">
          Each case exercises a different retrieval behaviour, including one that
          should refuse to answer.
        </p>
        <ul className="rail__cases">
          {PREPARED_CASES.map((prepared) => (
            <li key={prepared.id}>
              <button
                type="button"
                className="case"
                onClick={() => onPreparedCase(prepared.question)}
                disabled={busy}
              >
                <strong>{prepared.label}</strong>
                <small>{prepared.hint}</small>
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="rail__section">
        <h2 className="rail__heading">Retrieval profile</h2>
        <label className="field">
          <span className="field__label">Profile</span>
          <select
            value={profile}
            onChange={(event) =>
              onProfileChange(event.target.value as RetrievalProfile)
            }
            disabled={busy}
          >
            {PROFILES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </section>

      <section className="rail__section">
        <h2 className="rail__heading">Collections</h2>
        {collections.length === 0 ? (
          <p className="rail__copy rail__copy--empty">
            No collections indexed yet.
          </p>
        ) : (
          <ul className="rail__collections">
            {collections.map((name) => {
              const active =
                selectedCollections.length === 0 ||
                selectedCollections.includes(name);
              return (
                <li key={name}>
                  <button
                    type="button"
                    className={`pill${active ? " pill--active" : ""}`}
                    aria-pressed={active}
                    onClick={() => toggleCollection(name)}
                    disabled={busy}
                  >
                    {name}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </aside>
  );
}
