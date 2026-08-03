import * as Dialog from "@radix-ui/react-dialog";

import type { GenerationTrace, RetrievalTrace } from "../api/types";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  retrieval: RetrievalTrace | null;
  generation: GenerationTrace | null;
  latencyMs: number | null;
}

/** Token counts are null whenever the provider did not report usage. Rendering
 *  a zero would read as "this was free", which is exactly the wrong thing to
 *  tell someone reading a cost figure. */
function tokens(value: number | null): string {
  return value === null ? "not reported" : value.toLocaleString();
}

/** Radix Dialog rather than a hand-rolled panel: it supplies the focus trap,
 *  focus restore, escape-to-close and `aria-modal` semantics that the first
 *  version got wrong. Native form controls elsewhere are left alone, because a
 *  native `select` is more accessible than a custom one, not less. */
export function TraceDrawer({
  open,
  onOpenChange,
  retrieval,
  generation,
  latencyMs,
}: Props) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Content className="drawer" aria-describedby={undefined}>
          <header className="drawer__header">
            <Dialog.Title className="drawer__title">Execution trace</Dialog.Title>
            <Dialog.Close asChild>
              <button type="button" className="button button--quiet">
                Close
              </button>
            </Dialog.Close>
          </header>

          <div className="drawer__body">
            <section>
              <h3 className="drawer__heading">Retrieval</h3>
              {retrieval ? (
                <dl className="trace">
                  <div>
                    <dt>Profile</dt>
                    <dd>{retrieval.profile}</dd>
                  </div>
                  <div>
                    <dt>Fusion</dt>
                    <dd>{retrieval.fusion ?? "none"}</dd>
                  </div>
                  <div>
                    <dt>Reranker</dt>
                    <dd>{retrieval.reranker ?? "none"}</dd>
                  </div>
                  <div>
                    <dt>Candidates</dt>
                    <dd>
                      {retrieval.candidates_considered} of{" "}
                      {retrieval.candidate_limit}
                    </dd>
                  </div>
                  <div>
                    <dt>Retrieval</dt>
                    <dd>{retrieval.retrieval_ms} ms</dd>
                  </div>
                  <div>
                    <dt>Rerank</dt>
                    <dd>{retrieval.rerank_ms} ms</dd>
                  </div>
                </dl>
              ) : (
                <p className="drawer__empty">Ask a question to record a trace.</p>
              )}
            </section>

            <section>
              <h3 className="drawer__heading">Generation cost</h3>
              {generation ? (
                <dl className="trace">
                  <div>
                    <dt>Provider</dt>
                    <dd>{generation.provider}</dd>
                  </div>
                  <div>
                    <dt>Context</dt>
                    <dd>
                      {generation.context_sources} sources ·{" "}
                      {generation.context_characters.toLocaleString()} chars
                    </dd>
                  </div>
                  <div>
                    <dt>Prompt tokens</dt>
                    <dd>{tokens(generation.prompt_tokens)}</dd>
                  </div>
                  <div>
                    <dt>Completion tokens</dt>
                    <dd>{tokens(generation.completion_tokens)}</dd>
                  </div>
                  <div>
                    <dt>Total tokens</dt>
                    <dd>{tokens(generation.total_tokens)}</dd>
                  </div>
                  <div>
                    <dt>Generation</dt>
                    <dd>{generation.generation_ms} ms</dd>
                  </div>
                  {latencyMs !== null ? (
                    <div>
                      <dt>End to end</dt>
                      <dd>{latencyMs} ms</dd>
                    </div>
                  ) : null}
                </dl>
              ) : (
                <p className="drawer__empty">Ask a question to record a trace.</p>
              )}
            </section>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
