const state = {
  documents: [],
  sources: [],
  selectedCollections: new Set([
    "Customer contracts",
    "Billing & renewals",
    "Security & compliance",
    "People operations",
  ]),
  health: null,
};

const preparedQuestions = {
  cancel:
    "Can an enterprise customer cancel during the committed term, and who approves an exception under 50,000 USD?",
  security: "What process applies after a serious security incident affects a contract?",
  refund: "When is an unused annual plan eligible for a refund?",
};

const elements = {
  chatView: document.querySelector("#chat-view"),
  libraryView: document.querySelector("#library-view"),
  viewTitle: document.querySelector("#view-title"),
  answer: document.querySelector("#answer"),
  retrievalState: document.querySelector("#retrieval-state"),
  userQuestion: document.querySelector("#user-question"),
  answerMeta: document.querySelector("#answer-meta"),
  requestError: document.querySelector("#request-error"),
  questionInput: document.querySelector("#question-input"),
  sendQuestion: document.querySelector("#send-question"),
  copyAnswer: document.querySelector("#copy-answer"),
  sourceCards: document.querySelector("#source-cards"),
  passageCard: document.querySelector("#passage-card"),
  passageTitle: document.querySelector("#passage-title"),
  passageText: document.querySelector("#passage-text"),
  passageCollection: document.querySelector("#passage-collection"),
  coverageLabel: document.querySelector("#coverage-label"),
  sourceCount: document.querySelector("#source-count"),
  generationMode: document.querySelector("#generation-mode"),
  latencyValue: document.querySelector("#latency-value"),
  retrievalStatus: document.querySelector("#retrieval-status"),
  retrievalProfile: document.querySelector("#retrieval-profile"),
  traceProfile: document.querySelector("#trace-profile"),
  fusionMode: document.querySelector("#fusion-mode"),
  candidatesCount: document.querySelector("#candidates-count"),
  retrievalLatency: document.querySelector("#retrieval-latency"),
  rerankLatency: document.querySelector("#rerank-latency"),
  addDocument: document.querySelector("#add-document"),
  composerUpload: document.querySelector("#composer-upload"),
  documentUpload: document.querySelector("#document-upload"),
  uploadCollection: document.querySelector("#upload-collection"),
  documentList: document.querySelector("#document-list"),
  documentSearch: document.querySelector("#document-search"),
  documentCount: document.querySelector("#document-count"),
  navDocumentCount: document.querySelector("#nav-document-count"),
  sidebarDocumentCount: document.querySelector("#sidebar-document-count"),
  chunkCount: document.querySelector("#chunk-count"),
  healthLabel: document.querySelector("#health-label"),
  providerLabel: document.querySelector("#provider-label"),
  embeddingLabel: document.querySelector("#embedding-label"),
  generationLabel: document.querySelector("#generation-label"),
  selectedCollectionCount: document.querySelector("#selected-collection-count"),
  scopeLabel: document.querySelector("#scope-label"),
  toast: document.querySelector("#toast"),
  toastTitle: document.querySelector("#toast-title"),
  toastMessage: document.querySelector("#toast-message"),
};

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (response.ok) {
    if (response.status === 204) return null;
    return response.json();
  }
  let message = `Request failed (${response.status})`;
  try {
    const payload = await response.json();
    message = payload.detail || message;
  } catch {
    // The status code remains a useful error if the response was not JSON.
  }
  throw new Error(message);
}

function setView(view) {
  const showLibrary = view === "library";
  elements.chatView.hidden = showLibrary;
  elements.libraryView.hidden = !showLibrary;
  elements.viewTitle.textContent = showLibrary ? "Source library" : "Research company knowledge";
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
}

function showToast(title, message, isError = false) {
  elements.toast.classList.toggle("error", isError);
  elements.toastTitle.textContent = title;
  elements.toastMessage.textContent = message;
  elements.toast.classList.add("show");
  window.setTimeout(() => elements.toast.classList.remove("show"), 3500);
}

function formatBytes(size) {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(value) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}

