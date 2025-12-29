/* AEGIS UI - app.js (single-file frontend logic)
   - FIXED: no HTML in CSS, no /chat/new dependency
   - Robust: tolerates different response shapes from backend
*/

const MODES = { CHAT: "chat", WEB: "web", URL: "url", CRYPTO: "crypto", IMAGE: "image" };
const LANG = { ES: "es", EN: "en" };

const CHAT_MAX_TIMEOUT_MS = 420000;
const RESET_CONV_ON_LOAD = false;
const TRADE_TEST_DEFAULT = false; // keep trades educational unless you flip it server-side

const endpoints = {
  websearch: "/websearch",
  chat: "/chat",
  fetchUrl: "/fetch_url",
  conversations: "/chat/list",
  archiveConversation: (id) => `/chat/${id}/archive`,
  unarchiveConversation: (id) => `/chat/${id}/unarchive`,
  deleteConversation: (id) => `/chat/${id}`,
  analyzeImage: "/analyze_image",
  conversationEvents: (id) => `/chat/${id}/events`,

  cryptoPredict: "/crypto/predict",
  cryptoModels: "/crypto/models",
  cryptoOhlcv: "/crypto/ohlcv",
  cryptoTrade: "/crypto/trade",
  cryptoTrades: "/crypto/trades",
  cryptoPnl: "/crypto/pnl",
  cryptoNews: "/crypto/news",
  adminRefresh: "/admin/refresh-crypto",
  adminRefreshLog: "/admin/refresh-log",

  toolsTree: "/tools/tree",
  toolsContent: "/tools/content",

  filesUploadZip: "/files/upload-zip",
  filesClone: "/files/clone",
  filesDeleteProject: "/tools/delete_project",
  filesIngest: "/files/ingest",
  filesIngestStatus: "/files/ingest/status",
  filesIngestJobs: "/files/ingest/jobs",
  filesIngestLog: "/files/ingest/log",
};

const state = {
  mode: MODES.CHAT,
  lang: localStorage.getItem("aegis_lang") || LANG.ES,
  conversationId: localStorage.getItem("aegis_conv") || null,
  useExistingConversation: localStorage.getItem("aegis_use_existing") === "1",
  apiKey: localStorage.getItem("aegis_api_key") || "",

  pending: false,
  activeControllers: new Set(),
  cancelledByUser: false,
  lastLatencyMs: null,

  // UI / sidebar
  currentProjectRoot: "app",

  // crypto + chart
  chartSymbol: "BTCUSDT",
  chartInstance: null,
  lastPoints: [],
  tradesOnChart: [],
  cryptoModelsMeta: { available: ["ensemble"], default: "ensemble" },
  selectedCryptoModel: "ensemble",
  savePredictions: JSON.parse(localStorage.getItem("aegis_save_preds") || "true"),
  alertsOn: JSON.parse(localStorage.getItem("aegis_alerts") || "false"),
  showNewsMarkers: true,

  // timers
  liveTimer: null,
  newsTimer: null,
  logsTimer: null,
  logIsAdmin: false,
  alertsTimer: null,
  ingestPollTimer: null,
  ingestJobsTimer: null,
  ingestJobId: null,
  convEventsTimer: null,
  convEventsSince: null,
  convEventsItems: [],

  // session modal
  conversationList: [],
  conversationsIncludeArchived: false,

  // logs
  logPath: null,

  // alerts
  seenAlerts: new Set(),

  // theme
  theme: "future", // default: future palette; toggle removed from header
};

const dom = {};

document.addEventListener("DOMContentLoaded", () => {
  cacheDom();
  wireUI();
  initState();
  updateAllUI();
  appendBubble(state.lang === LANG.ES ? "AEGIS listo." : "AEGIS ready.", "bot");
  localizeHelp();
});

function cacheDom() {
  dom.chat = document.getElementById("chat");
  dom.modeIndicator = document.getElementById("modeIndicator");
  dom.msgInput = document.getElementById("msg");
  dom.sendBtn = document.getElementById("sendBtn");
  dom.cancelBtn = document.getElementById("cancelBtn");

  dom.webBtn = document.getElementById("webBtn");
  dom.urlBtn = document.getElementById("urlBtn");
  dom.cryptoBtn = document.getElementById("cryptoBtn");
  dom.imgBtn = document.getElementById("imgBtn");
  dom.imgInput = document.getElementById("imgInput");

  dom.langEs = document.getElementById("langEs");
  dom.langEn = document.getElementById("langEn");

  dom.convIdDisplay = document.getElementById("conv-id-display");
  dom.convIdChip = document.getElementById("conv-id-chip");
  dom.timeoutLabel = document.getElementById("timeout-label");
  dom.convEventsList = document.getElementById("convEventsList");
  dom.convEventsRefresh = document.getElementById("convEventsRefresh");

  dom.apiKeyBtn = document.getElementById("apiKeyBtn");
  dom.helpBtn = document.getElementById("helpBtn");
  dom.helpModal = document.getElementById("helpModal");
  dom.helpClose = document.getElementById("helpClose");

  dom.hintBtn = document.getElementById("hintBtn");
  dom.hintTooltip = document.getElementById("chat-hint-tooltip");

  dom.sessionsBtn = document.getElementById("sessionsBtn");
  dom.sessionsModal = document.getElementById("sessionsModal");
  dom.sessionsClose = document.getElementById("sessionsClose");
  dom.sessionsList = document.getElementById("sessionsList");
  dom.sessionsIncludeArchived = document.getElementById("sessionsIncludeArchived");

  // sidebar sources
  dom.sourcesTitle = document.getElementById("sources-title");
  dom.sourcesContent = document.getElementById("sources-content");
  dom.logsLiveToggle = document.getElementById("logsLiveToggle");
  dom.savePredToggle = document.getElementById("savePredToggle");
  dom.alertsToggle = document.getElementById("alertsToggle");
  dom.predsBtn = document.getElementById("predsBtn");
  dom.pnlBtn = document.getElementById("pnlBtn");
  dom.statsBtn = document.getElementById("statsBtn");

  dom.newsList = document.getElementById("news-list");
  dom.newsMomentum = document.getElementById("newsMomentum");
  dom.newsRefreshBtn = document.getElementById("newsRefreshBtn");

  // files
  dom.treeBtn = document.getElementById("treeBtn");
  dom.projectSelect = document.getElementById("projectSelect");
  dom.refreshTreeBtn = document.getElementById("refreshTreeBtn");
  dom.projectTree = document.getElementById("projectTree");
  dom.projectUploadBtn = document.getElementById("projectUploadBtn");
  dom.projectUploadInput = document.getElementById("projectUploadInput");
  dom.projectCloneBtn = document.getElementById("projectCloneBtn");
  dom.projectDeleteBtn = document.getElementById("projectDeleteBtn");
  dom.ingestStatusBtn = document.getElementById("ingestStatusBtn");
  dom.ingestStatusText = document.getElementById("ingestStatusText");
  dom.ingestJobsList = document.getElementById("ingestJobsList");
  dom.ingestJobsRefresh = document.getElementById("ingestJobsRefresh");

  dom.fileViewerTitle = document.getElementById("fileViewerTitle");
  dom.fileViewerBody = document.getElementById("fileViewerBody");
  dom.copyFileBtn = document.getElementById("copyFileBtn");

  // crypto controls
  dom.cryptoInline = document.getElementById("cryptoInline");
  dom.cryptoModelSelect = document.getElementById("cryptoModelSelect");
  dom.cryptoHorizon = document.getElementById("cryptoHorizon");
  dom.chatTradeQty = document.getElementById("chatTradeQty");
  dom.buyBtn = document.getElementById("buyBtn");
  dom.sellBtn = document.getElementById("sellBtn");

  // chart
  dom.chartPanel = document.getElementById("chartPanel");
  dom.chartSymbol = document.getElementById("chartSymbol");
  dom.chartRefresh = document.getElementById("chartRefresh");
  dom.chartExpandBtn = document.getElementById("chartExpandBtn");
  dom.chartTitle = document.getElementById("chartTitle");
  dom.priceChart = document.getElementById("priceChart");
  dom.chartLive = document.getElementById("chartLive");
  dom.newsMarkersToggle = document.getElementById("newsMarkersToggle");

  dom.tradeStatus = document.getElementById("tradeStatus");

  dom.predictionCompareTitle = document.getElementById("predictionCompareTitle");
  dom.predictionCompareBody = document.getElementById("predictionCompareBody");
  dom.predictionCompareRefresh = document.getElementById("predictionCompareRefresh");
  dom.predictionCompareHelp = document.getElementById("predictionCompareHelp");
  dom.predictionCompareTooltip = document.getElementById("predictionCompareTooltip");

  dom.adminRefresh = document.getElementById("adminRefresh");

  // tabs
  dom.tabButtons = Array.from(document.querySelectorAll(".tab-btn"));
  dom.tabPanels = {
    sources: document.getElementById("tab-sources"),
    files: document.getElementById("tab-files"),
    session: document.getElementById("tab-session"),
  };
}

function initState() {
  if (RESET_CONV_ON_LOAD) {
    state.conversationId = null;
    state.useExistingConversation = false;
    localStorage.removeItem("aegis_conv");
    localStorage.removeItem("aegis_use_existing");
  }
  applyTheme(state.theme);
  updateConversationIndicators(state.conversationId);
  resetConversationEvents();
  setProjectRoot(state.currentProjectRoot);
}

