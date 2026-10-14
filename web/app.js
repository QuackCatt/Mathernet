const state = {
  formulas: [],
  statusCounts: { all: 0, learning: 0, reviewed: 0 },
  selectedId: null,
  selectedCard: null,
  graph: null,
  health: null,
  query: "",
  status: "",
  depth: 1,
  tab: "overview",
  notesDirty: false,
  pendingRejectEdgeId: null,
  libraryRequest: 0,
  selectionRequest: 0,
  deepDiveRequest: 0,
  deepGenerationRequest: 0,
  deepDiveFormulaId: null,
  deepSessions: [],
  activeDeepSession: null,
  deepChatBusy: false,
  deepLoading: false,
  deepGenerating: false,
  introductions: {},
  introduction: null,
  introductionLoading: false,
  introductionError: "",
  introductionRequest: 0,
  gateway: null,
  firstRun: true,
};

const elements = {
  connection: document.querySelector("#connection-state"),
  connectionLabel: document.querySelector("#connection-label"),
  globalSearch: document.querySelector("#global-search"),
  globalQuery: document.querySelector("#global-query"),
  globalSubmit: document.querySelector("#global-submit"),
  libraryQuery: document.querySelector("#library-query"),
  formulaList: document.querySelector("#formula-list"),
  graphEmpty: document.querySelector("#graph-empty"),
  graphDescription: document.querySelector("#graph-description"),
  inspectorTitle: document.querySelector("#inspector-title"),
  inspectorStatus: document.querySelector("#inspector-status"),
  overviewEmpty: document.querySelector("#overview-empty"),
  overviewContent: document.querySelector("#overview-content"),
  learningEmpty: document.querySelector("#learning-empty"),
  learningContent: document.querySelector("#learning-content"),
  deepDiveDialog: document.querySelector("#deep-dive-dialog"),
  deepDiveTitle: document.querySelector("#deep-dive-title"),
  deepDiveFormula: document.querySelector("#deep-dive-formula"),
  deepDiveContent: document.querySelector("#deep-dive-content"),
  deepSessionNew: document.querySelector("#deep-session-new"),
  deepSessionNewLabel: document.querySelector("#deep-session-new-label"),
  deepSessionDelete: document.querySelector("#deep-session-delete"),
  deepSessionList: document.querySelector("#deep-session-list"),
  deepChatForm: document.querySelector("#deep-chat-form"),
  deepChatInput: document.querySelector("#deep-chat-input"),
  deepChatSubmit: document.querySelector("#deep-chat-submit"),
  deepChatStatus: document.querySelector("#deep-chat-status"),
  rejectDialog: document.querySelector("#reject-dialog"),
  confirmReject: document.querySelector("#confirm-reject"),
  toastRegion: document.querySelector("#toast-region"),
  themeToggle: document.querySelector("#theme-toggle"),
  settingsDialog: document.querySelector("#settings-dialog"),
  settingsForm: document.querySelector("#settings-form"),
  settingsProvider: document.querySelector("#settings-provider"),
  settingsApiKey: document.querySelector("#settings-api-key"),
  settingsModel: document.querySelector("#settings-model"),
  settingsError: document.querySelector("#settings-error"),
  settingsAiState: document.querySelector("#settings-ai-state"),
  settingsAiMessage: document.querySelector("#settings-ai-message"),
  settingsSave: document.querySelector("#settings-save"),
};

const statusLabels = {
  new: "New",
  learning: "Learning",
  reviewed: "Reviewed",
  needs_review: "Needs review",
};

const relationLabels = {
  prerequisite: "Prerequisite",
  derivation_basis: "Derivation basis",
  special_case: "Special case",
  generalization: "Generalization",
  equivalent_form: "Equivalent form",
};

const busyContent = new WeakMap();

class ApiError extends Error {
  constructor(message, code = "request_failed", status = 0, reasonCode = "") {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.reasonCode = reasonCode;
  }
}