function collectionClass(collection) {
  if (collection.startsWith("Customer")) return "indigo-pill";
  if (collection.startsWith("Billing")) return "cyan-pill";
  if (collection.startsWith("Security")) return "amber-pill";
  return "green-pill";
}

function fileType(filename) {
  const extension = filename.split(".").pop().toUpperCase();
  return extension === "MD" ? "TXT" : extension;
}

function createElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function renderDocuments() {
  const query = elements.documentSearch.value.trim().toLowerCase();
  const documents = state.documents.filter((document) => {
    return `${document.title} ${document.filename} ${document.collection}`
      .toLowerCase()
      .includes(query);
  });
  elements.documentList.replaceChildren();
  if (!documents.length) {
    elements.documentList.append(
      createElement("div", "document-empty", query ? "No documents match this search." : "No documents indexed."),
    );
    return;
  }

  documents.forEach((document) => {
    const row = createElement("div", "document-row");
    row.dataset.documentId = document.id;

    const nameCell = createElement("span", "document-name");
    const icon = createElement("i", "file-icon doc", fileType(document.filename));
    const nameText = createElement("span");
    nameText.append(
      createElement("strong", "", document.title),
      createElement("small", "", `${formatBytes(document.size_bytes)} · ${document.filename}`),
    );
    nameCell.append(icon, nameText);

    const collectionCell = createElement("span");
    collectionCell.append(
      createElement(
        "span",
        `collection-pill ${collectionClass(document.collection)}`,
        document.collection,
      ),
    );

    const chunkCell = createElement("span", "chunk-value", String(document.chunk_count));
    const dateCell = createElement("span", "", formatDate(document.created_at));
    const statusCell = createElement("span");
    statusCell.append(createElement("span", "status-pill indexed", "✓ Indexed"));

    const actions = createElement("span");
    const remove = createElement("button", "delete-document", "Delete");
    remove.type = "button";
    remove.dataset.deleteDocument = document.id;
    remove.setAttribute("aria-label", `Delete ${document.title}`);
    actions.append(remove);

    row.append(nameCell, collectionCell, chunkCell, dateCell, statusCell, actions);
    elements.documentList.append(row);
  });
}

function updateDocumentMetrics() {
  const count = state.documents.length;
  const chunks = state.documents.reduce((total, document) => total + document.chunk_count, 0);
  elements.documentCount.textContent = String(count);
  elements.navDocumentCount.textContent = String(count);
  elements.sidebarDocumentCount.textContent = `${count} document${count === 1 ? "" : "s"}`;
  elements.chunkCount.textContent = String(chunks);
}

async function loadDocuments() {
  state.documents = await api("/api/documents");
  updateDocumentMetrics();
  renderDocuments();
}

async function loadHealth() {
  try {
    state.health = await api("/api/health");
    elements.healthLabel.textContent = "Knowledge base healthy";
    elements.providerLabel.textContent =
      `${state.health.embedding_provider} retrieval · ${state.health.chunking_profile} chunks · ${state.health.generation_provider} answers`;
    elements.embeddingLabel.textContent = state.health.embedding_provider;
    elements.generationLabel.textContent = state.health.generation_provider;
  } catch (error) {
    elements.healthLabel.textContent = "API unavailable";
    elements.providerLabel.textContent = error.message;
    throw error;
  }
}

function updateScope() {
  const count = state.selectedCollections.size;
  elements.selectedCollectionCount.textContent = `${count} active`;
  elements.scopeLabel.textContent = `${count} collection${count === 1 ? "" : "s"} selected`;
}

function renderAnswerText(answer) {
  elements.answer.replaceChildren();
  answer.split(/\n{2,}/).forEach((paragraph) => {
    const node = createElement("p");
    const parts = paragraph.split(/(\[\d+])/g);
    parts.forEach((part) => {
      const citation = part.match(/^\[(\d+)]$/);
      if (!citation) {
        node.append(document.createTextNode(part));
        return;
      }
      const rank = Number(citation[1]);
      const button = createElement("button", "citation", String(rank));
      button.type = "button";
      button.dataset.sourceRank = String(rank);
      button.addEventListener("click", () => selectSource(rank));
      node.append(button);
    });
    elements.answer.append(node);
  });
}