function wireUI() {
  // send
  dom.sendBtn?.addEventListener("click", onSend);
  dom.msgInput?.addEventListener("input", () => autoSizeTextarea(dom.msgInput));
  dom.msgInput?.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  });

  // cancel
  dom.cancelBtn?.addEventListener("click", () => cancelAllRequests());

  // mode buttons
  dom.webBtn?.addEventListener("click", () => setMode(state.mode === MODES.WEB ? MODES.CHAT : MODES.WEB));
  dom.urlBtn?.addEventListener("click", () => setMode(state.mode === MODES.URL ? MODES.CHAT : MODES.URL));
  dom.cryptoBtn?.addEventListener("click", () => setMode(state.mode === MODES.CRYPTO ? MODES.CHAT : MODES.CRYPTO));
  dom.imgBtn?.addEventListener("click", () => {
    setMode(MODES.IMAGE);
    dom.imgInput?.click();
  });

  // image input
  dom.imgInput?.addEventListener("change", async () => {
    const f = dom.imgInput.files?.[0];
    dom.imgInput.value = "";
    if (!f) return;
    await analyzeImage(f);
  });

  // language
  dom.langEs?.addEventListener("click", () => setLang(LANG.ES));
  dom.langEn?.addEventListener("click", () => setLang(LANG.EN));

  // hint tooltip
  dom.hintBtn?.addEventListener("click", () => toggleHint());

  // help modal
  dom.helpBtn?.addEventListener("click", () => openModal(dom.helpModal));
  dom.helpClose?.addEventListener("click", () => closeModal(dom.helpModal));
  dom.helpModal?.addEventListener("click", (e) => {
    if (e.target === dom.helpModal) closeModal(dom.helpModal);
  });

  // sessions modal
  dom.sessionsBtn?.addEventListener("click", () => openSessionsModal());
  dom.sessionsClose?.addEventListener("click", () => closeSessionsModal());
  dom.sessionsModal?.addEventListener("click", (e) => {
    if (e.target === dom.sessionsModal) closeSessionsModal();
  });
  dom.sessionsIncludeArchived?.addEventListener("change", (e) => {
    state.conversationsIncludeArchived = !!e.target.checked;
    loadConversationList(state.conversationsIncludeArchived);
  });

  // API key
  dom.apiKeyBtn?.addEventListener("click", () => {
    const current = state.apiKey || "";
    const next = prompt(state.lang === LANG.ES ? "X-API-Key (vacío para borrar):" : "X-API-Key (empty to clear):", current);
    if (next == null) return;
    state.apiKey = next.trim();
    if (state.apiKey) localStorage.setItem("aegis_api_key", state.apiKey);
    else localStorage.removeItem("aegis_api_key");
    appendBubble(state.lang === LANG.ES ? "API key actualizada." : "API key updated.", "bot");
  });

  // tabs
  dom.tabButtons?.forEach((b) => {
    b.addEventListener("click", () => {
      const tab = b.getAttribute("data-tab");
      if (tab) activateTab(tab);
    });
  });

  // files tree
  dom.treeBtn?.addEventListener("click", () => {
    activateTab("files");
    loadProjectTree();
  });
  dom.projectSelect?.addEventListener("change", () => {
    setProjectRoot(dom.projectSelect.value || "app");
    loadProjectTree();
  });
  dom.refreshTreeBtn?.addEventListener("click", loadProjectTree);
  dom.copyFileBtn?.addEventListener("click", copyFileViewer);

  // upload zip / clone / delete
  dom.projectUploadBtn?.addEventListener("click", () => dom.projectUploadInput?.click());
  dom.projectUploadInput?.addEventListener("change", uploadZipProject);
  dom.projectCloneBtn?.addEventListener("click", cloneRepo);
  dom.projectDeleteBtn?.addEventListener("click", deleteProject);
  dom.ingestStatusBtn?.addEventListener("click", startIngest);
  dom.ingestJobsRefresh?.addEventListener("click", loadIngestJobs);

  // crypto + chart
  dom.chartRefresh?.addEventListener("click", () => loadChartData(dom.chartSymbol?.value));
  dom.chartExpandBtn?.addEventListener("click", toggleChartExpand);
  dom.chartLive?.addEventListener("change", () => (dom.chartLive.checked ? startLiveChart() : stopLiveChart()));
  dom.newsMarkersToggle?.addEventListener("change", () => {
    state.showNewsMarkers = !!dom.newsMarkersToggle.checked;
    if (state.lastPoints?.length) renderChart(state.lastPoints);
  });

  dom.buyBtn?.addEventListener("click", () => submitTrade("BUY"));
  dom.sellBtn?.addEventListener("click", () => submitTrade("SELL"));

  dom.cryptoModelSelect?.addEventListener("change", () => {
    state.selectedCryptoModel = dom.cryptoModelSelect.value || "ensemble";
    localStorage.setItem("aegis_crypto_model", state.selectedCryptoModel);
    loadCryptoPrediction();
  });
  dom.cryptoHorizon?.addEventListener("change", () => loadCryptoPrediction());

  dom.predictionCompareHelp?.addEventListener("click", (e) => {
    e.stopPropagation();
    const open = dom.predictionCompareHelp.getAttribute("aria-expanded") === "true";
    dom.predictionCompareHelp.setAttribute("aria-expanded", String(!open));
    dom.predictionCompareTooltip.hidden = open;
  });
  dom.predictionCompareRefresh?.addEventListener("click", () => loadPredictionComparison(state.chartSymbol, { force: true }));

  dom.newsRefreshBtn?.addEventListener("click", () => loadNews(state.chartSymbol, { force: true }));

  // sidebar tools
  dom.predsBtn?.addEventListener("click", () => loadRecentPredictions());
  dom.statsBtn?.addEventListener("click", () => loadStats());
  dom.pnlBtn?.addEventListener("click", () => loadPnl());

  dom.savePredToggle?.addEventListener("change", () => {
    state.savePredictions = !!dom.savePredToggle.checked;
    localStorage.setItem("aegis_save_preds", JSON.stringify(state.savePredictions));
    appendBubble(state.lang === LANG.ES ? "Save toggled." : "Save toggled.", "bot");
  });

  dom.alertsToggle?.addEventListener("change", () => {
    state.alertsOn = !!dom.alertsToggle.checked;
    localStorage.setItem("aegis_alerts", JSON.stringify(state.alertsOn));
    if (state.alertsOn) startAlertsPolling();
    else stopAlertsPolling();
  });

  dom.logsLiveToggle?.addEventListener("change", () => {
    if (dom.logsLiveToggle.checked) startLogsPolling();
    else stopLogsPolling();
  });

  // admin refresh
  dom.adminRefresh?.addEventListener("click", adminRefreshCrypto);
  dom.convEventsRefresh?.addEventListener("click", () => loadConversationEvents({ force: true }));
}

function updateAllUI() {
  // lang buttons
  if (dom.langEs && dom.langEn) {
    dom.langEs.classList.toggle("selected", state.lang === LANG.ES);
    dom.langEn.classList.toggle("selected", state.lang === LANG.EN);
    dom.langEs.setAttribute("aria-pressed", String(state.lang === LANG.ES));
    dom.langEn.setAttribute("aria-pressed", String(state.lang === LANG.EN));
  }
  // placeholder
  if (dom.msgInput) dom.msgInput.placeholder = state.lang === LANG.ES ? "Escribe tu mensaje..." : "Type your message...";

  // mode UI
  updateModeIndicator();
  updateModeButtons();
  updateCryptoInlineVisibility();
  updateTogglesVisibility();
  updateLatencyLabel();
  localizeUI();

  // init sources
  clearSources();

  // preload crypto models + chart
  loadCryptoModels();
  loadChartData(state.chartSymbol);
  updatePredictionTooltipText();
}

function setLang(lang) {
  state.lang = lang;
  localStorage.setItem("aegis_lang", state.lang);
  updateAllUI();
  appendBubble(state.lang === LANG.ES ? "Idioma: ES." : "Language: EN.", "bot");
  localizeHelp();
}

function setMode(mode) {
  state.mode = mode;
  updateModeIndicator();
  updateModeButtons();
  updateCryptoInlineVisibility();
  updateTogglesVisibility();

  // when entering crypto, refresh chart/prediction
  if (state.mode === MODES.CRYPTO) {
    loadCryptoModels();
    loadCryptoPrediction();
    loadPredictionComparison(state.chartSymbol, { force: true });
  }
}

function updateModeIndicator() {
  if (!dom.modeIndicator) return;
  const label =
    state.mode === MODES.WEB ? (state.lang === LANG.ES ? "Modo: Web" : "Mode: Web") :
    state.mode === MODES.URL ? (state.lang === LANG.ES ? "Modo: URL" : "Mode: URL") :
    state.mode === MODES.CRYPTO ? (state.lang === LANG.ES ? "Modo: Cripto" : "Mode: Crypto") :
    state.mode === MODES.IMAGE ? (state.lang === LANG.ES ? "Modo: Imagen" : "Mode: Image") :
    (state.lang === LANG.ES ? "Modo: Chat" : "Mode: Chat");
  dom.modeIndicator.textContent = label;
}

function updateModeButtons() {
  const map = [
    [dom.webBtn, state.mode === MODES.WEB],
    [dom.urlBtn, state.mode === MODES.URL],
    [dom.cryptoBtn, state.mode === MODES.CRYPTO],
    [dom.imgBtn, state.mode === MODES.IMAGE],
  ];
  map.forEach(([btn, on]) => {
    if (!btn) return;
    btn.setAttribute("aria-pressed", String(!!on));
    btn.style.opacity = on ? "1" : "";
  });
}

function updateCryptoInlineVisibility() {
  if (!dom.cryptoInline) return;
  const show = state.mode === MODES.CRYPTO;
  dom.cryptoInline.style.display = show ? "flex" : "none";
  dom.cryptoInline.setAttribute("aria-hidden", String(!show));
}

function updateTogglesVisibility() {
  // show save/alerts/logs only in crypto mode
  const show = state.mode === MODES.CRYPTO;
  if (dom.savePredToggle?.parentElement) dom.savePredToggle.parentElement.style.display = show ? "inline-flex" : "none";
  if (dom.alertsToggle?.parentElement) dom.alertsToggle.parentElement.style.display = show ? "inline-flex" : "none";
  if (dom.logsLiveToggle?.parentElement) dom.logsLiveToggle.parentElement.style.display = show ? "inline-flex" : "none";
  if (!show) {
    stopLogsPolling();
    stopAlertsPolling();
  }
  if (dom.savePredToggle) dom.savePredToggle.checked = show && !!state.savePredictions;
  if (dom.alertsToggle) dom.alertsToggle.checked = show && !!state.alertsOn;
}

function toggleHint() {
  if (!dom.hintBtn || !dom.hintTooltip) return;
  const open = dom.hintBtn.getAttribute("aria-expanded") === "true";
  dom.hintBtn.setAttribute("aria-expanded", String(!open));
  dom.hintTooltip.hidden = open;
}

function openModal(node) { node?.classList?.remove("hidden"); }
function closeModal(node) { node?.classList?.add("hidden"); }

function activateTab(tab) {
  dom.tabButtons.forEach((b) => b.classList.toggle("active", b.getAttribute("data-tab") === tab));
  Object.entries(dom.tabPanels).forEach(([k, panel]) => {
    panel?.classList.toggle("active", k === tab);
  });
}

function el(tag, opts = {}) {
  const e = document.createElement(tag);
  if (opts.class) e.className = opts.class;
  if (opts.text != null) e.textContent = opts.text;
  if (opts.html != null) e.innerHTML = opts.html;
  if (opts.attrs) Object.entries(opts.attrs).forEach(([k, v]) => e.setAttribute(k, v));
  return e;
}

function scrollBottom() {
  if (!dom.chat) return;
  dom.chat.scrollTop = dom.chat.scrollHeight;
}

function autoSizeTextarea(node) {
  if (!node) return;
  node.style.height = "auto";
  node.style.height = Math.min(node.scrollHeight, 160) + "px";
}

function appendBubble(text, role = "bot", allowHtml = false) {
  if (!dom.chat) return null;
  const node = el("div", {
    class: `bubble ${role === "user" ? "user" : role === "error" ? "error" : "bot"}`,
    attrs: { role: "article" },
  });

  if (allowHtml) node.innerHTML = sanitizeAndRenderMarkdown(text);
  else node.textContent = text;

  dom.chat.appendChild(node);
  scrollBottom();
  return node;
}

function appendTyping() {
  removeTyping();
  const t = el("div", { class: "bubble bot typing", attrs: { id: "typing-bubble" } });
  t.textContent = state.lang === LANG.ES ? "Escribiendo…" : "Typing…";
  dom.chat?.appendChild(t);
  scrollBottom();
}

