const state = {
  formulas: [],
  total: 0,
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
  gateway: null,
  firstRun: true,
};

const elements = {
  connection: document.querySelector("#connection-state"),
  connectionLabel: document.querySelector("#connection-label"),
  globalSearch: document.querySelector("#global-search"),
  globalQuery: document.querySelector("#global-query"),
  libraryQuery: document.querySelector("#library-query"),
  formulaCount: document.querySelector("#formula-count"),
  formulaList: document.querySelector("#formula-list"),
  graphEmpty: document.querySelector("#graph-empty"),
  graphDescription: document.querySelector("#graph-description"),
  inspectorTitle: document.querySelector("#inspector-title"),
  inspectorFormula: document.querySelector("#inspector-formula"),
  inspectorStatus: document.querySelector("#inspector-status"),
  overviewEmpty: document.querySelector("#overview-empty"),
  overviewContent: document.querySelector("#overview-content"),
  sourcesEmpty: document.querySelector("#sources-empty"),
  sourcesContent: document.querySelector("#sources-content"),
  learningEmpty: document.querySelector("#learning-empty"),
  learningContent: document.querySelector("#learning-content"),
  learnDialog: document.querySelector("#learn-dialog"),
  learnForm: document.querySelector("#learn-form"),
  learnQuery: document.querySelector("#learn-query"),
  learnError: document.querySelector("#learn-error"),
  learnSubmit: document.querySelector("#learn-submit"),
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
  state.tab = ["overview", "sources", "learning"].includes(tab) ? tab : "overview";
  state.selectedId = params.get("formula");
  elements.globalQuery.value = state.query;
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
  elements.formulaCount.textContent = String(state.total);
  elements.formulaList.setAttribute("aria-busy", "false");
  if (!state.formulas.length) {
    elements.formulaList.innerHTML = `
      <div class="list-empty">
        <h3>No formulas found</h3>
        <p>Try another name or learn a new formula from an approved source.</p>
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
            <span>${formula.source_count} source${formula.source_count === 1 ? "" : "s"}</span>
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
  const ai = formula.ai_module;
  const user = formula.user_module;
  elements.overviewEmpty.hidden = true;
  elements.overviewContent.hidden = false;
  elements.overviewContent.innerHTML = `
    <section class="inspector-section">
      <span class="section-label">Formula identity</span>
      <div
        class="formula-display formula-latex"
        role="math"
        aria-label="${escapeHTML(formulaValue(card) || card.display)}"
      >${latexMarkup(formulaValue(card), card.display, true)}</div>
      <p class="body-copy">${escapeHTML(ai.summary)}</p>
    </section>
    <section class="inspector-section">
      <span class="section-label">AI Module · Generated</span>
      <h3>What it means</h3>
      <p class="body-copy">${escapeHTML(ai.explanation)}</p>
      ${
        ai.examples.length
          ? `<h3>Examples</h3><ul class="example-list">${ai.examples.map((item) => `<li>${escapeHTML(item)}</li>`).join("")}</ul>`
          : ""
      }
      ${
        ai.derivation_steps.length
          ? `<h3>Derivation steps</h3><ol class="derivation-list">${ai.derivation_steps.map((item) => `<li>${escapeHTML(item)}</li>`).join("")}</ol>`
          : ""
      }
    </section>
    <section class="inspector-section">
      <span class="section-label user-label">User Module · Yours</span>
      <h3>Study note</h3>
      <p class="body-copy">${escapeHTML(user.notes || "No personal note yet. Open Learning to write one.")}</p>
      <button class="button button-secondary" type="button" data-open-learning>Open learning notes</button>
    </section>
  `;
}

function renderSources() {
  const card = state.selectedCard;
  if (!card || !card.sources.length) {
    elements.sourcesEmpty.hidden = false;
    elements.sourcesContent.hidden = true;
    elements.sourcesContent.innerHTML = "";
    return;
  }
  elements.sourcesEmpty.hidden = true;
  elements.sourcesContent.hidden = false;
  elements.sourcesContent.innerHTML = `
    <div class="source-list">
      ${card.sources
        .map(
          (source) => `
            <article class="source-item">
              <div class="source-meta">
                <p class="source-publisher">${escapeHTML(source.publisher)}</p>
                <a class="source-link" href="${escapeHTML(safeUrl(source.url))}" target="_blank" rel="noopener noreferrer">
                  Open source ${icon("external")}
                </a>
              </div>
              <h3 class="source-title">${escapeHTML(source.title)}</h3>
              <p class="source-excerpt">${escapeHTML(source.excerpt)}</p>
              <time class="source-time" datetime="${escapeHTML(source.retrieved_at)}">Retrieved ${escapeHTML(formatDate(source.retrieved_at))}</time>
            </article>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderEdges(edges) {
  if (!edges.length) {
    return `
      <div class="list-empty">
        <h3>No dependency decisions</h3>
        <p>Relations appear here when Mathernet finds a supported prerequisite or derivation basis.</p>
      </div>
    `;
  }
  return `
    <div class="edge-list">
      ${edges
        .map((edge) => {
          const pending = edge.requires_user_confirmation;
          return `
            <article class="edge-item">
              <div class="edge-direction">
                <strong>${escapeHTML(edge.source_name)}</strong>
                <span class="edge-arrow" aria-hidden="true">→</span>
                <strong>${escapeHTML(edge.target_name)}</strong>
              </div>
              <span class="edge-relation">${escapeHTML(relationLabels[edge.relation] || edge.relation)}</span>
              <p class="edge-rationale">${escapeHTML(edge.rationale)}</p>
              ${
                pending
                  ? `<div class="edge-actions">
                      <button class="edge-action confirm" type="button" data-confirm-edge="${escapeHTML(edge.id)}" data-edge-updated="${escapeHTML(edge.updated_at)}">
                        ${icon("check")} Confirm relation
                      </button>
                      <button class="edge-action reject" type="button" data-reject-edge="${escapeHTML(edge.id)}" data-edge-updated="${escapeHTML(edge.updated_at)}">
                        ${icon("x")} Reject
                      </button>
                    </div>`
                  : `<div class="decision-state ${edge.verification_status === "rejected" ? "rejected" : "accepted"}">
                      ${icon(edge.verification_status === "rejected" ? "x" : "check")}
                      ${escapeHTML(edge.verification_status.replaceAll("_", " "))}
                    </div>`
              }
            </article>
          `;
        })
        .join("")}
    </div>
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
  const edges = [...card.incoming_edges, ...card.outgoing_edges];
  const pendingCount = edges.filter((edge) => edge.requires_user_confirmation).length;
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
      <p class="field-hint">Study status records activity, not mastery.</p>
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
    <section class="inspector-section">
      <span class="section-label">Dependency decisions</span>
      <h3>${pendingCount ? `${pendingCount} suggestion${pendingCount === 1 ? "" : "s"} need your decision` : "Connected relationships"}</h3>
      ${renderEdges(edges)}
    </section>
  `;
}

function renderInspector() {
  const card = state.selectedCard;
  if (!card) {
    elements.inspectorTitle.textContent = "Select a formula";
    elements.inspectorFormula.textContent = "Choose an item from the library or graph.";
    elements.inspectorFormula.removeAttribute("role");
    elements.inspectorFormula.removeAttribute("aria-label");
    elements.inspectorStatus.textContent = "No selection";
    elements.inspectorStatus.className = "status-badge neutral";
  } else {
    const formula = card.formula;
    elements.inspectorTitle.textContent = formula.name;
    elements.inspectorFormula.setAttribute("role", "math");
    elements.inspectorFormula.setAttribute("aria-label", formulaValue(card) || card.display);
    elements.inspectorFormula.innerHTML = latexMarkup(formulaValue(card), card.display);
    elements.inspectorStatus.textContent = statusLabels[formula.status] || formula.status;
    elements.inspectorStatus.className = `status-badge ${formula.status}`;
  }
  renderOverview();
  renderSources();
  renderLearning();
  setTab(state.tab, false);
}

function renderAll() {
  renderLibrary();
  renderGraph();
  renderInspector();
}

function setTab(tab, focus = true) {
  state.tab = ["overview", "sources", "learning"].includes(tab) ? tab : "overview";
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
    setConnection(
      true,
      `${state.health.formula_count} formulas · ${state.health.pending_edge_count} pending`,
    );
  } catch {
    setConnection(false, "Local service offline");
  }
}

async function loadFormulas({ focusFirst = false } = {}) {
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
    state.total = payload.total;
    renderLibrary();
    syncUrl();
    if (focusFirst && state.formulas[0]) {
      await selectFormula(state.formulas[0].id);
    }
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
  state.notesDirty = false;
  renderAll();
  syncUrl();
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

function openLearnDialog() {
  elements.learnError.textContent = "";
  elements.learnQuery.value = state.query || "";
  elements.learnDialog.showModal();
  window.setTimeout(() => elements.learnQuery.focus(), 0);
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

async function submitLearn(event) {
  event.preventDefault();
  const query = elements.learnQuery.value.trim();
  elements.learnError.textContent = "";
  if (!query) {
    elements.learnError.textContent = "Enter a formula name or expression.";
    elements.learnQuery.focus();
    return;
  }
  setBusy(elements.learnSubmit, true, "Finding sources…");
  try {
    const result = await api("/api/learn", {
      method: "POST",
      body: JSON.stringify({ query }),
    });
    closeDialog(elements.learnDialog);
    await loadFormulas();
    await loadSelection(result.formula.formula.id);
    showToast(result.created ? "Formula card created." : "Existing formula card opened.");
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
    elements.learnError.textContent =
      error.reasonCode === "no_reliable_source"
        ? "The configured source tool returned no usable material. Try another formula name or leave MCP empty to use the AI provider directly."
        : error.message;
    elements.learnQuery.focus();
  } finally {
    setBusy(elements.learnSubmit, false);
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
  elements.globalSearch.addEventListener("submit", async (event) => {
    event.preventDefault();
    state.query = elements.globalQuery.value.trim();
    elements.libraryQuery.value = state.query;
    await loadFormulas({ focusFirst: true });
  });

  let libraryTimer;
  elements.libraryQuery.addEventListener("input", () => {
    window.clearTimeout(libraryTimer);
    libraryTimer = window.setTimeout(async () => {
      state.query = elements.libraryQuery.value.trim();
      elements.globalQuery.value = state.query;
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

  document.querySelectorAll("#open-learn, #library-learn").forEach((button) => {
    button.addEventListener("click", openLearnDialog);
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

  elements.learnForm.addEventListener("submit", submitLearn);
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
    if (event.target.closest("[data-open-learning]")) setTab("learning");
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