function renderSources() {
  elements.sourceCards.replaceChildren();
  if (!state.sources.length) {
    elements.sourceCards.append(
      createElement("div", "source-empty", "No relevant passages were returned."),
    );
    elements.passageCard.hidden = true;
    return;
  }
  state.sources.forEach((source) => {
    const card = createElement("button", "source-card");
    card.type = "button";
    card.dataset.sourceRank = String(source.rank);
    const top = createElement("div", "source-top");
    top.append(createElement("span", "file-icon doc", fileType(source.filename)));
    const text = createElement("div");
    text.append(
      createElement("strong", "", source.title),
      createElement(
        "small",
        "",
        `${source.page ? `Page ${source.page}` : "Text source"} · ${source.collection}`,
      ),
    );
    const rankScore =
      source.rerank_score === null
        ? `F ${source.score.toFixed(3)}`
        : `R ${source.rerank_score.toFixed(2)}`;
    top.append(text, createElement("span", "match", rankScore));
    card.append(top, createElement("p", "", source.passage.slice(0, 120)));
    card.addEventListener("click", () => selectSource(source.rank));
    elements.sourceCards.append(card);
  });
  selectSource(1);
}

function selectSource(rank) {
  const source = state.sources.find((candidate) => candidate.rank === rank);
  if (!source) return;
  document.querySelectorAll("[data-source-rank]").forEach((element) => {
    element.classList.toggle("active", Number(element.dataset.sourceRank) === rank);
  });
  elements.passageCard.hidden = false;
  elements.passageTitle.textContent =
    `${source.title}${source.page ? ` · page ${source.page}` : ""}`;
  elements.passageText.textContent = source.passage;
  elements.passageCollection.textContent = source.collection;
}

function setQueryLoading(question) {
  elements.userQuestion.classList.remove("empty-question");
  elements.userQuestion.textContent = question;
  elements.answer.hidden = true;
  elements.requestError.hidden = true;
  elements.retrievalState.hidden = false;
  elements.answerMeta.textContent = "Searching indexed sources…";
  elements.retrievalStatus.textContent = "Searching";
  elements.traceProfile.textContent = elements.retrievalProfile.value;
  elements.fusionMode.textContent = "running";
  elements.candidatesCount.textContent = "—";
  elements.retrievalLatency.textContent = "—";
  elements.rerankLatency.textContent = "—";
  elements.sendQuestion.disabled = true;
  elements.copyAnswer.disabled = true;
}

function setQueryError(error) {
  elements.retrievalState.hidden = true;
  elements.answer.hidden = false;
  elements.answer.className = "answer empty-state";
  elements.answer.replaceChildren(
    createElement("strong", "", "The request could not be completed"),
    createElement("p", "", "Check that the API is running, then try again."),
  );
  elements.requestError.textContent = error.message;
  elements.requestError.hidden = false;
  elements.answerMeta.textContent = "Request failed";
  elements.retrievalStatus.textContent = "Failed";
}

async function ask(question) {
  const normalized = question.trim();
  if (normalized.length < 3 || elements.sendQuestion.disabled) return;
  setView("chat");
  setQueryLoading(normalized);
  try {
    const payload = await api("/api/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question: normalized,
        collections: [...state.selectedCollections],
        retrieval_profile: elements.retrievalProfile.value,
      }),
    });
    state.sources = payload.sources;
    elements.retrievalState.hidden = true;
    elements.answer.hidden = false;
    elements.answer.className = "answer";
    renderAnswerText(payload.answer);
    renderSources();
    elements.answerMeta.textContent =
      `${payload.sources.length} sources · ${payload.generation_mode} mode`;
    elements.coverageLabel.textContent =
      `${payload.sources.length} source${payload.sources.length === 1 ? "" : "s"}`;
    elements.sourceCount.textContent = String(payload.sources.length);
    elements.generationMode.textContent = payload.generation_mode;
    elements.latencyValue.textContent = `${payload.latency_ms} ms`;
    elements.traceProfile.textContent = payload.retrieval.profile;
    elements.fusionMode.textContent = payload.retrieval.fusion || "none";
    elements.candidatesCount.textContent = String(payload.retrieval.candidates_considered);
    elements.retrievalLatency.textContent = `${payload.retrieval.retrieval_ms} ms`;
    const rerankerLabel =
      payload.retrieval.reranker === "colbert-late-interaction"
        ? "ColBERT MaxSim"
        : payload.retrieval.reranker === "cross-encoder"
          ? "Cross-encoder"
          : payload.retrieval.reranker;
    elements.rerankLatency.textContent = rerankerLabel
      ? `${rerankerLabel} · ${payload.retrieval.rerank_ms} ms`
      : "not run";
    elements.retrievalStatus.textContent = payload.sources.length ? "Retrieved" : "No match";
    elements.copyAnswer.disabled = false;
  } catch (error) {
    setQueryError(error);
  } finally {
    elements.sendQuestion.disabled = false;
  }
}