function removeTyping() {
  const t = document.getElementById("typing-bubble");
  if (t) t.remove();
}

function sanitizeAndRenderMarkdown(md) {
  try {
    if (typeof marked === "undefined" || typeof DOMPurify === "undefined") {
      const div = document.createElement("div");
      div.textContent = md || "";
      return div.innerHTML;
    }
    const raw = marked.parse(md || "");
    return DOMPurify.sanitize(raw, {
      ALLOWED_TAGS: ["p","a","strong","em","code","pre","ul","ol","li","br","img","blockquote"],
      ALLOWED_ATTR: ["href","target","rel","src","alt"],
    });
  } catch {
    const div = document.createElement("div");
    div.textContent = md || "";
    return div.innerHTML;
  }
}

function formatLatency(ms) {
  if (ms == null) return "—";
  const s = ms / 1000;
  return s < 1 ? `${ms.toFixed(0)} ms` : `${s.toFixed(1)} s`;
}

function applyTheme(name) {
  const allowed = ["original", "future", "retro"];
  state.theme = allowed.includes(name) ? name : "future";
  document.body.dataset.theme = state.theme;
  localStorage.setItem("aegis_theme", state.theme);
  if (dom.themeBtn) {
    const label = state.lang === LANG.ES ? "Tema" : "Theme";
    dom.themeBtn.setAttribute("title", `${label}: ${state.theme}`);
  }
}

function cycleTheme() {
  const order = ["original", "future", "retro"];
  const idx = order.indexOf(state.theme);
  const next = order[(idx + 1) % order.length];
  applyTheme(next);
   appendBubble(
     state.lang === LANG.ES ? `Tema: ${next}` : `Theme: ${next}`,
     "bot"
   );
}

function updateLatencyLabel() {
  if (!dom.timeoutLabel) return;
  const base = state.lang === LANG.ES ? "Tiempo de respuesta: " : "Response time: ";
  const label = base + formatLatency(state.lastLatencyMs);
  dom.timeoutLabel.textContent = label;
}

function localizeUI() {
  const es = state.lang === LANG.ES;
  const map = {
    subtitle: es ? "Memoria • Búsqueda web • LLM local y remoto" : "Memory • Web search • Local + remote LLM",
    send_btn: es ? "Enviar" : "Send",
    trade_buy: es ? "Comprar" : "Buy",
    trade_sell: es ? "Vender" : "Sell",
    live_label: es ? "En vivo" : "Live",
    news_label: es ? "Noticias" : "News",
    alerts_label: es ? "Alertas" : "Alerts",
    save_label: es ? "Guardar" : "Save",
    logs_label: es ? "Logs" : "Logs",
    tab_sources: es ? "Fuentes" : "Sources",
    tab_files: es ? "Archivos" : "Files",
    tab_session: es ? "Sesión" : "Session",
    sources_title: es ? "Fuentes" : "Sources",
    compare_title: es ? "Comparación post-horizonte" : "Post-horizon comparison",
    file_viewer_placeholder: es ? "Selecciona un archivo en Archivos" : "Select a file in Files",
  };
  Object.entries(map).forEach(([key, text]) => {
    document.querySelectorAll(`[data-i18n='${key}']`).forEach((el) => {
      el.textContent = text;
    });
  });
  if (dom.sendBtn) dom.sendBtn.textContent = map.send_btn;
}

function localizeHelp() {
  const es = state.lang === LANG.ES;
  const map = {
    help_title: es ? "Guía rápida de AEGIS" : "AEGIS quick guide",
    hint_title: es ? "Guía breve" : "Quick tips",
    hint_chat: es
      ? "Preguntas generales, debugging local o instrucciones paso a paso."
      : "General questions, local debugging, step-by-step help.",
    hint_web: es
      ? "Agrega web: cuando necesites fuentes recientes o enlaces citables."
      : "Use web: when you need fresh sources or citations.",
    hint_url: es
      ? "Usa url:https://... para que lea y resuma un enlace específico."
      : "Use url:https://... to read and summarize a specific link.",
    hint_crypto: es
      ? "Activa el panel para predicciones, trades simulados y métricas P&L."
      : "Enable the panel for predictions, simulated trades, and P&L metrics.",
    hint_image: es
      ? "Sube capturas y obtén OCR para explicar errores o textos."
      : "Upload screenshots to OCR and explain errors or text.",
  };

  for (const [key, text] of Object.entries(map)) {
    document.querySelectorAll(`[data-i18n='${key}']`).forEach((el) => {
      if (key.startsWith("hint_") && el.querySelector("span:nth-child(2)")) {
        el.querySelector("span:nth-child(2)").textContent = text;
      } else {
        el.textContent = text;
      }
    });
  }

  if (dom.helpBtn) {
    dom.helpBtn.title = es ? "Guía rápida de herramientas" : "Quick tools guide";
  }
}

function updateConversationIndicators(id) {
  const display = id || "—";
  if (dom.convIdDisplay) dom.convIdDisplay.textContent = display;
  if (dom.convIdChip) dom.convIdChip.textContent = id ? `${id.slice(0, 8)}${id.length > 8 ? "…" : ""}` : "—";
  if (id) startConversationEventsPolling();
  else stopConversationEventsPolling();
}

function setPending(on) {
  state.pending = !!on;
  if (dom.sendBtn) dom.sendBtn.disabled = state.pending;
  if (dom.cancelBtn) dom.cancelBtn.disabled = !state.pending;
}

function registerAbortController(controller) {
  if (controller) state.activeControllers.add(controller);
  return controller;
}
function unregisterAbortController(controller) {
  if (controller) state.activeControllers.delete(controller);
}

function cancelAllRequests() {
  if (state.activeControllers.size) {
    const arr = Array.from(state.activeControllers);
    state.activeControllers.clear();
    arr.forEach((c) => { try { c.abort(); } catch {} });
  }
  removeTyping();
  setPending(false);
  state.cancelledByUser = true;
  appendBubble(state.lang === LANG.ES ? "Solicitud cancelada." : "Request cancelled.", "bot");
}

async function fetchWithTimeout(url, opts = {}, { timeout = CHAT_MAX_TIMEOUT_MS, retries = 0 } = {}) {
  for (let attempt = 0; attempt <= retries; attempt++) {
    const controller = registerAbortController(new AbortController());
    const id = setTimeout(() => controller.abort(), timeout);
    try {
      const merged = { ...opts };
      merged.headers = {
        ...(opts.headers || {}),
        ...(state.apiKey ? { "X-API-Key": state.apiKey } : {}),
      };
      return await fetch(url, { ...merged, signal: controller.signal });
    } catch (err) {
      if (attempt === retries) throw err;
      await new Promise((r) => setTimeout(r, 300 * (attempt + 1)));
    } finally {
      clearTimeout(id);
      unregisterAbortController(controller);
    }
  }
}

async function safeJson(res) {
  try { return await res.json(); } catch { return null; }
}

function clearSources() {
  if (!dom.sourcesContent) return;
  dom.sourcesContent.innerHTML = "";
  dom.sourcesContent.appendChild(el("div", { text: state.lang === LANG.ES ? "Sin recursos externos aún." : "No external resources yet." }));
}

function getDomainFromUrl(url) {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return url; }
}

function setProjectRoot(newRoot) {
  if (!newRoot) return;
  state.currentProjectRoot = newRoot;
  if (!dom.projectSelect) return;

  let opt = Array.from(dom.projectSelect.options || []).find((o) => o.value === newRoot);
  if (!opt) {
    opt = document.createElement("option");
    opt.value = newRoot;
    opt.textContent = newRoot;
    dom.projectSelect.appendChild(opt);
  }
  dom.projectSelect.value = newRoot;
}

/* ------------------------- SEND / CHAT ------------------------- */

async function onSend() {
  if (state.pending) return;
  const raw = (dom.msgInput?.value || "").trim();
  if (!raw) return;

  // auto prefix routing
  let modeForThis = state.mode;
  let text = raw;

  if (/^web:\s*/i.test(raw)) { modeForThis = MODES.WEB; text = raw.replace(/^web:\s*/i, "").trim(); }
  if (/^url:\s*/i.test(raw)) { modeForThis = MODES.URL; text = raw.replace(/^url:\s*/i, "").trim(); }

  // trade command shortcut in any mode
  if (await tryHandleTradeCommand(text)) {
    dom.msgInput.value = "";
    autoSizeTextarea(dom.msgInput);
    return;
  }

  appendBubble(raw, "user");
  dom.msgInput.value = "";
  autoSizeTextarea(dom.msgInput);

  setPending(true);
  appendTyping();

  const t0 = performance.now();
  try {
    if (modeForThis === MODES.WEB) {
      await handleWeb(text);
    } else if (modeForThis === MODES.URL) {
      await handleUrl(text);
    } else if (modeForThis === MODES.CRYPTO) {
      await handleChat(text, { mode: "crypto" });
    } else {
      await handleChat(text, { mode: "general" });
    }
  } catch (err) {
    appendBubble(state.lang === LANG.ES ? "Error de red." : "Network error.", "error");
    console.error(err);
  } finally {
    removeTyping();
    setPending(false);
    state.lastLatencyMs = performance.now() - t0;
    updateLatencyLabel();
  }
}

async function handleChat(text, { mode = "general" } = {}) {
  const payload = {
    message: text,
    lang: state.lang,
    mode,
    conversation_id: state.conversationId || undefined,
    use_existing: !!state.conversationId,
  };

  const res = await fetchWithTimeout(endpoints.chat, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(payload),
  });

  const data = await safeJson(res);

  if (!res.ok) {
    const msg = data?.detail || data?.error || `HTTP ${res.status}`;
    appendBubble(String(msg), "error");
    return;
  }

  // grab conversation id if backend returns it
  const conv = data?.conversation_id || data?.conversationId || data?.id || null;
  if (conv && conv !== state.conversationId) {
    state.conversationId = conv;
    state.useExistingConversation = true;
    localStorage.setItem("aegis_conv", conv);
    localStorage.setItem("aegis_use_existing", "1");
    updateConversationIndicators(conv);
  }

  const answer = data?.response ?? data?.answer ?? data?.text ?? data?.message ?? "";
  if (answer) appendBubble(String(answer), "bot", true);

  // if backend returns sources, show them
  const sources = normalizeWebResults(data?.sources || data?.results || data?.web_results || data?.items || null);
  if (sources.length) renderWebSources(text, sources, data);

  // crypto side-effects
  if (state.mode === MODES.CRYPTO) {
    loadPredictionComparison(state.chartSymbol, { force: false });
  }
}

async function handleWeb(query) {
  // Try /websearch for sources
  const results = await webSearch(query);
  if (results.length) {
    renderWebSources(query, results, null);
    appendBubble(
      state.lang === LANG.ES
        ? `Encontré ${results.length} fuentes. Ahora te respondo con contexto.`
        : `Found ${results.length} sources. Now answering with context.`,
      "bot"
    );
  }
  // Then ask backend chat in web mode (so it can answer)
  await handleChat(query, { mode: "web" });
}

