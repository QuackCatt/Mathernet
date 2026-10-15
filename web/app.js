const state = {
  mapSessions: [],
  activeMapSession: null,
  activeMapSessionId: null,
  leftView: "sessions",
  leftCollapsed: false,
  rightCollapsed: false,
  sessionMenuId: null,
  renamingSessionId: null,
  formulas: [],
  selectedId: null,
  selectedCard: null,
  graph: null,
  query: "",
  tab: "overview",
  notesDirty: false,
  pendingRejectEdgeId: null,
  pendingRelationship: null,
  pendingUnlinkEdge: null,
  pendingExploreEdge: null,
  libraryRequest: 0,
  selectionRequest: 0,
  deepDiveRequest: 0,
  deepGenerationRequest: 0,
  deepDiveFormulaId: null,
  deepDiveMode: "formula",
  deepDiveEdge: null,
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
  providerDrafts: {},
};

const elements = {
  globalSearch: document.querySelector("#global-search"),
  globalQuery: document.querySelector("#global-query"),
  globalSubmit: document.querySelector("#global-submit"),
  workspace: document.querySelector("#workspace"),
  leftTrack: document.querySelector("#left-track"),
  sessionList: document.querySelector("#session-list"),
  sessionCreate: document.querySelector("#session-create"),
  sessionName: document.querySelector("#session-name"),
  newMapSession: document.querySelector("#new-map-session"),
  backToSessions: document.querySelector("#back-to-sessions"),
  activeMapLabel: document.querySelector("#active-map-label"),
  libraryQuery: document.querySelector("#library-query"),
  formulaList: document.querySelector("#formula-list"),
  graphTitle: document.querySelector("#graph-title"),
  graphEmpty: document.querySelector("#graph-empty"),
  graphDescription: document.querySelector("#graph-description"),
  inspectorTitle: document.querySelector("#inspector-title"),
  inspectorStatus: document.querySelector("#inspector-status"),
  deleteFormula: document.querySelector("#delete-formula"),
  overviewEmpty: document.querySelector("#overview-empty"),
  overviewContent: document.querySelector("#overview-content"),
  learningEmpty: document.querySelector("#learning-empty"),
  learningContent: document.querySelector("#learning-content"),
  deepDiveDialog: document.querySelector("#deep-dive-dialog"),
  deepDiveTitle: document.querySelector("#deep-dive-title"),
  deepDiveContent: document.querySelector("#deep-dive-content"),
  deepChatForm: document.querySelector("#deep-chat-form"),
  deepChatInput: document.querySelector("#deep-chat-input"),
  deepChatSubmit: document.querySelector("#deep-chat-submit"),
  deepChatStatus: document.querySelector("#deep-chat-status"),
  rejectDialog: document.querySelector("#reject-dialog"),
  confirmReject: document.querySelector("#confirm-reject"),
  relationshipDialog: document.querySelector("#relationship-dialog"),
  relationshipForm: document.querySelector("#relationship-form"),
  relationshipSource: document.querySelector("#relationship-source"),
  relationshipTarget: document.querySelector("#relationship-target"),
  relationshipKind: document.querySelector("#relationship-kind"),
  relationshipReason: document.querySelector("#relationship-reason"),
  relationshipSwap: document.querySelector("#relationship-swap"),
  confirmRelationship: document.querySelector("#confirm-relationship"),
  unlinkDialog: document.querySelector("#unlink-dialog"),
  unlinkRelation: document.querySelector("#unlink-relation"),
  unlinkFormulas: document.querySelector("#unlink-formulas"),
  confirmUnlink: document.querySelector("#confirm-unlink"),
  relationshipExploreDialog: document.querySelector("#relationship-explore-dialog"),
  relationshipExploreSource: document.querySelector("#relationship-explore-source"),
  relationshipExploreTarget: document.querySelector("#relationship-explore-target"),
  relationshipExploreKind: document.querySelector("#relationship-explore-kind"),
  relationshipExploreOrigin: document.querySelector("#relationship-explore-origin"),
  relationshipExploreNote: document.querySelector("#relationship-explore-note"),
  confirmRelationshipExplore: document.querySelector("#confirm-relationship-explore"),
  toastRegion: document.querySelector("#toast-region"),
  themeToggle: document.querySelector("#theme-toggle"),
  toggleLeftPanel: document.querySelector("#toggle-left-panel"),
  toggleRightPanel: document.querySelector("#toggle-right-panel"),
  aiConnectionIndicator: document.querySelector("#ai-connection-indicator"),
  aiConnectionLabel: document.querySelector("#ai-connection-label"),
  settingsDialog: document.querySelector("#settings-dialog"),
  settingsForm: document.querySelector("#settings-form"),
  settingsProvider: document.querySelector("#settings-provider"),
  providerForm: document.querySelector("#provider-form"),
  settingsError: document.querySelector("#settings-error"),
  settingsAiState: document.querySelector("#settings-ai-state"),
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
  setOrDelete("map", state.activeMapSessionId);
  setOrDelete("formula", state.selectedId);
  setOrDelete("tab", state.tab, "overview");
  window.history.replaceState({}, "", url);
}