function escapeHTML(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function truncate(value, length) {
  const text = String(value ?? "");
  return text.length > length ? `${text.slice(0, Math.max(1, length - 1))}…` : text;
}

function latexMarkup(value, fallback = "", displayMode = false) {
  const source = String(value || fallback || "").trim();
  if (!source) return "";
  if (window.katex) {
    try {
      return window.katex.renderToString(source, {
        displayMode,
        throwOnError: false,
        strict: "ignore",
        trust: false,
        output: "html",
      });
    } catch {
      return escapeHTML(source);
    }
  }
  return escapeHTML(source);
}

function richText(value) {
  const source = String(value || "").trim();
  if (!source) return "";
  return source
    .split(/(\$\$[\s\S]+?\$\$|\$[^$\n]+\$)/g)
    .map((part) => {
      if (part.startsWith("$$") && part.endsWith("$$")) {
        return latexMarkup(part.slice(2, -2), part.slice(2, -2), true);
      }
      if (part.startsWith("$") && part.endsWith("$")) {
        return latexMarkup(part.slice(1, -1), part.slice(1, -1), false);
      }
      return escapeHTML(part).replaceAll("\n", "<br>");
    })
    .join("");
}

function articleMarkup(value) {
  const blocks = [];
  let paragraph = [];
  let list = [];
  const source = String(value || "").replace(/\s+(#{2,6}\s+)/g, "\n\n$1");

  const flushParagraph = () => {
    if (!paragraph.length) return;
    blocks.push(`<p>${paragraph.map((line) => richText(line)).join("<br>")}</p>`);
    paragraph = [];
  };
  const flushList = () => {
    if (!list.length) return;
    blocks.push(`<ul>${list.map((line) => `<li>${richText(line)}</li>`).join("")}</ul>`);
    list = [];
  };
  const flushAll = () => {
    flushParagraph();
    flushList();
  };

  for (const rawLine of source.split(/\r?\n/)) {
    const line = rawLine.trim();
    const heading = line.match(/^(#{2,6})\s+(.+)$/);
    const listItem = line.match(/^[-*]\s+(.+)$/);
    if (!line) {
      flushAll();
    } else if (heading) {
      flushAll();
      const level = Math.min(6, Math.max(3, heading[1].length + 1));
      blocks.push(`<h${level}>${richText(heading[2])}</h${level}>`);
    } else if (listItem) {
      flushParagraph();
      list.push(listItem[1]);
    } else {
      flushList();
      paragraph.push(line);
    }
  }
  flushAll();
  return blocks.join("");
}

function deepArticleMarkup(article) {
  if (typeof article === "string") return articleMarkup(article);
  const introduction = article?.introduction || "";
  const sections = Array.isArray(article?.sections) ? article.sections : [];
  const kindLabels = {
    story: "Story",
    application: "Application",
    background: "Background",
    context: "Context",
    other: "Further reading",
  };
  return `
    ${introduction ? `<div class="deep-article-intro">${articleMarkup(introduction)}</div>` : ""}
    ${sections
      .map(
        (section) => `
          <section class="deep-article-section">
            <p class="deep-article-subtitle">${escapeHTML(section.subtitle || kindLabels[section.kind] || "Context")}</p>
            <h3>${escapeHTML(section.heading)}</h3>
            <div class="deep-article-section-body">${articleMarkup(section.body)}</div>
          </section>
        `,
      )
      .join("")}
  `;
}

function formulaValue(card) {
  return card?.formula?.latex || card?.display || "";
}

function safeUrl(value) {
  try {
    const url = new URL(String(value));
    return ["http:", "https:"].includes(url.protocol) ? url.href : "#";
  } catch {
    return "#";
  }
}

function formatDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value ?? "");
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function icon(name) {
  return `<svg aria-hidden="true"><use href="#icon-${name}"></use></svg>`;
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  let response;
  try {
    response = await fetch(path, { ...options, headers });
  } catch {
    throw new ApiError(
      "Mathernet cannot reach the local service. Start it again with scripts/mathernet serve.",
      "network_error",
    );
  }

  const raw = await response.text();
  let payload = {};
  if (raw) {
    try {
      payload = JSON.parse(raw);
    } catch {
      throw new ApiError("The local service returned an unreadable response.", "invalid_response", response.status);
    }
  }

  if (!response.ok) {
    const error = payload.error || {};
    throw new ApiError(
      error.message || "The request could not be completed.",
      error.code || "request_failed",
      response.status,
      error.reason_code || "",
    );
  }
  return payload;
}

function setBusy(element, busy, busyLabel) {
  if (!element) return;
  if (busy) {
    if (!busyContent.has(element)) busyContent.set(element, element.innerHTML);
    element.disabled = true;
    element.setAttribute("aria-busy", "true");
    element.innerHTML = `<span>${escapeHTML(busyLabel)}</span>`;
  } else {
    element.disabled = false;
    element.removeAttribute("aria-busy");
    if (busyContent.has(element)) {
      element.innerHTML = busyContent.get(element);
      busyContent.delete(element);
    }
  }
}

function showToast(message, type = "success") {
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.innerHTML = `
    <span class="toast-icon">${icon(type === "success" ? "check" : "alert")}</span>
    <p class="toast-message">${escapeHTML(message)}</p>
    <button class="toast-close" type="button" aria-label="Dismiss message">${icon("x")}</button>
  `;
  toast.querySelector(".toast-close").addEventListener("click", () => toast.remove());
  elements.toastRegion.append(toast);
  window.setTimeout(() => toast.remove(), 5200);
}

function setConnection(online, label) {
  elements.connection.classList.toggle("is-online", online);
  elements.connection.classList.toggle("is-offline", !online);
  elements.connectionLabel.textContent = label;
}

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("mathernet-theme", theme);
  const nextTheme = theme === "dark" ? "light" : "dark";
  elements.themeToggle.setAttribute("aria-label", `Use ${nextTheme} theme`);
}

function currentTheme() {
  const saved = localStorage.getItem("mathernet-theme");
  if (saved === "dark" || saved === "light") return saved;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function syncUrl() {
  const url = new URL(window.location.href);
  const setOrDelete = (key, value, defaultValue = "") => {
    if (value && String(value) !== String(defaultValue)) {
      url.searchParams.set(key, String(value));
    } else {
      url.searchParams.delete(key);
    }
  };
  setOrDelete("formula", state.selectedId);
  setOrDelete("tab", state.tab, "overview");
  setOrDelete("depth", state.depth, 1);
  setOrDelete("q", state.query);
  setOrDelete("status", state.status);
  window.history.replaceState({}, "", url);
}

function restoreUrlState() {
  const params = new URLSearchParams(window.location.search);
  const depth = Number(params.get("depth"));
  const tab = params.get("tab");
  state.query = params.get("q") || "";
  state.status = params.get("status") || "";
  state.depth = [1, 2].includes(depth) ? depth : 1;
  state.tab = ["overview", "learning"].includes(tab) ? tab : "overview";
  state.selectedId = params.get("formula");
  elements.libraryQuery.value = state.query;
  document.querySelectorAll(".library-controls [data-status]").forEach((button) => {
    const active = button.dataset.status === state.status;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  document.querySelectorAll("[data-depth]").forEach((button) => {
    const active = Number(button.dataset.depth) === state.depth;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

function renderLibrary() {
  document.querySelectorAll("[data-status-count]").forEach((element) => {
    const count = state.statusCounts[element.dataset.statusCount] ?? 0;
    element.textContent = `(${count})`;
  });
  elements.formulaList.setAttribute("aria-busy", "false");
  if (!state.formulas.length) {
    elements.formulaList.innerHTML = `
      <div class="list-empty">
        <h3>No formulas found</h3>
        <p>Use the search above to open an existing formula or learn a new one.</p>
      </div>
    `;
    return;
  }

  elements.formulaList.innerHTML = state.formulas
    .map((formula) => {
      const topic = formula.topic_tags[0] || "Mathematics";
      return `
        <button
          class="formula-row ${formula.id === state.selectedId ? "is-selected" : ""}"
          type="button"
          data-formula-id="${escapeHTML(formula.id)}"
          aria-pressed="${formula.id === state.selectedId}"
        >
          <span class="formula-row-title">${escapeHTML(formula.name)}</span>
          <span class="formula-row-meta">
            <span class="formula-row-topic">${escapeHTML(topic)}</span>
            <span aria-hidden="true">·</span>
            <span class="row-state" data-state="${escapeHTML(formula.status)}">${escapeHTML(statusLabels[formula.status] || formula.status)}</span>
          </span>
        </button>
      `;
    })
    .join("");
}

function renderGraph() {
  window.MathernetGraph?.render(state.graph, {
    onSelect: selectFormula,
    selectedId: state.selectedId,
  });
}

function renderOverview() {
  const card = state.selectedCard;
  if (!card) {
    elements.overviewEmpty.hidden = false;
    elements.overviewContent.hidden = true;
    elements.overviewContent.innerHTML = "";
    return;
  }
  const formula = card.formula;
  const introduction = state.introduction?.introduction || "";
  elements.overviewEmpty.hidden = true;
  elements.overviewContent.hidden = false;
  elements.overviewContent.innerHTML = `
    <section class="inspector-section">
      <span class="section-label">Formula</span>
      <div
        class="formula-display formula-latex"
        role="math"
        aria-label="${escapeHTML(formulaValue(card) || card.display)}"
      >${latexMarkup(formulaValue(card), card.display, true)}</div>
    </section>
    <section class="inspector-section">
      <span class="section-label">Simple introduction</span>
      ${
        state.introductionLoading
          ? `<div class="introduction-status" aria-busy="true">
              <span class="introduction-spinner" aria-hidden="true"></span>
              <p><strong>Writing a concise introduction…</strong></p>
              <p>Mathernet is checking the formula's definition and common uses. This can take up to a minute.</p>
            </div>`
          : state.introductionError
            ? `<div class="introduction-status is-error">
                <p><strong>The introduction could not be generated.</strong></p>
                <p>${escapeHTML(state.introductionError)}</p>
                <button class="button button-secondary" type="button" data-retry-introduction>Try again</button>
              </div>`
            : introduction
              ? `<div class="introduction-copy">${articleMarkup(introduction)}</div>`
              : `<p class="body-copy">An introduction is not available yet.</p>`
      }
      <button class="button button-primary deep-dive-button" type="button" data-open-deep-dive>
        Explore deeper
        ${icon("arrow-right")}
      </button>
    </section>
  `;
}

function renderLearning() {
  const card = state.selectedCard;
  if (!card) {
    elements.learningEmpty.hidden = false;
    elements.learningContent.hidden = true;
    elements.learningContent.innerHTML = "";
    return;
  }
  const formula = card.formula;
  elements.learningEmpty.hidden = true;
  elements.learningContent.hidden = false;
  elements.learningContent.innerHTML = `
    <section class="inspector-section">
      <span class="section-label user-label">Study status</span>
      <h3>Where is this formula in your study?</h3>
      <div class="status-control" role="group" aria-label="Study status">
        ${Object.entries(statusLabels)
          .map(
            ([value, label]) => `
              <button
                class="status-option ${formula.status === value ? "is-active" : ""}"
                type="button"
                data-set-status="${value}"
                aria-pressed="${formula.status === value}"
              >${escapeHTML(label)}</button>
            `,
          )
          .join("")}
      </div>
    </section>
    <section class="inspector-section">
      <span class="section-label user-label">Personal note</span>
      <form id="notes-form">
        <div class="field">
          <label for="user-notes">Your explanation, question, or reminder</label>
          <textarea id="user-notes" name="notes" maxlength="20000" placeholder="Write what you want to remember…">${escapeHTML(formula.user_module.notes)}</textarea>
        </div>
        <div class="notes-meta">
          <span class="unsaved-label" id="notes-dirty-label" ${state.notesDirty ? "" : "hidden"}>Unsaved note</span>
          <button class="button button-primary" id="save-notes" type="submit" ${state.notesDirty ? "" : "disabled"}>
            ${icon("pencil")} Save note
          </button>
        </div>
      </form>
    </section>
  `;
}

function renderDeepSessionList() {
  if (!elements.deepSessionList) return;
  elements.deepSessionList.innerHTML = state.deepSessions.length
    ? state.deepSessions
        .map((session, index) => `
          <button
            class="deep-session-tab ${session.id === state.activeDeepSession?.id ? "is-active" : ""}"
            type="button"
            data-deep-session-id="${escapeHTML(session.id)}"
            aria-pressed="${session.id === state.activeDeepSession?.id}"
          >
            <span>${richText(session.title || `Session ${index + 1}`)}</span>
            <small>${session.message_count || 0} message${session.message_count === 1 ? "" : "s"}</small>
          </button>
        `)
        .join("")
    : `<p class="deep-session-empty">No saved sessions yet.</p>`;
  const busy = state.deepLoading || state.deepGenerating || state.deepChatBusy;
  elements.deepSessionNew.disabled = busy;
  elements.deepSessionNew.setAttribute("aria-busy", String(state.deepGenerating));
  if (elements.deepSessionNewLabel) {
    elements.deepSessionNewLabel.textContent = state.deepGenerating
      ? "Generating…"
      : state.deepLoading
        ? "Opening…"
        : "New session";
  }
  elements.deepSessionDelete.disabled = !state.activeDeepSession || busy;
  elements.deepChatInput.disabled = busy;
  elements.deepChatSubmit.disabled = busy || !state.activeDeepSession;
}

function renderDeepLoading(
  label = "Preparing a new session…",
  detail = "Mathernet is reading the formula context.",
) {
  elements.deepDiveContent.setAttribute("aria-busy", "true");
  elements.deepDiveContent.innerHTML = `
    <div class="deep-loading" aria-label="${escapeHTML(label)}">
      <span></span><span></span><span></span>
      <p class="deep-loading-label">${escapeHTML(label)}</p>
      <p class="deep-loading-detail">${escapeHTML(detail)}</p>
    </div>
  `;
}

function renderDeepDive({ scrollToBottom = false } = {}) {
  const session = state.activeDeepSession;
  if (!session) return;
  elements.deepDiveContent.setAttribute("aria-busy", "false");
  const sources = session.sources || [];
  const messages = session.messages || [];
  elements.deepDiveContent.innerHTML = `
    <article class="deep-article">
      <header class="deep-article-header">
        <p class="section-kicker">Saved session</p>
        <h3>${richText(session.title || "Deep dive")}</h3>
      </header>
      <div class="deep-article-body">${deepArticleMarkup(session.article)}</div>
      ${session.warnings?.length
        ? `<aside class="deep-warnings">${session.warnings.map((warning) => `<p>${escapeHTML(warning)}</p>`).join("")}</aside>`
        : ""}
    </article>
    ${messages.length
      ? `<section class="deep-chat-log" aria-label="Conversation">
          ${messages
            .map(
              (message) => `
                <article class="deep-message ${message.role === "user" ? "is-user" : "is-assistant"}">
                  <span class="deep-message-role">${message.role === "user" ? "You" : "Mathernet"}</span>
                  <div class="deep-message-body">${richText(message.content)}</div>
                </article>
              `,
            )
            .join("")}
        </section>`
      : ""}
    ${sources.length
      ? `<section class="deep-references">
          <span class="section-label">References</span>
          <ul class="reference-links">
            ${sources
              .slice(0, 5)
              .map(
                (source) => `
                  <li>
                    <a href="${escapeHTML(safeUrl(source.url))}" target="_blank" rel="noopener noreferrer">
                      ${escapeHTML(source.title)}
                      ${icon("external")}
                    </a>
                    <span>${escapeHTML(source.publisher)}</span>
                  </li>
                `,
              )
              .join("")}
          </ul>
        </section>`
      : ""}
  `;
  renderDeepSessionList();
  if (scrollToBottom) {
    elements.deepDiveContent.scrollTop = elements.deepDiveContent.scrollHeight;
  }
}

function showDeepDiveError(error) {
  elements.deepDiveContent.setAttribute("aria-busy", "false");
  elements.deepDiveContent.innerHTML = `
    <div class="deep-error">
      <h3>Deep dive unavailable</h3>
      <p>${escapeHTML(error.message)}</p>
      <button class="button button-secondary" type="button" data-create-deep-session>Start a new session</button>
    </div>
  `;
  renderDeepSessionList();
}

async function loadDeepSession(sessionId, fromLoader = false) {
  const formulaId = state.deepDiveFormulaId;
  if (state.deepGenerating || state.deepChatBusy) {
    showToast("Mathernet is still working in this deep dive. Please wait for it to finish.", "notice");
    return;
  }
  if (state.deepLoading && !fromLoader) return;
  const requestId = ++state.deepDiveRequest;
  state.deepLoading = true;
  renderDeepLoading("Opening the saved session…", "Restoring the article and conversation.");
  try {
    const session = await api(`/api/formulas/${encodeURIComponent(formulaId)}/deep-dive/sessions/${encodeURIComponent(sessionId)}`);
    if (requestId !== state.deepDiveRequest || state.deepDiveFormulaId !== formulaId) return;
    state.activeDeepSession = session;
    renderDeepDive();
  } catch (error) {
    if (requestId === state.deepDiveRequest) showDeepDiveError(error);
  } finally {
    state.deepLoading = false;
    renderDeepSessionList();
  }
}

async function createDeepSession(fromLoader = false) {
  const formulaId = state.deepDiveFormulaId;
  if (!formulaId || state.deepChatBusy) return;
  if (state.deepGenerating) {
    if (!fromLoader) showToast("A deep dive is already being generated. Please wait for it to finish.", "notice");
    return;
  }
  if (state.deepLoading && !fromLoader) return;
  const requestId = ++state.deepGenerationRequest;
  state.deepGenerating = true;
  renderDeepSessionList();
  renderDeepLoading(
    "Generating a fresh deep dive…",
    "Mathernet is researching and writing the opening article. This can take up to a minute.",
  );
  try {
    const session = await api(`/api/formulas/${encodeURIComponent(formulaId)}/deep-dive/sessions`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    if (requestId !== state.deepGenerationRequest || state.deepDiveFormulaId !== formulaId) return;
    state.activeDeepSession = session;
    state.deepSessions = await api(`/api/formulas/${encodeURIComponent(formulaId)}/deep-dive/sessions`).then((payload) => payload.sessions || []);
    renderDeepDive();
  } catch (error) {
    if (requestId === state.deepGenerationRequest && state.deepDiveFormulaId === formulaId) showDeepDiveError(error);
  } finally {
    if (requestId === state.deepGenerationRequest) state.deepGenerating = false;
    renderDeepSessionList();
  }
}

async function loadDeepDiveSessions({ createIfEmpty = false } = {}) {
  const card = state.selectedCard;
  if (!card) return;
  const formulaId = card.formula.id;
  state.deepDiveFormulaId = formulaId;
  const requestId = ++state.deepDiveRequest;
  state.deepLoading = true;
  renderDeepSessionList();
  renderDeepLoading("Opening your saved sessions…", "Checking this formula's saved explorations.");
  try {
    const payload = await api(`/api/formulas/${encodeURIComponent(formulaId)}/deep-dive/sessions`);
    if (requestId !== state.deepDiveRequest || state.deepDiveFormulaId !== formulaId) return;
    state.deepSessions = payload.sessions || [];
    if (!state.deepSessions.length && createIfEmpty) {
      if (state.deepGenerating && state.deepDiveFormulaId === formulaId) return;
      await createDeepSession(true);
      return;
    }
    if (state.deepSessions.length) {
      await loadDeepSession(state.deepSessions[0].id, true);
      return;
    }
    state.activeDeepSession = null;
    elements.deepDiveContent.innerHTML = `
      <div class="deep-empty">
        <h3>Start a deep dive</h3>
        <p>Create a new session when you are ready to explore this formula.</p>
        <button class="button button-primary" type="button" data-create-deep-session>
          ${icon("plus")} New session
        </button>
      </div>
    `;
    renderDeepSessionList();
  } catch (error) {
    if (requestId === state.deepDiveRequest) showDeepDiveError(error);
  } finally {
    state.deepLoading = false;
    renderDeepSessionList();
  }
}

function openDeepDive() {
  const card = state.selectedCard;
  if (!card) return;
  state.deepDiveFormulaId = card.formula.id;
  state.activeDeepSession = null;
  elements.deepDiveTitle.textContent = card.formula.name;
  elements.deepDiveFormula.setAttribute("role", "math");
  elements.deepDiveFormula.setAttribute("aria-label", formulaValue(card) || card.display);
  elements.deepDiveFormula.innerHTML = latexMarkup(formulaValue(card), card.display);
  if (!elements.deepDiveDialog.open) elements.deepDiveDialog.showModal();
  loadDeepDiveSessions({ createIfEmpty: true });
}

async function submitDeepChat(event) {
  event.preventDefault();
  const message = elements.deepChatInput.value.trim();
  const formulaId = state.deepDiveFormulaId;
  const session = state.activeDeepSession;
  if (!message || !formulaId || !session || state.deepChatBusy) return;
  state.deepChatBusy = true;
  elements.deepChatInput.value = "";
  elements.deepChatInput.disabled = true;
  setBusy(elements.deepChatSubmit, true, "Thinking…");
  elements.deepChatStatus.textContent = "Mathernet is considering your question…";
  const optimistic = {
    ...session,
    messages: [...(session.messages || []), { role: "user", content: message }],
  };
  state.activeDeepSession = optimistic;
  renderDeepDive({ scrollToBottom: true });
  try {
    const result = await api(
      `/api/formulas/${encodeURIComponent(formulaId)}/deep-dive/sessions/${encodeURIComponent(session.id)}/chat`,
      { method: "POST", body: JSON.stringify({ message }) },
    );
    state.activeDeepSession = result.session;
    state.deepSessions = await api(`/api/formulas/${encodeURIComponent(formulaId)}/deep-dive/sessions`).then((payload) => payload.sessions || []);
    elements.deepChatStatus.textContent = "Ask a follow-up whenever you are ready.";
  } catch (error) {
    state.activeDeepSession = session;
    elements.deepChatStatus.textContent = error.message;
    showToast(error.message, "error");
  } finally {
    state.deepChatBusy = false;
    elements.deepChatInput.disabled = false;
    setBusy(elements.deepChatSubmit, false);
    renderDeepDive({ scrollToBottom: true });
    elements.deepChatInput.focus();
  }
}

async function deleteDeepSession() {
  const formulaId = state.deepDiveFormulaId;
  const session = state.activeDeepSession;
  if (!formulaId || !session || state.deepChatBusy) return;
  const confirmed = window.confirm("Delete this deep-dive session and its conversation?");
  if (!confirmed) return;
  try {
    await api(
      `/api/formulas/${encodeURIComponent(formulaId)}/deep-dive/sessions/${encodeURIComponent(session.id)}`,
      { method: "DELETE" },
    );
    state.activeDeepSession = null;
    await loadDeepDiveSessions({ createIfEmpty: false });
    showToast("Deep-dive session deleted.");
  } catch (error) {
    showToast(error.message, "error");
  }
}

function renderInspector() {
  const card = state.selectedCard;
  if (!card) {
    elements.inspectorTitle.textContent = "Select a formula";
    elements.inspectorStatus.textContent = "No selection";
    elements.inspectorStatus.className = "status-badge neutral";
  } else {
    const formula = card.formula;
    elements.inspectorTitle.textContent = formula.name;
    elements.inspectorStatus.textContent = statusLabels[formula.status] || formula.status;
    elements.inspectorStatus.className = `status-badge ${formula.status}`;
  }
  renderOverview();
  renderLearning();
  setTab(state.tab, false);
}

function renderAll() {
  renderLibrary();
  renderGraph();
  renderInspector();
}

function setTab(tab, focus = true) {
  state.tab = ["overview", "learning"].includes(tab) ? tab : "overview";
  document.querySelectorAll("[data-tab]").forEach((button) => {
    const active = button.dataset.tab === state.tab;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
    if (active && focus) button.focus();
  });
  document.querySelectorAll("[data-tab-panel]").forEach((panel) => {
    panel.hidden = panel.dataset.tabPanel !== state.tab;
  });
  syncUrl();
}

async function loadHealth() {
  try {
    state.health = await api("/api/health");
    setConnection(true, "Service connected");
  } catch {
    setConnection(false, "Local service offline");
  }
}

async function loadFormulas() {
  const requestId = ++state.libraryRequest;
  elements.formulaList.setAttribute("aria-busy", "true");
  elements.formulaList.innerHTML = `<div class="loading-row">Loading formulas…</div>`;
  const params = new URLSearchParams();
  if (state.query) params.set("query", state.query);
  if (state.status) params.set("status", state.status);
  params.set("limit", "200");
  try {
    const payload = await api(`/api/formulas?${params.toString()}`);
    if (requestId !== state.libraryRequest) return;
    state.formulas = payload.items;
    state.statusCounts = {
      all: payload.status_counts?.all ?? payload.total,
      learning: payload.status_counts?.learning ?? 0,
      reviewed: payload.status_counts?.reviewed ?? 0,
    };
    renderLibrary();
    syncUrl();
  } catch (error) {
    if (requestId !== state.libraryRequest) return;
    elements.formulaList.setAttribute("aria-busy", "false");
    elements.formulaList.innerHTML = `
      <div class="list-empty">
        <h3>Formula library unavailable</h3>
        <p>${escapeHTML(error.message)}</p>
      </div>
    `;
  }
}

async function loadFormulaIntroduction(formulaId) {
  const requestId = ++state.introductionRequest;
  state.introductionLoading = true;
  state.introductionError = "";
  renderOverview();
  try {
    const introduction = await api(
      `/api/formulas/${encodeURIComponent(formulaId)}/introduction`,
      { method: "POST", body: JSON.stringify({}) },
    );
    if (requestId !== state.introductionRequest || state.selectedId !== formulaId) return;
    state.introduction = introduction;
    state.introductions[formulaId] = introduction;
  } catch (error) {
    if (requestId !== state.introductionRequest || state.selectedId !== formulaId) return;
    state.introductionError = error.message;
  } finally {
    if (requestId === state.introductionRequest && state.selectedId === formulaId) {
      state.introductionLoading = false;
      renderOverview();
    }
  }
}

async function loadSelection(formulaId) {
  const requestId = ++state.selectionRequest;
  const [card, graph] = await Promise.all([
    api(`/api/formulas/${encodeURIComponent(formulaId)}`),
    api(`/api/formulas/${encodeURIComponent(formulaId)}/graph?depth=${state.depth}`),
  ]);
  if (requestId !== state.selectionRequest) return;
  state.selectedId = formulaId;
  state.selectedCard = card;
  state.graph = graph;
  state.introduction = state.introductions[formulaId] || null;
  state.introductionLoading = !state.introduction;
  state.introductionError = "";
  state.notesDirty = false;
  renderAll();
  syncUrl();
  if (!state.introduction) loadFormulaIntroduction(formulaId);
}

async function selectFormula(formulaId) {
  if (state.selectedId && state.selectedId !== formulaId && state.notesDirty) {
    const leave = window.confirm("You have an unsaved note. Leave this formula without saving?");
    if (!leave) return;
  }
  try {
    await loadSelection(formulaId);
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function refreshSelection() {
  if (!state.selectedId) return loadFormulas();
  try {
    await loadSelection(state.selectedId);
  } catch (error) {
    showToast(error.message, "error");
  }
}

function closeDialog(dialog) {
  if (dialog.open) dialog.close();
}

function setSettingsState(element, kind, label) {
  if (!element) return;
  element.textContent = label;
  element.classList.toggle("is-connected", kind === "success");
  element.classList.toggle("is-error", kind === "error");
}

function providerPreset(provider) {
  return state.gateway?.provider_presets?.find((preset) => preset.id === provider);
}

function syncProviderOptions(provider) {
  elements.settingsProvider.value = provider || "";
  document.querySelectorAll(".provider-radio").forEach((radio) => {
    radio.checked = radio.value === provider;
    radio.closest(".provider-option")?.classList.toggle("is-selected", radio.checked);
  });
}

function gatewayPayload() {
  return {
    provider: elements.settingsProvider.value,
    api_key: elements.settingsApiKey.value.trim(),
    model: elements.settingsModel.value.trim(),
  };
}

function applyGatewayConfig(config) {
  state.gateway = config;
  state.firstRun = Boolean(config.first_run);
  syncProviderOptions(config.provider || "");
  elements.settingsModel.value = config.model || "";
  elements.settingsApiKey.value = "";
  elements.settingsApiKey.placeholder = config.api_key_hint ? `Saved key ${config.api_key_hint}` : "Paste a new key";
  setSettingsState(elements.settingsAiState, config.ai_configured ? "success" : "idle", config.ai_configured ? "Connected" : "Not connected");
}

async function loadGatewaySettings() {
  try {
    applyGatewayConfig(await api("/api/gateway"));
    if (state.firstRun) {
      elements.settingsDialog.showModal();
      window.setTimeout(() => document.querySelector(".provider-radio")?.focus(), 0);
    }
  } catch (error) {
    showToast(error.message, "error");
  }
}

function openSettingsDialog() {
  elements.settingsError.textContent = "";
  elements.settingsAiMessage.textContent = "";
  elements.settingsDialog.showModal();
}

function validateGatewayPayload(payload) {
  if (!payload.provider) return "Choose an AI provider.";
  if (!payload.api_key && !state.gateway?.api_key_hint) return "Enter an API key for the selected provider.";
  if (!payload.model) return "Enter the model you want to use.";
  return "";
}

async function saveGatewaySettings(silent = false) {
  const payload = gatewayPayload();
  const error = validateGatewayPayload(payload);
  elements.settingsError.textContent = error;
  if (error) return false;
  setBusy(elements.settingsSave, true, "Saving…");
  try {
    applyGatewayConfig(await api("/api/gateway", { method: "PATCH", body: JSON.stringify(payload) }));
    if (!silent) {
      closeDialog(elements.settingsDialog);
      showToast("Connection settings saved locally.");
    }
    return true;
  } catch (requestError) {
    elements.settingsError.textContent = requestError.message;
    return false;
  } finally {
    setBusy(elements.settingsSave, false);
  }
}

async function testGatewayConnection() {
  if (!(await saveGatewaySettings(true))) return;
  const button = document.querySelector("#test-ai");
  const message = elements.settingsAiMessage;
  setBusy(button, true, "Testing…");
  message.textContent = "";
  message.className = "settings-status";
  try {
    await api("/api/gateway/test-ai", { method: "POST" });
    message.textContent = "Connection is ready.";
    message.classList.add("is-success");
    setSettingsState(elements.settingsAiState, "success", "Connected");
  } catch (error) {
    message.textContent = error.message;
    message.classList.add("is-error");
    setSettingsState(elements.settingsAiState, "error", "Check settings");
  } finally {
    setBusy(button, false);
  }
}

async function submitFormulaSearch(event) {
  event.preventDefault();
  const query = elements.globalQuery.value.trim();
  if (!query) {
    showToast("Enter a formula name, expression, or description.", "notice");
    elements.globalQuery.focus();
    return;
  }
  setBusy(elements.globalSubmit, true, "Searching…");
  try {
    const result = await api("/api/learn", {
      method: "POST",
      body: JSON.stringify({ query }),
    });
    await loadFormulas();
    await selectFormula(result.formula.formula.id);
    showToast(result.created ? "Formula card created." : "Existing formula opened.");
    for (const warning of result.warnings || []) {
      showToast(warning, "notice");
    }
    const unresolvedCount = result.unresolved_dependencies?.length || 0;
    if (unresolvedCount) {
      showToast(
        `${unresolvedCount} suggested prerequisite${unresolvedCount === 1 ? " was" : "s were"} not in the local library.`,
        "notice",
      );
    }
    await loadHealth();
  } catch (error) {
    showToast(
      error.reasonCode === "no_reliable_source"
        ? "No usable source material was found. Try a more specific formula name or description."
        : error.message,
      "error",
    );
    elements.globalQuery.focus();
  } finally {
    setBusy(elements.globalSubmit, false);
  }
}

async function saveNotes(event) {
  event.preventDefault();
  if (!state.selectedCard) return;
  const textarea = document.querySelector("#user-notes");
  const button = document.querySelector("#save-notes");
  if (!textarea || !button) return;
  setBusy(button, true, "Saving…");
  try {
    const card = await api(
      `/api/formulas/${encodeURIComponent(state.selectedCard.formula.id)}/user-module`,
      {
        method: "PATCH",
        body: JSON.stringify({
          notes: textarea.value,
          expected_updated_at: state.selectedCard.formula.updated_at,
        }),
      },
    );
    state.selectedCard = card;
    state.notesDirty = false;
    renderInspector();
    showToast("Personal note saved.");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setBusy(button, false);
  }
}

async function setFormulaStatus(status) {
  if (!state.selectedCard) return;
  try {
    const card = await api(
      `/api/formulas/${encodeURIComponent(state.selectedCard.formula.id)}/status`,
      {
        method: "PATCH",
        body: JSON.stringify({
          status,
          expected_updated_at: state.selectedCard.formula.updated_at,
        }),
      },
    );
    state.selectedCard = card;
    renderInspector();
    renderLibrary();
    showToast(`Study status changed to ${statusLabels[status] || status}.`);
    await loadHealth();
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function confirmEdge(edgeId, updatedAt) {
  const button = document.querySelector(`[data-confirm-edge="${CSS.escape(edgeId)}"]`);
  setBusy(button, true, "Confirming…");
  try {
    await api(`/api/edges/${encodeURIComponent(edgeId)}/confirm`, {
      method: "POST",
      body: JSON.stringify({ expected_updated_at: updatedAt }),
    });
    await refreshSelection();
    showToast("Dependency confirmed.");
    await loadHealth();
  } catch (error) {
    showToast(error.message, "error");
    setBusy(button, false);
  }
}

async function rejectEdge(edgeId, updatedAt) {
  state.pendingRejectEdgeId = { edgeId, updatedAt };
  elements.rejectDialog.showModal();
}

async function confirmReject() {
  const pending = state.pendingRejectEdgeId;
  if (!pending) return;
  setBusy(elements.confirmReject, true, "Rejecting…");
  try {
    await api(`/api/edges/${encodeURIComponent(pending.edgeId)}/reject`, {
      method: "POST",
      body: JSON.stringify({ expected_updated_at: pending.updatedAt }),
    });
    closeDialog(elements.rejectDialog);
    state.pendingRejectEdgeId = null;
    await refreshSelection();
    showToast("Dependency suggestion rejected.");
    await loadHealth();
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setBusy(elements.confirmReject, false);
  }
}

function bindEvents() {
  elements.globalSearch.addEventListener("submit", submitFormulaSearch);

  let libraryTimer;
  elements.libraryQuery.addEventListener("input", () => {
    window.clearTimeout(libraryTimer);
    libraryTimer = window.setTimeout(async () => {
      state.query = elements.libraryQuery.value.trim();
      await loadFormulas();
    }, 220);
  });

  document.querySelectorAll("[data-status][aria-pressed]").forEach((button) => {
    button.addEventListener("click", async () => {
      state.status = button.dataset.status;
      document.querySelectorAll(".library-controls [data-status]").forEach((item) => {
        const active = item === button;
        item.classList.toggle("is-active", active);
        item.setAttribute("aria-pressed", String(active));
      });
      await loadFormulas();
    });
  });

  document.querySelectorAll("[data-depth]").forEach((button) => {
    button.addEventListener("click", async () => {
      state.depth = Number(button.dataset.depth);
      document.querySelectorAll("[data-depth]").forEach((item) => {
        const active = item === button;
        item.classList.toggle("is-active", active);
        item.setAttribute("aria-pressed", String(active));
      });
      await refreshSelection();
    });
  });

  elements.formulaList.addEventListener("click", (event) => {
    const row = event.target.closest("[data-formula-id]");
    if (row) selectFormula(row.dataset.formulaId);
  });

  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => setTab(button.dataset.tab, false));
    button.addEventListener("keydown", (event) => {
      const tabs = [...document.querySelectorAll("[data-tab]")];
      const current = tabs.indexOf(button);
      if (event.key === "ArrowRight") {
        event.preventDefault();
        setTab(tabs[(current + 1) % tabs.length].dataset.tab);
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        setTab(tabs[(current - 1 + tabs.length) % tabs.length].dataset.tab);
      } else if (event.key === "Home") {
        event.preventDefault();
        setTab(tabs[0].dataset.tab);
      } else if (event.key === "End") {
        event.preventDefault();
        setTab(tabs[tabs.length - 1].dataset.tab);
      }
    });
  });

  document.querySelectorAll("[data-close-dialog]").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.closeDialog === "settings-dialog" && state.firstRun) {
        showToast("Save a connection setup before entering the workspace.", "notice");
        return;
      }
      closeDialog(document.querySelector(`#${button.dataset.closeDialog}`));
    });
  });

  elements.settingsForm.addEventListener("submit", (event) => {
    event.preventDefault();
    saveGatewaySettings();
  });
  document.querySelector("#open-settings").addEventListener("click", openSettingsDialog);
  document.querySelector("#test-ai").addEventListener("click", testGatewayConnection);
  document.querySelectorAll(".provider-radio").forEach((radio) => {
    radio.addEventListener("change", () => {
      syncProviderOptions(radio.value);
      const preset = providerPreset(radio.value);
      if (preset?.default_model && !elements.settingsModel.value.trim()) {
        elements.settingsModel.value = preset.default_model;
      }
    });
  });
  elements.settingsDialog.addEventListener("cancel", (event) => {
    if (state.firstRun) event.preventDefault();
  });
  elements.confirmReject.addEventListener("click", confirmReject);
  elements.themeToggle.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    setTheme(next);
  });

  document.querySelector("#refresh-data").addEventListener("click", async () => {
    const button = document.querySelector("#refresh-data");
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    await Promise.all([loadHealth(), loadFormulas(), refreshSelection()]);
    button.disabled = false;
    button.removeAttribute("aria-busy");
    showToast("Formula library refreshed.");
  });

  elements.overviewContent.addEventListener("click", (event) => {
    if (event.target.closest("[data-open-deep-dive]")) openDeepDive();
    if (event.target.closest("[data-retry-introduction]") && state.selectedId) {
      loadFormulaIntroduction(state.selectedId);
    }
  });

  elements.deepSessionNew.addEventListener("click", createDeepSession);
  elements.deepSessionDelete.addEventListener("click", deleteDeepSession);
  elements.deepSessionList.addEventListener("click", (event) => {
    const button = event.target.closest("[data-deep-session-id]");
    if (button && !state.deepChatBusy) loadDeepSession(button.dataset.deepSessionId);
  });
  elements.deepDiveContent.addEventListener("click", (event) => {
    if (event.target.closest("[data-create-deep-session]")) createDeepSession();
  });
  elements.deepChatForm.addEventListener("submit", submitDeepChat);
  elements.deepChatInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      elements.deepChatForm.requestSubmit();
    }
  });

  elements.learningContent.addEventListener("submit", (event) => {
    if (event.target.id === "notes-form") saveNotes(event);
  });

  elements.learningContent.addEventListener("input", (event) => {
    if (event.target.id !== "user-notes") return;
    state.notesDirty = true;
    const label = document.querySelector("#notes-dirty-label");
    const save = document.querySelector("#save-notes");
    if (label) label.hidden = false;
    if (save) save.disabled = false;
  });

  elements.learningContent.addEventListener("click", (event) => {
    const statusButton = event.target.closest("[data-set-status]");
    if (statusButton) {
      setFormulaStatus(statusButton.dataset.setStatus);
      return;
    }
    const confirmButton = event.target.closest("[data-confirm-edge]");
    if (confirmButton) {
      confirmEdge(confirmButton.dataset.confirmEdge, confirmButton.dataset.edgeUpdated);
      return;
    }
    const rejectButton = event.target.closest("[data-reject-edge]");
    if (rejectButton) {
      rejectEdge(rejectButton.dataset.rejectEdge, rejectButton.dataset.edgeUpdated);
    }
  });

  window.addEventListener("beforeunload", (event) => {
    if (!state.notesDirty) return;
    event.preventDefault();
    event.returnValue = "";
  });
}

async function initialize() {
  setTheme(currentTheme());
  restoreUrlState();
  bindEvents();
  renderAll();
  await loadGatewaySettings();
  await Promise.all([loadHealth(), loadFormulas()]);
  const selected = state.selectedId || state.formulas[0]?.id;
  if (selected) {
    try {
      await loadSelection(selected);
    } catch (error) {
      showToast(error.message, "error");
    }
  } else {
    renderAll();
  }
}

initialize();