async function webSearch(query) {
  // Try q= then query= (backend variations)
  const url1 = new URL(endpoints.websearch, location.origin);
  url1.searchParams.set("q", query);
  url1.searchParams.set("lang", state.lang);

  let res = await fetchWithTimeout(url1.toString(), { headers: { Accept: "application/json" } }, { timeout: 12000, retries: 0 });
  if (!res.ok) {
    const url2 = new URL(endpoints.websearch, location.origin);
    url2.searchParams.set("query", query);
    url2.searchParams.set("lang", state.lang);
    res = await fetchWithTimeout(url2.toString(), { headers: { Accept: "application/json" } }, { timeout: 12000, retries: 0 });
  }
  const data = await safeJson(res);
  return normalizeWebResults(data);
}

async function handleUrl(urlText) {
  const url = urlText.trim();
  if (!/^https?:\/\//i.test(url) && !/\.onion/i.test(url)) {
    appendBubble(state.lang === LANG.ES ? "Eso no parece una URL válida." : "That doesn't look like a valid URL.", "error");
    return;
  }

  const payload = { url, lang: state.lang };
  const res = await fetchWithTimeout(endpoints.fetchUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(payload),
  }, { timeout: 30000, retries: 0 });

  const data = await safeJson(res);
  if (!res.ok) {
    appendBubble(data?.detail || data?.error || (state.lang === LANG.ES ? "No se pudo leer la URL." : "Could not fetch URL."), "error");
    return;
  }

  // Show as a “source”
  const title = data?.title || "";
  const snippet = (data?.summary || data?.text || data?.content || "").slice(0, 800);
  renderWebSources(url, [{ url, title, snippet }], data);

  appendBubble(
    state.lang === LANG.ES ? `Leído: ${title || getDomainFromUrl(url)}.\n\n${snippet}` : `Read: ${title || getDomainFromUrl(url)}.\n\n${snippet}`,
    "bot",
    false
  );

  // Optional: ask backend to summarize properly in chat
  await handleChat(`url:${url}`, { mode: "url" });
}

/* ------------------------- SOURCES RENDER ------------------------- */

function normalizeWebResults(raw) {
  if (!raw) return [];
  const arr =
    Array.isArray(raw) ? raw :
    Array.isArray(raw.results) ? raw.results :
    Array.isArray(raw.items) ? raw.items :
    Array.isArray(raw.sources) ? raw.sources :
    Array.isArray(raw.links) ? raw.links :
    [];

  const norm = [];
  for (const r of arr) {
    if (!r) continue;

    if (typeof r === "string") {
      const u = r.trim();
      if (u) norm.push({ url: u, title: "", snippet: "" });
      continue;
    }

    const url =
      r.url || r.link || r.href || r.uri ||
      r.source_url || r.sourceUrl || r.sourceURL ||
      r?.source?.url || r?.source?.link || r?.source?.href ||
      r?.meta?.url || r?.meta?.link || "";

    const title = r.title || r.name || r.heading || r.headline || r?.meta?.title || r?.source?.title || "";
    const snippet = r.snippet || r.description || r.summary || r.content || r?.meta?.snippet || r?.meta?.description || "";

    if (url) norm.push({ url: String(url).trim(), title: String(title || "").trim(), snippet: String(snippet || "").trim() });
  }
  return norm;
}

function renderWebSources(query, results, raw = null) {
  if (!dom.sourcesContent) return;

  const seen = new Set();
  const rows = [];
  for (const r of results || []) {
    const u = (r?.url || "").trim();
    if (!u || seen.has(u)) continue;
    seen.add(u);
    rows.push({ url: u, title: (r?.title || "").trim(), snippet: (r?.snippet || "").trim() });
  }

  dom.sourcesContent.innerHTML = "";

  const label = state.lang === LANG.ES ? `Fuentes web para: "${query}"` : `Web sources for: "${query}"`;
  const header = el("div", { text: label });
  header.style.marginBottom = "6px";
  header.style.fontWeight = "600";
  dom.sourcesContent.appendChild(header);

  if (!rows.length) {
    dom.sourcesContent.appendChild(el("div", { text: state.lang === LANG.ES ? "Sin URLs." : "No URLs." }));
    if (raw != null) {
      const pre = el("pre", { class: "sources-content" });
      pre.style.whiteSpace = "pre-wrap";
      pre.textContent = JSON.stringify(raw, null, 2);
      dom.sourcesContent.appendChild(pre);
    }
    return;
  }

  rows.forEach((r, idx) => {
    const card = el("div", { class: "source-card" });

    const head = el("div", { class: "source-card-header" });
    head.appendChild(el("span", { class: "source-rank", text: "#" + (idx + 1) }));
    head.appendChild(el("span", { class: "source-domain", text: getDomainFromUrl(r.url) }));
    card.appendChild(head);

    const a = el("a", { class: "source-link", attrs: { href: r.url, target: "_blank", rel: "noopener noreferrer" } });
    a.innerHTML = `<i class="fa-solid fa-up-right-from-square"></i> ${r.title ? r.title : r.url}`;
    card.appendChild(a);

    if (r.snippet) {
      const sn = el("div", { text: r.snippet });
      sn.style.marginTop = "6px";
      sn.style.fontSize = "0.85rem";
      sn.style.color = "var(--muted)";
      card.appendChild(sn);
    }
    dom.sourcesContent.appendChild(card);
  });
}

/* ------------------------- IMAGE OCR ------------------------- */

async function analyzeImage(file) {
  appendBubble(state.lang === LANG.ES ? "Analizando imagen…" : "Analyzing image…", "bot");
  const fd = new FormData();
  fd.append("file", file);
  fd.append("lang", state.lang);

  const res = await fetchWithTimeout(endpoints.analyzeImage, {
    method: "POST",
    body: fd,
  }, { timeout: 60000, retries: 0 });

  const data = await safeJson(res);
  if (!res.ok) {
    appendBubble(data?.detail || data?.error || (state.lang === LANG.ES ? "Falló OCR." : "OCR failed."), "error");
    return;
  }
  const text = data?.text || data?.ocr || data?.result || JSON.stringify(data, null, 2);
  appendBubble(text, "bot", false);
}

/* ------------------------- CRYPTO: MODELS / PREDICT / TRADE ------------------------- */

function setTradeStatus(text, isError = false) {
  if (!dom.tradeStatus) return;
  dom.tradeStatus.textContent = text || "";
  dom.tradeStatus.style.color = isError ? "#fca5a5" : "var(--muted)";
}

async function loadCryptoModels() {
  try {
    const res = await fetchWithTimeout(endpoints.cryptoModels, { headers: { Accept: "application/json" } }, { timeout: 8000, retries: 0 });
    const data = await safeJson(res);
    if (res.ok && data) {
      const available = data.available || data.models || ["ensemble"];
      state.cryptoModelsMeta.available = Array.isArray(available) ? available : ["ensemble"];
      state.cryptoModelsMeta.default = data.default || state.cryptoModelsMeta.available[0] || "ensemble";
    }
  } catch {}
  const saved = localStorage.getItem("aegis_crypto_model");
  state.selectedCryptoModel = saved || state.cryptoModelsMeta.default || "ensemble";
  if (dom.cryptoModelSelect) {
    dom.cryptoModelSelect.innerHTML = "";
    state.cryptoModelsMeta.available.forEach((m) => {
      const opt = document.createElement("option");
      opt.value = m;
      opt.textContent = m;
      if (m === state.selectedCryptoModel) opt.selected = true;
      dom.cryptoModelSelect.appendChild(opt);
    });
  }
}

function updateChartTitle(symbol) {
  if (dom.chartTitle) dom.chartTitle.textContent = symbol;
  if (dom.chartSymbol) dom.chartSymbol.value = symbol;
}

function parseOhlcv(raw) {
  if (!raw) return [];
  const rows = Array.isArray(raw) ? raw : raw.candles || raw.klines || raw.items || [];
  const points = [];
  rows.forEach((r) => {
    if (Array.isArray(r)) {
      const ts = r[0];
      const close = parseFloat(r[4] ?? r[1]);
      if (Number.isFinite(close)) points.push({ t: ts, c: close });
      return;
    }
    const ts = r.close_time ?? r.time ?? r.timestamp ?? r.t ?? r.ts;
    const close = parseFloat(r.close ?? r.c ?? r.price);
    if (Number.isFinite(close) && ts != null) points.push({ t: ts, c: close });
  });
  return points;
}

function renderChart(points) {
  state.lastPoints = points || [];
  if (!dom.priceChart || typeof Chart === "undefined") return;
  if (!points.length) {
    setTradeStatus(state.lang === LANG.ES ? "Sin datos de precio." : "No price data.", true);
    return;
  }

  const labels = points.map((p) => new Date(Number(p.t)).toLocaleTimeString());
  const mainData = points.map((p) => p.c);

  const tradePoints = (state.tradesOnChart || []).map((tr) => {
    let nearestIdx = points.length - 1;
    let bestDiff = Number.POSITIVE_INFINITY;
    points.forEach((p, idx) => {
      const diff = Math.abs(Number(p.t) - Number(tr.t || Date.now()));
      if (diff < bestDiff) { bestDiff = diff; nearestIdx = idx; }
    });
    return { x: labels[nearestIdx], y: tr.price ?? mainData[nearestIdx], side: tr.side };
  });

  const newsPoints =
    state.showNewsMarkers && state.newsFeed?.length
      ? state.newsFeed.map((n) => {
          let nearestIdx = points.length - 1;
          let bestDiff = Number.POSITIVE_INFINITY;
          points.forEach((p, idx) => {
            const diff = Math.abs(Number(p.t) - Number(n.ts || Date.now()));
            if (diff < bestDiff) { bestDiff = diff; nearestIdx = idx; }
          });
          return { x: labels[nearestIdx], y: mainData[nearestIdx], title: n.title, sentiment: n.sentiment };
        })
      : [];

  if (state.chartInstance) state.chartInstance.destroy();

  state.chartInstance = new Chart(dom.priceChart, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: state.chartSymbol,
          data: mainData,
          borderColor: "#22d3ee",
          backgroundColor: "rgba(34, 211, 238, 0.15)",
          tension: 0.2,
          fill: true,
        },
        ...(tradePoints.length ? [{
          type: "scatter",
          label: "Trades",
          data: tradePoints,
          pointRadius: 4,
          pointHoverRadius: 5,
          pointBackgroundColor: (ctx) => (ctx.raw?.side === "SELL" ? "#f87171" : "#22c55e"),
          showLine: false,
        }] : []),
        ...(newsPoints.length ? [{
          type: "scatter",
          label: "News",
          data: newsPoints,
          pointRadius: 3,
          pointHoverRadius: 4,
          pointBackgroundColor: (ctx) => {
            const s = ctx.raw?.sentiment ?? 0;
            if (s > 0.15) return "#22c55e";
            if (s < -0.15) return "#f87171";
            return "#a1a1aa";
          },
          showLine: false,
        }] : []),
      ],
    },
    options: {
      interaction: { mode: "index", intersect: false },
      plugins: { tooltip: { enabled: true }, legend: { display: false } },
      scales: {
        x: { grid: { color: "rgba(148,163,184,0.1)" }, ticks: { color: "#9ca3af", maxRotation: 0, autoSkip: true, maxTicksLimit: 6 } },
        y: { grid: { color: "rgba(148,163,184,0.1)" }, ticks: { color: "#9ca3af" } },
      },
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
    },
  });
}