function restoreUrlState() {
  const params = new URLSearchParams(window.location.search);
  const tab = params.get("tab");
  state.query = params.get("q") || "";
  state.tab = ["overview", "learning"].includes(tab) ? tab : "overview";
  state.selectedId = params.get("formula");
  state.activeMapSessionId = params.get("map") || localStorage.getItem("mathernet-map-session");
  state.leftCollapsed = localStorage.getItem("mathernet-left-collapsed") === "true";
  state.rightCollapsed = localStorage.getItem("mathernet-right-collapsed") === "true";
  elements.libraryQuery.value = state.query;
  applyPanelLayout();
}

function applyPanelLayout() {
  elements.workspace.classList.toggle("left-collapsed", state.leftCollapsed);
  elements.workspace.classList.toggle("right-collapsed", state.rightCollapsed);
  elements.leftTrack.dataset.leftView = state.leftView;
  for (const [button, collapsed, label] of [
    [elements.toggleLeftPanel, state.leftCollapsed, "left"],
    [elements.toggleRightPanel, state.rightCollapsed, "right"],
  ]) {
    button.classList.toggle("is-active", !collapsed);
    button.setAttribute("aria-pressed", String(!collapsed));
    button.setAttribute("aria-label", `${collapsed ? "Show" : "Hide"} ${label} panel`);
  }
}

function renderSessionList() {
  if (!state.mapSessions.length) {
    elements.sessionList.innerHTML = `
      <div class="list-empty">
        <h3>No mind maps</h3>
        <p>Create a mind map to begin.</p>
      </div>
    `;
    return;
  }
  elements.sessionList.innerHTML = state.mapSessions.map((session) => {
    const active = session.id === state.activeMapSessionId;
    const renaming = session.id === state.renamingSessionId;
    return `
      <div class="session-item ${active ? "is-active" : ""}" data-session-id="${escapeHTML(session.id)}">
        ${
          renaming
            ? `<form class="session-rename" data-rename-session>
                <label class="sr-only" for="rename-${escapeHTML(session.id)}">Mind map name</label>
                <input id="rename-${escapeHTML(session.id)}" name="name" maxlength="120" value="${escapeHTML(session.name)}" autocomplete="off">
                <button class="button button-primary button-small" type="submit">Save</button>
              </form>`
            : `<button class="session-open" type="button" data-open-session aria-pressed="${active}">
                <span class="session-name">${escapeHTML(session.name)}</span>
                <span class="session-count">${session.formula_count}</span>
                ${session.pinned ? icon("pin") : ""}
              </button>`
        }
        <button
          class="session-more icon-button icon-button-compact"
          type="button"
          data-session-menu
          aria-label="More actions for ${escapeHTML(session.name)}"
          aria-expanded="${state.sessionMenuId === session.id}"
        >
          ${icon("more")}
        </button>
        ${
          state.sessionMenuId === session.id
            ? `<div class="session-menu" role="menu">
                <button type="button" role="menuitem" data-session-rename>${icon("pencil")} Rename</button>
                <button type="button" role="menuitem" data-session-pin>${icon("pin")} ${session.pinned ? "Unpin" : "Pin"}</button>
                <button class="menu-danger" type="button" role="menuitem" data-session-delete>${icon("trash")} Delete</button>
              </div>`
            : ""
        }
      </div>
    `;
  }).join("");
  if (state.renamingSessionId) {
    elements.sessionList.querySelector(".session-rename input")?.focus();
    elements.sessionList.querySelector(".session-rename input")?.select();
  }
}

function renderLibrary() {
  elements.formulaList.setAttribute("aria-busy", "false");
  if (!state.formulas.length) {
    elements.formulaList.innerHTML = `
      <div class="list-empty">
        <h3>No formulas in this map</h3>
        <p>Use the search above to open an existing formula or create a new one.</p>
      </div>
    `;
    return;
  }

  const query = state.query.trim().toLowerCase();
  const groups = new Map();
  for (const formula of state.formulas) {
    if (query && ![formula.name, ...(formula.aliases || []), ...(formula.topic_tags || [])]
      .some((value) => String(value).toLowerCase().includes(query))) continue;
    const topic = formula.topic_tags?.[0] || "Mathematics";
    if (!groups.has(topic)) groups.set(topic, []);
    groups.get(topic).push(formula);
  }
  const markup = [...groups.entries()].sort(([left], [right]) => left.localeCompare(right)).map(([topic, formulas]) => `
    <section class="formula-group" aria-labelledby="topic-${escapeHTML(topic.toLowerCase().replace(/[^a-z0-9]+/g, "-"))}">
      <h3 id="topic-${escapeHTML(topic.toLowerCase().replace(/[^a-z0-9]+/g, "-"))}">${escapeHTML(topic)}</h3>
      ${formulas.map((formula) => `
        <button
          class="formula-row ${formula.id === state.selectedId ? "is-selected" : ""}"
          type="button"
          data-formula-id="${escapeHTML(formula.id)}"
          aria-pressed="${formula.id === state.selectedId}"
        >
          <span class="formula-row-title">${escapeHTML(formula.name)}</span>
          <span class="row-state" data-state="${escapeHTML(formula.status)}">${escapeHTML(statusLabels[formula.status] || formula.status)}</span>
        </button>
      `).join("")}
    </section>
  `).join("");
  elements.formulaList.innerHTML = markup || `
    <div class="list-empty">
      <h3>No matching formulas</h3>
      <p>Try a different name, alias, or topic.</p>
    </div>
  `;
}

function renderGraph() {
  window.MathernetGraph?.render(state.graph, {
    onSelect: selectFormula,
    selectedId: state.selectedId,
    onCreateRelationship: openRelationshipDialog,
    onCutRelationship: openUnlinkDialog,
    onInspectRelationship: openRelationshipExploreDialog,
    onClearSelection: clearFormulaSelection,
  });
}