async function uploadSelectedDocument() {
  const [file] = elements.documentUpload.files;
  if (!file) return;
  const collection = elements.uploadCollection.value;
  const body = new FormData();
  body.append("file", file);
  body.append("collection", collection);
  elements.addDocument.disabled = true;
  elements.addDocument.textContent = "Indexing…";
  try {
    const document = await api("/api/documents", { method: "POST", body });
    await loadDocuments();
    showToast("Document indexed", `${document.filename} is ready for retrieval.`);
  } catch (error) {
    showToast("Upload failed", error.message, true);
  } finally {
    elements.addDocument.disabled = false;
    elements.addDocument.textContent = "＋ Add document";
    elements.documentUpload.value = "";
  }
}

async function deleteDocument(documentId) {
  const document = state.documents.find((candidate) => candidate.id === documentId);
  if (!document) return;
  if (!window.confirm(`Delete ${document.title} from this local index?`)) return;
  try {
    await api(`/api/documents/${documentId}`, { method: "DELETE" });
    await loadDocuments();
    showToast("Document removed", `${document.filename} was removed from the index.`);
  } catch (error) {
    showToast("Delete failed", error.message, true);
  }
}

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.view));
});

document.querySelectorAll("[data-question]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll("[data-question]").forEach((candidate) => {
      candidate.classList.toggle("selected", candidate === button);
    });
    const question = preparedQuestions[button.dataset.question];
    elements.questionInput.value = question;
    ask(question);
  });
});

document.querySelectorAll("[data-collection]").forEach((button) => {
  button.addEventListener("click", () => {
    const collection = button.dataset.collection;
    if (state.selectedCollections.has(collection) && state.selectedCollections.size === 1) {
      showToast("Keep one collection active", "Questions need at least one collection to search.", true);
      return;
    }
    if (state.selectedCollections.has(collection)) {
      state.selectedCollections.delete(collection);
    } else {
      state.selectedCollections.add(collection);
    }
    button.classList.toggle("active", state.selectedCollections.has(collection));
    updateScope();
  });
});

elements.sendQuestion.addEventListener("click", () => ask(elements.questionInput.value));
elements.questionInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    ask(elements.questionInput.value);
  }
});
elements.copyAnswer.addEventListener("click", async () => {
  await navigator.clipboard.writeText(elements.answer.textContent.trim());
  showToast("Answer copied", "The grounded answer was copied to the clipboard.");
});
elements.addDocument.addEventListener("click", () => elements.documentUpload.click());
elements.composerUpload.addEventListener("click", () => {
  setView("library");
  elements.documentUpload.click();
});
elements.documentUpload.addEventListener("change", uploadSelectedDocument);
elements.documentSearch.addEventListener("input", renderDocuments);
elements.documentList.addEventListener("click", (event) => {
  const button = event.target.closest("[data-delete-document]");
  if (button) deleteDocument(button.dataset.deleteDocument);
});

async function initialize() {
  updateScope();
  try {
    await Promise.all([loadHealth(), loadDocuments()]);
  } catch (error) {
    elements.documentList.replaceChildren(
      createElement("div", "document-empty error-text", `API unavailable: ${error.message}`),
    );
    showToast("API unavailable", "Start the FastAPI service and reload the page.", true);
  }
}

initialize();