async function loadChartData(symbolInput) {
  const symbol = (symbolInput || state.chartSymbol || "BTCUSDT").trim().toUpperCase();
  state.chartSymbol = symbol || "BTCUSDT";
  updateChartTitle(state.chartSymbol);

  try {
    const url = new URL(endpoints.cryptoOhlcv, location.origin);
    url.searchParams.set("symbol", state.chartSymbol);
    url.searchParams.set("interval", "1m");
    url.searchParams.set("limit", "120");

    const res = await fetchWithTimeout(url.toString(), {}, { timeout: 12000, retries: 0 });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const json = await safeJson(res);
    const points = parseOhlcv(json);
    renderChart(points);
    setTradeStatus(state.lang === LANG.ES ? "Gráfico actualizado." : "Chart updated.");
    loadNews(state.chartSymbol);
    if (state.mode === MODES.CRYPTO) {
      loadCryptoPrediction();
      loadPredictionComparison(state.chartSymbol, { force: false });
    }
  } catch (err) {
    console.error(err);
    setTradeStatus(state.lang === LANG.ES ? "No se pudo cargar el gráfico." : "Could not load chart.", true);
  }
}

function startLiveChart() {
  stopLiveChart();
  state.liveTimer = setInterval(() => loadChartData(state.chartSymbol), 15000);
}
function stopLiveChart() {
  if (state.liveTimer) clearInterval(state.liveTimer);
  state.liveTimer = null;
}

function toggleChartExpand() {
  if (!dom.chartPanel) return;
  dom.chartPanel.classList.toggle("expanded");
  if (state.lastPoints?.length) renderChart(state.lastPoints);
}

async function loadCryptoPrediction() {
  if (state.mode !== MODES.CRYPTO) return;

  const symbol = (dom.chartSymbol?.value || state.chartSymbol || "BTCUSDT").trim().toUpperCase();
  const horizon = parseInt(dom.cryptoHorizon?.value || "15", 10);
  const model = dom.cryptoModelSelect?.value || state.selectedCryptoModel || "ensemble";

  try {
    const payload = { symbol, horizon_minutes: horizon, model, save: !!state.savePredictions };
    const res = await fetchWithTimeout(endpoints.cryptoPredict, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload),
    }, { timeout: 12000, retries: 0 });

    const data = await safeJson(res);
    if (!res.ok) return;

    // decision/prob highlight
    const decision = data?.decision || data?.signal || "HOLD";
    const prob = data?.probability_up ?? data?.prob_up ?? data?.p_up;
    applySignalHighlight(decision, prob);

    const px = data?.current_price ?? data?.price ?? "—";
    const probText = typeof prob === "number" ? `${(prob * 100).toFixed(1)}%` : "—";

    setTradeStatus(
      state.lang === LANG.ES
        ? `Señal: ${decision} • p=${probText} • px=${px}`
        : `Signal: ${decision} • p=${probText} • px=${px}`
    );
  } catch {}
}

function clearSignalHighlight() {
  [dom.buyBtn, dom.sellBtn].filter(Boolean).forEach((btn) => {
    btn.classList.remove("signal-buy","signal-sell","signal-weak","signal-medium","signal-strong");
    btn.removeAttribute("title");
  });
}

function getSignalStrength(prob) {
  if (typeof prob !== "number" || !Number.isFinite(prob)) return "weak";
  const edge = Math.abs(prob - 0.5);
  if (edge >= 0.15) return "strong";
  if (edge >= 0.08) return "medium";
  return "weak";
}

function applySignalHighlight(decision, prob) {
  if (!dom.buyBtn || !dom.sellBtn) return;
  clearSignalHighlight();
  const strength = getSignalStrength(prob);
  const probText = typeof prob === "number" ? `${(prob * 100).toFixed(1)}%` : "—";
  const prefix = state.lang === LANG.ES ? "Señal" : "Signal";
  const shouldGlow = strength !== "weak";

  if (decision === "BUY") {
    if (shouldGlow) dom.buyBtn.classList.add("signal-buy", `signal-${strength}`);
    dom.buyBtn.setAttribute("title", `${prefix} BUY • p=${probText} • ${strength}`);
  } else if (decision === "SELL") {
    if (shouldGlow) dom.sellBtn.classList.add("signal-sell", `signal-${strength}`);
    dom.sellBtn.setAttribute("title", `${prefix} SELL • p=${probText} • ${strength}`);
  }
}

function parseTradeCommand(text) {
  if (!text) return null;
  const cmd = text.trim();

  let m = cmd.match(/^(buy|sell)\s+([0-9]*\.?[0-9]+)\s+([a-zA-Z]{2,12})/i);
  if (m) {
    const side = m[1].toUpperCase();
    const qty = parseFloat(m[2]);
    let symbol = m[3].toUpperCase();
    if (!symbol.endsWith("USDT")) symbol += "USDT";
    if (!Number.isFinite(qty) || qty <= 0) return null;
    return { side, quantity: qty, symbol };
  }

  m = cmd.match(/^(buy|sell)\s+([a-zA-Z]{2,12})/i);
  if (m) {
    const side = m[1].toUpperCase();
    let symbol = m[2].toUpperCase();
    if (!symbol.endsWith("USDT")) symbol += "USDT";
    const qtyField = dom.chatTradeQty?.value || "0.001";
    const qty = parseFloat(qtyField);
    if (!Number.isFinite(qty) || qty <= 0) return null;
    return { side, quantity: qty, symbol };
  }
  return null;
}

async function tryHandleTradeCommand(text) {
  const cmd = parseTradeCommand(text);
  if (!cmd) return false;

  appendBubble(text, "user");
  appendBubble(state.lang === LANG.ES ? "Ejecutando orden (test)..." : "Executing order (test)...", "bot");

  try {
    const res = await fetchWithTimeout(endpoints.cryptoTrade, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ ...cmd, test: true }),
    }, { timeout: 15000, retries: 0 });

    const data = await safeJson(res);
    if (!res.ok) throw new Error("HTTP " + res.status);

    const price = data?.price ?? data?.current_price ?? data?.predicted_price;
    const status = data?.status || "SIMULATED";
    appendBubble(
      state.lang === LANG.ES
        ? `Orden ${cmd.side} ${cmd.symbol} qty=${cmd.quantity} → ${status}${price ? ` @ ${price}` : ""}`
        : `Order ${cmd.side} ${cmd.symbol} qty=${cmd.quantity} → ${status}${price ? ` @ ${price}` : ""}`,
      "bot"
    );

    if (Number.isFinite(price)) {
      state.tradesOnChart.push({ t: Date.now(), price: parseFloat(price), side: cmd.side });
      if (state.lastPoints?.length) renderChart(state.lastPoints);
    }
  } catch (err) {
    console.error(err);
    appendBubble(state.lang === LANG.ES ? "No se pudo enviar la orden (simulada)." : "Failed to send order (simulated).", "error");
  }
  return true;
}

async function submitTrade(side) {
  const symbol = (dom.chartSymbol?.value || state.chartSymbol || "").trim().toUpperCase();
  const qty = parseFloat(dom.chatTradeQty?.value || "0");

  if (!symbol) return setTradeStatus(state.lang === LANG.ES ? "Escribe un símbolo." : "Enter a symbol.", true);
  if (!Number.isFinite(qty) || qty <= 0) return setTradeStatus(state.lang === LANG.ES ? "Cantidad inválida." : "Invalid quantity.", true);

  setTradeStatus(state.lang === LANG.ES ? "Enviando orden..." : "Sending order...");
  try {
    const payload = { symbol, side, quantity: qty, test: TRADE_TEST_DEFAULT };
    const res = await fetchWithTimeout(endpoints.cryptoTrade, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload),
    }, { timeout: 15000, retries: 0 });

    const data = await safeJson(res);
    if (!res.ok) throw new Error("HTTP " + res.status);

    const tradePrice = parseFloat(data?.price ?? data?.executedPrice ?? data?.avgPrice ?? data?.lastPrice ?? data?.current_price);
    setTradeStatus(
      state.lang === LANG.ES
        ? `Orden ${side} enviada (${qty}). ${data?.status || ""}`.trim()
        : `${side} order sent (${qty}). ${data?.status || ""}`.trim(),
      false
    );

    if (Number.isFinite(tradePrice)) {
      state.tradesOnChart.push({ t: Date.now(), price: tradePrice, side });
      if (state.lastPoints?.length) renderChart(state.lastPoints);
    }
  } catch (err) {
    console.error(err);
    setTradeStatus(state.lang === LANG.ES ? "Fallo la orden." : "Order failed.", true);
  }
}

/* ------------------------- NEWS ------------------------- */

async function loadNews(symbolInput, { force = false } = {}) {
  const symbol = (symbolInput || state.chartSymbol || "BTCUSDT").trim().toUpperCase();
  try {
    const url = new URL(endpoints.cryptoNews, location.origin);
    url.searchParams.set("symbol", symbol);
    if (force) url.searchParams.set("force", "true");

    const res = await fetchWithTimeout(url.toString(), {}, { timeout: 9000, retries: 0 });
    const data = await safeJson(res);
    if (!res.ok || !data) return;

    state.newsFeed = Array.isArray(data.items) ? data.items : [];
    state.newsMomentum = data.momentum ?? null;

    renderNewsList(state.newsFeed, state.newsMomentum);

    if (state.lastPoints?.length) renderChart(state.lastPoints);
  } catch (err) {
    if (err?.name !== "AbortError") console.error(err);
  }
}

function renderNewsList(items, momentum) {
  if (!dom.newsList) return;
  dom.newsList.innerHTML = "";
  if (dom.newsMomentum) dom.newsMomentum.textContent = momentum == null ? "—" : String(momentum);

  if (!items?.length) {
    dom.newsList.appendChild(el("div", { class: "news-card", text: state.lang === LANG.ES ? "Sin noticias." : "No news." }));
    return;
  }

  items.slice(0, 20).forEach((n) => {
    const card = el("div", { class: "news-card" });
    const header = el("header");
    const title = el("div", { text: n.title || n.headline || "—" });
    title.style.fontWeight = "700";

    const meta = el("div", { class: "news-meta" });
    meta.textContent = (n.source || n.domain || "news") + (n.ts ? ` • ${new Date(n.ts).toLocaleString()}` : "");

    const sent = n.sentiment ?? 0;
    const pill = el("span", {
      class: `sentiment-pill ${sent > 0.15 ? "sentiment-pos" : sent < -0.15 ? "sentiment-neg" : "sentiment-neutral"}`,
      text: sent > 0.15 ? "POS" : sent < -0.15 ? "NEG" : "NEU",
    });

    header.appendChild(title);
    header.appendChild(pill);
    card.appendChild(header);
    card.appendChild(meta);

    if (n.url) {
      const a = el("a", { attrs: { href: n.url, target: "_blank", rel: "noopener noreferrer" } });
      a.textContent = n.url;
      a.style.color = "var(--accent)";
      a.style.fontSize = "0.78rem";
      card.appendChild(a);
    }

    dom.newsList.appendChild(card);
  });
}