function deepDiveBasePath() {
  const ownerId = state.deepDiveFormulaId;
  if (!ownerId) return "";
  const kind = state.deepDiveMode === "relationship" ? "edges" : "formulas";
  return `/api/${kind}/${encodeURIComponent(ownerId)}/deep-dive`;
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

function updateDeepDiveControls() {
  const busy = state.deepLoading || state.deepGenerating || state.deepChatBusy;
  elements.deepChatInput.disabled = busy;
  elements.deepChatSubmit.disabled = busy || !state.activeDeepSession;
}

function renderDeepLoading(
  label = "Preparing the exploration…",
  detail = "Mathernet is reading the saved context.",
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
  updateDeepDiveControls();
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
        <button class="button button-secondary" type="button" data-retry-deep-dive>Try again</button>
    </div>
  `;
  updateDeepDiveControls();
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
    const session = await api(`${deepDiveBasePath()}/sessions/${encodeURIComponent(sessionId)}`);
    if (requestId !== state.deepDiveRequest || state.deepDiveFormulaId !== formulaId) return;
    state.activeDeepSession = session;
    renderDeepDive();
  } catch (error) {
    if (requestId === state.deepDiveRequest) showDeepDiveError(error);
  } finally {
    state.deepLoading = false;
    updateDeepDiveControls();
  }
}

async function createInitialDeepSession() {
  const formulaId = state.deepDiveFormulaId;
  if (!formulaId || state.deepChatBusy) return;
  if (state.deepGenerating || state.deepLoading) return;
  const requestId = ++state.deepGenerationRequest;
  state.deepGenerating = true;
  updateDeepDiveControls();
  renderDeepLoading(
    "Generating your exploration…",
    "Mathernet is researching and writing the opening article. This can take up to a minute.",
  );
  try {
    const session = await api(`${deepDiveBasePath()}/sessions`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    if (requestId !== state.deepGenerationRequest || state.deepDiveFormulaId !== formulaId) return;
    state.activeDeepSession = session;
    state.deepSessions = await api(`${deepDiveBasePath()}/sessions`).then((payload) => payload.sessions || []);
    renderDeepDive();
  } catch (error) {
    if (requestId === state.deepGenerationRequest && state.deepDiveFormulaId === formulaId) showDeepDiveError(error);
  } finally {
    if (requestId === state.deepGenerationRequest) state.deepGenerating = false;
    updateDeepDiveControls();
  }
}

async function loadDeepDiveSessions({ createIfEmpty = false } = {}) {
  const formulaId = state.deepDiveFormulaId;
  if (!formulaId) return;
  const requestId = ++state.deepDiveRequest;
  state.deepLoading = true;
  updateDeepDiveControls();
  renderDeepLoading("Opening your saved sessions…", "Checking this formula's saved explorations.");
  try {
    const payload = await api(`${deepDiveBasePath()}/sessions`);
    if (requestId !== state.deepDiveRequest || state.deepDiveFormulaId !== formulaId) return;
    state.deepSessions = payload.sessions || [];
    if (!state.deepSessions.length && createIfEmpty) {
      if (state.deepGenerating && state.deepDiveFormulaId === formulaId) return;
      await createInitialDeepSession();
      return;
    }
    if (state.deepSessions.length) {
      await loadDeepSession(state.deepSessions[0].id, true);
      return;
    }
    state.activeDeepSession = null;
    elements.deepDiveContent.innerHTML = `
      <div class="deep-empty">
        <h3>Exploration removed</h3>
        <p>Reopen Explore deeper when you want Mathernet to generate another exploration.</p>
      </div>
    `;
    updateDeepDiveControls();
  } catch (error) {
    if (requestId === state.deepDiveRequest) showDeepDiveError(error);
  } finally {
    state.deepLoading = false;
    updateDeepDiveControls();
  }
}

function openDeepDive() {
  const card = state.selectedCard;
  if (!card) return;
  state.deepDiveMode = "formula";
  state.deepDiveFormulaId = card.formula.id;
  state.deepDiveEdge = null;
  state.activeDeepSession = null;
  elements.deepDiveTitle.textContent = card.formula.name;
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
      `${deepDiveBasePath()}/sessions/${encodeURIComponent(session.id)}/chat`,
      { method: "POST", body: JSON.stringify({ message }) },
    );
    state.activeDeepSession = result.session;
    state.deepSessions = await api(`${deepDiveBasePath()}/sessions`).then((payload) => payload.sessions || []);
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

function renderInspector() {
  const card = state.selectedCard;
  if (!card) {
    elements.inspectorTitle.textContent = "Select a formula";
    elements.inspectorStatus.textContent = "No selection";
    elements.inspectorStatus.className = "status-badge neutral";
    elements.deleteFormula.disabled = true;
  } else {
    const formula = card.formula;
    elements.inspectorTitle.textContent = formula.name;
    elements.inspectorStatus.textContent = statusLabels[formula.status] || formula.status;
    elements.inspectorStatus.className = `status-badge ${formula.status}`;
    elements.deleteFormula.disabled = false;
  }
  renderOverview();
  renderLearning();
  setTab(state.tab, false);
}

function renderAll() {
  renderSessionList();
  renderLibrary();
  renderGraph();
  renderInspector();
  applyPanelLayout();
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

async function loadMapSessions({ preferredId = "" } = {}) {
  try {
    const payload = await api("/api/map-sessions");
    state.mapSessions = payload.sessions || [];
    const requestedId = preferredId || state.activeMapSessionId;
    const selected = state.mapSessions.find((session) => session.id === requestedId)
      || state.mapSessions.find((session) => session.id === localStorage.getItem("mathernet-map-session"))
      || state.mapSessions[0];
    renderSessionList();
    if (selected) {
      await openMapSession(selected.id, { updateUrl: false });
    } else {
      state.activeMapSessionId = null;
      state.activeMapSession = null;
      state.formulas = [];
      state.graph = { nodes: [], edges: [], root_id: null };
      renderAll();
    }
  } catch (error) {
    elements.sessionList.innerHTML = `
      <div class="list-empty">
        <h3>Mind maps unavailable</h3>
        <p>${escapeHTML(error.message)}</p>
      </div>
    `;
  }
}

async function openMapSession(
  sessionId,
  { updateUrl = true, revealFormulas = updateUrl } = {},
) {
  if (!sessionId) return;
  if (state.notesDirty && state.activeMapSessionId && state.activeMapSessionId !== sessionId) {
    const leave = window.confirm("You have an unsaved note. Leave it and open another mind map?");
    if (!leave) return;
  }
  const requestId = ++state.libraryRequest;
  elements.formulaList.setAttribute("aria-busy", "true");
  elements.formulaList.innerHTML = `<div class="loading-row">Opening mind map…</div>`;
  try {
    const [session, graph] = await Promise.all([
      api(`/api/map-sessions/${encodeURIComponent(sessionId)}`),
      api(`/api/map-sessions/${encodeURIComponent(sessionId)}/graph`),
    ]);
    if (requestId !== state.libraryRequest) return;
    state.activeMapSession = session;
    state.activeMapSessionId = session.id;
    state.formulas = session.formulas || [];
    state.graph = graph;
    state.leftView = revealFormulas ? "formulas" : state.leftView;
    state.sessionMenuId = null;
    state.renamingSessionId = null;
    localStorage.setItem("mathernet-map-session", session.id);
    if (!state.formulas.some((formula) => formula.id === state.selectedId)) {
      state.selectedId = null;
      state.selectedCard = null;
      state.introduction = null;
      state.notesDirty = false;
    }
    elements.graphTitle.textContent = session.name;
    elements.activeMapLabel.textContent = session.name;
    renderAll();
    if (updateUrl) syncUrl();
    if (state.selectedId) await refreshSelection();
  } catch (error) {
    if (requestId !== state.libraryRequest) return;
    if (error.status === 404) {
      state.activeMapSessionId = null;
      localStorage.removeItem("mathernet-map-session");
      await loadMapSessions();
      return;
    }
    elements.formulaList.setAttribute("aria-busy", "false");
    elements.formulaList.innerHTML = `
      <div class="list-empty">
        <h3>Mind map unavailable</h3>
        <p>${escapeHTML(error.message)}</p>
      </div>
    `;
    showToast(error.message, "error");
  }
}

async function loadFormulas() {
  if (state.activeMapSessionId) {
    await openMapSession(state.activeMapSessionId);
    return;
  }
  await loadMapSessions();
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
    showToast(error.message, "error");
  } finally {
    if (requestId === state.introductionRequest && state.selectedId === formulaId) {
      state.introductionLoading = false;
      renderOverview();
    }
  }
}

async function loadSelection(formulaId) {
  const requestId = ++state.selectionRequest;
  const card = await api(`/api/formulas/${encodeURIComponent(formulaId)}`);
  if (requestId !== state.selectionRequest) return;
  state.selectedId = formulaId;
  state.selectedCard = card;
  state.introduction = state.introductions[formulaId] || null;
  state.introductionLoading = !state.introduction;
  state.introductionError = "";
  state.notesDirty = false;
  state.rightCollapsed = false;
  localStorage.setItem("mathernet-right-collapsed", "false");
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

function clearFormulaSelection() {
  if (state.notesDirty) {
    const leave = window.confirm("You have an unsaved note. Clear this formula without saving?");
    if (!leave) return;
  }
  state.selectionRequest += 1;
  state.selectedId = null;
  state.selectedCard = null;
  state.introduction = null;
  state.introductionLoading = false;
  state.introductionError = "";
  state.notesDirty = false;
  renderAll();
  syncUrl();
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

function setConnectionIndicator(status, label) {
  const normalized = ["connected", "check_settings"].includes(status) ? status : "checking";
  if (elements.aiConnectionIndicator) {
    elements.aiConnectionIndicator.dataset.state = normalized;
    elements.aiConnectionIndicator.title = `AI connection: ${label}`;
  }
  if (elements.aiConnectionLabel) {
    elements.aiConnectionLabel.textContent = `AI connection: ${label}`;
  }
}

function providerPreset(provider) {
  return state.gateway?.provider_presets?.find((preset) => preset.id === provider);
}

function providerDraft(provider) {
  if (!state.providerDrafts[provider]) state.providerDrafts[provider] = {};
  return state.providerDrafts[provider];
}

function captureProviderDraft(provider) {
  if (!provider || elements.settingsProvider.value !== provider) return;
  const draft = providerDraft(provider);
  const apiKey = document.querySelector("#settings-api-key");
  const model = document.querySelector("#settings-model");
  if (apiKey) draft.apiKey = apiKey.value;
  if (model) draft.model = model.value;
}

function renderProviderForm(provider) {
  const preset = providerPreset(provider);
  if (!preset) {
    elements.providerForm.innerHTML = `
      <div class="provider-form-empty">
        <p class="section-kicker">Provider setup</p>
        <h3>Choose an AI provider</h3>
        <p>Connection fields will appear here.</p>
      </div>
    `;
    return;
  }

  const draft = providerDraft(provider);
  const savedForProvider = state.gateway?.provider === provider ? state.gateway : null;
  const keyHint = savedForProvider?.api_key_hint
    ? `Saved key ${savedForProvider.api_key_hint}`
    : "Paste your API key";
  const modelField = preset.managed_model
    ? `
      <div class="managed-model">
        <div>
          <p class="managed-model-label">Managed model</p>
          <strong>${escapeHTML(preset.default_model)}</strong>
        </div>
        <span class="managed-model-badge">Automatic</span>
      </div>
      <p class="field-hint">Mathernet selects DeepSeek's stable chat model automatically. No model ID is required.</p>
    `
    : `
      <div class="field">
        <div class="field-label-row">
          <label for="settings-model">Model route</label>
          <button class="button button-quiet button-small" id="load-provider-models" type="button">
            ${icon("refresh")}
            Load models
          </button>
        </div>
        <input
          id="settings-model"
          name="model"
          type="text"
          autocomplete="off"
          list="provider-model-options"
          placeholder="provider/model-id"
          value="${escapeHTML(draft.model ?? savedForProvider?.model ?? preset.default_model ?? "")}"
          spellcheck="false"
        >
        <datalist id="provider-model-options"></datalist>
        <p class="field-hint">OpenRouter sends each request to this exact routed model ID.</p>
      </div>
    `;

  elements.providerForm.innerHTML = `
    <div class="provider-form-heading">
      <div>
        <p class="section-kicker">${escapeHTML(preset.label)} connection</p>
        <h3 id="provider-form-title">${preset.managed_model ? "Connect with an API key" : "Connect and choose a route"}</h3>
        <p class="provider-form-description">${escapeHTML(preset.description)}</p>
      </div>
      <a class="provider-account-link" href="${escapeHTML(preset.api_key_url)}" target="_blank" rel="noreferrer">
        API keys
        ${icon("external")}
      </a>
    </div>
    <div class="field">
      <label for="settings-api-key">API key</label>
      <input
        id="settings-api-key"
        name="api_key"
        type="password"
        autocomplete="off"
        placeholder="${escapeHTML(keyHint)}"
        value="${escapeHTML(draft.apiKey ?? "")}"
        spellcheck="false"
      >
      <p class="field-hint">Stored locally and never shown after saving.</p>
    </div>
    ${modelField}
    <p class="settings-status" id="settings-ai-message" role="status"></p>
  `;

  document.querySelector("#load-provider-models")?.addEventListener("click", loadProviderModels);
}

function syncProviderOptions(provider) {
  elements.settingsProvider.value = provider || "";
  document.querySelectorAll(".provider-radio").forEach((radio) => {
    radio.checked = radio.value === provider;
    radio.closest(".provider-option")?.classList.toggle("is-selected", radio.checked);
  });
  renderProviderForm(provider);
  if (!provider) {
    setSettingsState(elements.settingsAiState, "idle", "Choose provider");
  } else if (state.gateway?.provider !== provider) {
    setSettingsState(elements.settingsAiState, "idle", "Not tested");
  } else if (!state.gateway?.ai_configured) {
    setSettingsState(elements.settingsAiState, "idle", "Not configured");
  } else if (state.gateway?.ai_connection_status === "connected") {
    setSettingsState(elements.settingsAiState, "success", "Connected");
  } else if (state.gateway?.ai_connection_status === "check_settings") {
    setSettingsState(elements.settingsAiState, "error", "Check settings");
  } else {
    setSettingsState(elements.settingsAiState, "idle", "Checking…");
  }
}

function gatewayPayload() {
  const payload = {
    provider: elements.settingsProvider.value,
    api_key: document.querySelector("#settings-api-key")?.value.trim() || "",
  };
  const model = document.querySelector("#settings-model")?.value.trim();
  if (model) payload.model = model;
  return payload;
}

function applyGatewayConfig(config) {
  state.gateway = config;
  state.firstRun = Boolean(config.first_run);
  const provider = config.provider || "";
  if (provider) {
    state.providerDrafts[provider] = {
      ...(state.providerDrafts[provider] || {}),
      apiKey: "",
      model: config.model || "",
    };
  }
  syncProviderOptions(provider);
  const connectionLabel =
    config.ai_connection_status === "connected"
      ? "Connected"
      : config.ai_connection_status === "check_settings"
        ? "Check settings"
        : config.ai_configured
          ? "Checking…"
          : "Not configured";
  setConnectionIndicator(config.ai_connection_status, connectionLabel);
}

async function loadGatewaySettings() {
  try {
    const config = await api("/api/gateway");
    applyGatewayConfig(config);
    if (state.firstRun) {
      openSettingsDialog();
    } else if (config.ai_configured) {
      refreshGatewayConnection();
    }
  } catch (error) {
    showToast(error.message, "error");
  }
}

function openSettingsDialog() {
  elements.settingsError.textContent = "";
  const message = document.querySelector("#settings-ai-message");
  if (message) message.textContent = "";
  elements.settingsDialog.showModal();
  if (state.gateway?.ai_configured) refreshGatewayConnection();
}

function validateGatewayPayload(payload) {
  if (!payload.provider) return "Choose an AI provider.";
  const preset = providerPreset(payload.provider);
  const savedForProvider = state.gateway?.provider === payload.provider ? state.gateway : null;
  if (!payload.api_key && !savedForProvider?.api_key_hint) return "Enter an API key for the selected provider.";
  if (preset?.model_required && !payload.model) return "Choose the OpenRouter model route to use.";
  return "";
}

async function loadProviderModels() {
  const provider = elements.settingsProvider.value;
  const preset = providerPreset(provider);
  const button = document.querySelector("#load-provider-models");
  const input = document.querySelector("#settings-model");
  const datalist = document.querySelector("#provider-model-options");
  const apiKey = document.querySelector("#settings-api-key")?.value.trim() || "";
  const savedForProvider = state.gateway?.provider === provider ? state.gateway : null;
  if (!preset?.models_endpoint_path || !input || !datalist) return;
  if (!apiKey && !savedForProvider?.api_key_hint) {
    elements.settingsError.textContent = "Enter the OpenRouter API key before loading models.";
    document.querySelector("#settings-api-key")?.focus();
    return;
  }

  setBusy(button, true, "Loading…");
  elements.settingsError.textContent = "";
  try {
    const result = await api("/api/gateway/models", {
      method: "POST",
      body: JSON.stringify({ provider, api_key: apiKey }),
    });
    datalist.innerHTML = result.models
      .map((model) => `<option value="${escapeHTML(model.id)}">${escapeHTML(model.name)}</option>`)
      .join("");
    if (!input.value.trim() && result.default_model) input.value = result.default_model;
    showToast(`${result.models.length} model routes loaded.`);
  } catch (error) {
    elements.settingsError.textContent = error.message;
  } finally {
    setBusy(button, false);
  }
}

async function saveGatewaySettings(silent = false) {
  const payload = gatewayPayload();
  const error = validateGatewayPayload(payload);
  elements.settingsError.textContent = error;
  if (error) return false;
  setBusy(elements.settingsSave, true, "Saving…");
  try {
    applyGatewayConfig(await api("/api/gateway", { method: "PATCH", body: JSON.stringify(payload) }));
    const connected = await refreshGatewayConnection();
    if (!silent && connected) {
      closeDialog(elements.settingsDialog);
      showToast("Connection settings saved locally.");
    }
    return connected;
  } catch (requestError) {
    elements.settingsError.textContent = requestError.message;
    return false;
  } finally {
    setBusy(elements.settingsSave, false);
  }
}

async function testGatewayConnection() {
  await saveGatewaySettings(true);
}

async function refreshGatewayConnection() {
  const button = document.querySelector("#test-ai");
  const message = document.querySelector("#settings-ai-message");
  setBusy(button, true, "Testing…");
  if (message) {
    message.textContent = "";
    message.className = "settings-status";
  }
  try {
    const result = await api("/api/gateway/test-ai", { method: "POST" });
    state.gateway = {
      ...(state.gateway || {}),
      ai_connection_status: result.ai_connection_status || "connected",
      ai_connection_message: result.message || "connected",
      ai_connection_checked_at: result.ai_connection_checked_at || "",
    };
    if (message) {
      message.textContent = "Connection is ready.";
      message.classList.add("is-success");
    }
    setSettingsState(elements.settingsAiState, "success", "Connected");
    setConnectionIndicator("connected", "Connected");
    return true;
  } catch (error) {
    state.gateway = {
      ...(state.gateway || {}),
      ai_connection_status: "check_settings",
      ai_connection_message: error.message,
    };
    if (message) {
      message.textContent = error.message;
      message.classList.add("is-error");
    }
    setSettingsState(elements.settingsAiState, "error", "Check settings");
    setConnectionIndicator("check_settings", "Check settings");
    return false;
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
      body: JSON.stringify({
        query,
        map_session_id: state.activeMapSessionId || "",
      }),
    });
    const formulaId = result.formula.formula.id;
    if (state.activeMapSessionId) {
      await api(`/api/map-sessions/${encodeURIComponent(state.activeMapSessionId)}/formulas`, {
        method: "POST",
        body: JSON.stringify({ formula_id: formulaId }),
      });
    }
    await loadMapSessions({ preferredId: state.activeMapSessionId });
    await selectFormula(formulaId);
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
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setBusy(elements.confirmReject, false);
  }
}

function openRelationshipDialog({ sourceId, targetId }) {
  const source = state.graph?.nodes?.find((node) => node.id === sourceId);
  const target = state.graph?.nodes?.find((node) => node.id === targetId);
  if (!source || !target) return;
  state.pendingRelationship = { sourceId, targetId };
  elements.relationshipSource.textContent = source.name;
  elements.relationshipTarget.textContent = target.name;
  elements.relationshipKind.value = "prerequisite";
  elements.relationshipReason.value = "These formulas describe related mathematical structures.";
  elements.relationshipDialog.showModal();
}

function openUnlinkDialog({ edge }) {
  if (!edge) return;
  state.pendingUnlinkEdge = edge;
  elements.unlinkRelation.textContent = relationLabels[edge.relation] || edge.relation;
  elements.unlinkFormulas.textContent = `${edge.source_name} → ${edge.target_name}`;
  elements.unlinkDialog.showModal();
}

function openRelationshipExploreDialog({ edge }) {
  if (!edge) return;
  state.pendingExploreEdge = edge;
  elements.relationshipExploreSource.textContent = edge.source_name;
  elements.relationshipExploreTarget.textContent = edge.target_name;
  elements.relationshipExploreKind.textContent = relationLabels[edge.relation] || edge.relation;
  const origin = edge.created_by === "manual" ? "Your relationship" : "AI relationship";
  const evidence = edge.evidence_status === "supported"
    ? "Evidence-supported"
    : "Unconfirmed";
  elements.relationshipExploreOrigin.textContent = `${origin} · ${evidence}`;
  elements.relationshipExploreNote.textContent = edge.rationale;
  elements.relationshipExploreDialog.showModal();
}

function openRelationshipDeepDive(edge) {
  if (!edge) return;
  state.deepDiveMode = "relationship";
  state.deepDiveFormulaId = edge.id;
  state.deepDiveEdge = edge;
  state.activeDeepSession = null;
  elements.deepDiveTitle.textContent = `${edge.source_name} → ${edge.target_name}`;
  if (!elements.deepDiveDialog.open) elements.deepDiveDialog.showModal();
  loadDeepDiveSessions({ createIfEmpty: true });
}

async function createRelationship(event) {
  event.preventDefault();
  const pending = state.pendingRelationship;
  if (!pending) return;
  setBusy(elements.confirmRelationship, true, "Checking relationship…");
  try {
    const created = await api("/api/edges", {
      method: "POST",
      body: JSON.stringify({
        source_id: pending.sourceId,
        target_id: pending.targetId,
        relation: elements.relationshipKind.value,
        rationale: elements.relationshipReason.value.trim(),
        source_ids: [],
        manual: true,
      }),
    });
    closeDialog(elements.relationshipDialog);
    state.pendingRelationship = null;
    await loadMapSessions({ preferredId: state.activeMapSessionId });
    showToast(
      created.evidence_status === "supported"
        ? "Relationship verified and connected."
        : "Relationship saved as an unconfirmed dashed connection.",
      created.evidence_status === "supported" ? "success" : "notice",
    );
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setBusy(elements.confirmRelationship, false);
  }
}

async function removeRelationship() {
  const edge = state.pendingUnlinkEdge;
  if (!edge) return;
  setBusy(elements.confirmUnlink, true, "Removing…");
  try {
    await api(`/api/edges/${encodeURIComponent(edge.id)}`, {
      method: "DELETE",
      body: JSON.stringify({ expected_updated_at: edge.updated_at }),
    });
    closeDialog(elements.unlinkDialog);
    state.pendingUnlinkEdge = null;
    await loadMapSessions({ preferredId: state.activeMapSessionId });
    showToast("Relationship removed.");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setBusy(elements.confirmUnlink, false);
  }
}

function openSessionComposer() {
  elements.sessionCreate.hidden = false;
  elements.sessionName.value = "";
  elements.sessionName.focus();
}

async function createMapSession(event) {
  event.preventDefault();
  const name = elements.sessionName.value.trim();
  if (!name) {
    elements.sessionName.focus();
    return;
  }
  const button = elements.sessionCreate.querySelector("button[type='submit']");
  setBusy(button, true, "Creating…");
  try {
    const session = await api("/api/map-sessions", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    elements.sessionCreate.hidden = true;
    await loadMapSessions({ preferredId: session.id });
    showToast(`Mind map “${session.name}” created.`);
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setBusy(button, false);
  }
}

async function updateMapSession(sessionId, payload) {
  try {
    const updated = await api(`/api/map-sessions/${encodeURIComponent(sessionId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    state.sessionMenuId = null;
    state.renamingSessionId = null;
    await loadMapSessions({ preferredId: sessionId });
    showToast(payload.name ? "Mind map renamed." : updated.pinned ? "Mind map pinned." : "Mind map unpinned.");
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function deleteMapSession(sessionId) {
  const session = state.mapSessions.find((item) => item.id === sessionId);
  const confirmed = window.confirm(`Delete the mind map “${session?.name || "Untitled"}”? Formula cards will stay in your library.`);
  if (!confirmed) return;
  try {
    await api(`/api/map-sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
    state.sessionMenuId = null;
    if (state.activeMapSessionId === sessionId) {
      state.activeMapSessionId = null;
      state.activeMapSession = null;
      state.selectedId = null;
      state.selectedCard = null;
    }
    await loadMapSessions();
    showToast("Mind map deleted.");
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function deleteSelectedFormula() {
  const card = state.selectedCard;
  if (!card) return;
  const name = card.formula.name;
  const confirmed = window.confirm(`Delete “${name}” from Mathernet? This removes the formula card and its relationships from every mind map.`);
  if (!confirmed) return;
  setBusy(elements.deleteFormula, true, "");
  try {
    await api(`/api/formulas/${encodeURIComponent(card.formula.id)}`, { method: "DELETE" });
    state.selectedId = null;
    state.selectedCard = null;
    state.introduction = null;
    state.notesDirty = false;
    await loadMapSessions({ preferredId: state.activeMapSessionId });
    showToast(`“${name}” deleted.`);
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setBusy(elements.deleteFormula, false);
  }
}

function bindEvents() {
  elements.globalSearch.addEventListener("submit", submitFormulaSearch);

  let libraryTimer;
  elements.libraryQuery.addEventListener("input", () => {
    window.clearTimeout(libraryTimer);
    libraryTimer = window.setTimeout(() => {
      state.query = elements.libraryQuery.value.trim();
      renderLibrary();
      syncUrl();
    }, 120);
  });

  elements.newMapSession.addEventListener("click", openSessionComposer);
  elements.sessionCreate.addEventListener("submit", createMapSession);
  elements.backToSessions.addEventListener("click", () => {
    state.leftView = "sessions";
    state.sessionMenuId = null;
    state.renamingSessionId = null;
    renderSessionList();
    applyPanelLayout();
  });
  elements.sessionList.addEventListener("submit", (event) => {
    const form = event.target.closest("[data-rename-session]");
    if (!form) return;
    event.preventDefault();
    const item = event.target.closest("[data-session-id]");
    const name = new FormData(form).get("name")?.toString().trim();
    if (item && name) updateMapSession(item.dataset.sessionId, { name });
  });
  elements.sessionList.addEventListener("click", (event) => {
    const item = event.target.closest("[data-session-id]");
    if (!item) return;
    const sessionId = item.dataset.sessionId;
    if (event.target.closest("[data-open-session]")) {
      openMapSession(sessionId);
    } else if (event.target.closest("[data-session-menu]")) {
      state.sessionMenuId = state.sessionMenuId === sessionId ? null : sessionId;
      state.renamingSessionId = null;
      renderSessionList();
    } else if (event.target.closest("[data-session-rename]")) {
      state.sessionMenuId = null;
      state.renamingSessionId = sessionId;
      renderSessionList();
    } else if (event.target.closest("[data-session-pin]")) {
      const session = state.mapSessions.find((item) => item.id === sessionId);
      updateMapSession(sessionId, { pinned: !session?.pinned });
    } else if (event.target.closest("[data-session-delete]")) {
      deleteMapSession(sessionId);
    }
  });

  elements.formulaList.addEventListener("click", (event) => {
    const row = event.target.closest("[data-formula-id]");
    if (row) selectFormula(row.dataset.formulaId);
  });

  document.addEventListener("click", (event) => {
    if (!event.target.closest(".session-item") && state.sessionMenuId) {
      state.sessionMenuId = null;
      renderSessionList();
    }
    const sessionComposerOpen = !elements.sessionCreate.hidden;
    const clickedComposer = event.target.closest("#session-create, #new-map-session");
    if (
      sessionComposerOpen
      && !clickedComposer
      && !elements.sessionName.value.trim()
    ) {
      elements.sessionCreate.hidden = true;
    }
  });

  elements.toggleLeftPanel.addEventListener("click", () => {
    state.leftCollapsed = !state.leftCollapsed;
    localStorage.setItem("mathernet-left-collapsed", String(state.leftCollapsed));
    applyPanelLayout();
  });
  elements.toggleRightPanel.addEventListener("click", () => {
    state.rightCollapsed = !state.rightCollapsed;
    localStorage.setItem("mathernet-right-collapsed", String(state.rightCollapsed));
    applyPanelLayout();
    if (!state.rightCollapsed && state.selectedId) refreshSelection();
  });
  elements.deleteFormula.addEventListener("click", deleteSelectedFormula);

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
      captureProviderDraft(elements.settingsProvider.value);
      const draft = providerDraft(radio.value);
      const preset = providerPreset(radio.value);
      if (preset?.model_required && !draft.model) draft.model = preset.default_model || "";
      syncProviderOptions(radio.value);
    });
  });
  elements.settingsDialog.addEventListener("cancel", (event) => {
    if (state.firstRun) event.preventDefault();
  });
  elements.confirmReject.addEventListener("click", confirmReject);
  elements.relationshipForm.addEventListener("submit", createRelationship);
  elements.relationshipSwap.addEventListener("click", () => {
    const pending = state.pendingRelationship;
    if (!pending) return;
    state.pendingRelationship = {
      sourceId: pending.targetId,
      targetId: pending.sourceId,
    };
    const source = elements.relationshipSource.textContent;
    elements.relationshipSource.textContent = elements.relationshipTarget.textContent;
    elements.relationshipTarget.textContent = source;
  });
  elements.confirmUnlink.addEventListener("click", removeRelationship);
  elements.confirmRelationshipExplore.addEventListener("click", () => {
    const edge = state.pendingExploreEdge;
    if (!edge) return;
    closeDialog(elements.relationshipExploreDialog);
    state.pendingExploreEdge = null;
    openRelationshipDeepDive(edge);
  });
  elements.themeToggle.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    setTheme(next);
  });

  document.querySelector("#refresh-data").addEventListener("click", async () => {
    const button = document.querySelector("#refresh-data");
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    await loadMapSessions({ preferredId: state.activeMapSessionId });
    button.disabled = false;
    button.removeAttribute("aria-busy");
    showToast("Mind map refreshed.");
  });

  elements.overviewContent.addEventListener("click", (event) => {
    if (event.target.closest("[data-open-deep-dive]")) openDeepDive();
    if (event.target.closest("[data-retry-introduction]") && state.selectedId) {
      loadFormulaIntroduction(state.selectedId);
    }
  });

  elements.deepDiveContent.addEventListener("click", (event) => {
    if (event.target.closest("[data-retry-deep-dive]")) {
      loadDeepDiveSessions({ createIfEmpty: true });
    }
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
  await loadMapSessions();
}

initialize();
