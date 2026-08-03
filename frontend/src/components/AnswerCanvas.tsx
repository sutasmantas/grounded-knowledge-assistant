import type { QueryResponse } from "../api/types";
import { PREPARED_CASES } from "./QueryRail";

interface Props {
  question: string;
  onQuestionChange: (question: string) => void;
  onSubmit: () => void;
  busy: boolean;
  result: QueryResponse | null;
  error: string | null;
  activeCitation: number | null;
  onCitationSelect: (rank: number) => void;
  onPreparedCase: (question: string) => void;
  /** Partial answer while a stream is in flight; null once the trace lands. */
  streamingAnswer: string | null;
  /** Atlas disowned the finished answer. It stays visible but must be marked,
   *  because a silently-kept ungrounded answer is worse than a visible one. */
  retracted: string | null;
  streaming: boolean;
  onStreamingChange: (streaming: boolean) => void;
}

/** Splits an answer into text and citation markers so `[1]` becomes a control
 *  that selects the matching source instead of inert punctuation. */
function renderAnswer(
  answer: string,
  activeCitation: number | null,
  onCitationSelect: (rank: number) => void,
) {
  const parts = answer.split(/(\[\d+\])/g);
  return parts.map((part, index) => {
    const match = /^\[(\d+)\]$/.exec(part);
    if (!match?.[1]) {
      return <span key={index}>{part}</span>;
    }
    const rank = Number(match[1]);
    return (
      <button
        key={index}
        type="button"
        className={`citation${activeCitation === rank ? " citation--active" : ""}`}
        onClick={() => onCitationSelect(rank)}
        aria-label={`Show evidence for source ${rank}`}
      >
        {rank}
      </button>
    );
  });
}

export function AnswerCanvas({
  question,
  onQuestionChange,
  onSubmit,
  busy,
  result,
  error,
  activeCitation,
  onCitationSelect,
  onPreparedCase,
  streamingAnswer,
  retracted,
  streaming,
  onStreamingChange,
}: Props) {
  const abstained =
    result !== null && result.sources.length === 0 && streamingAnswer === null;
  const settled = !busy && result !== null && streamingAnswer === null;

  return (
    <section className="canvas" aria-label="Answer">
      <form
        className="composer"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
      >
        <label className="visually-hidden" htmlFor="question">
          Question
        </label>
        <textarea
          id="question"
          className="composer__input"
          value={question}
          placeholder="Ask a policy question…"
          rows={2}
          onChange={(event) => onQuestionChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              onSubmit();
            }
          }}
        />
        <button
          type="submit"
          className="button button--primary"
          disabled={busy || question.trim().length < 3}
        >
          {busy ? "Retrieving…" : "Ask"}
        </button>
      </form>

      <label className="composer__option">
        <input
          type="checkbox"
          checked={streaming}
          onChange={(event) => onStreamingChange(event.target.checked)}
          disabled={busy}
        />
        <span>
          Stream the answer — evidence appears as soon as retrieval finishes.
          Unstreamed requests refuse an ungrounded answer before it is shown;
          streamed ones can only retract it afterwards.
        </span>
      </label>

      {error ? (
        <div className="notice notice--danger" role="alert">
          <strong>The request failed.</strong>
          <span>{error}</span>
        </div>
      ) : null}

      {streamingAnswer !== null ? (
        <article className="answer" aria-live="polite" aria-busy="true">
          {renderAnswer(streamingAnswer, activeCitation, onCitationSelect)}
          <span className="answer__cursor" aria-hidden="true" />
        </article>
      ) : null}

      {busy && streamingAnswer === null && result === null ? (
        <div className="answer answer--loading" aria-busy="true">
          <span className="skeleton skeleton--line" />
          <span className="skeleton skeleton--line" />
          <span className="skeleton skeleton--line skeleton--short" />
        </div>
      ) : null}

      {retracted ? (
        <div className="notice notice--danger" role="alert">
          <strong>This answer was retracted.</strong>
          <span>
            {retracted} It is left on screen so you can see what was produced,
            but Atlas does not consider it grounded in the cited sources.
          </span>
        </div>
      ) : null}

      {!busy && !result && !error && streamingAnswer === null ? (
        <div className="empty">
          <h2>Ask company knowledge and inspect the evidence.</h2>
          <p>
            Every answer cites the exact source URI, document version and
            checksum it used. Start with a prepared case:
          </p>
          <ul className="empty__cases">
            {PREPARED_CASES.slice(0, 3).map((prepared) => (
              <li key={prepared.id}>
                <button
                  type="button"
                  className="button"
                  onClick={() => onPreparedCase(prepared.question)}
                >
                  {prepared.label}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {settled ? (
        abstained ? (
          <div className="notice notice--muted" role="status">
            <strong>No supporting evidence was found.</strong>
            <span>
              Atlas refused rather than answering from an unsupported guess. This
              is the expected behaviour for an out-of-corpus question.
            </span>
          </div>
        ) : result.answer ? (
          <article className={`answer${retracted ? " answer--retracted" : ""}`}>
            {renderAnswer(result.answer, activeCitation, onCitationSelect)}
          </article>
        ) : null
      ) : null}
    </section>
  );
}