/* ------------------------- PREDICTION COMPARISON / STATS / PNL ------------------------- */

function updatePredictionTooltipText() {
  if (!dom.predictionCompareTooltip) return;
  dom.predictionCompareTooltip.innerHTML =
    state.lang === LANG.ES
      ? [
          "<strong>¿Qué significa esto?</strong>",
          "<p>Compara la señal con el resultado real después del horizonte (H).</p>",
          "<p><strong>p%</strong> es la probabilidad de subida. 50% = neutro.</p>",
          "<p><strong>Δ%</strong> es el cambio real: BUY gana si sube, SELL si baja, HOLD acierta si |Δ|&lt;1%.</p>",
          "<p>El “retorno hipotético” es educativo, no consejo financiero.</p>",
        ].join("")
      : [
          "<strong>What does this mean?</strong>",
          "<p>It compares the signal with the real outcome after the horizon (H).</p>",
          "<p><strong>p%</strong> is the probability of an upward move. 50% = neutral.</p>",
          "<p><strong>Δ%</strong> is the real move: BUY wins if price rises, SELL if it falls, HOLD hits if |Δ|&lt;1%.</p>",
          "<p>“Hypothetical return” is educational, not financial advice.</p>",
        ].join("");
}

function formatPct(v, digits = 2) {
  if (!Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}
function formatProb(v) {
  if (!Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

async function loadPredictionComparison(symbolInput, { force = false } = {}) {
  if (!dom.predictionCompareBody) return;
  const symbol = (symbolInput || state.chartSymbol || "").trim().toUpperCase();
  const title = state.lang === LANG.ES ? "Comparación post-horizonte" : "Post-horizon comparison";
  if (dom.predictionCompareTitle) dom.predictionCompareTitle.textContent = symbol ? `${title} • ${symbol}` : title;

  dom.predictionCompareBody.textContent = state.lang === LANG.ES ? "Cargando..." : "Loading...";

  // These endpoints must exist in your backend; if not, it will show a friendly message
  const predsUrl = new URL("/crypto/predictions", location.origin);
  predsUrl.searchParams.set("limit", "20");
  if (symbol) predsUrl.searchParams.set("symbol", symbol);

  const outsUrl = new URL("/crypto/predictions/outcomes", location.origin);
  outsUrl.searchParams.set("limit", "40");
  if (symbol) outsUrl.searchParams.set("symbol", symbol);

  try {
    const [pRes, oRes] = await Promise.all([
      fetchWithTimeout(predsUrl.toString(), {}, { timeout: 10000, retries: 0 }),
      fetchWithTimeout(outsUrl.toString(), {}, { timeout: 10000, retries: 0 }),
    ]);

    if (!pRes.ok || !oRes.ok) {
      dom.predictionCompareBody.textContent = state.lang === LANG.ES
        ? "Comparación no disponible (endpoint o auth)."
        : "Comparison unavailable (endpoint or auth).";
      return;
    }

    const preds = await safeJson(pRes) || [];
    const outs = await safeJson(oRes) || [];
    const outMap = new Map();
    outs.forEach((o) => o?.log_id && outMap.set(o.log_id, o));

    const joined = (Array.isArray(preds) ? preds : [])
      .map((p) => ({ p, o: outMap.get(p.id) }))
      .filter((x) => x.o);

    joined.sort((a, b) => (b.o?.ts || 0) - (a.o?.ts || 0));

    dom.predictionCompareBody.innerHTML = "";
    if (!joined.length) {
      dom.predictionCompareBody.appendChild(el("div", { text: state.lang === LANG.ES ? "Aún no hay resultados." : "No results yet." }));
      return;
    }

    joined.slice(0, 3).forEach(({ p, o }) => {
      const card = el("div", { class: "compare-row" });
      const left = el("div", { class: "compare-metric" });
      const right = el("div", { class: "compare-metric" });

      left.appendChild(el("div", { class: "compare-label", text: state.lang === LANG.ES ? "Señal" : "Signal" }));
      left.appendChild(el("div", { class: "compare-value", text: `${p.decision || "HOLD"} • p=${formatProb(p.probability_up)} • H=${p.horizon_minutes || "?"}m` }));
      left.appendChild(el("div", { class: "compare-label", text: state.lang === LANG.ES ? "Precio base" : "Base price" }));
      left.appendChild(el("div", { class: "compare-value", text: p.current_price ?? "—" }));

      right.appendChild(el("div", { class: "compare-label", text: state.lang === LANG.ES ? "Resultado" : "Outcome" }));
      const delta = o.delta_pct;
      right.appendChild(el("span", {
        class: `compare-pill ${Number.isFinite(delta) ? (delta >= 0 ? "positive" : "negative") : ""}`,
        text: `Δ ${formatPct(delta)}`,
      }));
      right.appendChild(el("div", { class: "compare-label", text: state.lang === LANG.ES ? "Precio real" : "Actual price" }));
      right.appendChild(el("div", { class: "compare-value", text: o.actual_price ?? "—" }));

      card.appendChild(left);
      card.appendChild(right);
      dom.predictionCompareBody.appendChild(card);
    });
  } catch (err) {
    console.error(err);
    dom.predictionCompareBody.textContent = state.lang === LANG.ES ? "Error al cargar comparación." : "Error loading comparison.";
  }
}

async function loadRecentPredictions() {
  const url = new URL("/crypto/predictions", location.origin);
  url.searchParams.set("limit", "30");
  try {
    const res = await fetchWithTimeout(url.toString(), {}, { timeout: 9000, retries: 0 });
    const data = await safeJson(res);
    if (!res.ok) throw new Error();
    renderSimpleList(data, state.lang === LANG.ES ? "Últimas predicciones" : "Recent predictions");
  } catch {
    renderErrorInSources(state.lang === LANG.ES ? "No disponible." : "Unavailable.");
  }
}

async function loadStats() {
  const url = new URL("/crypto/predictions/stats", location.origin);
  url.searchParams.set("limit", "200");
  try {
    const res = await fetchWithTimeout(url.toString(), {}, { timeout: 9000, retries: 0 });
    const data = await safeJson(res);
    if (!res.ok) throw new Error();
    renderSimpleList(data, state.lang === LANG.ES ? "Stats" : "Stats");
  } catch {
    renderErrorInSources(state.lang === LANG.ES ? "No disponible." : "Unavailable.");
  }
}

async function loadPnl() {
  try {
    const [tRes, pRes] = await Promise.all([
      fetchWithTimeout(endpoints.cryptoTrades, {}, { timeout: 9000, retries: 0 }),
      fetchWithTimeout(endpoints.cryptoPnl, {}, { timeout: 9000, retries: 0 }),
    ]);
    const trades = await safeJson(tRes) || [];
    const pnl = await safeJson(pRes) || {};
    renderSimpleList({ pnl, trades }, "P&L");
  } catch {
    renderErrorInSources(state.lang === LANG.ES ? "No disponible." : "Unavailable.");
  }
}

function renderErrorInSources(msg) {
  if (!dom.sourcesContent) return;
  dom.sourcesContent.innerHTML = "";
  dom.sourcesContent.appendChild(el("div", { class: "sources-list-item", text: msg }));
}

function renderSimpleList(obj, title) {
  if (!dom.sourcesContent) return;
  dom.sourcesContent.innerHTML = "";
  const h = el("div", { text: title });
  h.style.fontWeight = "700";
  h.style.marginBottom = "6px";
  dom.sourcesContent.appendChild(h);

  const pre = el("pre", { class: "sources-content" });
  pre.style.whiteSpace = "pre-wrap";
  pre.textContent = JSON.stringify(obj, null, 2);
  dom.sourcesContent.appendChild(pre);
}

/* ------------------------- SESSIONS ------------------------- */

function closeSessionsModal() {
  dom.sessionsModal?.classList?.add("hidden");
}

function openSessionsModal() {
  if (dom.sessionsIncludeArchived) dom.sessionsIncludeArchived.checked = !!state.conversationsIncludeArchived;
  dom.sessionsModal?.classList?.remove("hidden");
  loadConversationList(state.conversationsIncludeArchived);
}

async function loadConversationList(includeArchived = false) {
  if (!dom.sessionsList) return;
  dom.sessionsList.innerHTML = `<li class="sessions-empty">${state.lang === LANG.ES ? "Cargando..." : "Loading..."}</li>`;
  try {
    const url = new URL(endpoints.conversations, window.location.origin);
    url.searchParams.set("limit", "40");
    if (includeArchived) url.searchParams.set("include_archived", "1");

    const res = await fetchWithTimeout(url.toString(), { headers: { Accept: "application/json" } }, { timeout: 9000, retries: 0 });
    const data = await safeJson(res);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    state.conversationList = data?.items || [];
    renderConversationList(state.conversationList);
  } catch (err) {
    console.error(err);
    dom.sessionsList.innerHTML = `<li class="sessions-empty">${state.lang === LANG.ES ? "No se pudieron cargar conversaciones." : "Could not load conversations."}</li>`;
  }
}

function renderConversationList(items) {
  if (!dom.sessionsList) return;
  dom.sessionsList.innerHTML = "";

  if (!items?.length) {
    dom.sessionsList.innerHTML = `<li class="sessions-empty">${state.lang === LANG.ES ? "Sin conversaciones." : "No conversations."}</li>`;
    return;
  }

  items.forEach((item) => {
    const li = document.createElement("li");
    li.className = "sessions-item";

    const header = document.createElement("div");
    header.className = "sessions-item-header";
    header.textContent = item.id || "(no id)";
    if (item.archived) {
      const badge = document.createElement("span");
      badge.className = "badge-archived";
      badge.textContent = state.lang === LANG.ES ? "Archivada" : "Archived";
      header.appendChild(badge);
    }

    const meta = document.createElement("div");
    meta.className = "session-meta";
    const updated = item.updated_at ? new Date(item.updated_at * 1000).toLocaleString() : "—";
    meta.textContent = `${state.lang === LANG.ES ? "Actualizada" : "Updated"}: ${updated}`;

    const summary = document.createElement("div");
    summary.className = "session-summary";
    summary.textContent = item.summary ? String(item.summary).slice(0, 280) : (state.lang === LANG.ES ? "Sin resumen." : "No summary.");

    const actions = document.createElement("div");
    actions.className = "session-actions";

    const useBtn = document.createElement("button");
    useBtn.textContent = state.lang === LANG.ES ? "Usar" : "Select";
    useBtn.addEventListener("click", () => selectConversation(item.id));
    actions.appendChild(useBtn);

    const archiveBtn = document.createElement("button");
    archiveBtn.className = "archive";
    archiveBtn.textContent = item.archived ? (state.lang === LANG.ES ? "Restaurar" : "Unarchive") : (state.lang === LANG.ES ? "Archivar" : "Archive");
    archiveBtn.addEventListener("click", () => toggleArchiveConversation(item.id, item.archived));
    actions.appendChild(archiveBtn);

    const deleteBtn = document.createElement("button");
    deleteBtn.className = "delete";
    deleteBtn.textContent = state.lang === LANG.ES ? "Eliminar" : "Delete";
    deleteBtn.addEventListener("click", () => deleteConversationById(item.id));
    actions.appendChild(deleteBtn);

    li.appendChild(header);
    li.appendChild(meta);
    li.appendChild(summary);
    li.appendChild(actions);
    dom.sessionsList.appendChild(li);
  });
}

function selectConversation(convId) {
  if (!convId) return;
  state.conversationId = convId;
  state.useExistingConversation = true;
  localStorage.setItem("aegis_conv", convId);
  localStorage.setItem("aegis_use_existing", "1");
  updateConversationIndicators(convId);
  appendBubble(state.lang === LANG.ES ? `Sesión ${convId} activada.` : `Conversation ${convId} selected.`, "bot");
  closeSessionsModal();
}

async function toggleArchiveConversation(convId, currentlyArchived) {
  if (!convId) return;
  const endpoint = currentlyArchived ? endpoints.unarchiveConversation(convId) : endpoints.archiveConversation(convId);
  try {
    const res = await fetchWithTimeout(endpoint, { method: "POST" }, { timeout: 9000, retries: 0 });
    if (!res.ok) throw new Error();
    appendBubble(
      currentlyArchived ? (state.lang === LANG.ES ? "Sesión restaurada." : "Conversation unarchived.")
                        : (state.lang === LANG.ES ? "Sesión archivada." : "Conversation archived."),
      "bot"
    );
    loadConversationList(state.conversationsIncludeArchived);
  } catch {
    appendBubble(state.lang === LANG.ES ? "No se pudo actualizar la sesión." : "Could not update session.", "error");
  }
}

async function deleteConversationById(convId) {
  if (!convId) return;
  const ok = window.confirm(state.lang === LANG.ES ? "¿Eliminar esta conversación? No se puede deshacer." : "Delete this conversation? This cannot be undone.");
  if (!ok) return;
  try {
    const res = await fetchWithTimeout(endpoints.deleteConversation(convId), { method: "DELETE" }, { timeout: 12000, retries: 0 });
    if (!res.ok) throw new Error();
    if (state.conversationId === convId) clearConversation(true);
    appendBubble(state.lang === LANG.ES ? "Conversación eliminada." : "Conversation deleted.", "bot");
    loadConversationList(state.conversationsIncludeArchived);
  } catch {
    appendBubble(state.lang === LANG.ES ? "No se pudo eliminar." : "Could not delete.", "error");
  }
}

function clearConversation(silent = false) {
  state.conversationId = null;
  state.useExistingConversation = false;
  localStorage.removeItem("aegis_conv");
  localStorage.removeItem("aegis_use_existing");
  updateConversationIndicators(null);
  resetConversationEvents();
  if (!silent) appendBubble(state.lang === LANG.ES ? "Sesión local borrada." : "Local session cleared.", "bot");
}

function resetConversationEvents() {
  state.convEventsSince = null;
  state.convEventsItems = [];
  if (dom.convEventsList) {
    dom.convEventsList.innerHTML = `<li class="sessions-empty">${state.lang === LANG.ES ? "Sin eventos." : "No events yet."}</li>`;
  }
}

function renderConversationEvents(items) {
  if (!dom.convEventsList) return;
  if (!items.length) {
    dom.convEventsList.innerHTML = `<li class="sessions-empty">${state.lang === LANG.ES ? "Sin eventos." : "No events yet."}</li>`;
    return;
  }
  dom.convEventsList.innerHTML = "";
  items.slice(-200).forEach((evt) => {
    const li = document.createElement("li");
    li.className = "event-item";

    const meta = document.createElement("div");
    meta.className = "event-meta";

    const stage = document.createElement("span");
    stage.className = "event-stage";
    stage.textContent = evt.stage || "event";

    const level = document.createElement("span");
    level.className = `event-level ${(evt.level || "info").toLowerCase()}`;
    level.textContent = evt.level || "info";

    meta.appendChild(stage);
    meta.appendChild(level);

    const detail = document.createElement("div");
    detail.className = "event-detail";
    const ts = evt.ts ? new Date(evt.ts).toLocaleTimeString() : "";
    const msg = evt.detail || "";
    detail.textContent = `${ts}${msg ? ` · ${msg}` : ""}`;

    li.appendChild(meta);
    li.appendChild(detail);
    dom.convEventsList.appendChild(li);
  });
}

async function loadConversationEvents({ force = false } = {}) {
  if (!dom.convEventsList) return;
  const convId = state.conversationId;
  if (!convId) {
    resetConversationEvents();
    return;
  }

  try {
    const url = new URL(endpoints.conversationEvents(convId), location.origin);
    if (!force && state.convEventsSince) {
      url.searchParams.set("since", String(state.convEventsSince));
    }
    url.searchParams.set("limit", "200");
    const res = await fetchWithTimeout(url.toString(), { headers: { Accept: "application/json" } }, { timeout: 20000, retries: 0 });
    const data = await safeJson(res);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const items = data?.items || [];
    if (!items.length && !state.convEventsItems.length) {
      renderConversationEvents([]);
      return;
    }
    if (force) {
      state.convEventsItems = items;
    } else {
      state.convEventsItems = state.convEventsItems.concat(items);
    }
    if (state.convEventsItems.length > 200) {
      state.convEventsItems = state.convEventsItems.slice(-200);
    }
    if (items.length) {
      state.convEventsSince = items[items.length - 1]?.ts || state.convEventsSince;
    }
    renderConversationEvents(state.convEventsItems);
  } catch (err) {
    if (err?.name === "AbortError") return;
    console.error(err);
  }
}

function startConversationEventsPolling() {
  if (state.convEventsTimer) return;
  resetConversationEvents();
  loadConversationEvents({ force: true });
  state.convEventsTimer = setInterval(() => loadConversationEvents(), 2000);
}

function stopConversationEventsPolling() {
  if (state.convEventsTimer) {
    clearInterval(state.convEventsTimer);
    state.convEventsTimer = null;
  }
}

/* ------------------------- FILE TREE / CONTENT / INGEST ------------------------- */

async function loadProjectTree() {
  if (!dom.projectTree) return;
  dom.projectTree.textContent = state.lang === LANG.ES ? "Cargando..." : "Loading...";

  try {
    const url = new URL(endpoints.toolsTree, location.origin);
    url.searchParams.set("root", state.currentProjectRoot);

    const res = await fetchWithTimeout(url.toString(), {}, { timeout: 20000, retries: 0 });
    const data = await safeJson(res);
    if (!res.ok) throw new Error();

    dom.projectTree.innerHTML = "";
    const tree = data?.tree || data?.items || data || [];
    renderTree(tree, dom.projectTree, "");
  } catch (err) {
    console.error(err);
    dom.projectTree.textContent = state.lang === LANG.ES ? "No se pudo cargar el árbol." : "Could not load tree.";
  }
}

function renderTree(tree, container, basePath) {
  // support both: array of {name,type,children,path} OR dict-like
  const nodes = Array.isArray(tree) ? tree : [];
  nodes.forEach((n) => {
    const isDir = n.type === "dir" || n.is_dir === true || Array.isArray(n.children);
    const name = n.name || n.path || "node";
    const path = n.path || (basePath ? `${basePath}/${name}` : name);

    const row = el("div", { class: `tree-node ${isDir ? "dir" : "file"}` });
    row.innerHTML = `<span class="icon">${isDir ? "📁" : "📄"}</span><span>${name}</span>`;
    container.appendChild(row);

    if (isDir) {
      const childrenWrap = el("div", { class: "tree-children" });
      childrenWrap.style.display = "none";
      container.appendChild(childrenWrap);

      row.addEventListener("click", () => {
        const open = childrenWrap.style.display !== "none";
        childrenWrap.style.display = open ? "none" : "block";
      });

      if (Array.isArray(n.children) && n.children.length) {
        renderTree(n.children, childrenWrap, path);
      }
    } else {
      row.addEventListener("click", () => loadFileContent(path));
    }
  });
}

async function loadFileContent(path) {
  if (!path) return;
  if (dom.fileViewerTitle) dom.fileViewerTitle.textContent = path;
  if (dom.fileViewerBody) dom.fileViewerBody.textContent = state.lang === LANG.ES ? "Cargando archivo..." : "Loading file...";

  try {
    const url = new URL(endpoints.toolsContent, location.origin);
    url.searchParams.set("path", path);
    const res = await fetchWithTimeout(url.toString(), {}, { timeout: 20000, retries: 0 });
    const data = await safeJson(res);
    if (!res.ok) throw new Error();

    const content = data?.content ?? (typeof data === "string" ? data : JSON.stringify(data, null, 2));
    dom.fileViewerBody.textContent = String(content ?? "");
  } catch (err) {
    console.error(err);
    dom.fileViewerBody.textContent = state.lang === LANG.ES ? "Error al cargar archivo." : "Error loading file.";
  }
}

async function copyFileViewer() {
  const text = dom.fileViewerBody?.textContent || "";
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    appendBubble(state.lang === LANG.ES ? "Archivo copiado." : "File copied.", "bot");
  } catch {
    appendBubble(state.lang === LANG.ES ? "No se pudo copiar." : "Could not copy.", "error");
  }
}

async function uploadZipProject() {
  const f = dom.projectUploadInput?.files?.[0];
  dom.projectUploadInput.value = "";
  if (!f) return;

  appendBubble(state.lang === LANG.ES ? "Subiendo ZIP..." : "Uploading ZIP...", "bot");
  const fd = new FormData();
  fd.append("file", f);
  fd.append("root", state.currentProjectRoot);

  try {
    const res = await fetchWithTimeout(endpoints.filesUploadZip, { method: "POST", body: fd }, { timeout: 120000, retries: 0 });
    const data = await safeJson(res);
    if (!res.ok) throw new Error(data?.detail || "upload failed");
    appendBubble(state.lang === LANG.ES ? "ZIP subido." : "ZIP uploaded.", "bot");
    if (data?.path) setProjectRoot(data.path);
    loadProjectTree();
  } catch (err) {
    console.error(err);
    appendBubble(state.lang === LANG.ES ? "No se pudo subir el ZIP." : "Could not upload ZIP.", "error");
  }
}

async function cloneRepo() {
  const repo = prompt(state.lang === LANG.ES ? "URL del repo (https://...)" : "Repo URL (https://...)");
  if (!repo) return;
  const branch = prompt(state.lang === LANG.ES ? "Branch (opcional)" : "Branch (optional)") || "";

  appendBubble(state.lang === LANG.ES ? "Clonando..." : "Cloning...", "bot");
  try {
    const res = await fetchWithTimeout(endpoints.filesClone, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ repo_url: repo, branch: branch || undefined, root: state.currentProjectRoot }),
    }, { timeout: 180000, retries: 0 });

    const data = await safeJson(res);
    if (!res.ok) throw new Error(data?.detail || "clone failed");
    appendBubble(state.lang === LANG.ES ? "Repo clonado." : "Repo cloned.", "bot");
    if (data?.path) setProjectRoot(data.path);
    loadProjectTree();
  } catch {
    appendBubble(state.lang === LANG.ES ? "No se pudo clonar." : "Clone failed.", "error");
  }
}

async function deleteProject() {
  const ok = window.confirm(state.lang === LANG.ES ? "¿Eliminar proyecto cargado?" : "Delete uploaded project?");
  if (!ok) return;

  if (!state.currentProjectRoot) {
    appendBubble(state.lang === LANG.ES ? "No hay proyecto seleccionado." : "No project selected.", "error");
    return;
  }
  const isUploadPath = String(state.currentProjectRoot || "").includes("uploads");
  if (!isUploadPath) {
    appendBubble(state.lang === LANG.ES ? "Solo se pueden borrar proyectos subidos/clonados." : "Only uploaded/cloned projects can be deleted.", "error");
    return;
  }

  try {
    const res = await fetchWithTimeout(endpoints.filesDeleteProject, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ path: state.currentProjectRoot }),
    }, { timeout: 30000, retries: 0 });

    const data = await safeJson(res);
    if (!res.ok) throw new Error(data?.detail || "delete failed");
    appendBubble(state.lang === LANG.ES ? "Proyecto eliminado." : "Project deleted.", "bot");
    if (state.ingestPollTimer) {
      clearInterval(state.ingestPollTimer);
      state.ingestPollTimer = null;
    }
    state.ingestJobId = null;
    setProjectRoot("app");
    loadProjectTree();
  } catch {
    appendBubble(state.lang === LANG.ES ? "No se pudo eliminar." : "Could not delete.", "error");
  }
}

async function startIngest() {
  appendBubble(state.lang === LANG.ES ? "Ingestando..." : "Ingesting...", "bot");
  if (!state.currentProjectRoot) {
    appendBubble(state.lang === LANG.ES ? "Selecciona un proyecto válido." : "Select a valid project first.", "error");
    return;
  }
  if (!String(state.currentProjectRoot || "").includes("uploads")) {
    appendBubble(state.lang === LANG.ES ? "La ingesta solo acepta rutas subidas/clonadas." : "Ingest only accepts uploaded/cloned paths.", "error");
    return;
  }
  try {
    const res = await fetchWithTimeout(endpoints.filesIngest, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ path: state.currentProjectRoot, background: true }),
    }, { timeout: 60000, retries: 0 });

    const data = await safeJson(res);
    if (!res.ok) throw new Error(data?.detail || "ingest failed");

    state.ingestJobId = data?.job_id ? String(data.job_id) : null;
    if (state.ingestPollTimer) {
      clearInterval(state.ingestPollTimer);
      state.ingestPollTimer = null;
    }
    if (state.ingestJobId) {
      appendBubble(
        state.lang === LANG.ES ? `Ingesta en background (job ${state.ingestJobId}).` : `Ingest queued (job ${state.ingestJobId}).`,
        "bot"
      );
      pollIngestStatus();
    } else {
      appendBubble(state.lang === LANG.ES ? "Ingesta completada." : "Ingest finished.", "bot");
    }
    loadIngestJobs();
  } catch {
    appendBubble(state.lang === LANG.ES ? "No se pudo iniciar ingesta." : "Could not start ingest.", "error");
  }
}

function pollIngestStatus() {
  if (!state.ingestJobId) return;
  if (state.ingestPollTimer) clearInterval(state.ingestPollTimer);
  loadIngestStatus();
  state.ingestPollTimer = setInterval(loadIngestStatus, 3000);
}

async function loadIngestStatus() {
  if (!state.ingestJobId) return;
  try {
    const url = new URL(endpoints.filesIngestStatus, location.origin);
    url.searchParams.set("job_id", state.ingestJobId);
    const res = await fetchWithTimeout(url.toString(), {}, { timeout: 8000, retries: 0 });
    const data = await safeJson(res);
    if (!res.ok || !data) throw new Error();

    const status = data.status || data.state || "queued";
    if (dom.ingestStatusText) dom.ingestStatusText.textContent = status;

    const statusLower = String(status).toLowerCase();
    const active = ["queued", "running", "processing", "embedding", "indexing"].includes(statusLower);
    dom.ingestStatusBtn?.classList.toggle("active", active);

    if (!active) {
      clearInterval(state.ingestPollTimer);
      state.ingestPollTimer = null;
      appendBubble(
        statusLower === "failed"
          ? (state.lang === LANG.ES ? "Ingesta falló." : "Ingest failed.")
          : (state.lang === LANG.ES ? "Ingesta finalizada." : "Ingest done."),
        statusLower === "failed" ? "error" : "bot"
      );
      state.ingestJobId = null;
    }
  } catch {
    clearInterval(state.ingestPollTimer);
    state.ingestPollTimer = null;
    state.ingestJobId = null;
    dom.ingestStatusBtn?.classList.remove("active");
    if (dom.ingestStatusText) dom.ingestStatusText.textContent = state.lang === LANG.ES ? "error" : "error";
  }
}

async function loadIngestJobs() {
  if (!dom.ingestJobsList) return;
  dom.ingestJobsList.innerHTML = "";
  try {
    const url = new URL(endpoints.filesIngestJobs, location.origin);
    const res = await fetchWithTimeout(url.toString(), {}, { timeout: 10000, retries: 0 });
    const data = await safeJson(res);
    if (!res.ok) throw new Error();

    const items = data.items || data.jobs || data || [];
    if (!items.length) {
      dom.ingestJobsList.innerHTML = `<li class="sessions-empty">${state.lang === LANG.ES ? "Sin trabajos." : "No jobs."}</li>`;
      return;
    }

    items.slice(0, 25).forEach((j) => {
      const li = document.createElement("li");
      li.className = "jobs-item";
      const status = j.status || j.state || "—";
      li.innerHTML = `
        <div class="jobs-item-header">
          <span>${j.id || "(job)"}</span>
          <span class="jobs-status ${String(status).toLowerCase()}">${status}</span>
        </div>
        <div class="jobs-meta">${j.updated_at ? new Date(j.updated_at * 1000).toLocaleString() : ""}</div>
      `;
      dom.ingestJobsList.appendChild(li);
    });
  } catch {
    dom.ingestJobsList.innerHTML = `<li class="sessions-empty">${state.lang === LANG.ES ? "No se pudieron cargar trabajos." : "Could not load jobs."}</li>`;
  }
}

/* ------------------------- LOGS + ALERTS ------------------------- */

async function adminRefreshCrypto() {
  appendBubble(state.lang === LANG.ES ? "Lanzando refresh cripto..." : "Launching crypto refresh...", "bot");
  try {
    const res = await fetchWithTimeout(
      endpoints.adminRefresh,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      },
      { timeout: 30000, retries: 0 }
    );
    const data = await safeJson(res);
    if (!res.ok) throw new Error();
    const rawLog = data?.log_path || data?.logPath || null;
    if (rawLog) {
      const rel = rawLog.includes("/logs/") ? rawLog.split("/logs/").pop() : rawLog;
      state.logPath = rel ? `logs/${rel}` : rawLog;
      state.logIsAdmin = true;
    } else {
      state.logPath = null;
      state.logIsAdmin = false;
    }
    activateTab("sources");
    if (dom.logsLiveToggle) dom.logsLiveToggle.checked = true;
    startLogsPolling();
  } catch {
    appendBubble(state.lang === LANG.ES ? "No se pudo iniciar refresh." : "Could not start refresh.", "error");
  }
}

function startLogsPolling() {
  stopLogsPolling();
  state.logsTimer = setInterval(loadLogs, 3000);
  loadLogs();
}
function stopLogsPolling() {
  if (state.logsTimer) clearInterval(state.logsTimer);
  state.logsTimer = null;
}

async function loadLogs() {
  if (!dom.sourcesContent) return;
  try {
    let url;
    if ((state.logPath && state.logPath.includes("refresh_")) || state.logIsAdmin) {
      url = new URL(endpoints.adminRefreshLog, location.origin);
      url.searchParams.set("path", state.logPath);
    } else {
      url = new URL(endpoints.filesIngestLog, location.origin);
      if (state.logPath) url.searchParams.set("path", state.logPath);
    }

    const res = await fetchWithTimeout(url.toString(), {}, { timeout: 9000, retries: 0 });
    const data = await safeJson(res);
    if (!res.ok) return;

    const lines = data?.lines || data?.log || data?.content || data;
    dom.sourcesContent.innerHTML = "";
    if (state.logIsAdmin) {
      const info = el("div", { class: "log-hint" });
      info.textContent = state.lang === LANG.ES
        ? "🔍 Log de refresh cripto (fetch -> train): si Reddit bloquea (403) el sentimiento queda en 0; si Binance depth hace timeout, se ignora. El entrenamiento continúa. Para saltar Reddit usa AEGIS_SKIP_REDDIT_SENTIMENT=1."
        : "🔍 Crypto refresh log (fetch -> train): if Reddit blocks (403) sentiment is set to 0; if Binance depth times out, it’s skipped. Training continues. To skip Reddit set AEGIS_SKIP_REDDIT_SENTIMENT=1.";
      dom.sourcesContent.appendChild(info);
    }
    const pre = el("pre", { class: "sources-content" });
    pre.style.whiteSpace = "pre-wrap";
    pre.textContent = Array.isArray(lines) ? lines.join("") : String(lines ?? "");
    dom.sourcesContent.appendChild(pre);
  } catch {}
}

function startAlertsPolling() {
  stopAlertsPolling();
  state.alertsTimer = setInterval(checkAlerts, 12000);
  checkAlerts();
}
function stopAlertsPolling() {
  if (state.alertsTimer) clearInterval(state.alertsTimer);
  state.alertsTimer = null;
}

async function checkAlerts() {
  // simple local alert: watch outcomes and bubble when a miss happens
  try {
    const url = new URL("/crypto/predictions/outcomes", location.origin);
    url.searchParams.set("limit", "40");
    const res = await fetchWithTimeout(url.toString(), {}, { timeout: 8000, retries: 0 });
    const outs = await safeJson(res);
    if (!res.ok || !Array.isArray(outs)) return;

    let emitted = 0;
    outs.forEach((o) => {
      const id = o.log_id || o.id;
      if (!id || state.seenAlerts.has(id)) return;
      const delta = Math.abs(Number(o.delta_pct || 0));
      if (delta < 0.02) return; // ignore tiny moves (<2%)
      state.seenAlerts.add(id);
      if (o.hit === false && emitted < 3) {
        appendBubble(
          state.lang === LANG.ES
            ? `⚠️ Alert: fallo en ${o.symbol || "—"} Δ ${formatPct(o.delta_pct)}`
            : `⚠️ Alert: miss on ${o.symbol || "—"} Δ ${formatPct(o.delta_pct)}`,
          "error"
        );
        emitted += 1;
      }
    });
  } catch {}
}
