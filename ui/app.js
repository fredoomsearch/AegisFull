/* AEGIS UI - app.js (single-file frontend logic)
   - FIXED: no HTML in CSS, no /chat/new dependency
   - Robust: tolerates different response shapes from backend
*/

// Boot marker + crash capture (used by index.html watchdog)
try {
  window.__AEGIS_UI_BOOTED__ = true;
  window.__AEGIS_UI_BOOT_ERROR__ = null;
} catch {}

const MODES = { CHAT: "chat", WEB: "web", URL: "url", CRYPTO: "crypto", IMAGE: "image" };
const LANG = { ES: "es", EN: "en" };

// Frontend should not cut model responses by default.
// Long-running endpoints are handled without client-side abort deadlines.
const CHAT_MAX_TIMEOUT_MS = 0;
const AUTH_RETRY_BASE_MS = 1500;
const AUTH_RETRY_MAX_MS = 30000;
const RESET_CONV_ON_LOAD = false;
// Keep all explicit modes visible by default (chat/web/url/crypto/image).
const CHAT_ONLY_EXPERIENCE = false;
// Keep agent internals available server-side, but hide agent-centric UI controls by default.
const AGENT_UI_ENABLED = false;
// Keep snapshot/session view concise; detailed crypto analytics stay in crypto panel.
const SNAPSHOT_MINIMAL_VIEW = true;

const endpoints = {
  websearch: "/websearch",
  chat: "/chat",
  fetchUrl: "/fetch_url",
  conversations: "/chat/list",
  conversationBundle: (id) => `/chat/${id}/bundle`,
  archiveConversation: (id) => `/chat/${id}/archive`,
  unarchiveConversation: (id) => `/chat/${id}/unarchive`,
  deleteConversation: (id) => `/chat/${id}`,
  analyzeAttachment: "/analyze_attachment",
  conversationEvents: (id) => `/chat/${id}/events`,

  cryptoPredict: "/crypto/predict",
  cryptoModels: "/crypto/models",
  cryptoOhlcv: "/crypto/ohlcv",
  cryptoTrade: "/crypto/trade",
  cryptoTradePreview: "/crypto/trade/preview",
  cryptoTrades: "/crypto/trades",
  cryptoTradesClear: "/crypto/trades",
  cryptoPnl: "/crypto/pnl",
  cryptoNews: "/crypto/news",
  cryptoPredictions: "/crypto/predictions",
  cryptoPredictionThresholds: "/crypto/predictions/thresholds",
  cryptoPredictionCredibility: "/crypto/predictions/credibility",
  cryptoPredictionLeaderboard: "/crypto/predictions/leaderboard",
  cryptoPredictionStatsExport: "/crypto/predictions/stats/export",
  cryptoPredictionsClear: "/crypto/predictions",
  cryptoModelsRegistry: "/crypto/models/registry",
  cryptoSymbolsMeta: "/crypto/symbols/meta",
  cryptoState: "/crypto/state",
  cryptoStateStream: "/crypto/stream",
  adminRefresh: "/admin/refresh-crypto",
  adminRefreshLog: "/admin/refresh-log",
  adminCancelAll: "/admin/cancel-all",
  systemSnapshot: "/system/snapshot",
  systemLlmProvider: "/system/llm/provider",
  systemCapabilities: "/system/capabilities",
  imageGenerate: "/image/generate",
  imageGenerateWithReference: "/image/generate_with_reference",
  imageRecent: "/image/recent",
  imageCheckpoints: "/image/checkpoints",
  healthz: "/healthz",
  authToken: "/auth/token",
  authRefresh: "/auth/refresh",

  systemReadyz: "/system/readyz",
  systemDemoCheck: "/system/demo_check",
  systemShutdown: "/system/shutdown",
  authLogout: "/auth/logout",

  filesTree: "/files/tree",
  filesContent: "/files/content",
  filesDiffContent: "/files/content/diff",
  filesSaveContent: "/files/content/save",
  filesRenameContent: "/files/content/rename",
  filesDeleteContent: "/files/content/delete",
  filesCreateDir: "/files/path/mkdir",
  filesMovePath: "/files/path/move",
  filesBatchPreview: "/files/batch/preview",
  filesBatchApply: "/files/batch/apply",
  filesApplyIdea: (id, ideaId) => `/files/projects/${id}/ideas/${ideaId}/apply`,

  filesUploadZip: "/files/upload-zip",
  filesProjects: "/files/projects",
  filesProjectDetail: (id) => `/files/projects/${id}`,
  filesProjectFiles: (id) => `/files/projects/${id}/files`,
  filesProjectSymbols: (id) => `/files/projects/${id}/symbols`,
  filesProjectEntrypoints: (id) => `/files/projects/${id}/entrypoints`,
  filesProjectDependencies: (id) => `/files/projects/${id}/dependencies`,
  filesProjectConfigs: (id) => `/files/projects/${id}/configs`,
  filesProjectIdeas: (id) => `/files/projects/${id}/ideas`,
  filesProjectIntelligence: (id) => `/files/projects/${id}/intelligence`,
  filesProjectImpact: (id) => `/files/projects/${id}/impact`,
  filesProjectRenamePlan: (id) => `/files/projects/${id}/rename_plan`,
  filesClone: "/files/clone",
  filesDeleteProject: "/files/delete_project",
  filesRegisterRoot: "/files/register-root",
  filesIngest: "/files/ingest",
  filesIngestStatus: "/files/ingest/status",
  filesIngestJobs: "/files/ingest/jobs",
  filesIngestRecent: "/files/ingest/recent",
  filesIngestLog: "/files/ingest/log",
  filesAvStatus: "/files/av/status",
  filesAvRecent: "/files/av/recent",
  bindConversationProject: (id) => `/chat/${id}/project`,
  conversationState: (id) => `/chat/${id}/state`,
  conversationTurns: (id) => `/chat/${id}/turns`,
  conversationTurnDetail: (id, turnId) => `/chat/${id}/turns/${turnId}`,
  conversationExecuteTool: (id) => `/chat/${id}/execute_tool`,
  conversationAgentStep: (id) => `/chat/${id}/agent_step`,
  conversationAgentRun: (id) => `/chat/${id}/agent_run`,
  conversationAgentContinue: (id) => `/chat/${id}/agent_continue`,
};

const CRYPTO_SEARCH_SYMBOLS = [
  "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "TRXUSDT",
  "LINKUSDT", "MATICUSDT", "LTCUSDT", "ATOMUSDT", "ETCUSDT", "XLMUSDT", "BCHUSDT", "APTUSDT", "ARBUSDT", "OPUSDT",
  "SUIUSDT", "NEARUSDT", "AAVEUSDT", "UNIUSDT", "XMRUSDT", "FILUSDT", "ALGOUSDT", "XTZUSDT", "MKRUSDT", "INJUSDT",
  "RUNEUSDT", "KASUSDT", "IMXUSDT", "TIAUSDT", "WIFUSDT", "PEPEUSDT", "SHIBUSDT", "BONKUSDT", "SEIUSDT", "STXUSDT",
  "THETAUSDT", "ICPUSDT", "RNDRUSDT", "GRTUSDT", "SANDUSDT", "MANAUSDT", "ENJUSDT", "EOSUSDT", "EGLDUSDT", "VETUSDT",
  "HBARUSDT", "QNTUSDT", "LDOUSDT", "JUPUSDT", "JTOUSDT", "PYTHUSDT", "FETUSDT", "WLDUSDT", "CRVUSDT", "COMPUSDT",
  "SNXUSDT", "FTMUSDT", "GALAUSDT", "DYDXUSDT", "ARUSDT", "AXSUSDT", "PENDLEUSDT", "ONDOUSDT", "STRKUSDT", "1INCHUSDT",
  "IOTAUSDT", "KAVAUSDT", "ZRXUSDT", "CAKEUSDT", "CELOUSDT", "GMXUSDT", "FLOWUSDT",
];

const cleanKey = (k) =>
  (k || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)[0] || "";

function readJsonStorage(key, fallback) {
  try {
    const raw = readSecretItem(key);
    if (!raw) return fallback;
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

function readSecretItem(key) {
  const k = String(key || "").trim();
  if (!k) return "";
  try {
    const sessionValue = sessionStorage.getItem(k) || "";
    if (sessionValue) return sessionValue;
    const legacyValue = localStorage.getItem(k) || "";
    if (legacyValue) {
      sessionStorage.setItem(k, legacyValue);
      localStorage.removeItem(k);
    }
    return legacyValue;
  } catch {
    try {
      return sessionStorage.getItem(k) || "";
    } catch {
      return "";
    }
  }
}

function writeSecretItem(key, value) {
  const k = String(key || "").trim();
  if (!k) return;
  try {
    if (value) sessionStorage.setItem(k, String(value));
    else sessionStorage.removeItem(k);
  } catch {}
  try {
    localStorage.removeItem(k);
  } catch {}
}

function hasMainApiKey() {
  if (state.cookieAuth) return Array.isArray(state.authScopes) ? state.authScopes.length > 0 : false;
  return !!cleanKey(state.apiKey);
}

function hasFilesApiKey() {
  if (state.cookieAuth) {
    return Array.isArray(state.authScopes) && state.authScopes.includes("files");
  }
  return !!cleanKey(state.filesApiKey || state.apiKey);
}

function hasAuthForScope(scope = "main") {
  return scope === "files" ? hasFilesApiKey() : hasMainApiKey();
}

const state = {
  mode: MODES.CHAT,
  lang: localStorage.getItem("aegis_lang") || LANG.ES,
  conversationId: localStorage.getItem("aegis_conv") || null,
  useExistingConversation: localStorage.getItem("aegis_use_existing") === "1",
  apiKey: cleanKey(readSecretItem("aegis_api_key")),
  filesApiKey: cleanKey(readSecretItem("aegis_files_api_key") || readSecretItem("aegis_api_key")),
  cookieAuth: readSecretItem("aegis_cookie_auth") === "1",
  authScopes: readJsonStorage("aegis_auth_scopes", []),
  authCookieExp: Number(readSecretItem("aegis_auth_cookie_exp") || "0"),
  imageReferenceFile: null,
  chatAttachment: null,
  chatAttachmentAutoWeb: JSON.parse(localStorage.getItem("aegis_attachment_auto_web") || "true"),

  pending: false,
  activeControllers: new Set(),
  cancelledByUser: false,
  lastLatencyMs: null,
  lastReadyz: null,
  readyzTimer: null,
  llmProviderMenuOpen: false,
  llmProviderState: null,

  // UI / sidebar (input auxiliar; el proyecto activo real vive en activeProjectId)
  manualProjectRoot: String(localStorage.getItem("aegis_project_root") || "").trim(),
  fileViewerPath: "",
  fileViewerContent: "",
  fileViewerEditing: false,
  fileViewerIsNew: false,
  fileViewerDiffMode: false,
  fileViewerDiffText: "",
  fileViewerPreviousPath: "",
  fileViewerPreviousContent: "",
  treeSelectionPath: "",
  treeSelectionIsDir: false,
  batchApplyReviewToken: "",
  batchApplyReviewedPayload: "",
  batchApplyPreviewText: "",

  // crypto + chart
  chartSymbol: "BTCUSDT",
  chartInstance: null,
  lastPoints: [],
  tradesOnChart: [],
  compareMarkers: [],
  compareHighlightId: null,
  cryptoModelsMeta: { available: ["ensemble"], default: "ensemble" },
  cryptoModelRegistry: [],
  cryptoSymbolMeta: null,
  selectedCryptoModel: "ensemble",
  cryptoExecutionMode: localStorage.getItem("aegis_crypto_execution_mode") || "simulated",
  cryptoPreviewSide: localStorage.getItem("aegis_crypto_preview_side") || "BUY",
  cryptoState: null,
  cryptoTradePreview: null,
  cryptoTradePreviewPendingOrder: null,
  cryptoTradePreviewArmed: false,
  cryptoStatsEngine: localStorage.getItem("aegis_crypto_stats_engine") || "trained",
  cryptoThresholdRec: null,
  cryptoCredibility: null,
  cryptoLeaderboard: [],
  lastPrediction: null,
  lastTradeQuote: null,
  savePredictions: JSON.parse(localStorage.getItem("aegis_save_preds") || "true"),
  alertsOn: JSON.parse(localStorage.getItem("aegis_alerts") || "false"),
  showNewsMarkers: localStorage.getItem("aegis_show_news_markers") === "1",
  newsProvider: null,
  chatSideVisible: false,
  layoutCollapsed: localStorage.getItem("aegis_layout_collapsed") === "1",
  // Keep crypto chart/sources collapsed by default until user explicitly opens it.
  chartVisible: localStorage.getItem("aegis_chart_visible") === "1",
  sidebarVisible: localStorage.getItem("aegis_sidebar_visible") !== "0",
  chartRangeMinutes: Math.max(0, Number(localStorage.getItem("aegis_chart_range_minutes") || "0")) || 0,
  chartViewMode: "auto", // auto (preset/all) | manual (wheel zoom/pan)
  chartWindow: null, // { start, end } index window for manual view

  // timers
  liveTimer: null,
  newsTimer: null,
  logsTimer: null,
  logIsAdmin: false,
  logJobId: null,
  alertsTimer: null,
  snapshotTimer: null,
  autoSnapshotEnabled: true,
  tokenRefreshTimer: null,
  ingestPollTimer: null,
  ingestJobsTimer: null,
  ingestJobId: null,
  convEventsTimer: null,
  convEventsSince: null,
  convEventsItems: [],
  convEventsFailures: 0,
  convAuthBlockedAt: 0,
  convTurnsItems: [],
  convTurnsTimer: null,
  turnsFilter: localStorage.getItem("aegis_turns_filter") || "",
  convTurnsInFlight: false,
  convTurnsForceQueued: false,
  convEventsInFlight: false,
  convEventsForceQueued: false,
  readyzInFlight: false,
  chartInFlight: false,
  chartQueued: false,
  chartQueuedSymbol: "",
  newsInFlight: false,
  newsForceQueued: false,
  snapshotInFlight: false,
  snapshotQueued: false,
  alertsInFlight: false,
  cryptoPredictionInFlight: false,
  cryptoPredictionQueued: false,
  cryptoStateInFlight: false,
  cryptoStateQueued: false,
  cryptoStateTimer: null,
  cryptoStateStreamActive: false,
  cryptoStateStreamInFlight: false,
  cryptoStateStreamController: null,
  cryptoStateStreamReconnectTimer: null,
  cryptoStateStreamKey: "",
  cryptoStateStreamFailures: 0,
  cryptoStateStreamLastHeartbeatAt: 0,
  cryptoStateStreamFallbackActive: false,
  cryptoTradePreviewInFlight: false,
  cryptoTradePreviewQueued: false,
  cryptoTradePreviewTimer: null,
  lastCryptoStateAt: 0,
  lastCryptoStateKey: "",
  lastCryptoTradePreviewAt: 0,
  lastCryptoTradePreviewKey: "",
  lastCryptoPredictionAt: 0,
  lastCryptoPredictionKey: "",

  // session modal
  conversationList: [],
  conversationsIncludeArchived: false,
  lastTranscriptConversationId: "",

  // logs
  logPath: null,

  // alerts
  seenAlerts: new Set(),

  // theme
  theme: "serious", // sober default palette for daily use
  debugTraceEnabled: localStorage.getItem("aegis_debug_trace") === "1",
  chatOnlyExperience: CHAT_ONLY_EXPERIENCE,
  lastSourceUsageNotice: "",
  statusNoticeTimes: new Map(),
  uploadedProjects: [],
  projectRecords: [],
  showProjectList: localStorage.getItem("aegis_show_project_list") === "1",
  showProjectAdvanced: localStorage.getItem("aegis_show_project_advanced") === "1",
  showTempProjects: localStorage.getItem("aegis_show_temp_projects") === "1",
  activeProjectId: localStorage.getItem("aegis_active_project_id") || "",
  activeProjectDetail: null,
  activeProjectImpact: null,
  lastSnapshot: null,
  lastChatContext: null,
  accessToken: "",
  refreshToken: "",
  tokenExp: 0,
  authDiag: {
    failures: 0,
    lastError: null,
    lastOkAt: 0,
  },
  authRetryFailures: 0,
  authRetryBlockedUntil: 0,
  authHintShown: false,
};

const dom = {};

document.addEventListener("DOMContentLoaded", () => {
  try {
    document.body.classList.add("perf-lite");
    cacheDom();
    wireUI();
    initState();
    updateAllUI();
    loadLlmProviderState();
    applyAuthState();
    appendBubble(state.lang === LANG.ES ? "AEGIS listo." : "AEGIS ready.", "bot");
    localizeHelp();
    // placeholders
    if (dom.filesLogContent) dom.filesLogContent.textContent = state.lang === LANG.ES ? "Selecciona un log (ingest/admin) para verlo aquí." : "Select a log (ingest/admin) to view it here.";
    renderProjectList();
    void loadCryptoSymbolsMeta().then(() => loadSymbolsList(dom.chartSymbol?.value || ""));
    startTokenAutoRefresh();
    startReadyzPolling();
    document.addEventListener("visibilitychange", updateCryptoStatePolling);
    applyLayoutCollapsed();
    if (state.autoSnapshotEnabled) scheduleSnapshot(1500);
  } catch (err) {
    try {
      window.__AEGIS_UI_BOOT_ERROR__ = err?.stack || err?.message || String(err);
    } catch {}
    // Best-effort visible fallback (doesn't depend on markdown libs)
    try {
      const diag = document.getElementById("uiBootDiagBody");
      const wrap = document.getElementById("uiBootDiag");
      if (diag && wrap) {
        diag.textContent =
          "UI init failed.\n\n" +
          (err?.stack || err?.message || String(err));
        wrap.style.display = "block";
      }
    } catch {}
    console.error(err);
  }
});

function applyAuthState() {
  const es = state.lang === LANG.ES;
  const missingKey = !hasAuthForScope("main");
  // Do not hard-disable primary actions when the key is missing: it confuses users ("nothing happens").
  // Instead, let clicks open the API key modal and show a clear message.
  const disabled = !!state.pending;
  if (dom.sendBtn) {
    dom.sendBtn.disabled = disabled;
    dom.sendBtn.classList.toggle("requires-key", missingKey);
    dom.sendBtn.title = missingKey
      ? (es ? "Configura tu clave de arranque (🔑) para autenticar." : "Set your bootstrap key (🔑) to authenticate.")
      : "";
  }
  if (dom.stopBtn) {
    const activeWork = !!state.pending || state.activeControllers.size > 0;
    dom.stopBtn.hidden = !activeWork;
    dom.stopBtn.disabled = !activeWork;
    dom.stopBtn.title = es
      ? "Detener solicitudes activas y procesos del panel"
      : "Stop active requests and panel jobs";
  }
  if (dom.apiKeyBtn) dom.apiKeyBtn.classList.toggle("danger", missingKey);

  if (missingKey && !state.authHintShown) {
    state.authHintShown = true;
    appendBubble(
      es
        ? "Configura tu clave de arranque (ícono 🔑 arriba) para usar Chat/Files. La UI guarda solo una sesión HttpOnly y limpia la clave luego del bootstrap."
        : "Set your bootstrap key (🔑 icon) to use Chat/Files. The UI keeps only an HttpOnly session and clears the key after bootstrap.",
      "error"
    );
    // Reduce confusion: if the modal exists, open it once automatically.
    try {
      const prompted = localStorage.getItem("aegis_api_key_prompted") === "1";
      if (!prompted && dom.apiKeyModal) {
        localStorage.setItem("aegis_api_key_prompted", "1");
        setTimeout(() => openModal(dom.apiKeyModal), 50);
      }
    } catch {}
  }
}

function ensureApiKeyOrPrompt({ action = "chat" } = {}) {
  if (hasAuthForScope("main")) return true;

  const es = state.lang === LANG.ES;
  appendBubble(
    es
      ? `Falta la clave de arranque. Abre 🔑 para continuar (${action}).`
      : `Missing bootstrap key. Open 🔑 to continue (${action}).`,
    "error"
  );
  try {
    if (dom.apiKeyModal) openModal(dom.apiKeyModal);
    else dom.apiKeyBtn?.click?.();
  } catch {}
  return false;
}

function cacheDom() {
  dom.chat = document.getElementById("chat");
  dom.modeIndicator = document.getElementById("modeIndicator");
  dom.runtimeStatusBadge = document.getElementById("runtimeStatusBadge");
  dom.webStatusBadge = document.getElementById("webStatusBadge");
  dom.llmProviderShell = document.getElementById("llmProviderShell");
  dom.llmProviderBtn = document.getElementById("llmProviderBtn");
  dom.llmProviderBtnText = dom.llmProviderBtn ? dom.llmProviderBtn.querySelector(".llm-provider-btn-text") : null;
  dom.llmProviderMenu = document.getElementById("llmProviderMenu");
  dom.llmProviderMenuTitle = document.getElementById("llmProviderMenuTitle");
  dom.llmProviderSummary = document.getElementById("llmProviderSummary");
  dom.llmProviderLocalState = document.getElementById("llmProviderLocalState");
  dom.llmProviderCloudState = document.getElementById("llmProviderCloudState");
  dom.llmProviderLocalNote = document.getElementById("llmProviderLocalNote");
  dom.llmProviderCloudNote = document.getElementById("llmProviderCloudNote");
  dom.llmProviderLocalBtn = document.getElementById("llmProviderLocalBtn");
  dom.llmProviderCloudBtn = document.getElementById("llmProviderCloudBtn");
  dom.msgInput = document.getElementById("msg");
  dom.stopBtn = document.getElementById("stopBtn");
  dom.backendStopBtn = document.getElementById("backendStopBtn");
  dom.backendProcessBadge = document.getElementById("backendProcessBadge");
  dom.sendBtn = document.getElementById("sendBtn");

  dom.chatBtn = document.getElementById("chatBtn");
  dom.webBtn = document.getElementById("webBtn");
  dom.urlBtn = document.getElementById("urlBtn");
  dom.cryptoBtn = document.getElementById("cryptoBtn");
  dom.imgBtn = document.getElementById("imgBtn");
  dom.attachBtn = document.getElementById("attachBtn");
  dom.layoutToggle = document.getElementById("layoutToggle");
  dom.imgInput = document.getElementById("imgInput");
  dom.attachmentInput = document.getElementById("attachmentInput");
  dom.chatAttachmentBar = document.getElementById("chatAttachmentBar");
  dom.chatAttachmentLabel = document.getElementById("chatAttachmentLabel");
  dom.chatAttachmentAutoWeb = document.getElementById("chatAttachmentAutoWeb");
  dom.chatAttachmentClear = document.getElementById("chatAttachmentClear");
  dom.imageQuickBar = document.getElementById("imageQuickBar");
  dom.imageModeGuide = document.getElementById("imageModeGuide");

  dom.langEs = document.getElementById("langEs");
  dom.langEn = document.getElementById("langEn");

  dom.convIdDisplay = document.getElementById("conv-id-display");
  dom.convIdChip = document.getElementById("conv-id-chip");
  dom.convEventsList = document.getElementById("convEventsList");
  dom.convEventsRefresh = document.getElementById("convEventsRefresh");
  dom.convTurnsList = document.getElementById("convTurnsList");
  dom.sessionsEventsWrap = document.querySelector(".sessions-events-wrap");
  dom.sessionsTurnsWrap = document.querySelector(".sessions-turns-wrap");
  dom.turnsFilter = document.getElementById("turnsFilter");
  dom.turnsOpenBtn = document.getElementById("turnsOpenBtn");
  dom.turnsQuickFilters = document.getElementById("turnsQuickFilters");
  dom.turnDetailModal = document.getElementById("turnDetailModal");
  dom.turnDetailTitle = document.getElementById("turnDetailTitle");
  dom.turnDetailSummary = document.getElementById("turnDetailSummary");
  dom.turnDetailToolWrap = document.getElementById("turnDetailToolWrap");
  dom.turnDetailToolLabel = document.getElementById("turnDetailToolLabel");
  dom.turnDetailToolOut = document.getElementById("turnDetailToolOut");
  dom.turnDetailJsonLabel = document.getElementById("turnDetailJsonLabel");
  dom.turnDetailBody = document.getElementById("turnDetailBody");
  dom.turnDetailClose = document.getElementById("turnDetailClose");
  dom.turnDetailCopy = document.getElementById("turnDetailCopy");

  dom.apiKeyBtn = document.getElementById("apiKeyBtn");
  dom.apiKeyModal = document.getElementById("apiKeyModal");
  dom.apiKeyClose = document.getElementById("apiKeyClose");
  dom.apiKeySave = document.getElementById("apiKeySave");
  dom.apiKeyClear = document.getElementById("apiKeyClear");
  dom.apiKeyMainInput = document.getElementById("apiKeyMainInput");
  dom.apiKeyFilesInput = document.getElementById("apiKeyFilesInput");
  dom.apiKeyUseSame = document.getElementById("apiKeyUseSame");
  dom.globalSnapshotBtn = document.getElementById("globalSnapshotBtn");
  dom.showCryptoPanelBtn = document.getElementById("showCryptoPanelBtn");
  dom.showFilesPanelBtn = document.getElementById("showFilesPanelBtn");
  dom.helpBtn = document.getElementById("helpBtn");
  dom.helpModal = document.getElementById("helpModal");
  dom.helpClose = document.getElementById("helpClose");
  dom.symbolsBtn = document.getElementById("symbolsBtn");
  dom.symbolsModal = document.getElementById("symbolsModal");
  dom.symbolsClose = document.getElementById("symbolsClose");
  dom.symbolsList = document.getElementById("symbolsList");
  dom.symbolsQuotes = document.getElementById("symbolsQuotes");

  dom.hintBtn = document.getElementById("hintBtn");
  dom.hintTooltip = document.getElementById("chat-hint-tooltip");

  dom.sessionsList = document.getElementById("sessionsList");
  dom.sessionsIncludeArchived = document.getElementById("sessionsIncludeArchived");
  dom.focusSelect = null;

  // sidebar sources
  dom.sourcesContent = document.getElementById("sources-content");
  dom.logsLiveToggle = document.getElementById("logsLiveToggle");
  dom.savePredToggle = document.getElementById("savePredToggle");
  dom.alertsToggle = document.getElementById("alertsToggle");
  dom.predsBtn = document.getElementById("predsBtn");
  dom.pnlBtn = document.getElementById("pnlBtn");
  dom.statsBtn = document.getElementById("statsBtn");
  dom.clearCryptoBtn = document.getElementById("clearCryptoBtn");
  dom.debugTraceToggle = document.getElementById("debugTraceToggle");
  dom.statusList = document.getElementById("statusList");
  dom.copyConvId = document.getElementById("copyConvId");

  dom.newsList = document.getElementById("news-list");
  dom.newsMomentum = document.getElementById("newsMomentum");
  dom.newsProvider = document.getElementById("newsProvider");
  dom.newsRefreshBtn = document.getElementById("newsRefreshBtn");
  dom.newsCompactToggle = document.getElementById("newsCompactToggle");

  // files
  dom.projectSelect = document.getElementById("projectSelect");
  dom.refreshTreeBtn = document.getElementById("refreshTreeBtn");
  dom.projectTree = document.getElementById("projectTree");
  dom.projectUploadBtn = document.getElementById("projectUploadBtn");
  dom.projectUploadInput = document.getElementById("projectUploadInput");
  dom.projectCloneBtn = document.getElementById("projectCloneBtn");
  dom.projectDeleteBtn = document.getElementById("projectDeleteBtn");
  dom.activeProjectBadge = document.getElementById("activeProjectBadge");
  dom.activeProjectSelect = document.getElementById("activeProjectSelect");
  dom.filesToChatBtn = document.getElementById("filesToChatBtn");
  dom.projectMeta = document.getElementById("projectMeta");
  dom.ingestLogBtn = document.getElementById("ingestLogBtn");
  dom.ingestStatusBtn = document.getElementById("ingestStatusBtn");
  dom.ingestStatusText = document.getElementById("ingestStatusText");
  dom.ingestJobsList = document.getElementById("ingestJobsList");
  dom.ingestJobsRefresh = document.getElementById("ingestJobsRefresh");
  dom.filesLogContent = document.getElementById("filesLogContent");
  dom.filesExpandBtn = document.getElementById("filesExpandBtn");
  dom.projectList = document.getElementById("projectList");
  dom.projectList && (dom.projectList.title = state.lang === LANG.ES ? "Proyectos cargados/clonados" : "Uploaded/cloned projects");
  dom.sourceOriginBar = document.getElementById("sourceOriginBar");

  dom.fileViewerTitle = document.getElementById("fileViewerTitle");
  dom.fileEditorPath = document.getElementById("fileEditorPath");
  dom.fileViewerBody = document.getElementById("fileViewerBody");
  dom.fileEditorBody = document.getElementById("fileEditorBody");
  dom.copyFileBtn = document.getElementById("copyFileBtn");
  dom.newFileBtn = document.getElementById("newFileBtn");
  dom.newFolderBtn = document.getElementById("newFolderBtn");
  dom.movePathBtn = document.getElementById("movePathBtn");
  dom.batchApplyBtn = document.getElementById("batchApplyBtn");
  dom.renameFileBtn = document.getElementById("renameFileBtn");
  dom.editFileBtn = document.getElementById("editFileBtn");
  dom.diffFileBtn = document.getElementById("diffFileBtn");
  dom.deleteFileBtn = document.getElementById("deleteFileBtn");
  dom.saveFileBtn = document.getElementById("saveFileBtn");
  dom.cancelFileEditBtn = document.getElementById("cancelFileEditBtn");
  syncFileViewerMode();

  dom.chatSidePanel = document.getElementById("chatSidePanel");
  dom.chatSideToggle = document.getElementById("chatSideToggle");
  dom.chatSideShow = document.getElementById("chatSideShow");
  dom.chatCol = document.querySelector(".chat-col");
  dom.appSidebar = document.querySelector(".app-sidebar");

  dom.batchApplyModal = document.getElementById("batchApplyModal");
  dom.batchApplyClose = document.getElementById("batchApplyClose");
  dom.batchApplyInput = document.getElementById("batchApplyInput");
  dom.batchApplyPreview = document.getElementById("batchApplyPreview");
  dom.batchApplyPreviewBtn = document.getElementById("batchApplyPreviewBtn");
  dom.batchApplyRun = document.getElementById("batchApplyRun");
  dom.batchApplyTemplate = document.getElementById("batchApplyTemplate");

  // crypto controls
  dom.cryptoModelSelect = document.getElementById("cryptoModelSelect");
  dom.cryptoHorizon = document.getElementById("cryptoHorizon");
  dom.chatTradeQty = document.getElementById("chatTradeQty");
  dom.cryptoStopLossPct = document.getElementById("cryptoStopLossPct");
  dom.cryptoTakeProfitPct = document.getElementById("cryptoTakeProfitPct");
  dom.cryptoMaxExposureQuote = document.getElementById("cryptoMaxExposureQuote");
  dom.cryptoMaxOrderSizePct = document.getElementById("cryptoMaxOrderSizePct");
  dom.cryptoRiskExplain = document.getElementById("cryptoRiskExplain");
  dom.buyBtn = document.getElementById("buyBtn");
  dom.sellBtn = document.getElementById("sellBtn");
  dom.cryptoExecutionGroup = document.getElementById("cryptoExecutionGroup");
  dom.cryptoExecutionMeta = document.getElementById("cryptoExecutionMeta");
  dom.cryptoTradePreview = document.getElementById("cryptoTradePreview");
  dom.cryptoOrderBook = document.getElementById("cryptoOrderBook");

  // chart
  dom.chartPanel = document.getElementById("chartPanel");
  dom.chartSymbol = document.getElementById("chartSymbol");
  dom.chartRefresh = document.getElementById("chartRefresh");
  dom.chartExpandBtn = document.getElementById("chartExpandBtn");
  dom.chartTitle = document.getElementById("chartTitle");
  dom.priceChart = document.getElementById("priceChart");
  dom.chartModeHint = document.getElementById("chartModeHint");
  dom.chartRangeButtons = Array.from(document.querySelectorAll("[data-chart-range]"));
  dom.chartResetZoom = document.getElementById("chartResetZoom");
  dom.chartLive = document.getElementById("chartLive");
  dom.newsMarkersToggle = document.getElementById("newsMarkersToggle");
  dom.signalBar = document.getElementById("signalBar");
  dom.priceSourceBadge = document.getElementById("priceSourceBadge");
  dom.cryptoContextPill = document.getElementById("cryptoContextPill");

  dom.tradeStatus = document.getElementById("tradeStatus");

  dom.predictionCompareTitle = document.getElementById("predictionCompareTitle");
  dom.predictionCompareBody = document.getElementById("predictionCompareBody");
  dom.predictionCompareRefresh = document.getElementById("predictionCompareRefresh");
  dom.predictionCompareHelp = document.getElementById("predictionCompareHelp");
  dom.predictionCompareTooltip = document.getElementById("predictionCompareTooltip");

  // tabs (sidebar reduced to Archivos only, keep structure simple)
  dom.tabButtons = Array.from(document.querySelectorAll(".tab-btn"));
  dom.tabPanels = {
    files: document.getElementById("tab-files"),
  };
}

function initState() {
  if (RESET_CONV_ON_LOAD) {
    state.conversationId = null;
    state.useExistingConversation = false;
    localStorage.removeItem("aegis_conv");
    localStorage.removeItem("aegis_use_existing");
  }
  const storedSide = localStorage.getItem("aegis_chat_side_visible");
  if (storedSide === "1") state.chatSideVisible = true;
  if (storedSide === "0") state.chatSideVisible = false;
  // Snapshot polling is always-on in current UX contract.
  state.autoSnapshotEnabled = true;
  localStorage.setItem("aegis_auto_snapshot", "1");
  // tokens already pulled from localStorage in state init
  applyTheme(state.theme);
  document.body.dataset.mode = state.mode;
  updateConversationIndicators(state.conversationId);
  resetConversationEvents();
  syncProjectSelectValue(state.manualProjectRoot);
  if (hasAuthForScope("main")) {
    loadConversationList(state.conversationsIncludeArchived);
  } else if (dom.sessionsList) {
    dom.sessionsList.innerHTML = `<li class="sessions-empty">${
      state.lang === LANG.ES
        ? "Auth requerida. Configura la clave de arranque (🔑)."
        : "Auth required. Set the bootstrap key (🔑)."
    }</li>`;
  }
  if (state.conversationId && hasAuthForScope("main")) {
    void restoreConversationTranscript(state.conversationId, { force: true });
  }
  applyChatSideVisible();
  applyPanelVisibility();
  if (hasAuthForScope("files")) {
    if (state.activeProjectId || getEffectiveProjectRoot()) {
      loadProjectTree();
    }
    loadRegisteredProjects();
  } else {
    state.projectRecords = [];
    renderProjectList();
    renderActiveProjectSelect();
  }
  if (state.conversationId && hasAuthForScope("main")) syncConversationState(state.conversationId);
  if (dom.chatAttachmentAutoWeb) dom.chatAttachmentAutoWeb.checked = !!state.chatAttachmentAutoWeb;
  if (dom.newsMarkersToggle) dom.newsMarkersToggle.checked = !!state.showNewsMarkers;
  updateChatAttachmentBar();
  updateImageQuickBar();
  setDebugTraceEnabled(state.debugTraceEnabled, { persist: false, silent: true });
  loadSymbolsList();
  applyChatOnlyExperience();
  updateCryptoExecutionUI();
  updateCryptoStatePolling();
  if (state.chartVisible || state.mode === MODES.CRYPTO) {
    loadCryptoState({ force: true });
  }
}

function hideNode(node, hide = true) {
  if (!node) return;
  node.style.display = hide ? "none" : "";
  node.setAttribute("aria-hidden", String(!!hide));
}

function applyChatOnlyExperience() {
  if (!state.chatOnlyExperience) return;
  state.mode = MODES.CHAT;
  document.body.dataset.mode = state.mode;

  [
    dom.webBtn,
    dom.urlBtn,
    dom.cryptoBtn,
    dom.imgBtn,
    dom.attachBtn,
    dom.showCryptoPanelBtn,
  ].forEach((node) => hideNode(node, true));

  state.chartVisible = false;
  localStorage.setItem("aegis_chart_visible", "0");
  if (dom.chartPanel) dom.chartPanel.classList.add("chart-hidden");

  document.querySelectorAll("[data-i18n='hint_crypto'], [data-i18n='hint_image']").forEach((node) => {
    if (node instanceof HTMLElement) node.style.display = "none";
  });
  document.querySelectorAll("[data-i18n='help_item_crypto_label'], [data-i18n='help_item_image_label']").forEach((node) => {
    const li = node instanceof HTMLElement ? node.closest("li") : null;
    if (li instanceof HTMLElement) li.style.display = "none";
  });
}

function wireUI() {
  // send
  dom.sendBtn?.addEventListener("click", onSend);
  dom.stopBtn?.addEventListener("click", async () => {
    const activeWork = !!state.pending || state.activeControllers.size > 0;
    if (!activeWork) {
      notifyStatus(
        state.lang === LANG.ES ? "No hay procesos activos." : "No active processes.",
        { kind: "info", key: "stop:none", dedupeMs: 1200, ttlMs: 1400 }
      );
      return;
    }
    await cancelAllRequests(true);
  });
  dom.backendStopBtn?.addEventListener("click", async () => {
    const es = state.lang === LANG.ES;
    const warn = es
      ? "Esto intentará apagar el backend AEGIS en esta máquina. ¿Continuar?"
      : "This will attempt to stop the AEGIS backend on this machine. Continue?";
    if (!confirm(warn)) return;
    await cancelAllRequests(true);
    await shutdownServer(true);
  });
  dom.msgInput?.addEventListener("input", () => autoSizeTextarea(dom.msgInput));
  dom.msgInput?.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  });

  // cancel
  // mode buttons
  dom.chatBtn?.addEventListener("click", () => setMode(MODES.CHAT));
  dom.webBtn?.addEventListener("click", () => setMode(MODES.WEB));
  dom.urlBtn?.addEventListener("click", () => setMode(state.mode === MODES.URL ? MODES.CHAT : MODES.URL));
  dom.cryptoBtn?.addEventListener("click", () => setMode(state.mode === MODES.CRYPTO ? MODES.CHAT : MODES.CRYPTO));
  dom.imgBtn?.addEventListener("click", () => {
    const enteringImage = state.mode !== MODES.IMAGE;
    setMode(enteringImage ? MODES.IMAGE : MODES.CHAT);
  });
  dom.layoutToggle?.addEventListener("click", toggleLayoutCollapse);
  // image input
  dom.imgInput?.addEventListener("change", async () => {
    const f = dom.imgInput.files?.[0];
    dom.imgInput.value = "";
    if (!f) return;
    state.imageReferenceFile = f;
    await analyzeAttachment(f, { showPreview: true });
  });

  dom.attachmentInput?.addEventListener("change", async () => {
    const f = dom.attachmentInput.files?.[0];
    dom.attachmentInput.value = "";
    if (!f) return;
    await analyzeAttachment(f);
  });

  dom.attachBtn?.addEventListener("click", (e) => {
    e.preventDefault();
    if (state.mode === MODES.IMAGE) {
      dom.imgInput?.click();
    } else {
      dom.attachmentInput?.click();
    }
  });

  dom.chatAttachmentClear?.addEventListener("click", (e) => {
    e.preventDefault();
    clearChatAttachment({ clearImageRef: true });
    appendBubble(state.lang === LANG.ES ? "Adjunto limpiado." : "Attachment cleared.", "bot");
  });

  dom.chatAttachmentAutoWeb?.addEventListener("change", () => {
    state.chatAttachmentAutoWeb = !!dom.chatAttachmentAutoWeb?.checked;
    localStorage.setItem("aegis_attachment_auto_web", JSON.stringify(state.chatAttachmentAutoWeb));
    updateChatAttachmentBar();
  });

  dom.llmProviderBtn?.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    toggleLlmProviderMenu();
  });
  dom.llmProviderLocalBtn?.addEventListener("click", async (e) => {
    e.preventDefault();
    e.stopPropagation();
    await setRuntimeLlmProvider("local");
  });
  dom.llmProviderCloudBtn?.addEventListener("click", async (e) => {
    e.preventDefault();
    e.stopPropagation();
    await setRuntimeLlmProvider("cloud");
  });

  document.addEventListener("click", (e) => {
    if (!state.llmProviderMenuOpen) return;
    const shell = dom.llmProviderShell;
    if (shell instanceof HTMLElement && !shell.contains(e.target)) {
      toggleLlmProviderMenu(false);
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && state.llmProviderMenuOpen) toggleLlmProviderMenu(false);
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

  // symbols modal (pares válidos / deploy tips)
  dom.symbolsBtn?.addEventListener("click", () => {
    void loadCryptoSymbolsMeta();
    loadSymbolsList(dom.chartSymbol?.value || "");
    openModal(dom.symbolsModal);
  });
  dom.symbolsClose?.addEventListener("click", () => closeModal(dom.symbolsModal));
  dom.symbolsModal?.addEventListener("click", (e) => {
    if (e.target === dom.symbolsModal) closeModal(dom.symbolsModal);
  });

  dom.batchApplyClose?.addEventListener("click", () => closeModal(dom.batchApplyModal));
  dom.batchApplyRun?.addEventListener("click", () => { void applyBatchWorkspacePlan(); });
  dom.batchApplyPreviewBtn?.addEventListener("click", () => { void previewBatchWorkspacePlan(); });
  dom.batchApplyTemplate?.addEventListener("click", fillBatchApplyTemplate);
  dom.batchApplyInput?.addEventListener("input", clearBatchApplyReview);
  dom.batchApplyModal?.addEventListener("click", (e) => {
    if (e.target === dom.batchApplyModal) closeModal(dom.batchApplyModal);
  });

  // focus selector
  // focus selector removed

  dom.sessionsIncludeArchived?.addEventListener("change", (e) => {
    state.conversationsIncludeArchived = !!e.target.checked;
    loadConversationList(state.conversationsIncludeArchived);
  });

  dom.turnsFilter?.addEventListener("input", (e) => {
    state.turnsFilter = String(e.target.value || "");
    localStorage.setItem("aegis_turns_filter", state.turnsFilter);
    renderConversationTurns(state.convTurnsItems);
  });
  dom.turnsOpenBtn?.addEventListener("click", () => {
    const q = String(dom.turnsFilter?.value || "").trim();
    if (!q) return;
    const convId = state.conversationId;
    const id = q.replace(/^id:\s*/i, "").trim();
    const items = Array.isArray(state.convTurnsItems) ? state.convTurnsItems : [];
    const match = items.find((t) => String(t?.turn_id || "").startsWith(id));
    if (match) {
      openTurnDetail(match);
      return;
    }
    if (!convId || !id) return;
    // Fetch exact turn (works even if not in the last N turns)
    (async () => {
      try {
        const url = new URL(endpoints.conversationTurnDetail(convId, id), location.origin);
        const res = await fetchWithTimeout(url.toString(), { headers: { Accept: "application/json" } }, { timeout: 20000, retries: 0 });
        const data = await safeJson(res);
        if (!res.ok) return;
        const turn = data?.turn && typeof data.turn === "object" ? data.turn : null;
        if (turn) openTurnDetail(turn);
      } catch (err) {
        if (err?.name === "AbortError") return;
        console.error(err);
      }
    })();
  });

  // API key
  dom.apiKeyBtn?.addEventListener("click", () => {
    if (!dom.apiKeyModal) {
      // Fallback for stale HTML (older UI without the modal). Keep a working path.
      const es = state.lang === LANG.ES;
      appendBubble(
        es
          ? "UI desactualizada: no se encontró el modal de arranque/auth. Haz hard refresh (Ctrl+Shift+R) y reinicia el servidor si hace falta. Fallback: usando prompts."
          : "Stale UI: bootstrap/auth modal not found. Hard refresh (Ctrl+Shift+R) and restart the server if needed. Fallback: using prompts.",
        "error"
      );
      const msgMain = es ? "Clave de arranque (vacío para borrar):" : "Bootstrap key (empty to clear):";
      const next = prompt(msgMain, state.apiKey || "");
      if (next == null) return;
      state.apiKey = cleanKey(next || "");

      const msgFiles = es
        ? "Clave de Files (Enter para usar la misma):"
        : "Files bootstrap key (Enter to reuse main):";
      const nextFiles = prompt(msgFiles, state.filesApiKey || state.apiKey || "");
      if (nextFiles !== null) {
        const trimmed = cleanKey(nextFiles || "");
        state.filesApiKey = trimmed || state.apiKey || "";
      }
      clearAuthRetryCooldown();
      clearTokens();
      ensureAccessToken()
        .then((ok) => ok ? refreshAuthedPanels().catch(() => {}) : Promise.resolve())
        .finally(() => {
          applyAuthState();
          appendBubble(es ? "Clave de arranque actualizada." : "Bootstrap key updated.", "bot");
        });
      return;
    }
    // Fill modal inputs from current state (do not show in cleartext unless user types).
    if (dom.apiKeyMainInput) dom.apiKeyMainInput.value = state.apiKey || "";
    if (dom.apiKeyFilesInput) dom.apiKeyFilesInput.value = state.filesApiKey && state.filesApiKey !== state.apiKey ? state.filesApiKey : "";
    if (dom.apiKeyUseSame) dom.apiKeyUseSame.checked = true;
    openModal(dom.apiKeyModal);
  });
  dom.apiKeyClose?.addEventListener("click", () => closeModal(dom.apiKeyModal));
  dom.apiKeyModal?.addEventListener("click", (e) => {
    if (e.target === dom.apiKeyModal) closeModal(dom.apiKeyModal);
  });
  dom.apiKeyUseSame?.addEventListener("change", () => {
    if (!dom.apiKeyUseSame?.checked) return;
    if (dom.apiKeyFilesInput) dom.apiKeyFilesInput.value = "";
  });
  dom.apiKeySave?.addEventListener("click", async () => {
    const main = cleanKey(dom.apiKeyMainInput?.value || "");
    const useSame = !!dom.apiKeyUseSame?.checked;
    const files = useSame ? "" : cleanKey(dom.apiKeyFilesInput?.value || "");

    state.apiKey = main;
    state.filesApiKey = files || state.apiKey || "";

    clearAuthRetryCooldown();
    clearTokens();
    await ensureAccessToken();
    await refreshAuthedPanels().catch(() => {});
    applyAuthState();
    closeModal(dom.apiKeyModal);
    appendBubble(state.lang === LANG.ES ? "Clave de arranque actualizada." : "Bootstrap key updated.", "bot");
  });
  dom.apiKeyClear?.addEventListener("click", async () => {
    state.apiKey = "";
    state.filesApiKey = "";
    clearAuthRetryCooldown();
    await logoutAuthSession();
    stopConversationEventsPolling();
    applyAuthState();
    closeModal(dom.apiKeyModal);
    appendBubble(state.lang === LANG.ES ? "Keys borradas." : "Keys cleared.", "bot");
  });
  dom.globalSnapshotBtn?.addEventListener("click", () => {
    // Manual snapshot should not force-open crypto panel.
    loadSnapshot({ renderInSources: !!state.chartVisible, forceToast: true, source: "manual" });
  });
  dom.showCryptoPanelBtn?.addEventListener("click", showCryptoPanelFromToolbar);
  dom.showFilesPanelBtn?.addEventListener("click", showFilesPanelFromToolbar);

  // tabs
  dom.tabButtons?.forEach((b) => {
    b.addEventListener("click", () => {
      const tab = b.getAttribute("data-tab");
      if (tab) activateTab(tab);
    });
  });

  // files tree
  dom.projectSelect?.addEventListener("change", async () => {
    const selected = String(dom.projectSelect.value || "").trim();
    if (selected === "app" || selected === "ui") {
      clearManualProjectRoot({ syncSelect: true });
      appendBubble(
        state.lang === LANG.ES
          ? "Ese selector legacy ya no registra roots relativos. Usa el selector de proyecto activo o un root absoluto manual."
          : "That legacy selector no longer registers relative roots. Use active project selector or an absolute manual root.",
        "error"
      );
      loadProjectTree();
      return;
    }
    const prev = String(state.activeProjectId || "").trim();
    setManualProjectRoot(dom.projectSelect.value || "");
    try {
      // Make manual roots converge to a canonical project_id.
      const data = await ensureCurrentRootRegistered();
      const nextId = String(data?.project_id || state.activeProjectId || "").trim();
      if (nextId && nextId !== prev) {
        appendBubble(
          state.lang === LANG.ES
            ? `Root registrado → proyecto activo ${nextId}.`
            : `Root registered → active project ${nextId}.`,
          "bot"
        );
      }
    } catch (err) {
      console.warn("root-register-failed", err);
      if (String(err?.message || "").includes("manual-root-must-be-absolute")) {
        appendBubble(
          state.lang === LANG.ES
            ? "Root manual inválido. Usa una ruta absoluta o selecciona un proyecto activo."
            : "Invalid manual root. Use an absolute path or select an active project.",
          "error"
        );
      }
    }
    loadProjectTree();
  });
  dom.filesToChatBtn?.addEventListener("click", () => {
    setMode(MODES.CHAT);
    try { dom.msgInput?.focus(); } catch {}
  });
  dom.activeProjectSelect?.addEventListener("change", () => {
    setActiveProject(dom.activeProjectSelect.value || "");
  });
  dom.refreshTreeBtn?.addEventListener("click", loadProjectTree);
  dom.copyFileBtn?.addEventListener("click", copyFileViewer);
  dom.newFileBtn?.addEventListener("click", startNewFileMode);
  dom.newFolderBtn?.addEventListener("click", createFolderInWorkspace);
  dom.movePathBtn?.addEventListener("click", moveSelectedWorkspacePath);
  dom.batchApplyBtn?.addEventListener("click", openBatchApplyModal);
  dom.renameFileBtn?.addEventListener("click", renameFileViewer);
  dom.editFileBtn?.addEventListener("click", enterFileEditMode);
  dom.diffFileBtn?.addEventListener("click", toggleFileDiffMode);
  dom.deleteFileBtn?.addEventListener("click", deleteFileViewer);
  dom.saveFileBtn?.addEventListener("click", saveFileViewer);
  dom.cancelFileEditBtn?.addEventListener("click", cancelFileEditMode);
  window.addEventListener("beforeunload", handleBeforeUnload);

  // upload zip / clone / delete
  dom.projectUploadBtn?.addEventListener("click", () => dom.projectUploadInput?.click());
  dom.projectUploadInput?.addEventListener("change", uploadZipProject);
  dom.projectCloneBtn?.addEventListener("click", cloneRepo);
  dom.projectDeleteBtn?.addEventListener("click", deleteProject);
  // focus selector removed
  dom.ingestLogBtn?.addEventListener("click", () => {
    // Prefer current job id; fall back to last known job id from status list.
    const jobId = state.ingestJobId || state.logJobId;
    if (!jobId) {
      appendBubble(state.lang === LANG.ES ? "Primero inicia una ingesta para ver su log." : "Start an ingest first to view its log.", "error");
      return;
    }
    state.logJobId = jobId;
    state.logPath = null;
    state.logIsAdmin = false;
    if (dom.logsLiveToggle) dom.logsLiveToggle.checked = true;
    startLogsPolling();
    appendBubble(state.lang === LANG.ES ? `Mostrando log de ingesta (${jobId}).` : `Showing ingest log (${jobId}).`, "bot");
  });
  dom.ingestStatusBtn?.addEventListener("click", startIngest);
  dom.ingestJobsRefresh?.addEventListener("click", loadIngestJobs);
  dom.filesExpandBtn?.addEventListener("click", (e) => {
    if (e.shiftKey) {
      toggleFilesExpand();
      return;
    }
    toggleSidebarVisibility();
  });
  dom.chatSideToggle?.addEventListener("click", toggleChatSidePanel);
  dom.chatSideShow?.addEventListener("click", toggleChatSidePanel);

  // crypto + chart
  dom.chartRefresh?.addEventListener("click", () => loadChartData(dom.chartSymbol?.value));
  dom.chartSymbol?.addEventListener("change", () => {
    loadSymbolsList(dom.chartSymbol?.value || "");
    loadChartData(dom.chartSymbol?.value);
    if (state.chartVisible) {
      loadPredictionComparison(dom.chartSymbol?.value, { force: true });
    }
    loadCryptoTradePreview({ side: state.cryptoPreviewSide || "BUY", force: true });
  });
  dom.chartSymbol?.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    loadChartData(dom.chartSymbol?.value);
    if (state.chartVisible) {
      loadPredictionComparison(dom.chartSymbol?.value, { force: true });
    }
    loadCryptoTradePreview({ side: state.cryptoPreviewSide || "BUY", force: true });
  });
  dom.chartSymbol?.addEventListener("input", () => {
    loadSymbolsList(dom.chartSymbol?.value || "");
    if (state.chartVisible || state.mode === MODES.CRYPTO) {
      scheduleCryptoTradePreviewRefresh({ force: false, side: state.cryptoPreviewSide || "BUY" });
    }
  });
  dom.chartRangeButtons?.forEach((btn) => {
    btn.addEventListener("click", () => {
      const minutes = Number(btn.getAttribute("data-chart-range") || "0");
      setChartRangePreset(minutes, { rerender: true });
    });
  });
  dom.chartResetZoom?.addEventListener("click", () => resetChartZoom({ rerender: true }));
  dom.priceChart?.addEventListener("wheel", handleChartWheel, { passive: false });
  dom.priceChart?.addEventListener("dblclick", () => resetChartZoom({ rerender: true }));
  dom.chartExpandBtn?.addEventListener("click", (e) => {
    if (e.shiftKey) {
      toggleChartExpand();
      return;
    }
    toggleChartVisibility();
  });
  dom.chartLive?.addEventListener("change", () => (dom.chartLive.checked ? startLiveChart() : stopLiveChart()));
  dom.newsMarkersToggle?.addEventListener("change", () => {
    state.showNewsMarkers = !!dom.newsMarkersToggle.checked;
    localStorage.setItem("aegis_show_news_markers", state.showNewsMarkers ? "1" : "0");
    if (state.lastPoints?.length) renderChart(state.lastPoints);
  });

  dom.buyBtn?.addEventListener("click", () => requestCryptoTradePreview("BUY"));
  dom.sellBtn?.addEventListener("click", () => requestCryptoTradePreview("SELL"));
  dom.cryptoExecutionGroup?.addEventListener("click", (event) => {
    const btn = event.target?.closest?.("[data-execution-mode]");
    if (!btn) return;
    const mode = normalizeCryptoExecutionMode(btn.dataset.executionMode || btn.getAttribute("data-execution-mode"));
    state.cryptoExecutionMode = mode;
    localStorage.setItem("aegis_crypto_execution_mode", mode);
    updateCryptoExecutionUI();
    loadCryptoState({ force: true });
    loadCryptoPrediction({ force: true });
    loadCryptoTradePreview({ side: state.cryptoPreviewSide || "BUY", force: true });
  });

  dom.cryptoModelSelect?.addEventListener("change", () => {
    state.selectedCryptoModel = dom.cryptoModelSelect.value || "ensemble";
    localStorage.setItem("aegis_crypto_model", state.selectedCryptoModel);
    loadCryptoPrediction({ force: true });
    loadCryptoState({ force: true });
    loadCryptoTradePreview({ side: state.cryptoPreviewSide || "BUY", force: true });
  });
  dom.cryptoHorizon?.addEventListener("change", () => {
    loadCryptoPrediction({ force: true });
    loadPredictionComparison(dom.chartSymbol?.value || state.chartSymbol, { force: true });
    loadCryptoState({ force: true });
    loadCryptoTradePreview({ side: state.cryptoPreviewSide || "BUY", force: true });
  });
  dom.chatTradeQty?.addEventListener("input", () => {
    if (!state.chartVisible && state.mode !== MODES.CRYPTO) return;
    scheduleCryptoTradePreviewRefresh({ force: false, side: state.cryptoPreviewSide || "BUY" });
  });
  dom.chatTradeQty?.addEventListener("change", () => {
    loadCryptoPrediction({ force: true });
    loadCryptoState({ force: true });
    loadCryptoTradePreview({ side: state.cryptoPreviewSide || "BUY", force: true });
  });

  dom.copyConvId?.addEventListener("click", async () => {
    const id = state.conversationId || "";
    if (!id) return appendBubble(state.lang === LANG.ES ? "Sin sesión activa." : "No active session.", "error");
    try {
      await navigator.clipboard.writeText(id);
      appendBubble(state.lang === LANG.ES ? "ID copiado." : "ID copied.", "bot");
    } catch {
      appendBubble(id, "bot");
    }
  });

  dom.predictionCompareHelp?.addEventListener("click", (e) => {
    e.stopPropagation();
    const open = dom.predictionCompareHelp.getAttribute("aria-expanded") === "true";
    dom.predictionCompareHelp.setAttribute("aria-expanded", String(!open));
    dom.predictionCompareTooltip.hidden = open;
  });
  dom.predictionCompareRefresh?.addEventListener("click", () => loadPredictionComparison(state.chartSymbol, { force: true }));

  dom.newsRefreshBtn?.addEventListener("click", () => loadNews(state.chartSymbol, { force: true }));
  dom.newsCompactToggle?.addEventListener("change", () => renderNews(state.lastNews || []));

  // sidebar tools
  dom.predsBtn?.addEventListener("click", () => loadRecentPredictions());
  dom.statsBtn?.addEventListener("click", () => loadStats());
  dom.clearCryptoBtn?.addEventListener("click", () => clearCryptoHistory());
  dom.pnlBtn?.addEventListener("click", () => loadPnl());
  dom.debugTraceToggle?.addEventListener("click", () => {
    setDebugTraceEnabled(!state.debugTraceEnabled);
  });

  dom.savePredToggle?.addEventListener("change", () => {
    state.savePredictions = !!dom.savePredToggle.checked;
    localStorage.setItem("aegis_save_preds", JSON.stringify(state.savePredictions));
    appendBubble(state.lang === LANG.ES ? "Guardado de señales actualizado." : "Signal saving updated.", "bot");
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

  dom.convEventsRefresh?.addEventListener("click", () => loadConversationEvents({ force: true }));

  dom.turnDetailClose?.addEventListener("click", () => closeModal(dom.turnDetailModal));
  dom.turnDetailCopy?.addEventListener("click", async () => {
    const raw = String(dom.turnDetailBody?.textContent || "").trim();
    if (!raw) return;
    try {
      await navigator.clipboard.writeText(raw);
      appendBubble(state.lang === LANG.ES ? "Turn copiado." : "Turn copied.", "bot");
    } catch {
      appendBubble(raw, "bot");
    }
  });

  hydrateCryptoRiskInputs();
  [
    [dom.cryptoStopLossPct, CRYPTO_RISK_INPUT_KEYS.stopLossPct],
    [dom.cryptoTakeProfitPct, CRYPTO_RISK_INPUT_KEYS.takeProfitPct],
    [dom.cryptoMaxExposureQuote, CRYPTO_RISK_INPUT_KEYS.maxExposureQuote],
    [dom.cryptoMaxOrderSizePct, CRYPTO_RISK_INPUT_KEYS.maxOrderSizePct],
  ].forEach(([input, key]) => {
    if (!input) return;
    input.addEventListener("input", () => {
      persistCryptoRiskInput(input, key);
      if (!state.chartVisible && state.mode !== MODES.CRYPTO) return;
      scheduleCryptoTradePreviewRefresh({ force: false, side: state.cryptoPreviewSide || "BUY" });
    });
    input.addEventListener("change", () => {
      persistCryptoRiskInput(input, key);
      loadCryptoPrediction({ force: true });
      loadCryptoState({ force: true });
      loadCryptoTradePreview({ side: state.cryptoPreviewSide || "BUY", force: true });
    });
  });
}

function updateAllUI() {
  updateLlmProviderButton();
  // lang buttons
  if (dom.langEs && dom.langEn) {
    dom.langEs.classList.toggle("selected", state.lang === LANG.ES);
    dom.langEn.classList.toggle("selected", state.lang === LANG.EN);
    dom.langEs.setAttribute("aria-pressed", String(state.lang === LANG.ES));
    dom.langEn.setAttribute("aria-pressed", String(state.lang === LANG.EN));
  }
  // placeholder / composer state
  updateComposeUI();
  if (dom.turnsFilter) {
    dom.turnsFilter.placeholder = state.lang === LANG.ES
      ? "filtrar: id:, tool:, texto..."
      : "filter: id:, tool:, text...";
    if (dom.turnsFilter.value !== String(state.turnsFilter || "")) {
      dom.turnsFilter.value = String(state.turnsFilter || "");
    }
  }
  if (dom.turnsOpenBtn) {
    dom.turnsOpenBtn.title = state.lang === LANG.ES ? "Abrir por ID" : "Open by ID";
  }
  renderTurnsQuickFilters();

  // mode UI
  updateModeIndicator();
  updateModeButtons();
  updateImageQuickBar();
  updateTogglesVisibility();
  updateChatAttachmentBar();
  updateStatusCenter();
  updateSnapshotToggleUI();
  localizeUI();
  updateChartRangeButtons();
  applyPanelVisibility();

  // init sources
  clearSources();

  // Lazy-load crypto data only when the crypto panel is visible.
  if (state.chartVisible) {
    loadCryptoModels();
    loadChartData(state.chartSymbol);
    loadCryptoState({ force: true });
  } else {
    updateChartTitle(state.chartSymbol);
  }
  updatePredictionTooltipText();
}

function renderTurnsQuickFilters() {
  if (!dom.turnsQuickFilters) return;
  const es = state.lang === LANG.ES;
  dom.turnsQuickFilters.innerHTML = "";
  const presets = [
    { q: "", label: es ? "Todos" : "All", cls: "" },
    { q: "status:failed", label: es ? "Fallidos" : "Failed", cls: "warn" },
    { q: "tool:llm", label: "tool:llm", cls: "" },
    { q: "tool:web_search", label: "tool:web_search", cls: "" },
    { q: "tool:project_manifest", label: "tool:project_manifest", cls: "" },
  ];
  presets.forEach((p) => {
    const chip = el("span", { class: `mini-chip ${p.cls || ""}`.trim(), text: p.label });
    chip.addEventListener("click", () => {
      state.turnsFilter = p.q;
      localStorage.setItem("aegis_turns_filter", state.turnsFilter);
      if (dom.turnsFilter) dom.turnsFilter.value = state.turnsFilter;
      renderConversationTurns(state.convTurnsItems);
    });
    dom.turnsQuickFilters.appendChild(chip);
  });
}

function providerMetaForUi(value, es) {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === "groq" || normalized === "cloud") {
    return {
      id: "cloud",
      label: es ? "Cloud" : "Cloud",
      description: es
        ? "Groq remoto. Mejor para chat general mas rapido y razonamiento mas fuerte."
        : "Remote Groq model. Better for faster general chat and stronger reasoning.",
    };
  }
  return {
    id: "local",
    label: es ? "Local" : "Local",
    description: es
      ? "Modelo GGUF local. Mejor para trabajo offline y fallback local."
      : "Local GGUF model. Better for offline work and local fallback.",
  };
}

function syncLlmProviderFromReadyz(data = null) {
  const payload = data && typeof data === "object" ? data : state.lastReadyz;
  const llmConfig = (payload && payload.resources && payload.resources.llm_config) || null;
  if (!llmConfig || typeof llmConfig !== "object") return;
  state.llmProviderState = {
    configured_provider: String(llmConfig.provider || "").trim().toLowerCase(),
    effective_provider: String(llmConfig.effective_provider || "").trim().toLowerCase(),
    model: String(llmConfig.model || "").trim(),
    remote_ready: !!llmConfig.remote_ready,
    options: [
      { id: "local", provider: "local" },
      { id: "cloud", provider: "groq" },
    ],
  };
  updateLlmProviderButton();
}

function updateLlmProviderButton() {
  if (!dom.llmProviderBtn) return;
  const es = state.lang === LANG.ES;
  const providerState = state.llmProviderState || {};
  const hasProviderState = !!String(providerState.effective_provider || providerState.configured_provider || "").trim();
  if (!hasProviderState) {
    if (dom.llmProviderBtnText) dom.llmProviderBtnText.textContent = `${es ? "Models" : "Models"}: --`;
    else dom.llmProviderBtn.textContent = `${es ? "Models" : "Models"}: --`;
    dom.llmProviderBtn.title = es
      ? "Esperando confirmacion del runtime LLM. Revisa auth o readyz."
      : "Waiting for runtime LLM confirmation. Check auth or readyz.";
    dom.llmProviderBtn.classList.add("llm-provider-btn-pending");
    dom.llmProviderBtn.classList.remove("active-local", "active-cloud");
    if (dom.llmProviderLocalState) dom.llmProviderLocalState.textContent = es ? "Listo" : "Ready";
    if (dom.llmProviderCloudState) dom.llmProviderCloudState.textContent = es ? "Listo" : "Ready";
    return;
  }
  const effective = String(providerState.effective_provider || providerState.configured_provider || "local").trim().toLowerCase();
  const meta = providerMetaForUi(effective, es);
  const model = String(providerState.model || "").trim();
  if (dom.llmProviderBtnText) dom.llmProviderBtnText.textContent = `${es ? "Models" : "Models"}: ${meta.label}`;
  else dom.llmProviderBtn.textContent = `${es ? "Models" : "Models"}: ${meta.label}`;
  dom.llmProviderBtn.title = model ? `${meta.description} (${model})` : meta.description;
  dom.llmProviderBtn.classList.remove("llm-provider-btn-pending");
  dom.llmProviderBtn.classList.toggle("active-local", meta.id === "local");
  dom.llmProviderBtn.classList.toggle("active-cloud", meta.id === "cloud");

  if (dom.llmProviderMenuTitle) dom.llmProviderMenuTitle.textContent = es ? "Models" : "Models";
  if (dom.llmProviderSummary) {
    dom.llmProviderSummary.textContent = model
      ? `${meta.description} ${es ? "Activo" : "Active"}: ${model}`
      : meta.description;
  }
  if (dom.llmProviderLocalBtn) {
    dom.llmProviderLocalBtn.title = es
      ? "Modelo GGUF local. Menor dependencia de red."
      : "Local GGUF model. Lower network dependency.";
    dom.llmProviderLocalBtn.classList.toggle("active-local", meta.id === "local");
  }
  if (dom.llmProviderLocalState) dom.llmProviderLocalState.textContent = meta.id === "local" ? (es ? "Activo" : "Active") : (es ? "Listo" : "Ready");
  if (dom.llmProviderLocalNote) dom.llmProviderLocalNote.textContent = es
    ? "Ejecuta el modelo GGUF en esta maquina. Mejor para fallback local y trabajo offline."
    : "Runs the GGUF model on this machine. Better for local fallback and offline work.";
  if (dom.llmProviderCloudBtn) {
    dom.llmProviderCloudBtn.title = es
      ? "Groq remoto. Mejor para respuestas rapidas y razonamiento general."
      : "Remote Groq model. Better for fast answers and general reasoning.";
    dom.llmProviderCloudBtn.classList.toggle("active-cloud", meta.id === "cloud");
  }
  if (dom.llmProviderCloudState) dom.llmProviderCloudState.textContent = meta.id === "cloud" ? (es ? "Activo" : "Active") : (es ? "Listo" : "Ready");
  if (dom.llmProviderCloudNote) dom.llmProviderCloudNote.textContent = es
    ? "Usa Groq en la nube. Mejor para chat general mas rapido y mejor razonamiento."
    : "Uses Groq in the cloud. Better for faster general chat and stronger reasoning.";
}

function toggleLlmProviderMenu(force = null) {
  if (!dom.llmProviderMenu) return;
  const next = typeof force === "boolean" ? force : !state.llmProviderMenuOpen;
  state.llmProviderMenuOpen = next;
  dom.llmProviderMenu.classList.toggle("hidden", !next);
  dom.llmProviderMenu.setAttribute("aria-hidden", next ? "false" : "true");
}

async function loadLlmProviderState() {
  if (!hasAuthForScope("main")) {
    updateLlmProviderButton();
    return;
  }
  try {
    const res = await fetchWithTimeout(
      endpoints.systemLlmProvider,
      { headers: { Accept: "application/json" } },
      { timeout: 7000, retries: 0 }
    );
    const data = await safeJson(res);
    if (res.ok && data && typeof data === "object") {
      state.llmProviderState = data;
      updateLlmProviderButton();
    }
  } catch (err) {
    console.error("llm-provider-load", err);
  }
}

async function setRuntimeLlmProvider(provider) {
  const es = state.lang === LANG.ES;
  const target = provider === "cloud" ? "cloud" : "local";
  try {
    const res = await fetchWithTimeout(
      endpoints.systemLlmProvider,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ provider: target }),
      },
      { timeout: 10000, retries: 0 }
    );
    const data = await safeJson(res);
    if (!res.ok) {
      const detail = data && data.detail ? String(data.detail) : `${res.status}`;
      throw new Error(detail);
    }
    state.llmProviderState = data && typeof data === "object" ? data : state.llmProviderState;
    if (state.lastReadyz && state.lastReadyz.resources && state.lastReadyz.resources.llm_config) {
      state.lastReadyz.resources.llm_config.provider = String(state.llmProviderState.configured_provider || "");
      state.lastReadyz.resources.llm_config.effective_provider = String(state.llmProviderState.effective_provider || "");
      state.lastReadyz.resources.llm_config.model = String(state.llmProviderState.model || "");
      state.lastReadyz.resources.llm_config.remote_ready = !!state.llmProviderState.remote_ready;
    }
    updateLlmProviderButton();
    updateStatusCenter();
    toggleLlmProviderMenu(false);
    appendBubble(
      target === "cloud"
        ? (es ? "Modelo activo cambiado a Cloud (Groq)." : "Active model changed to Cloud (Groq).")
        : (es ? "Modelo activo cambiado a Local." : "Active model changed to Local."),
      "bot"
    );
  } catch (err) {
    console.error("llm-provider-set", err);
    appendBubble(
      es ? "No pude cambiar el modelo activo." : "Could not change the active model.",
      "error"
    );
  }
}

function updateStatusCenter() {
  if (!dom.statusList) return;
  const es = state.lang === LANG.ES;
  const items = [];

  // Runtime capabilities (from latest /system/readyz or snapshot)
  try {
    const readyz = state.lastReadyz || state.lastSnapshot?.readyz || {};
    const snap = state.lastSnapshot?.snapshot || {};
    const process = readyz.process || snap.process || {};
    const status = String(readyz.status || snap.status || "").trim() || "unknown";
    const webStatus = String((readyz.web_search && readyz.web_search.status) || "").trim();
    const webSummary = getWebProviderSummary((readyz.web_search && readyz.web_search) || {}, es);
    const imgStatus = String((readyz.image && readyz.image.status) || "").trim();
    const llmStatus = String((readyz.llm && readyz.llm.status) || "").trim() || (readyz.checks?.llm ? "ready" : "");
    const llmConfig = (readyz.resources && readyz.resources.llm_config)
      || (snap.resources && snap.resources.llm_config)
      || {};
    const llmProvider = String(llmConfig.provider || "").trim();
    const llmEffective = String(llmConfig.effective_provider || "").trim();
    const llmModel = String(llmConfig.model || "").trim();

    const noteParts = [];
    noteParts.push(`readyz:${status}`);
    if (webStatus) noteParts.push(`web:${webStatus}${webSummary.configured ? `(${webSummary.ready}/${webSummary.available}/${webSummary.configured})` : ""}`);
    if (imgStatus) noteParts.push(`image:${imgStatus}`);
    if (llmStatus) noteParts.push(`llm:${llmStatus}`);
    const note = noteParts.join(" ");

    const level = status === "ready" ? "on" : (status === "degraded" || status === "fallback-only" ? "warn" : "off");
    items.push({
      label: es ? "Runtime" : "Runtime",
      note,
      status: level,
    });

    const pid = Number(process?.pid || 0) || 0;
    const host = String(process?.hostname || "").trim();
    const uptime = Number(process?.uptime_s || 0) || 0;
    const backendNote = `${pid ? `pid:${pid}` : "pid:?"}${host ? ` @ ${host}` : ""}${uptime ? ` · up ${uptime >= 60 ? `${Math.floor(uptime / 60)}m ${Math.round(uptime % 60)}s` : `${Math.round(uptime)}s`}` : ""}`;
    if (dom.backendProcessBadge) {
      dom.backendProcessBadge.textContent = pid || host || uptime
        ? `${es ? "Backend" : "Backend"}: ${backendNote}`
        : `${es ? "Backend" : "Backend"}: ?`;
      dom.backendProcessBadge.title = pid || host || uptime
        ? (es ? `Proceso backend actual (${backendNote})` : `Current backend process (${backendNote})`)
        : (es ? "Proceso backend actual" : "Current backend process");
    }
    if (dom.backendStopBtn) {
      dom.backendStopBtn.title = pid || host || uptime
        ? (es ? `Detener backend actual (${backendNote})` : `Stop current backend (${backendNote})`)
        : (es ? "Detener backend de AEGIS" : "Stop AEGIS backend");
    }
    if (pid || host || uptime) {
      items.push({
        label: es ? "Backend" : "Backend",
        note: backendNote,
        status: "on",
      });
    }
    if (llmProvider || llmEffective || llmModel) {
      const providerBits = [];
      if (llmProvider) providerBits.push("provider:" + llmProvider);
      if (llmEffective && llmEffective !== llmProvider) providerBits.push("effective:" + llmEffective);
      if (llmModel) providerBits.push("model:" + llmModel);
      const providerNote = providerBits.length ? providerBits.join(" · ") : (es ? "Desconocido" : "Unknown");
      const providerStatus = (llmEffective || llmProvider) === "groq" ? "on" : "off";
      items.push({
        label: es ? "LLM proveedor" : "LLM provider",
        note: providerNote,
        status: providerStatus,
      });
    }
  } catch {}

  items.push({
    label: es ? "Solicitudes" : "Requests",
    note: state.pending ? (es ? "En curso" : "In progress") : (es ? "Libre" : "Idle"),
    status: state.pending ? "on" : "off",
    progress: state.pending ? "indeterminate" : null,
  });

  items.push({
    label: es ? "Debug trazas" : "Debug traces",
    note: state.debugTraceEnabled
      ? (es ? "ON (muestra decisiones/rutas internas)" : "ON (shows internal routing/decisions)")
      : (es ? "OFF (salida limpia para usuario)" : "OFF (clean user-facing output)"),
    status: state.debugTraceEnabled ? "warn" : "off",
  });

  const authErr = state.authDiag?.lastError || null;
  const hasCreds = !!(state.cookieAuth || state.apiKey || state.filesApiKey);
  const retryMsLeft = Math.max(0, Number(state.authRetryBlockedUntil || 0) - Date.now());
  const retryNote = retryMsLeft > 0
    ? ` · ${es ? "reintento" : "retry"} ${Math.ceil(retryMsLeft / 1000)}s`
    : "";
  items.push({
    label: "Auth",
    note: authErr
      ? `${authErr.scope || "main"} ${authErr.status || 401} (${authErr.hasKey ? "key" : "no-key"}|${authErr.hasBearer ? "bearer" : "no-bearer"})${authErr.detail ? ` · ${authErr.detail}` : ""}${retryNote}`
      : hasCreds
        ? `${es ? "Credenciales cargadas" : "Credentials loaded"}${retryNote}`
        : (es ? "Sin credenciales" : "No credentials"),
    status: (authErr || retryMsLeft > 0) ? "warn" : (hasCreds ? "on" : "off"),
  });

  const cryptoStatusVisible = !!(state.chartVisible || state.mode === MODES.CRYPTO || state.liveTimer || state.alertsTimer);
  if (cryptoStatusVisible) {
    items.push({
      label: es ? "Gráfico live" : "Live chart",
      note: state.liveTimer ? (es ? "Actualizando cada 60s" : "Refreshing every 60s") : (es ? "Pausado" : "Paused"),
      status: state.liveTimer ? "on" : "off",
      progress: state.liveTimer ? "indeterminate" : null,
    });

    items.push({
      label: es ? "Alertas" : "Alerts",
      note: state.alertsTimer ? (es ? "Monitoreando outcomes" : "Monitoring outcomes") : (es ? "Off" : "Off"),
      status: state.alertsTimer ? "on" : "off",
    });
  }

  items.push({
    label: es ? "Logs" : "Logs",
    note: state.logsTimer ? (es ? "Auto-leyendo" : "Auto-reading") : (es ? "Manual" : "Manual"),
    status: state.logsTimer ? "on" : "off",
    progress: state.logsTimer ? "indeterminate" : null,
  });

  items.push({
    label: es ? "Ingesta" : "Ingest",
    note: state.ingestJobId ? (es ? "Trabajo activo" : "Job active") : (es ? "Sin trabajo" : "No job"),
    status: state.ingestJobId ? "warn" : "off",
    progress: state.ingestJobId ? "indeterminate" : null,
  });

  items.push({
    label: es ? "Eventos chat" : "Chat events",
    note: state.convEventsTimer ? (es ? "Subscripción activa" : "Subscription active") : (es ? "Inactiva" : "Inactive"),
    status: state.convEventsTimer ? "on" : "off",
  });

  if (state.logIsAdmin) {
    items.push({
      label: es ? "Cripto refresh" : "Crypto refresh",
      note: state.logIsAdmin ? (es ? "Log activo (usa /admin/refresh-log)" : "Log active (via /admin/refresh-log)") : (es ? "Sin log" : "No log"),
      status: state.logIsAdmin ? "warn" : "off",
      progress: state.logIsAdmin ? "indeterminate" : null,
    });
  }

  dom.statusList.innerHTML = "";
  items.forEach((it) => {
    const li = document.createElement("li");
    li.className = "status-item";
    const dot = document.createElement("span");
    dot.className = "status-dot";
    if (it.status === "on") dot.classList.add("on");
    if (it.status === "warn") dot.classList.add("warn");

    const textWrap = document.createElement("div");
    const label = document.createElement("div");
    label.className = "status-label";
    label.textContent = it.label;
    const note = document.createElement("div");
    note.className = "status-note";
    note.textContent = it.note;

    textWrap.appendChild(label);
    textWrap.appendChild(note);
    li.appendChild(dot);
    li.appendChild(textWrap);
    if (it.progress) {
      const bar = document.createElement("div");
      bar.className = "status-progress";
      if (it.progress === "indeterminate") bar.classList.add("indeterminate");
      li.appendChild(bar);
    }
    dom.statusList.appendChild(li);
  });
}

function setLang(lang) {
  state.lang = lang;
  localStorage.setItem("aegis_lang", state.lang);
  updateAllUI();
  setDebugTraceEnabled(state.debugTraceEnabled, { persist: false, silent: true });
  appendBubble(state.lang === LANG.ES ? "Idioma: ES." : "Language: EN.", "bot");
  localizeHelp();
}

function isImageQuestionPrompt(text) {
  const raw = String(text || "").trim();
  if (!raw) return false;
  if (/[?？]\s*$/.test(raw)) return true;
  return /^(?:what|how|why|can you|could you|describe|explain|summarize|analyze|que|qué|como|cómo|por qué|puedes|describe|explica|resume|analiza)\b/i.test(raw);
}

function getComposePlaceholder() {
  const es = state.lang === LANG.ES;
  if (state.mode === MODES.URL) {
    return es ? "Pega una URL o usa url:https://..." : "Paste a URL or use url:https://...";
  }
  if (state.mode === MODES.CRYPTO) {
    return es ? "BTCUSDT H=15m o usa el panel Cripto..." : "BTCUSDT H=15m or use the Crypto panel...";
  }
  if (state.mode === MODES.IMAGE) {
    return es
      ? "Dibuja un dragón, /img ciudad neón, o sube una imagen de referencia..."
      : "Draw a dragon, /img neon city, or upload a reference image...";
  }
  return es ? "Escribe tu mensaje..." : "Type your message...";
}

function getSendButtonLabel() {
  const es = state.lang === LANG.ES;
  if (state.mode === MODES.URL) return es ? "Leer" : "Read";
  if (state.mode === MODES.CRYPTO) return es ? "Predecir" : "Predict";
  if (state.mode === MODES.IMAGE) return es ? "Dibujar" : "Draw";
  return es ? "Enviar" : "Send";
}

function getPendingBubbleLabel(mode = state.mode, text = "") {
  const es = state.lang === LANG.ES;
  if (mode === MODES.WEB) return es ? "Buscando en web…" : "Searching web…";
  if (mode === MODES.URL) return es ? "Leyendo URL…" : "Reading URL…";
  if (mode === MODES.CRYPTO) return es ? "Calculando señal…" : "Calculating signal…";
  if (mode === MODES.IMAGE) {
    return isImageQuestionPrompt(text)
      ? (es ? "Analizando imagen…" : "Analyzing image…")
      : (es ? "Generando imagen…" : "Generating image…");
  }
  return es ? "Escribiendo…" : "Typing…";
}

function getWorkPendingLabel(kind = "agent") {
  const es = state.lang === LANG.ES;
  if (kind === "action") return es ? "Ejecutando acción…" : "Running action…";
  if (kind === "attachment") return es ? "Analizando adjunto…" : "Analyzing attachment…";
  return es ? "Ejecutando agente…" : "Running agent…";
}

function updateComposeUI() {
  const es = state.lang === LANG.ES;
  if (dom.msgInput) dom.msgInput.placeholder = getComposePlaceholder();
  if (dom.sendBtn) {
    dom.sendBtn.textContent = getSendButtonLabel();
    dom.sendBtn.title =
      state.mode === MODES.IMAGE
        ? (es ? "Generar imagen desde el chat" : "Generate image from chat")
        : state.mode === MODES.CRYPTO
          ? (es ? "Ejecutar predicción cripto" : "Run crypto prediction")
          : state.mode === MODES.URL
            ? (es ? "Leer URL" : "Read URL")
            : (es ? "Enviar mensaje" : "Send message");
  }
  if (dom.stopBtn) {
    const activeWork = !!state.pending || state.activeControllers.size > 0;
    dom.stopBtn.textContent = es ? "Detener" : "Stop";
    dom.stopBtn.hidden = !activeWork;
    dom.stopBtn.disabled = !activeWork;
  }
}

function setMode(mode) {
  if (state.chatOnlyExperience && mode !== MODES.CHAT) {
    mode = MODES.CHAT;
  }
  state.mode = mode;
  document.body.dataset.mode = state.mode;
  updateModeIndicator();
  updateModeButtons();
  updateImageQuickBar();
  updateComposeUI();
  updateTogglesVisibility();
  applyPanelVisibility();
  notifyStatus(
    state.lang === LANG.ES
      ? `Modo: ${
          state.mode === MODES.WEB ? "Web" :
          state.mode === MODES.URL ? "URL" :
          state.mode === MODES.CRYPTO ? "Cripto" :
          state.mode === MODES.IMAGE ? "Imagen" : "Chat"
        }`
      : `Mode: ${
          state.mode === MODES.WEB ? "Web" :
          state.mode === MODES.URL ? "URL" :
          state.mode === MODES.CRYPTO ? "Crypto" :
          state.mode === MODES.IMAGE ? "Image" : "Chat"
        }`,
    { kind: "info", key: `mode:${state.mode}`, dedupeMs: 1500, ttlMs: 1800 }
  );

  // when entering crypto, refresh chart/prediction
  if (!state.chatOnlyExperience && state.mode === MODES.CRYPTO) {
    if (!state.chartVisible) {
      state.chartVisible = true;
      localStorage.setItem("aegis_chart_visible", "1");
      applyPanelVisibility();
    }
    loadCryptoModels();
    loadCryptoPrediction({ force: true });
    loadPredictionComparison(state.chartSymbol, { force: true });
    loadCryptoState({ force: true });
    if (dom.chartLive?.checked && !state.liveTimer) {
      startLiveChart();
    }
  }

  if (!state.chatOnlyExperience && state.mode === MODES.IMAGE) {
    dom.msgInput?.focus();
  }
  updateCryptoStatePolling();
}

function updateModeIndicator() {
  if (!dom.modeIndicator) return;
  const label = state.chatOnlyExperience
    ? (state.lang === LANG.ES ? "Modo: Chat (auto web/local)" : "Mode: Chat (auto web/local)")
    : (
      state.mode === MODES.WEB ? (state.lang === LANG.ES ? "Modo: Web" : "Mode: Web") :
      state.mode === MODES.URL ? (state.lang === LANG.ES ? "Modo: URL" : "Mode: URL") :
      state.mode === MODES.CRYPTO ? (state.lang === LANG.ES ? "Modo: Cripto" : "Mode: Crypto") :
      state.mode === MODES.IMAGE ? (state.lang === LANG.ES ? "Modo: Imagen" : "Mode: Image") :
      (state.lang === LANG.ES ? "Modo: Chat" : "Mode: Chat")
    );
  const showHint = state.chatOnlyExperience ? true : [MODES.CHAT, MODES.WEB, MODES.URL].includes(state.mode);
  const hint = showHint ? formatModeRuntimeHint(state.lastChatContext) : "";
  dom.modeIndicator.textContent = hint ? `${label} • ${hint}` : label;
  updateRuntimeStatusBadge();
  updateWebStatusBadge();
}

function updateRuntimeStatusBadge() {
  if (!dom.runtimeStatusBadge) return;
  const es = state.lang === LANG.ES;

  const readyz = state.lastReadyz && typeof state.lastReadyz === "object"
    ? state.lastReadyz
    : (state.lastSnapshot?.readyz && typeof state.lastSnapshot.readyz === "object" ? state.lastSnapshot.readyz : {});

  const status = String(readyz?.status || "").trim() || "unknown";
  const degraded = Array.isArray(readyz?.degraded_reasons) ? readyz.degraded_reasons : [];
  const web = readyz?.web_search && typeof readyz.web_search === "object" ? readyz.web_search : {};
  const img = readyz?.image && typeof readyz.image === "object" ? readyz.image : {};
  const llm = readyz?.llm && typeof readyz.llm === "object" ? readyz.llm : {};

  const cls =
    status === "ready" ? "success"
    : (status === "degraded" || status === "fallback-only") ? "warn"
    : status === "error" ? "danger"
    : "muted";

  dom.runtimeStatusBadge.className = `pill ${cls} header-web-badge`.trim();
  dom.runtimeStatusBadge.textContent = `RUN: ${status}`;

  const parts = [];
  const webStatus = String(web?.status || "").trim();
  const imgStatus = String(img?.status || "").trim();
  const llmStatus = String(llm?.status || "").trim();
  if (webStatus) parts.push(`web:${webStatus}`);
  if (imgStatus) parts.push(`image:${imgStatus}`);
  if (llmStatus) parts.push(`llm:${llmStatus}`);
  if (degraded.length) parts.push(`${es ? "degraded" : "degraded"}:${degraded.slice(0, 4).join(",")}`);

  dom.runtimeStatusBadge.title = parts.length
    ? (es ? `Estado runtime (${parts.join(" ")})` : `Runtime status (${parts.join(" ")})`)
    : (es ? "Estado runtime" : "Runtime status");
}

function getWebProviderSummary(web, es = state.lang === LANG.ES) {
  const configured = Number(web?.provider_count || 0) || 0;
  const available = Number(web?.available_provider_count || 0) || 0;
  const ready = Number(web?.ready_provider_count || 0) || 0;
  const cooling = Number(web?.cooling_provider_count || 0) || 0;
  const reasons = Array.isArray(web?.unavailable_reasons) ? web.unavailable_reasons : [];
  const countsText = configured
    ? `${ready}/${available}/${configured} ${es ? "listas/disponibles/configuradas" : "ready/available/configured"}`
    : (es ? "sin providers configurados" : "no providers configured");
  const parts = [countsText];
  if (cooling) {
    parts.push(es ? `${cooling} en cooldown` : `${cooling} cooling down`);
  }
  if (reasons.length) {
    parts.push(`${es ? "sin disp." : "unavailable"}: ${reasons.slice(0, 2).join(", ")}`);
  }
  return {
    configured,
    available,
    ready,
    cooling,
    reasons,
    countsText,
    summaryText: parts.join(" • "),
  };
}

function updateWebStatusBadge() {
  if (!dom.webStatusBadge) return;
  const es = state.lang === LANG.ES;

  const ctx = state.lastChatContext && typeof state.lastChatContext === "object" ? state.lastChatContext : {};
  const readyz = state.lastReadyz && typeof state.lastReadyz === "object" ? state.lastReadyz : {};
  const readyzWeb = readyz.web_search && typeof readyz.web_search === "object" ? readyz.web_search : {};
  const providerSummary = getWebProviderSummary(readyzWeb, es);

  let label = es ? "WEB: —" : "WEB: —";
  let title = es
    ? "Estado web (auto). Usa `web:` para forzar búsqueda."
    : "Web status (auto). Use `web:` to force search.";
  let cls = "muted";

  if (ctx.using_live_web) {
    label = es ? "WEB: vivo" : "WEB: live";
    title = es
      ? "Última respuesta usó web en vivo (auto o forzada con `web:`)."
      : "Last answer used live web (auto or forced with `web:`).";
    cls = "success";
  } else if (ctx.using_cached_web || ctx.using_stale_cache) {
    label = es ? "WEB: caché" : "WEB: cache";
    title = es ? "Última respuesta usó caché web." : "Last answer used web cache.";
    cls = "warn";
  } else {
    const status = String(ctx.web_status || readyzWeb.status || "").trim();
    if (status === "ready") {
      label = es ? "WEB: listo" : "WEB: ready";
      cls = "success";
      title = es
        ? `Web disponible (${providerSummary.summaryText}).`
        : `Web available (${providerSummary.summaryText}).`;
    } else if (status === "cooldown") {
      label = es ? "WEB: cooldown" : "WEB: cooldown";
      cls = "warn";
      title = es
        ? `Providers en cooldown; usando local/caché (${providerSummary.summaryText}).`
        : `Providers cooling down; using local/cache (${providerSummary.summaryText}).`;
    } else if (status === "unavailable" || status === "error") {
      label = es ? "WEB: no disp." : "WEB: unavailable";
      cls = "muted";
      title = es
        ? `Web no disponible; respondiendo en local. ${providerSummary.summaryText}.`
        : `Web is unavailable; answering locally. ${providerSummary.summaryText}.`;
    } else if (status === "not-used") {
      label = es ? "WEB: auto/local" : "WEB: auto/local";
      cls = "muted";
      title = es
        ? "Esta respuesta se resolvió en local; la web sigue en modo automático."
        : "This answer was resolved locally; web remains in automatic mode.";
    } else if (status) {
      label = `WEB: ${status}`;
      cls = "muted";
    } else {
      label = es ? "WEB: auto" : "WEB: auto";
      cls = "muted";
      title = es
        ? "Web en modo automático; esta respuesta no necesitó web."
        : "Web is in automatic mode; this response did not need web.";
    }
  }

  dom.webStatusBadge.className = `pill ${cls} header-web-badge`.trim();
  dom.webStatusBadge.textContent = label;
  dom.webStatusBadge.title = title;
}

function updateModeButtons() {
  if (state.chatOnlyExperience) {
    if (dom.chatBtn) {
      dom.chatBtn.setAttribute("aria-pressed", "true");
      dom.chatBtn.style.opacity = "1";
    }
    return;
  }
  const map = [
    [dom.chatBtn, state.mode === MODES.CHAT],
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

function updateTogglesVisibility() {
  if (state.chatOnlyExperience) {
    if (dom.savePredToggle?.parentElement) dom.savePredToggle.parentElement.style.display = "none";
    if (dom.alertsToggle?.parentElement) dom.alertsToggle.parentElement.style.display = "none";
    if (dom.logsLiveToggle?.parentElement) dom.logsLiveToggle.parentElement.style.display = "none";
    stopLogsPolling();
    stopAlertsPolling();
    return;
  }
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

function toggleChatSidePanel() {
  state.chatSideVisible = !state.chatSideVisible;
  localStorage.setItem("aegis_chat_side_visible", state.chatSideVisible ? "1" : "0");
  applyChatSideVisible();
}

function applyChatSideVisible() {
  const visible = !!state.chatSideVisible;
  const es = state.lang === LANG.ES;
  if (dom.chatSidePanel) dom.chatSidePanel.classList.toggle("hidden", !visible);
  if (dom.chatCol) dom.chatCol.classList.toggle("panel-hidden", !visible);
  if (dom.chatSideToggle) {
    dom.chatSideToggle.title = visible
      ? (es ? "Ocultar panel" : "Hide panel")
      : (es ? "Mostrar panel" : "Show panel");
    dom.chatSideToggle.textContent = visible ? "✕" : "⤢";
  }
  if (dom.chatSideShow) {
    dom.chatSideShow.style.display = visible ? "none" : "flex";
    dom.chatSideShow.textContent = es ? "Estado / Sesión" : "Status / Session";
    dom.chatSideShow.setAttribute("aria-label", es ? "Mostrar panel Estado/Sesión" : "Show Status/Session panel");
  }
  if (!visible) {
    stopConversationEventsPolling();
  } else if (state.conversationId && hasAuthForScope("main") && state.debugTraceEnabled) {
    startConversationEventsPolling();
  }
}

function toggleLayoutCollapse() {
  state.layoutCollapsed = !state.layoutCollapsed;
  localStorage.setItem("aegis_layout_collapsed", state.layoutCollapsed ? "1" : "0");
  applyLayoutCollapsed();
}

function applyLayoutCollapsed() {
  const collapsed = !!state.layoutCollapsed;
  document.body.classList.toggle("layout-collapsed", collapsed);
  if (dom.layoutToggle) {
    dom.layoutToggle.setAttribute("aria-pressed", String(collapsed));
    dom.layoutToggle.title = collapsed
      ? (state.lang === LANG.ES ? "Mostrar paneles" : "Show panels")
      : (state.lang === LANG.ES ? "Ocultar paneles" : "Hide panels");
    dom.layoutToggle.innerHTML = collapsed
      ? '<i class="fas fa-up-right-and-down-left-from-center"></i>'
      : '<i class="fas fa-up-right-and-down-left-from-center"></i>';
  }
}

function setDebugTraceEnabled(enabled, { persist = true, silent = false } = {}) {
  state.debugTraceEnabled = !!enabled;
  if (persist) {
    localStorage.setItem("aegis_debug_trace", state.debugTraceEnabled ? "1" : "0");
  }
  const es = state.lang === LANG.ES;
  if (dom.debugTraceToggle) {
    dom.debugTraceToggle.classList.toggle("active", state.debugTraceEnabled);
    dom.debugTraceToggle.setAttribute("aria-pressed", state.debugTraceEnabled ? "true" : "false");
    dom.debugTraceToggle.title = state.debugTraceEnabled
      ? (es ? "Debug ON: muestra trazas internas (tools, rutas, evidencia)." : "Debug ON: shows internal traces (tools, routing, evidence).")
      : (es ? "Debug OFF: salida limpia (sin trazas internas)." : "Debug OFF: clean output (no internal traces).");
    dom.debugTraceToggle.textContent = state.debugTraceEnabled ? "DBG:ON" : "DBG:OFF";
  }
  if (!silent) {
    notifyStatus(
      state.debugTraceEnabled
        ? (es ? "Debug ON: trazas internas visibles." : "Debug ON: internal traces visible.")
        : (es ? "Debug OFF: salida limpia." : "Debug OFF: clean output."),
      { kind: state.debugTraceEnabled ? "warn" : "info", key: "debug-toggle", dedupeMs: 800, ttlMs: 2200 }
    );
  }
  if (dom.sessionsEventsWrap) dom.sessionsEventsWrap.style.display = state.debugTraceEnabled ? "" : "none";
  if (dom.sessionsTurnsWrap) dom.sessionsTurnsWrap.style.display = state.debugTraceEnabled ? "" : "none";
  if (!state.debugTraceEnabled) {
    stopConversationEventsPolling();
  } else if (state.chatSideVisible && state.conversationId && hasAuthForScope("main")) {
    startConversationEventsPolling();
  }
  renderSourceOriginBar(state.lastChatContext);
  updateStatusCenter();
}

function openModal(node) { node?.classList?.remove("hidden"); }
function closeModal(node) { node?.classList?.add("hidden"); }

function batchApplyTemplateObject() {
  return {
    operations: [
      { op: "mkdir", path: "app/generated" },
      { op: "write", path: "app/generated/example.py", content: "print('ok')\n", create: true },
    ],
  };
}

function fillBatchApplyTemplate() {
  if (!dom.batchApplyInput) return;
  dom.batchApplyInput.value = JSON.stringify(batchApplyTemplateObject(), null, 2);
  clearBatchApplyReview();
}

function openBatchApplyModal() {
  if (!state.activeProjectId) {
    appendBubble(state.lang === LANG.ES ? "No hay proyecto activo." : "No active project.", "error");
    return;
  }
  if (dom.batchApplyInput && !String(dom.batchApplyInput.value || "").trim()) {
    fillBatchApplyTemplate();
  }
  openModal(dom.batchApplyModal);
}

async function prepareSymbolRenamePlan(symbol) {
  if (!state.activeProjectId) {
    appendBubble(state.lang === LANG.ES ? "No hay proyecto activo." : "No active project.", "error");
    return;
  }
  const currentSymbol = String(symbol || "").trim();
  if (!currentSymbol) return;
  const es = state.lang === LANG.ES;
  const newSymbol = String(
    window.prompt(
      es ? `Nuevo nombre para ${currentSymbol}` : `New name for ${currentSymbol}`,
      `${currentSymbol}Renamed`
    ) || ""
  ).trim();
  if (!newSymbol || newSymbol === currentSymbol) return;
  try {
    const res = await fetchWithTimeout(
      endpoints.filesProjectRenamePlan(state.activeProjectId),
      {
        method: "POST",
        headers: withJsonHeaders({}, "files"),
        body: JSON.stringify({
          symbol: currentSymbol,
          new_symbol: newSymbol,
          limit: 20,
        }),
      },
      { timeout: 30000, retries: 0 }
    );
    const data = await safeJson(res);
    if (!res.ok) {
      throw new Error(data?.detail || `${res.status} ${res.statusText || ""}`.trim());
    }
    const operations = Array.isArray(data?.plan?.operations) ? data.plan.operations : [];
    if (!operations.length) {
      appendBubble(
        es
          ? "No encontré cambios seguros para ese rename."
          : "No safe changes were found for that rename.",
        "error"
      );
      return;
    }
    if (dom.batchApplyInput) {
      dom.batchApplyInput.value = JSON.stringify({ operations }, null, 2);
    }
    clearBatchApplyReview();
    openModal(dom.batchApplyModal);
    appendBubble(
      es
        ? `Plan de rename listo: ${operations.length} archivos`
        : `Rename plan ready: ${operations.length} files`,
      "bot"
    );
  } catch (err) {
    console.error(err);
    appendBubble(
      `${es ? "No se pudo preparar el rename." : "Could not prepare rename."} ${err?.message || ""}`.trim(),
      "error"
    );
  }
}

function batchApplyPayloadText() {
  return String(dom.batchApplyInput?.value || "").trim();
}

function clearBatchApplyReview() {
  state.batchApplyReviewToken = "";
  state.batchApplyReviewedPayload = "";
  state.batchApplyPreviewText = "";
  if (dom.batchApplyPreview) {
    dom.batchApplyPreview.textContent = "";
    dom.batchApplyPreview.hidden = true;
  }
  if (dom.batchApplyRun) {
    dom.batchApplyRun.disabled = true;
  }
}

function setBatchApplyPreview(data, payloadText) {
  state.batchApplyReviewToken = String(data?.review_token || "");
  state.batchApplyReviewedPayload = payloadText;
  state.batchApplyPreviewText = String(data?.combined_diff || "").trim();
  if (dom.batchApplyPreview) {
    dom.batchApplyPreview.hidden = false;
    dom.batchApplyPreview.textContent = state.batchApplyPreviewText || (
      state.lang === LANG.ES ? "Sin cambios en el preview." : "No changes in preview."
    );
  }
  if (dom.batchApplyRun) {
    dom.batchApplyRun.disabled = !state.batchApplyReviewToken;
  }
}

function batchApplyReviewIsCurrent() {
  return !!state.batchApplyReviewToken && state.batchApplyReviewedPayload === batchApplyPayloadText();
}

function batchApplyErrorMessage(data, fallback) {
  const detail = data?.detail;
  if (typeof detail === "string" && detail.trim()) return detail.trim();
  if (detail && typeof detail === "object") return String(detail.message || fallback || "").trim();
  return String(fallback || "").trim();
}

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

function appendBubble(text, role = "bot", allowHtml = false, traceContext = null) {
  if (!dom.chat) return null;
  let content = String(text ?? "");
  if (role === "bot") {
    content = sanitizeAssistantAnswerText(content);
  }
  const node = el("div", {
    class: `bubble ${role === "user" ? "user" : role === "error" ? "error" : "bot"}`,
    attrs: { role: "article" },
  });
  const body = el("div", { class: "bubble-body" });

  if (allowHtml) body.innerHTML = sanitizeAndRenderMarkdown(content);
  else body.textContent = content;

  node.appendChild(body);
  if (role === "bot" && state.debugTraceEnabled && traceContext && typeof traceContext === "object") {
    renderBubbleTrace(node, traceContext);
  }

  dom.chat.appendChild(node);
  scrollBottom();
  return node;
}

function normalizeChatImagePath(path) {
  const raw = String(path || "").trim();
  if (!raw) return "";
  const withoutHost = raw.replace(/^https?:\/\/[^/]+/i, "");
  const prefixed = withoutHost.startsWith("/") ? withoutHost : `/${withoutHost}`;
  return /^\/data\/images\/[A-Za-z0-9._/-]+$/.test(prefixed) ? prefixed : "";
}

function appendImageBubble({ imagePath = "", caption = "", meta = "", localFile = null } = {}) {
  if (!dom.chat) return null;
  const node = el("div", {
    class: "bubble bot bubble-media",
    attrs: { role: "article" },
  });
  const body = el("div", { class: "bubble-body" });

  if (caption) {
    body.appendChild(el("div", { class: "bubble-media-title", text: caption }));
  }

  const imageWrap = el("div", { class: "chat-image-card" });
  const img = document.createElement("img");
  img.className = "chat-image-preview";
  img.loading = "lazy";
  img.alt = caption || "Generated image";
  img.referrerPolicy = "no-referrer";
  img.decoding = "async";

  let localUrl = "";
  if (localFile instanceof File) {
    localUrl = URL.createObjectURL(localFile);
    img.src = localUrl;
    img.addEventListener("load", () => {
      try { URL.revokeObjectURL(localUrl); } catch {}
    }, { once: true });
    img.addEventListener("error", () => {
      try { URL.revokeObjectURL(localUrl); } catch {}
    }, { once: true });
  } else {
    const src = normalizeChatImagePath(imagePath);
    if (!src) return null;
    img.src = src;
  }

  imageWrap.appendChild(img);
  body.appendChild(imageWrap);

  if (meta) {
    body.appendChild(el("div", { class: "bubble-media-meta", text: meta }));
  }

  node.appendChild(body);
  dom.chat.appendChild(node);
  scrollBottom();
  return node;
}

function ensureStatusToastRail() {
  if (dom.statusToastRail && document.body.contains(dom.statusToastRail)) return dom.statusToastRail;
  const rail = el("div", {
    class: "status-toast-rail",
    attrs: { "aria-live": "polite", "aria-atomic": "false" },
  });
  document.body.appendChild(rail);
  dom.statusToastRail = rail;
  return rail;
}

function notifyStatus(message, options = {}) {
  const text = String(message || "").trim();
  if (!text) return;
  const key = String(options.key || text);
  const now = Date.now();
  const dedupeMs = Math.max(0, Number(options.dedupeMs || 2000));
  const last = Number(state.statusNoticeTimes.get(key) || 0);
  if (last && now - last < dedupeMs) return;
  state.statusNoticeTimes.set(key, now);

  const ttlMs = Math.max(1200, Number(options.ttlMs || 2000));
  const kind = String(options.kind || "info");
  const rail = ensureStatusToastRail();
  const node = el("div", { class: `status-toast ${kind}`, text });
  rail.appendChild(node);

  requestAnimationFrame(() => node.classList.add("show"));
  setTimeout(() => {
    node.classList.remove("show");
    setTimeout(() => node.remove(), 180);
  }, ttlMs);
}

function appendTyping(label = "") {
  removeTyping();
  const t = el("div", { class: "bubble bot typing", attrs: { id: "typing-bubble" } });
  t.textContent = String(label || "").trim() || (state.lang === LANG.ES ? "Escribiendo…" : "Typing…");
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
  const allowed = ["serious", "original", "future", "retro"];
  state.theme = allowed.includes(name) ? name : "serious";
  document.body.dataset.theme = state.theme;
  localStorage.setItem("aegis_theme", state.theme);
  if (dom.themeBtn) {
    const label = state.lang === LANG.ES ? "Tema" : "Theme";
    dom.themeBtn.setAttribute("title", `${label}: ${state.theme}`);
  }
}

function cycleTheme() {
  const order = ["serious", "original", "future", "retro"];
  const idx = order.indexOf(state.theme);
  const next = order[(idx + 1) % order.length];
  applyTheme(next);
   appendBubble(
     state.lang === LANG.ES ? `Tema: ${next}` : `Theme: ${next}`,
     "bot"
   );
}

function localizeUI() {
  const es = state.lang === LANG.ES;
  document.documentElement.lang = state.lang;
  const map = {
    subtitle: es ? "Memoria • Búsqueda web • LLM local y remoto" : "Memory • Web search • Local + remote LLM",
    help_title: es ? "Guía rápida de AEGIS" : "AEGIS quick guide",
    send_btn: es ? "Enviar" : "Send",
    trade_buy: es ? "Comprar" : "Buy",
    trade_sell: es ? "Vender" : "Sell",
    model_label: es ? "Modelo" : "Model",
    horizon_label: es ? "Horizonte" : "Horizon",
    qty_label: es ? "Cantidad" : "Qty",
    risk_controls_title: es ? "Controles de riesgo" : "Risk controls",
    risk_controls_note: es ? "Estos valores alimentan el risk gate antes de confirmar la orden." : "These values feed the risk gate before you confirm the order.",
    stop_loss_label: es ? "Stop loss %" : "Stop loss %",
    take_profit_label: es ? "Take profit %" : "Take profit %",
    max_exposure_label: es ? "Exposición máxima" : "Max exposure",
    max_order_size_label: es ? "Tamaño máx. de orden %" : "Max order size %",
    stop_loss_title: es ? "Corta la pérdida si el precio va en contra" : "Cut the loss if price moves against you",
    take_profit_title: es ? "Bloquea la ganancia al llegar al objetivo" : "Lock the gain when the target is reached",
    max_exposure_title: es ? "Máximo valor en moneda cotizada que puede usar esta orden" : "Maximum quote value this order can use",
    max_order_size_title: es ? "Máximo porcentaje del libro visible que puede consumir la orden" : "Maximum percent of visible book liquidity this order can consume",
    stop_loss_placeholder: es ? "0.8" : "0.8",
    take_profit_placeholder: es ? "1.5" : "1.5",
    max_exposure_placeholder: es ? "1000" : "1000",
    max_order_size_placeholder: es ? "5" : "5",
    risk_controls_explain: es
      ? "El risk gate usa estos valores antes de confirmar. Stop loss corta la operación si el precio va en contra. Take profit bloquea la ganancia al llegar al objetivo. Exposición máxima limita cuánto capital puede usar esta orden. Tamaño máx. de orden % limita cuánto libro visible consume tu orden."
      : "The risk gate uses these values before you confirm. Stop loss cuts the trade if price moves against you. Take profit locks gains when the target is reached. Max exposure caps how much quote currency this trade can use. Max order size % limits how much visible book liquidity your order may consume.",
    live_label: es ? "En vivo" : "Live",
    news_label: es ? "Noticias" : "News",
    news_compact: es ? "Compacto" : "Compact",
    alerts_label: es ? "Alertas" : "Alerts",
    save_label: es ? "Guardar" : "Save",
    logs_label: es ? "Logs" : "Logs",
    tab_sources: es ? "Fuentes" : "Sources",
    crypto_insights_title: es ? "Insights Cripto" : "Crypto Insights",
    tab_files: es ? "Archivos" : "Files",
    tab_session: es ? "Sesión" : "Session",
    sources_title: es ? "Fuentes" : "Sources",
    status_title: es ? "Estado" : "Status",
    news_heading: es ? "Noticias" : "News",
    files_heading: es ? "Archivos" : "Files",
    jobs_heading: es ? "Trabajos" : "Jobs",
    logs_heading: es ? "Logs" : "Logs",
    security_heading: es ? "Seguridad" : "Security",
    session_id_label: es ? "ID:" : "ID:",
    session_note: es ? "Logs de sesión son solo para depurar el flujo del chat." : "Session logs are only for debugging chat flow.",
    show_archived: es ? "Ver archivadas" : "Show archived",
    session_history_title: es ? "Historial" : "History",
    session_log_title: es ? "Log sesión" : "Session log",
    sessions_title: es ? "Conversaciones" : "Conversations",
    compare_title: es ? "Comparación post-horizonte" : "Post-horizon comparison",
    chart_mode_hint: es ? "Precio • trades • compare • fills" : "Price • trades • compare • fills",
    chart_mode_hint_title: es ? "Precio • trades • compare • fills" : "Price • trades • compare • fills",
    file_viewer_placeholder: es ? "Selecciona un archivo en Archivos" : "Select a file in Files",
    image_generator_title: es ? "Generador de imágenes (local demo)" : "Image generator (local demo)",
    image_flow_hint: es ? "Flujo: subir → extraer contexto → conversar/generar." : "Flow: upload → extract context → chat/generate.",
    image_prompt_label: es ? "Prompt" : "Prompt",
    image_prompt_placeholder: es ? "Describe la imagen..." : "Describe the image...",
    image_negative_label: es ? "Negativo" : "Negative",
    image_negative_placeholder: es ? "Evita... (opcional)" : "Avoid... (optional)",
    image_steps_label: es ? "Steps" : "Steps",
    image_seed_label: es ? "Seed" : "Seed",
    image_seed_placeholder: es ? "aleatoria" : "random",
    image_generate_btn: es ? "Generar" : "Generate",
    image_mode_inline_guide: es
      ? "Modo imagen: escribe directamente 'dibuja un dragón' o usa /img tu prompt. Si subes una imagen, puedes conversar con su contexto o generar usando esa referencia."
      : "Image mode: type directly 'draw a dragon' or use /img your prompt. If you upload an image, you can chat with its context or generate using that reference.",
    image_steps_help: es
      ? "Steps: cantidad de iteraciones. Más = mejor detalle, pero tarda más."
      : "Steps: denoising iterations. Higher = more detail, but slower.",
    image_seed_help: es
      ? "Seed: número base aleatorio. Mismo prompt + misma seed = resultado similar."
      : "Seed: random base number. Same prompt + same seed = similar result.",
    active_project_none: es ? "Sin proyecto activo" : "No active project",
    active_project_none_option: es ? "Sin proyecto activo" : "No active project",
    project_option_manual: es ? "Root manual..." : "Manual root...",
    project_option_app: es ? "app (backend)" : "app (backend)",
    project_option_ui: es ? "ui (frontend)" : "ui (frontend)",
    ready_label: es ? "Listo" : "Ready",
    help_item_chat_label: es ? "Chat" : "Chat",
    help_item_chat_desc: es ? "conversación normal con memoria. Usa modo Código/Cripto si aplica." : "normal conversation with memory. Use Code/Crypto mode when needed.",
    help_item_web_label: es ? "Web (auto)" : "Web (auto)",
    help_item_web_desc: es
      ? "el contexto web está activo en automático; usa `web:` para forzar búsqueda y ver fuentes."
      : "web context is auto-on; use `web:` to force search and show sources.",
    help_item_url_label: es ? "Modo URL" : "URL mode",
    help_item_url_desc: state.chatOnlyExperience
      ? (es ? "usa `url:https://...` para leer y resumir un enlace." : "use `url:https://...` to read and summarize a link.")
      : (es ? "pega una URL; /fetch_url la lee y la ves en Fuentes." : "paste a URL; /fetch_url reads it and you can see it in Sources."),
    help_item_code_label: es ? "Código" : "Code",
    help_item_code_desc: es ? "preguntas técnicas; usa RAG si hay índice local." : "technical questions; uses local RAG when indexed.",
    help_item_image_label: es ? "Imagen" : "Image",
    help_item_image_desc: es ? "sube una imagen y conversa en chat usando su contexto visual." : "upload an image and chat using its visual context.",
    attach_mode_title: es ? "Adjuntar imagen/documento para chat" : "Attach image/document for chat",
    attachment_button_title: es ? "Adjuntar archivo, documento o imagen al chat" : "Attach file, document, or image to chat",
    image_upload_chat_title: es ? "Subir imagen de referencia para analizar" : "Upload reference image for analysis",
    attachment_auto_web: es ? "Enriquecer con web (si hace falta)" : "Enrich with web (if needed)",
    attachment_clear_title: es ? "Quitar adjunto" : "Clear attachment",
    help_item_crypto_label: es ? "Cripto (señal + horizonte)" : "Crypto (signal + horizon)",
    help_item_crypto_desc: es
      ? "escribe “BTCUSDT H=2m” o usa el panel Cripto. Muestra señal BUY/SELL/HOLD, p%, horizonte, thresholds, risk gate, controles de riesgo, modo de ejecución (simulated/testnet/live) y comparación post-horizonte sincronizada con el gráfico."
      : "type “BTCUSDT H=2m” or use the Crypto panel. It shows BUY/SELL/HOLD, p%, horizon, thresholds, risk gate, risk controls, execution mode (simulated/testnet/live), and the post-horizon comparison synced with the chart.",
    symbols_modal_title: es ? "Despliegue rápido + monedas/pairs Binance permitidos" : "Quick deploy + allowed Binance coins/pairs",
    symbols_deploy_label: es ? "Deploy (local):" : "Deploy (local):",
    symbols_deploy_desc: es ? "activa DB + claves, luego" : "set DB + keys, then run",
    symbols_deploy_desc_2: es ? "Usa el ícono de llave para poner la misma clave en la UI." : "Use the key icon to set the same key in the UI.",
    symbols_keys_label: es ? "Claves mínimas:" : "Minimum keys:",
    symbols_keys_optional: es ? "Opcional:" : "Optional:",
    symbols_pairs_label: es ? "Pares Binance sugeridos (lista ampliada):" : "Suggested Binance pairs (expanded list):",
    symbols_tip: es ? "Puedes escribir nombre o alias (ej: bitcoin, ethereum, btc, eth). Se normaliza automáticamente al par Binance (USDT por defecto)." : "You can type coin name or alias (e.g. bitcoin, ethereum, btc, eth). It auto-normalizes to a Binance pair (USDT by default).",

    api_key_title: es ? "Configurar clave de arranque" : "Set bootstrap key",
    show_crypto_panel_title: es ? "Mostrar panel cripto" : "Show crypto panel",
    show_files_panel_title: es ? "Mostrar panel de archivos/repos" : "Show files/repos panel",
    tree_title: es ? "Ver árbol de proyecto" : "View project tree",
    symbols_title_btn: es ? "Monedas/Pares y despliegue rápido" : "Coins/Pairs and quick deploy",
    admin_refresh_title: es ? "Refrescar datos/modelos cripto (admin)" : "Refresh crypto data/models (admin)",
    agent_step_title: es ? "Agent step (tool-first). Shift=run" : "Agent step (tool-first). Shift=run",
    agent_run_title: es ? "Agent run (multi-step)" : "Agent run (multi-step)",
    stop_server_title: es ? "Apagar servidor (admin)" : "Stop server (admin)",
    clear_logs_title: es ? "Limpiar logs" : "Clear logs",
    cancel_all_title: es ? "Cancelar todo" : "Cancel all",
    help_btn_title: es ? "Guía rápida de herramientas" : "Quick tools guide",
    chat_side_show: es ? "Estado / Sesión" : "Status / Session",
    chat_side_show_aria: es ? "Mostrar panel Estado/Sesión" : "Show Status/Session panel",
    hide_panel_title: es ? "Ocultar panel" : "Hide panel",
    copy_id_title: es ? "Copiar ID" : "Copy ID",
    refresh_log_title: es ? "Actualizar log" : "Refresh log",
    mode_chat_title: es ? "Modo chat" : "Chat mode",
    mode_web_title: es ? "Modo búsqueda web" : "Web search mode",
    mode_url_title: es ? "Modo leer URL" : "Read URL mode",
    mode_crypto_title: es ? "Modo cripto" : "Crypto mode",
    mode_image_title: es ? "Modo imagen" : "Image mode",
    layout_toggle_title: es ? "Ocultar paneles laterales" : "Hide side panels",
    chart_symbol_aria: es ? "Símbolo cripto" : "Crypto symbol",
    chart_refresh_title: es ? "Actualizar gráfico" : "Refresh chart",
    chart_expand_title: es ? "Expandir/contraer gráfico" : "Expand/collapse chart",
    chart_mode_hint_title: es ? "Precio • trades • compare • fills" : "Price • trades • compare • fills",
    price_source_title: es ? "Fuente de precio" : "Price source",
    crypto_context_title: es ? "Contexto cripto" : "Crypto context",
    signal_confidence_aria: es ? "Confianza de la señal" : "Signal confidence",
    compare_help_title: es ? "¿Cómo leer esta sección?" : "How to read this section?",
    compare_refresh_title: es ? "Actualizar comparación" : "Refresh comparison",
    preds_btn_title: es ? "Últimas predicciones" : "Latest predictions",
    pnl_btn_title: es ? "P&L y trades" : "P&L and trades",
    stats_btn_title: es ? "Estadísticas de predicciones" : "Prediction stats",
    snapshot_btn_title: es ? "Ver snapshot del sistema" : "View system snapshot",
    clear_crypto_title: es ? "Borrar historial cripto" : "Clear crypto history",
    news_refresh_title: es ? "Refrescar noticias" : "Refresh news",
    image_status_title: es ? "Estado" : "Status",
    image_refresh_title: es ? "Recargar galería" : "Reload gallery",
    refresh_tree_title: es ? "Recargar árbol" : "Reload tree",
    upload_zip_title: es ? "Subir proyecto ZIP" : "Upload ZIP project",
    clone_repo_title: es ? "Clonar repo" : "Clone repo",
    delete_project_title: es ? "Eliminar proyecto" : "Delete project",
    files_to_chat_title: es ? "Volver a chat" : "Back to chat",
    ingest_log_title: es ? "Ver log de ingesta" : "View ingest log",
    files_expand_title: es ? "Expandir Archivos" : "Expand Files",
    ingest_status_title: es ? "Estado de ingesta" : "Ingest status",
    copy_content_title: es ? "Copiar contenido" : "Copy content",
    refresh_list_title: es ? "Actualizar lista" : "Refresh list",
    close_aria: es ? "Cerrar" : "Close",
  };
  Object.entries(map).forEach(([key, text]) => {
    document.querySelectorAll(`[data-i18n='${key}']`).forEach((el) => {
      el.textContent = text;
    });
  });
  document.querySelectorAll("[data-i18n-title]").forEach((el) => {
    const key = el.getAttribute("data-i18n-title");
    if (!key || !map[key]) return;
    el.setAttribute("title", map[key]);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    const key = el.getAttribute("data-i18n-placeholder");
    if (!key || !map[key]) return;
    el.setAttribute("placeholder", map[key]);
  });
  document.querySelectorAll("[data-i18n-aria-label]").forEach((el) => {
    const key = el.getAttribute("data-i18n-aria-label");
    if (!key || !map[key]) return;
    el.setAttribute("aria-label", map[key]);
  });
  updateComposeUI();
  if (dom.projectList) dom.projectList.title = es ? "Proyectos cargados/clonados" : "Uploaded/cloned projects";
  renderActiveProjectSelect();
  renderActiveProjectBadge();
  renderProjectMeta();
  renderSourceOriginBar(state.lastChatContext);
  if (dom.buyBtn) dom.buyBtn.title = es ? "Comprar (simulado, educativo)" : "Buy (simulated, educational)";
  if (dom.sellBtn) dom.sellBtn.title = es ? "Vender (simulado, educativo)" : "Sell (simulated, educational)";
  if (dom.predictionCompareHelp) {
    dom.predictionCompareHelp.title = es
      ? "Predicción vs. realidad: compara el movimiento esperado con el real y mira la precisión y el Δ promedio."
      : "Prediction vs actual: compare expected versus actual move and review accuracy plus average Δ.";
  }
  if (dom.statsBtn) {
    dom.statsBtn.title = es
      ? "Precisión y movimiento promedio; mira la barra para entender aciertos."
      : "Accuracy and average move; check the bar to interpret performance.";
  }
  if (dom.predsBtn) {
    dom.predsBtn.title = es
      ? "Últimas predicciones: qué se predijo y qué ocurrió."
      : "Recent predictions: what we predicted vs what happened.";
  }
  if (dom.pnlBtn) {
    dom.pnlBtn.title = es
      ? "P&L de trades simulados (educativos)."
      : "P&L from simulated trades (educational).";
  }

}

function localizeHelp() {
  const es = state.lang === LANG.ES;
  const map = {
    hint_title: es ? "Guía breve" : "Quick tips",
    hint_mode_chat: es ? "Chat" : "Chat",
    hint_mode_web: es ? "Web" : "Web",
    hint_mode_url: es ? "URL" : "URL",
    hint_mode_crypto: es ? "Cripto" : "Crypto",
    hint_mode_image: es ? "Imagen" : "Image",
    hint_chat: es
      ? "Preguntas generales, debugging local o instrucciones paso a paso."
      : "General questions, local debugging, and step-by-step help.",
    hint_web: es
      ? "El contexto web está en automático por defecto. Agrega web: para forzar búsqueda cuando necesites fuentes recientes o enlaces citables."
      : "Web context is automatic by default. Add web: to force search when you need fresh sources or citable links.",
    hint_url: es
      ? "Usa url:https://... para leer y resumir un enlace específico."
      : "Use url:https://... to read and summarize a specific link.",
    hint_crypto: es
      ? "Activa el panel para predicciones, trades simulados y métricas P&L."
      : "Enable the panel for predictions, simulated trades, and P&L metrics.",
    hint_image: es
      ? "Activa Imagen (📷), sube archivo y pregunta en chat para usar su contexto."
      : "Enable Image mode (📷), upload a file, and ask in chat using its context.",
  };

  for (const [key, text] of Object.entries(map)) {
    document.querySelectorAll(`[data-i18n='${key}']`).forEach((el) => {
      if (key.startsWith("hint_") && !key.startsWith("hint_mode_") && el.querySelector("span:nth-child(2)")) {
        el.querySelector("span:nth-child(2)").textContent = text;
      } else {
        el.textContent = text;
      }
    });
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
  applyAuthState();
  updateStatusCenter();
}

function toggleFilesExpand() {
  document.body.classList.toggle("files-wide");
}

function showCryptoPanelFromToolbar() {
  if (state.mode === MODES.IMAGE) {
    setMode(MODES.CHAT);
  }
  if (state.layoutCollapsed) {
    state.layoutCollapsed = false;
    localStorage.setItem("aegis_layout_collapsed", "0");
    applyLayoutCollapsed();
  }
  if (!state.chartVisible) {
    state.chartVisible = true;
    localStorage.setItem("aegis_chart_visible", "1");
  }
  applyPanelVisibility();
  loadCryptoModels();
  loadChartData(state.chartSymbol);
  loadCryptoPrediction({ force: true });
  loadCryptoState({ force: true });
  loadPredictionComparison(state.chartSymbol, { force: true });
  notifyStatus(
    state.lang === LANG.ES ? "Panel cripto abierto." : "Crypto panel opened.",
    { kind: "info", key: "crypto-panel-open", dedupeMs: 1500, ttlMs: 1800 }
  );
}

function showFilesPanelFromToolbar() {
  if (state.mode === MODES.IMAGE || state.mode === MODES.CRYPTO) {
    setMode(MODES.CHAT);
  }
  if (state.layoutCollapsed) {
    state.layoutCollapsed = false;
    localStorage.setItem("aegis_layout_collapsed", "0");
    applyLayoutCollapsed();
  }
  state.sidebarVisible = true;
  localStorage.setItem("aegis_sidebar_visible", "1");
  applyPanelVisibility();
  activateTab("files");
}

function toggleSidebarVisibility() {
  state.sidebarVisible = !state.sidebarVisible;
  localStorage.setItem("aegis_sidebar_visible", state.sidebarVisible ? "1" : "0");
  applyPanelVisibility();
}

function toggleChartVisibility() {
  state.chartVisible = !state.chartVisible;
  localStorage.setItem("aegis_chart_visible", state.chartVisible ? "1" : "0");
  applyPanelVisibility();
  updateCryptoStatePolling();
}

function applyPanelVisibility() {
  const chatOnly = !!state.chatOnlyExperience;
  const isCrypto = state.mode === MODES.CRYPTO;
  // Image mode now runs from the chat bar, so side panels follow normal visibility rules.
  const chartVisible = chatOnly ? false : !!state.chartVisible;
  const sidebarVisible = chatOnly ? true : (isCrypto ? false : !!state.sidebarVisible);
  const es = state.lang === LANG.ES;

  if (dom.chartPanel) dom.chartPanel.classList.toggle("chart-hidden", !chartVisible);
  if (dom.appSidebar) dom.appSidebar.classList.toggle("sidebar-hidden", !sidebarVisible);
  document.body.classList.toggle("chart-off", !chartVisible);
  document.body.classList.toggle("sidebar-off", !sidebarVisible);

  if (dom.chartExpandBtn) {
    dom.chartExpandBtn.innerHTML = chartVisible ? '<i class="fas fa-eye-slash"></i>' : '<i class="fas fa-eye"></i>';
    dom.chartExpandBtn.title = chartVisible
      ? (es ? "Ocultar panel cripto" : "Hide crypto panel")
      : (es ? "Mostrar panel cripto" : "Show crypto panel");
    dom.chartExpandBtn.setAttribute("aria-pressed", String(!chartVisible));
  }

  if (dom.filesExpandBtn) {
    dom.filesExpandBtn.innerHTML = sidebarVisible ? '<i class="fas fa-eye-slash"></i>' : '<i class="fas fa-eye"></i>';
    dom.filesExpandBtn.title = sidebarVisible
      ? (es ? "Ocultar panel de archivos/repos" : "Hide files/repos panel")
      : (es ? "Mostrar panel de archivos/repos" : "Show files/repos panel");
    dom.filesExpandBtn.setAttribute("aria-pressed", String(!sidebarVisible));
  }

  if (dom.showCryptoPanelBtn) {
    dom.showCryptoPanelBtn.classList.toggle("active", chartVisible);
    dom.showCryptoPanelBtn.setAttribute("aria-pressed", String(chartVisible));
    dom.showCryptoPanelBtn.title = chartVisible
      ? (es ? "Ocultar panel cripto" : "Hide crypto panel")
      : (es ? "Mostrar panel cripto" : "Show crypto panel");
  }
  if (dom.showFilesPanelBtn) {
    dom.showFilesPanelBtn.classList.toggle("active", sidebarVisible);
    dom.showFilesPanelBtn.setAttribute("aria-pressed", String(sidebarVisible));
    dom.showFilesPanelBtn.title = sidebarVisible
      ? (es ? "Ocultar panel de archivos/repos" : "Hide files/repos panel")
      : (es ? "Mostrar panel de archivos/repos" : "Show files/repos panel");
  }
  updateCryptoStatePolling();
}

function registerAbortController(controller) {
  if (controller) state.activeControllers.add(controller);
  updateComposeUI();
  return controller;
}
function unregisterAbortController(controller) {
  if (controller) state.activeControllers.delete(controller);
  updateComposeUI();
}

async function cancelAllRequests(fullStop = false) {
  if (state.activeControllers.size) {
    const arr = Array.from(state.activeControllers);
    state.activeControllers.clear();
    arr.forEach((c) => { try { c.abort(); } catch {} });
  }
  removeTyping();
  setPending(false);
  state.cancelledByUser = true;
  let backendNote = "";
  if (fullStop) {
    stopCryptoStateLiveStream();
    stopCryptoStatePolling();
    stopLiveChart();
    stopAlertsPolling();
    stopLogsPolling();
    if (state.newsTimer) clearInterval(state.newsTimer);
    state.newsTimer = null;
    if (state.ingestPollTimer) clearInterval(state.ingestPollTimer);
    state.ingestPollTimer = null;
    if (state.ingestJobsTimer) clearInterval(state.ingestJobsTimer);
    state.ingestJobsTimer = null;
    stopConversationEventsPolling();
    try {
      const res = await cancelBackendProcesses();
      if (res && Number.isFinite(res.terminated)) {
        backendNote = ` (${state.lang === LANG.ES ? "procesos backend" : "backend jobs"}: ${res.terminated})`;
      }
    } catch (err) {
      console.error("cancel backend failed", err);
    }
  }
  appendBubble(
    fullStop
      ? (state.lang === LANG.ES ? "Procesos detenidos." : "Processes stopped.") + backendNote
      : (state.lang === LANG.ES ? "Solicitud cancelada." : "Request cancelled."),
    "bot"
  );
  updateStatusCenter();
}

async function cancelBackendProcesses() {
  try {
    const res = await fetchWithTimeout(endpoints.adminCancelAll, { method: "POST" }, { timeout: 8000, retries: 0 });
    const data = await safeJson(res);
    if (!res.ok) throw new Error();
    return data || {};
  } catch (err) {
    console.error("cancel-backend-error", err);
    return null;
  }
}

async function shutdownServer(skipConfirm = false) {
  const es = state.lang === LANG.ES;
  const warn = es
    ? "Esto intentará apagar el servidor AEGIS en esta máquina. ¿Continuar?"
    : "This will attempt to shut down the AEGIS server on this machine. Continue?";
  if (!skipConfirm && !confirm(warn)) return;

  try {
    const res = await fetchWithTimeout(
      endpoints.systemShutdown,
      { method: "POST", headers: { Accept: "application/json" } },
      { timeout: 8000, retries: 0 },
    );
    const data = await safeJson(res);
    if (!res.ok) {
      const detail = (data && data.detail) ? String(data.detail) : `${res.status} ${res.statusText || ""}`.trim();
      if (res.status === 403) {
        appendBubble(
          es
            ? "Shutdown deshabilitado. Actívalo con `AEGIS_ENABLE_SHUTDOWN_ENDPOINT=1` o usa `./stop_aegis.sh`."
            : "Shutdown is disabled. Enable with `AEGIS_ENABLE_SHUTDOWN_ENDPOINT=1` or use `./stop_aegis.sh`.",
          "error",
        );
        return;
      }
      throw new Error(detail || "shutdown failed");
    }
    appendBubble(es ? "Servidor apagándose..." : "Server shutting down...", "bot");
  } catch (err) {
    console.error(err);
    appendBubble(es ? "No se pudo apagar el servidor." : "Could not shut down server.", "error");
  }
}

async function executeConversationTool(
  tool,
  args = {},
  {
    autoApprove = false,
    title = "",
    continueAfter = false,
    continueMessage = "",
    continueUseWeb = false,
    continueSynthesize = true,
    continueMaxIterations = 2,
    continueMaxTotalToolCalls = 6,
    continueMaxToolRetries = 1,
    continueToolRetryBackoffMs = 150,
  } = {},
) {
  const es = state.lang === LANG.ES;
  const convId = state.conversationId;
  if (!convId) {
    appendBubble(es ? "No hay conversación activa. Envía un mensaje primero." : "No active conversation. Send a message first.", "error");
    return null;
  }
  const url = new URL(endpoints.conversationExecuteTool(convId), location.origin);
  const payload = {
    tool: String(tool || "").trim(),
    args: args && typeof args === "object" ? args : {},
    continue_after: !!continueAfter,
    continue_message: String(continueMessage || "").trim() || undefined,
    continue_lang: state.lang,
    continue_use_web: !!continueUseWeb,
    continue_synthesize: !!continueSynthesize,
    continue_max_iterations: Number(continueMaxIterations || 2),
    continue_max_total_tool_calls: Number(continueMaxTotalToolCalls || 6),
    continue_max_tool_retries: Number(continueMaxToolRetries || 1),
    continue_tool_retry_backoff_ms: Number(continueToolRetryBackoffMs || 150),
  };

  const doCall = async (extra = {}) => {
    const res = await fetchWithTimeout(url.toString(), {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ ...payload, ...extra }),
    }, { timeout: 30000, retries: 0 });
    const data = await safeJson(res);
    return { res, data };
  };

  let first = null;
  try {
    first = await doCall();
  } catch (err) {
    console.error(err);
    appendBubble(es ? "Error ejecutando tool." : "Tool execution error.", "error");
    return null;
  }

  if (first.res.status === 409 && first.data && typeof first.data === "object") {
    const approval = first.data?.detail?.approval || first.data?.approval || null;
    const token = String(approval?.token || "").trim();
    if (!token) {
      appendBubble(es ? "Approval requerido, pero sin token." : "Approval required, but missing token.", "error");
      return null;
    }
    if (!autoApprove) {
      const warn = es
        ? `El servidor requiere aprobación para: ${payload.tool}. ¿Aprobar?`
        : `Server requires approval for: ${payload.tool}. Approve?`;
      if (!confirm(warn)) return null;
    }
    const second = await doCall({ approval_token: token });
    if (!second.res.ok) {
      const msg = second.data?.detail || second.data?.error || `HTTP ${second.res.status}`;
      appendBubble(String(msg), "error");
      return null;
    }
    if (second.data && typeof second.data === "object" && second.data.context && typeof second.data.context === "object") {
      state.lastChatContext = second.data.context;
      renderProjectMeta();
      renderSourceOriginBar(state.lastChatContext);
    }
    if (second.data?.continued && second.data?.continue_result?.response) {
      const contCtx = second.data?.continue_result?.context && typeof second.data.continue_result.context === "object"
        ? second.data.continue_result.context
        : state.lastChatContext;
      appendBubble(String(second.data.continue_result.response), "bot", true, contCtx);
      if (contCtx && typeof contCtx === "object") {
        state.lastChatContext = contCtx;
        renderProjectMeta();
        renderSourceOriginBar(state.lastChatContext);
      }
    }
    if (title) renderSimpleList(second.data, title);
    return second.data;
  }

  if (!first.res.ok) {
    const msg = first.data?.detail || first.data?.error || `HTTP ${first.res.status}`;
    appendBubble(String(msg), "error");
    return null;
  }
  if (first.data && typeof first.data === "object" && first.data.context && typeof first.data.context === "object") {
    state.lastChatContext = first.data.context;
    renderProjectMeta();
    renderSourceOriginBar(state.lastChatContext);
  }
  if (first.data?.continued && first.data?.continue_result?.response) {
    const contCtx = first.data?.continue_result?.context && typeof first.data.continue_result.context === "object"
      ? first.data.continue_result.context
      : state.lastChatContext;
    appendBubble(String(first.data.continue_result.response), "bot", true, contCtx);
    if (contCtx && typeof contCtx === "object") {
      state.lastChatContext = contCtx;
      renderProjectMeta();
      renderSourceOriginBar(state.lastChatContext);
    }
  }
  if (title) renderSimpleList(first.data, title);
  return first.data;
}

function withJsonHeaders(headers = {}, scope = "main") {
  const normalizedScope = scope === "files" ? "files" : "main";
  const keyToUse = state.cookieAuth ? "" : cleanKey(normalizedScope === "files" ? (state.filesApiKey || state.apiKey) : state.apiKey);
  return {
    Accept: "application/json",
    "Content-Type": "application/json",
    ...(headers || {}),
    ...(keyToUse ? { "X-API-Key": keyToUse } : {}),
  };
}

async function fetchWithTimeout(url, opts = {}, { timeout = CHAT_MAX_TIMEOUT_MS, retries = 0 } = {}) {
  for (let attempt = 0; attempt <= retries; attempt++) {
    const controller = registerAbortController(new AbortController());
    const timeoutMs = Number(timeout);
    const disableDeadline = isLongRunningEndpoint(url);
    const useDeadline = Number.isFinite(timeoutMs) && timeoutMs > 0 && !disableDeadline;
    const id = useDeadline ? setTimeout(() => controller.abort(), timeoutMs) : null;
    try {
      await ensureAccessToken();
      const scope = authScopeForUrl(url);
      const useFilesKey = scope === "files";
      const keyToUse = state.cookieAuth ? "" : cleanKey(useFilesKey ? (state.filesApiKey || state.apiKey) : state.apiKey);
      const merged = { ...opts };
      merged.credentials = "include";
      merged.headers = {
        ...(opts.headers || {}),
        ...(keyToUse ? { "X-API-Key": keyToUse } : {}),
      };
      const res = await fetch(url, { ...merged, signal: controller.signal });
      if (res.status === 401 || res.status === 403) {
        if (state.cookieAuth && await tryRefreshAccessToken()) {
          const retried = await fetch(url, { ...merged, signal: controller.signal });
          if (retried.status === 401 || retried.status === 403) {
            await markAuthFailure(url, retried, { scope, keyToUse });
            if (isConversationPollUrl(url)) {
              handleConversationPollAuthDenied(retried.status);
            }
          } else if (retried.ok) {
            clearAuthFailure();
          }
          return retried;
        }
        if (!state.cookieAuth && await fetchNewAccessToken()) {
          const retried = await fetch(url, { ...merged, signal: controller.signal });
          if (retried.status === 401 || retried.status === 403) {
            await markAuthFailure(url, retried, { scope, keyToUse });
            if (isConversationPollUrl(url)) {
              handleConversationPollAuthDenied(retried.status);
            }
          } else if (retried.ok) {
            clearAuthFailure();
          }
          return retried;
        }
        await markAuthFailure(url, res, { scope, keyToUse });
        if (isConversationPollUrl(url)) {
          handleConversationPollAuthDenied(res.status);
        }
        return res;
      }
      if (res.ok) {
        clearAuthFailure();
      }
      return res;
    } catch (err) {
      if (attempt === retries) throw err;
      await new Promise((r) => setTimeout(r, 300 * (attempt + 1)));
    } finally {
      if (id != null) clearTimeout(id);
      unregisterAbortController(controller);
    }
  }
}

function isLongRunningEndpoint(url) {
  try {
    const u = new URL(url, location.origin);
    const p = String(u.pathname || "");
    if (p === "/chat") return true;
    if (/^\/chat\/[^/]+\/agent_(step|run|continue)$/.test(p)) return true;
    if (p === "/image/generate" || p === "/image/generate_with_reference") return true;
    if (p === "/files/ingest") return true;
    if (p === "/crypto/predict") return true;
    if (p.startsWith("/crypto/")) return true;
    if (p === "/websearch" || p === "/fetch_url") return true;
    return false;
  } catch {
    return false;
  }
}

function isConversationPollUrl(url) {
  try {
    const u = new URL(url, location.origin);
    return /^\/chat\/[^/]+\/(events|turns)$/.test(String(u.pathname || ""));
  } catch {
    return false;
  }
}

function authScopeForUrl(url) {
  try {
    const u = new URL(url, location.origin);
    const p = u.pathname || "";
    // Conversation endpoints that can read local project state or execute tools should use FILES key.
    if (p.includes("/execute_tool") || p.includes("/agent_step") || p.includes("/agent_run") || p.endsWith("/project")) return "files";
    return p.startsWith("/files/") || p.startsWith("/image/") ? "files" : "main";
  } catch {
    return "main";
  }
}

async function responseDetailSafe(res) {
  try {
    const clone = res.clone();
    const data = await clone.json();
    if (typeof data?.detail === "string") return data.detail;
    if (typeof data?.error?.message === "string") return data.error.message;
    if (typeof data?.error === "string") return data.error;
    return "";
  } catch {
    try {
      const text = (await res.clone().text()).trim();
      return text.slice(0, 140);
    } catch {
      return "";
    }
  }
}

async function markAuthFailure(url, res, { scope, keyToUse } = {}) {
  const detailRaw = await responseDetailSafe(res);
  const detail = (detailRaw || "").replace(/\s+/g, " ").trim().slice(0, 110);
  const next = {
    url: String(url || ""),
    scope: scope || authScopeForUrl(url),
    status: Number(res?.status || 401),
    hasKey: !!cleanKey(keyToUse || ""),
    hasCookieAuth: !!state.cookieAuth,
    detail,
    ts: Date.now(),
  };
  const prev = state.authDiag?.lastError;
  state.authDiag.failures = Number(state.authDiag?.failures || 0) + 1;
  state.authDiag.lastError = next;
  if (
    !prev
    || prev.status !== next.status
    || prev.scope !== next.scope
    || prev.detail !== next.detail
  ) {
    updateStatusCenter();
  }
}

function clearAuthFailure() {
  if (!state.authDiag) return;
  state.authDiag.lastOkAt = Date.now();
  if (state.authDiag.lastError) {
    state.authDiag.lastError = null;
    updateStatusCenter();
  }
  if (state.conversationId && !state.convEventsTimer && !state.convTurnsTimer && state.debugTraceEnabled && state.chatSideVisible) {
    startConversationEventsPolling();
  }
  state.convAuthBlockedAt = 0;
}

function authDebugForUrl(url) {
  try {
    const scope = authScopeForUrl(url);
    const filesScope = scope === "files";
    const key = state.cookieAuth ? "" : cleanKey(filesScope ? (state.filesApiKey || state.apiKey) : state.apiKey);
    const cookie = state.cookieAuth ? "yes" : "no";
    return `${scope}:${key ? "key" : "no-key"},cookie:${cookie}`;
  } catch {
    return "unknown";
  }
}

async function safeJson(res) {
  try { return await res.json(); } catch { return null; }
}

function clearSources() {
  if (dom.sourceOriginBar) dom.sourceOriginBar.innerHTML = "";
  if (!dom.sourcesContent) return;
  dom.sourcesContent.innerHTML = "";
  dom.sourcesContent.appendChild(el("div", { text: state.lang === LANG.ES ? "Sin recursos externos aún." : "No external resources yet." }));
}

function getDomainFromUrl(url) {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return url; }
}

function formatAgo(ts) {
  if (!ts) return "";
  const tsMs = Number(ts);
  const t = tsMs > 1e12 ? tsMs : tsMs * 1000;
  const now = Date.now();
  const diffMs = now - t;
  if (!Number.isFinite(diffMs)) return "";
  const mins = Math.max(0, Math.floor(diffMs / 60000));
  if (mins < 1) return state.lang === LANG.ES ? "ahora" : "now";
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 48) return `${hrs}h`;
  const days = Math.floor(hrs / 24);
  return `${days}d`;
}

// =========================
// Auth token helpers
// =========================

function clearTokens() {
  state.accessToken = "";
  state.refreshToken = "";
  state.tokenExp = 0;
  state.cookieAuth = false;
  state.authScopes = [];
  state.authCookieExp = 0;
  writeSecretItem("aegis_cookie_auth", "");
  writeSecretItem("aegis_auth_scopes", "");
  writeSecretItem("aegis_auth_cookie_exp", "");
  try {
    applyAuthState();
    updateStatusCenter();
  } catch {}
}

function storeTokens({ scopes = [], expires_in = 0, refresh_expires_in = 0, cookie_auth = true } = {}) {
  state.cookieAuth = !!cookie_auth;
  state.authScopes = Array.isArray(scopes) ? scopes.map((s) => String(s || "").trim().toLowerCase()).filter(Boolean) : [];
  const now = Math.floor(Date.now() / 1000);
  state.authCookieExp = expires_in ? now + Math.max(0, Number(expires_in) || 0) : 0;
  state.tokenExp = state.authCookieExp;
  state.accessToken = "";
  state.refreshToken = "";
  if (state.cookieAuth) {
    writeSecretItem("aegis_cookie_auth", "1");
    writeSecretItem("aegis_auth_scopes", JSON.stringify(state.authScopes));
    writeSecretItem("aegis_auth_cookie_exp", String(state.authCookieExp));
    // Clear bootstrap secrets from storage once the cookie session is live.
    writeSecretItem("aegis_api_key", "");
    writeSecretItem("aegis_files_api_key", "");
  }
  void refresh_expires_in;
  try {
    applyAuthState();
    updateStatusCenter();
  } catch {}
}

function tokenExpiresSoon() {
  if (state.cookieAuth && state.authCookieExp) {
    const msLeft = state.authCookieExp * 1000 - Date.now();
    return msLeft < 120000; // 2 min
  }
  if (!state.tokenExp) return true;
  const msLeft = state.tokenExp * 1000 - Date.now();
  return msLeft < 120000; // 2 min
}

function clearAuthRetryCooldown() {
  if (!state.authRetryFailures && !state.authRetryBlockedUntil) return;
  state.authRetryFailures = 0;
  state.authRetryBlockedUntil = 0;
  updateStatusCenter();
}

function setAuthRetryCooldown() {
  state.authRetryFailures = Number(state.authRetryFailures || 0) + 1;
  const exp = Math.max(0, state.authRetryFailures - 1);
  const backoffMs = Math.min(AUTH_RETRY_MAX_MS, AUTH_RETRY_BASE_MS * (2 ** exp));
  state.authRetryBlockedUntil = Date.now() + backoffMs;
  updateStatusCenter();
}

function isAuthRetryBlocked() {
  return Number(state.authRetryBlockedUntil || 0) > Date.now();
}

async function fetchNewAccessToken() {
  const key = cleanKey(state.apiKey);
  if (isAuthRetryBlocked()) return false;
  if (!key && !state.cookieAuth) return false;
  try {
    const res = await fetch(endpoints.authToken, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...(key ? { "X-API-Key": key } : {}),
      },
      // Self-issued JWT scopes are intentionally limited server-side; keep this list
      // aligned with allowed non-privileged UI capabilities.
      body: JSON.stringify({ scopes: ["chat", "files", "crypto"], refresh: true }),
    });
    const data = await safeJson(res);
    if (!res.ok || !data?.cookie_auth) throw new Error("token failed");
    storeTokens({
      cookie_auth: true,
      scopes: data.scopes || ["chat", "files", "crypto"],
      expires_in: Number(data.expires_in) || 1800,
      refresh_expires_in: Number(data.refresh_expires_in) || 86400,
    });
    clearAuthRetryCooldown();
    clearBootstrapSecrets();
    return true;
  } catch {
    setAuthRetryCooldown();
    if (!state.cookieAuth) clearTokens();
    return false;
  }
}

async function tryRefreshAccessToken() {
  if (isAuthRetryBlocked()) return false;
  if (!state.cookieAuth) return false;
  try {
    const res = await fetch(endpoints.authRefresh, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({}),
    });
    const data = await safeJson(res);
    if (!res.ok || !data?.cookie_auth) throw new Error("refresh failed");
    storeTokens({
      cookie_auth: true,
      scopes: data.scopes || state.authScopes,
      expires_in: Number(data.expires_in) || 1800,
      refresh_expires_in: Number(data.refresh_expires_in) || 86400,
    });
    clearAuthRetryCooldown();
    return true;
  } catch {
    setAuthRetryCooldown();
    clearTokens();
    return false;
  }
}

async function ensureAccessToken() {
  if (isAuthRetryBlocked()) return false;
  if (state.cookieAuth) {
    if (!state.authCookieExp || tokenExpiresSoon()) {
      const ok = await tryRefreshAccessToken();
      if (!ok) {
        clearTokens();
        return false;
      }
    }
    return true;
  }
  if (!state.apiKey) return false;
  if (!state.accessToken || tokenExpiresSoon()) {
    const ok = await fetchNewAccessToken();
    if (!ok) {
      clearTokens();
      return false;
    }
  }
  return true;
}

function clearBootstrapSecrets() {
  state.apiKey = "";
  state.filesApiKey = "";
  writeSecretItem("aegis_api_key", "");
  writeSecretItem("aegis_files_api_key", "");
}

async function logoutAuthSession() {
  try {
    await fetch(endpoints.authLogout, {
      method: "POST",
      credentials: "include",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: "{}",
    });
  } catch {}
  clearTokens();
  clearBootstrapSecrets();
}

async function refreshAuthedPanels() {
  if (hasAuthForScope("main")) {
    await ensureAccessToken();
    await loadLlmProviderState();
    await loadConversationList(state.conversationsIncludeArchived);
    if (state.conversationId) {
      await syncConversationState(state.conversationId);
      await restoreConversationTranscript(state.conversationId);
      startConversationEventsPolling();
    }
  }

  if (hasAuthForScope("files")) {
    await loadRegisteredProjects();
    if (state.activeProjectId || getEffectiveProjectRoot()) {
      await loadProjectTree();
    }
  }

  updateStatusCenter();
}

function startTokenAutoRefresh() {
  if (state.tokenRefreshTimer) clearInterval(state.tokenRefreshTimer);
  state.tokenRefreshTimer = setInterval(() => {
    ensureAccessToken().catch(() => {});
  }, 5 * 60 * 1000); // every 5 min best-effort
}

function syncProjectSelectValue(rootValue) {
  const nextRoot = String(rootValue || "").trim();
  if (!dom.projectSelect) {
    renderProjectList();
    return;
  }

  let opt = Array.from(dom.projectSelect.options || []).find((o) => o.value === nextRoot);
  if (nextRoot && !opt) {
    opt = document.createElement("option");
    opt.value = nextRoot;
    opt.textContent = nextRoot;
    dom.projectSelect.appendChild(opt);
  }
  dom.projectSelect.value = nextRoot;
  renderProjectList();
}

function setManualProjectRoot(newRoot) {
  const nextRoot = String(newRoot || "").trim();
  state.manualProjectRoot = nextRoot;
  if (nextRoot) localStorage.setItem("aegis_project_root", nextRoot);
  else localStorage.removeItem("aegis_project_root");
  syncProjectSelectValue(nextRoot);
}

function clearManualProjectRoot({ syncSelect = false } = {}) {
  state.manualProjectRoot = "";
  localStorage.removeItem("aegis_project_root");
  if (syncSelect) syncProjectSelectValue("");
}

function getActiveProjectRecord() {
  return state.projectRecords.find((item) => String(item?.project_id || "") === String(state.activeProjectId || "")) || null;
}

function getEffectiveProjectRoot() {
  const detailRoot = String(
    state.activeProjectDetail?.project?.root_path
    || state.activeProjectDetail?.root_path
    || ""
  ).trim();
  if (detailRoot) return detailRoot;
  const projectRoot = String(getActiveProjectRecord()?.root_path || "").trim();
  if (projectRoot) return projectRoot;
  // Prevent "two-project" drift: manual root is only a fallback when no active project is selected.
  if (state.activeProjectId) return "";
  return String(state.manualProjectRoot || "").trim();
}

function resolveProjectSelectionState() {
  const activeProjectId = String(state.activeProjectId || "").trim();
  const detailProjectId = String(
    state.activeProjectDetail?.project?.project_id
    || state.activeProjectDetail?.project_id
    || state.activeProjectDetail?.id
    || ""
  ).trim();
  const projectId = activeProjectId || detailProjectId;
  const detailRoot = String(
    state.activeProjectDetail?.project?.root_path
    || state.activeProjectDetail?.root_path
    || ""
  ).trim();
  const recordRoot = String(getActiveProjectRecord()?.root_path || "").trim();
  const manualRoot = String(state.manualProjectRoot || "").trim();
  const rootPath = detailRoot || recordRoot || (!projectId ? manualRoot : "");
  return {
    projectId,
    rootPath,
    activeProjectId,
    detailProjectId,
    detailRoot,
    recordRoot,
    manualRoot,
  };
}

function addUploadedProject(path, projectId = null) {
  if (!path) return;
  if (!state.uploadedProjects.includes(path)) {
    state.uploadedProjects.push(path);
  }
  if (projectId) syncProjectSelectValue(path);
  else setManualProjectRoot(path);
  if (projectId) {
    state.activeProjectId = String(projectId);
    localStorage.setItem("aegis_active_project_id", state.activeProjectId);
  }
  loadRegisteredProjects();
}

async function loadRegisteredProjects() {
  if (!hasAuthForScope("files")) {
    state.projectRecords = [];
    renderProjectList();
    renderActiveProjectSelect();
    return;
  }
  try {
    const res = await fetchWithTimeout(endpoints.filesProjects, {}, { timeout: 10000, retries: 0 });
    const data = await safeJson(res);
    if (!res.ok) throw new Error(data?.detail || "projects failed");
    state.projectRecords = Array.isArray(data?.items) ? data.items : [];
    renderProjectList();
    renderActiveProjectSelect();
    if (state.activeProjectId) {
      const exists = state.projectRecords.some((item) => String(item?.project_id || "") === state.activeProjectId);
      if (exists) {
        await loadActiveProjectDetail(state.activeProjectId);
      } else {
        await setActiveProject("", { bindConversation: false, loadDetail: false });
      }
    } else {
      renderActiveProjectBadge();
      renderProjectMeta();
    }
  } catch (err) {
    console.error("load-projects-error", err);
    renderProjectList();
  }
}

function renderActiveProjectSelect() {
  if (!dom.activeProjectSelect) return;
  const current = state.activeProjectId || "";
  dom.activeProjectSelect.innerHTML = "";
  const emptyOpt = document.createElement("option");
  emptyOpt.value = "";
  emptyOpt.textContent = state.lang === LANG.ES ? "Sin proyecto activo" : "No active project";
  dom.activeProjectSelect.appendChild(emptyOpt);
  state.projectRecords.forEach((project) => {
    const opt = document.createElement("option");
    opt.value = String(project.project_id || "");
    opt.textContent = `${project.project_id} • ${project.ready_state || project.status || "uploaded"}`;
    dom.activeProjectSelect.appendChild(opt);
  });
  dom.activeProjectSelect.value = current;
  // Keep badge + manual-root UX in sync whenever the selector is rendered.
  renderActiveProjectBadge();
}

function renderActiveProjectBadge() {
  if (!dom.activeProjectBadge) return;
  const es = state.lang === LANG.ES;
  const manualRoot = String(state.manualProjectRoot || "").trim();
  dom.activeProjectBadge.className = `project-badge ${state.activeProjectId ? "project-badge-active" : "project-badge-empty"}`;
  dom.activeProjectBadge.textContent = state.activeProjectId
    ? `${es ? "Proyecto activo" : "Active project"}: ${state.activeProjectId}`
    : manualRoot
      ? (es ? `Sin proyecto activo • root manual: ${manualRoot}` : `No active project • manual root: ${manualRoot}`)
      : (es ? "Sin proyecto activo" : "No active project");
  updateManualRootControlState();
}

function updateManualRootControlState() {
  const es = state.lang === LANG.ES;
  if (!dom.projectSelect) return;
  const hasActive = !!String(state.activeProjectId || "").trim();
  // Manual root is only a fallback path to register a project_id; once active_project_id exists,
  // we disable it to prevent "two-project" mental model drift.
  dom.projectSelect.disabled = hasActive;
  // Also de-emphasize it visually when a canonical project_id is active.
  dom.projectSelect.style.opacity = hasActive ? "0.55" : "";
  dom.projectSelect.title = hasActive
    ? (es ? "Root manual está deshabilitado mientras haya un proyecto activo. Cambia el proyecto usando el selector de proyecto activo." : "Manual root is disabled while an active project exists. Switch projects using the active project selector.")
    : (es ? "Root manual (fallback): úsalo solo si no hay proyecto activo." : "Manual root (fallback): use only when no active project is selected.");
}

function persistUiToggle(key, value) {
  try {
    localStorage.setItem(key, value ? "1" : "0");
  } catch {}
}

function isEphemeralProjectRecord(project) {
  const id = String(project?.project_id || "").trim();
  const rootPath = String(project?.root_path || "").trim();
  return (
    rootPath.startsWith("/tmp/pytest-")
    || rootPath.includes("/tmp/pytest-of-")
    || (id.startsWith("proj_") && rootPath.startsWith("/tmp/"))
  );
}

function getProjectRecordCounts() {
  const records = Array.isArray(state.projectRecords) ? state.projectRecords : [];
  let hiddenTemp = 0;
  let visible = 0;
  records.forEach((project) => {
    const id = String(project?.project_id || "").trim();
    const hiddenByTemp = !state.showTempProjects && isEphemeralProjectRecord(project) && id !== String(state.activeProjectId || "");
    if (hiddenByTemp) hiddenTemp += 1;
    else visible += 1;
  });
  return {
    total: records.length,
    visible,
    hiddenTemp,
  };
}

function getVisibleProjectRecords() {
  const records = Array.isArray(state.projectRecords) ? state.projectRecords : [];
  return records.filter((project) => {
    const id = String(project?.project_id || "").trim();
    if (id === String(state.activeProjectId || "")) return true;
    if (state.showTempProjects) return true;
    return !isEphemeralProjectRecord(project);
  });
}

function updateProjectListVisibility() {
  if (!dom.projectList) return;
  dom.projectList.hidden = !state.showProjectList;
}

function toggleProjectListVisibility() {
  state.showProjectList = !state.showProjectList;
  persistUiToggle("aegis_show_project_list", state.showProjectList);
  renderProjectMeta();
  renderProjectList();
}

function toggleProjectAdvancedVisibility() {
  state.showProjectAdvanced = !state.showProjectAdvanced;
  persistUiToggle("aegis_show_project_advanced", state.showProjectAdvanced);
  renderProjectMeta();
}

function toggleTempProjectsVisibility() {
  state.showTempProjects = !state.showTempProjects;
  persistUiToggle("aegis_show_temp_projects", state.showTempProjects);
  renderProjectMeta();
  renderProjectList();
}

function getLatestProjectJob(projectId = String(state.activeProjectId || "")) {
  const jobs = Array.isArray(state.lastSnapshot?.snapshot?.jobs) ? state.lastSnapshot.snapshot.jobs : [];
  const target = String(projectId || "").trim();
  const matching = jobs.filter((job) => {
    const metaProjectId = String(job?.meta?.project_id || job?.result?.project_id || "").trim();
    if (!target) return true;
    return metaProjectId === target;
  });
  const pool = matching.length ? matching : jobs;
  return pool
    .slice()
    .sort((a, b) => Number(b?.updated_at || b?.created_at || 0) - Number(a?.updated_at || a?.created_at || 0))[0] || null;
}

function getWebRotationPreview(es = state.lang === LANG.ES) {
  const readyz = state.lastReadyz && typeof state.lastReadyz === "object"
    ? state.lastReadyz
    : (state.lastSnapshot?.readyz && typeof state.lastSnapshot.readyz === "object" ? state.lastSnapshot.readyz : {});
  const web = readyz?.web_search && typeof readyz.web_search === "object"
    ? readyz.web_search
    : (state.lastSnapshot?.snapshot?.web_search && typeof state.lastSnapshot.snapshot.web_search === "object" ? state.lastSnapshot.snapshot.web_search : {});
  const order = Array.isArray(web?.effective_provider_order) ? web.effective_provider_order.map((item) => String(item || "").trim()).filter(Boolean) : [];
  const mode = String(web?.rotation_mode || "auto").trim();
  const lastProvider = String(state.lastChatContext?.web_provider || "").trim();
  const summary = getWebProviderSummary(web, es);
  return {
    mode,
    order,
    orderText: order.length ? order.slice(0, 4).join(" → ") : (es ? "sin orden expuesto" : "no exposed order"),
    lastProvider,
    summary,
  };
}

function openRelevantProjectLog() {
  const latestJob = getLatestProjectJob();
  if (!state.logJobId && !state.ingestJobId && latestJob?.id) {
    state.logJobId = String(latestJob.id);
    state.logIsAdmin = false;
    state.logPath = null;
  }
  const jobId = state.ingestJobId || state.logJobId;
  if (!jobId && !state.logPath) {
    appendBubble(
      state.lang === LANG.ES ? "No hay log activo para abrir todavía." : "There is no active log to open yet.",
      "error"
    );
    return;
  }
  if (dom.logsLiveToggle) dom.logsLiveToggle.checked = true;
  startLogsPolling();
  dom.filesLogContent?.scrollIntoView({ behavior: "smooth", block: "center" });
}

function getRuntimeCapabilityItems() {
  const snap = state.lastSnapshot?.snapshot || null;
  if (!snap || typeof snap !== "object") return [];
  const readyz = state.lastSnapshot?.readyz || {};
  const checks = readyz?.checks || {};
  const levels = readyz?.levels || snap?.levels || {};
  const projectTools = snap?.project_tools || {};
  const image = snap?.image || {};
  const web = snap?.web_search || {};
  const llm = snap?.llm || {};
  const clamav = snap?.clamav || {};
  const browserRuntime = snap?.browser_runtime || {};
  const webSummary = getWebProviderSummary(web, false);
  return [
    { label: "LLM", value: llm.status || "unknown", ok: !!checks.llm, level: levels.llm || llm.status || "unknown" },
    { label: "Web", value: `${web.status || "unknown"}${webSummary.configured ? ` • ${webSummary.ready}/${webSummary.available}/${webSummary.configured}` : ""}`, ok: !!checks.web_search, level: levels.web_search || web.status || "unknown" },
    { label: "Image", value: image.status || "unknown", ok: !!checks.image_backend, level: levels.image || image.status || "unknown" },
    { label: "Browser", value: browserRuntime.status || "unknown", ok: !!checks.browser_runtime, level: levels.browser_runtime || browserRuntime.status || "unknown" },
    { label: "ClamAV", value: clamav.status || "unknown", ok: !!checks.clamav, level: levels.clamav || clamav.status || "unknown" },
    { label: "Projects", value: String(projectTools.registered_projects ?? 0), ok: !!checks.project_tools, level: levels.project_tools || projectTools.status || "unknown" },
  ];
}

function capabilityChipClass(item) {
  const level = String(item?.level || "").toLowerCase();
  if (level === "error") return "danger";
  if (level === "degraded" || level === "fallback-only" || level === "missing" || level === "cooldown") return "warn";
  return "";
}

function getValidationItems() {
  const snap = state.lastSnapshot?.snapshot || null;
  const validation = snap?.validation || state.lastSnapshot?.readyz?.validation || null;
  if (!validation || typeof validation !== "object") return null;
  return {
    startupGate: Array.isArray(validation.startup_gate) ? validation.startup_gate : [],
    verifyFull: Array.isArray(validation.verify_full) ? validation.verify_full : [],
    browserSmokeDefault: !!validation.browser_smoke_default,
    browserSmokeStrictDefault: !!validation.browser_smoke_strict_default,
    contractModeDefault: String(validation.contract_mode_default || "full"),
    lastRuns: validation.last_runs && typeof validation.last_runs === "object" ? validation.last_runs : {},
    lastUpdatedMs: Number(validation.last_updated_ms || 0),
    scripts: validation.scripts && typeof validation.scripts === "object" ? validation.scripts : {},
  };
}

function validationFlowStatus(flow) {
  const value = String(flow?.status || "").toLowerCase();
  if (value === "passed") return "success";
  if (value === "failed") return "danger";
  if (value === "running") return "warn";
  if (value === "skipped") return "neutral";
  return "neutral";
}

function plannerStopReason(context) {
  if (!context || typeof context !== "object") return "";
  const flat = String(context.stop_reason || "").trim();
  if (flat) return flat;
  const loop = context.planner_loop && typeof context.planner_loop === "object" ? context.planner_loop : null;
  return String(loop?.stop_reason || "").trim();
}

function plannerLoopMetrics(context) {
  if (!context || typeof context !== "object") return {};
  const loop = context.planner_loop && typeof context.planner_loop === "object" ? context.planner_loop : {};
  const asNum = (v) => {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  };
  return {
    iterationsCompleted: asNum(context.iterations_completed ?? loop.iterations_completed),
    totalToolCalls: asNum(context.total_tool_calls ?? loop.total_tool_calls),
    maxIterations: asNum(loop.max_iterations),
    maxTotalToolCalls: asNum(loop.max_total_tool_calls),
    budgetExhausted: Boolean(context.budget_exhausted ?? loop.budget_exhausted),
  };
}

function renderProjectMeta() {
  if (!dom.projectMeta) return;
  const es = state.lang === LANG.ES;
  const detail = state.activeProjectDetail;
  const capabilityItems = getRuntimeCapabilityItems();
  const validationItems = getValidationItems();
  const context = state.lastChatContext && typeof state.lastChatContext === "object" ? state.lastChatContext : null;
  const projectCounts = getProjectRecordCounts();
  dom.projectMeta.innerHTML = "";

  const buildProjectControls = () => {
    const latestJob = getLatestProjectJob();
    const logLabel = state.ingestJobId
      ? (es ? `Log activo: ${String(state.ingestJobId).slice(0, 8)}` : `Active log: ${String(state.ingestJobId).slice(0, 8)}`)
      : state.logJobId
        ? (es ? `Log seleccionado: ${String(state.logJobId).slice(0, 8)}` : `Selected log: ${String(state.logJobId).slice(0, 8)}`)
        : latestJob?.id
          ? (es ? `Último log: ${String(latestJob.id).slice(0, 8)}` : `Last log: ${String(latestJob.id).slice(0, 8)}`)
          : (es ? "Sin log activo" : "No active log");
    const bar = el("div", { class: "project-panel-toolbar" });

    const logBtn = el("button", {
      class: "action-btn",
      text: logLabel,
      attrs: { type: "button", title: es ? "Abrir log de trabajo actual" : "Open current work log" },
    });
    logBtn.addEventListener("click", openRelevantProjectLog);
    bar.appendChild(logBtn);

    const listBtn = el("button", {
      class: `action-btn ${state.showProjectList ? "active" : ""}`.trim(),
      text: state.showProjectList
        ? (es ? `Ocultar proyectos (${projectCounts.visible}/${projectCounts.total})` : `Hide projects (${projectCounts.visible}/${projectCounts.total})`)
        : (es ? `Proyectos (${projectCounts.visible}/${projectCounts.total})` : `Projects (${projectCounts.visible}/${projectCounts.total})`),
      attrs: { type: "button" },
    });
    listBtn.addEventListener("click", toggleProjectListVisibility);
    bar.appendChild(listBtn);

    if (projectCounts.hiddenTemp || state.showTempProjects) {
      const tempBtn = el("button", {
        class: `action-btn ${state.showTempProjects ? "active" : ""}`.trim(),
        text: state.showTempProjects
          ? (es ? "Ocultar temporales" : "Hide temp")
          : (es ? `Mostrar temporales (${projectCounts.hiddenTemp})` : `Show temp (${projectCounts.hiddenTemp})`),
        attrs: { type: "button" },
      });
      tempBtn.addEventListener("click", toggleTempProjectsVisibility);
      bar.appendChild(tempBtn);
    }

    const advancedBtn = el("button", {
      class: `action-btn ${state.showProjectAdvanced ? "active" : ""}`.trim(),
      text: state.showProjectAdvanced
        ? (es ? "Ocultar paneles" : "Hide panels")
        : (es ? "Más paneles" : "More panels"),
      attrs: { type: "button" },
    });
    advancedBtn.addEventListener("click", toggleProjectAdvancedVisibility);
    bar.appendChild(advancedBtn);
    return bar;
  };

  const buildProjectActivityCard = () => {
    const latestJob = getLatestProjectJob();
    const webRotation = getWebRotationPreview(es);
    const card = el("div", { class: "project-meta-card project-activity-card" });
    card.appendChild(el("strong", { text: es ? "Actividad / runtime" : "Activity / runtime" }));
    const chips = el("div", { class: "mini-list" });

    const logSource = state.ingestJobId || state.logJobId || latestJob?.id || "";
    chips.appendChild(
      el("span", {
        class: `mini-chip ${logSource ? "" : "warn"}`.trim(),
        text: logSource
          ? `${es ? "Log" : "Log"}: ${String(logSource).slice(0, 12)}`
          : `${es ? "Log" : "Log"}: ${es ? "ninguno" : "none"}`,
      })
    );

    if (latestJob?.status) {
      chips.appendChild(
        el("span", {
          class: `mini-chip ${String(latestJob.status).toLowerCase() === "failed" ? "danger" : String(latestJob.status).toLowerCase() === "running" ? "warn" : ""}`.trim(),
          text: `${es ? "Job" : "Job"}: ${latestJob.kind || "ingest"} • ${latestJob.status}`,
        })
      );
    }
    chips.appendChild(
      el("span", {
        class: "mini-chip",
        text: `${es ? "Rotación web" : "Web rotation"}: ${webRotation.mode || "auto"}`,
      })
    );
    chips.appendChild(
      el("span", {
        class: "mini-chip",
        text: `${es ? "Providers" : "Providers"}: ${webRotation.summary.ready}/${webRotation.summary.available}/${webRotation.summary.configured}`,
      })
    );
    if (webRotation.lastProvider) {
      chips.appendChild(
        el("span", {
          class: "mini-chip",
          text: `${es ? "Último provider" : "Last provider"}: ${webRotation.lastProvider}`,
        })
      );
    }
    card.appendChild(chips);

    card.appendChild(
      el("div", {
        class: "project-summary-text subtle",
        text: `${es ? "Orden efectivo" : "Effective order"}: ${webRotation.orderText}`,
      })
    );
    if (webRotation.summary.reasons.length) {
      card.appendChild(
        el("div", {
          class: "project-summary-text",
          text: `${es ? "No disponibles" : "Unavailable"}: ${webRotation.summary.reasons.slice(0, 2).join(" | ")}`,
        })
      );
    }
    if (latestJob?.meta?.stages?.length) {
      const lastStage = latestJob.meta.stages[latestJob.meta.stages.length - 1];
      card.appendChild(
        el("div", {
          class: "project-summary-text",
          text: `${es ? "Etapa" : "Stage"}: ${lastStage?.name || "—"}${lastStage?.status ? ` (${lastStage.status})` : ""}`,
        })
      );
    }

    const actions = el("div", { class: "mini-actions" });
    const openLogBtn = el("button", {
      class: "action-btn",
      text: es ? "Abrir log" : "Open log",
      attrs: { type: "button" },
    });
    openLogBtn.addEventListener("click", openRelevantProjectLog);
    actions.appendChild(openLogBtn);

    const jobsBtn = el("button", {
      class: "action-btn",
      text: es ? "Ir a trabajos" : "Go to jobs",
      attrs: { type: "button" },
    });
    jobsBtn.addEventListener("click", () => {
      dom.ingestJobsList?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
    actions.appendChild(jobsBtn);
    card.appendChild(actions);
    return card;
  };

  dom.projectMeta.appendChild(buildProjectControls());

  const buildPlannerCard = () => {
    if (!context) return null;
    const stopReason = plannerStopReason(context);
    const loopMetrics = plannerLoopMetrics(context);
    const hasPlannerData = Boolean(
      context.source_plan
      || (Array.isArray(context.source_origin) && context.source_origin.length)
      || context.current_task
      || context.current_subtask
      || context.next_step
      || context.next_tool
      || context.current_file_focus
      || context.current_symbol_focus
      || context.current_artifact_focus
      || (Array.isArray(context.web_findings) && context.web_findings.length)
      || (Array.isArray(context.recent_tool_failures) && context.recent_tool_failures.length)
      || (Array.isArray(context.missing_evidence) && context.missing_evidence.length)
      || (Array.isArray(context.tool_candidates) && context.tool_candidates.length)
      || stopReason
      || loopMetrics.iterationsCompleted != null
      || loopMetrics.totalToolCalls != null
    );
    if (!hasPlannerData) return null;

    const card = el("div", { class: "project-meta-card" });
    card.appendChild(el("strong", { text: es ? "Plan actual" : "Current plan" }));
    const list = el("div", { class: "mini-list" });
    if (context.source_plan) {
      list.appendChild(el("span", { class: "mini-chip", text: `${es ? "Plan de fuente" : "Source plan"}: ${prettySourcePlan(context.source_plan)}` }));
    }
    if (context.current_task) list.appendChild(el("span", { class: "mini-chip", text: `${es ? "Tarea" : "Task"}: ${context.current_task}` }));
    if (context.current_subtask) list.appendChild(el("span", { class: "mini-chip", text: `${es ? "Subtarea" : "Subtask"}: ${context.current_subtask}` }));
    if (context.current_file_focus) list.appendChild(el("span", { class: "mini-chip", text: `${es ? "Archivo" : "File"}: ${context.current_file_focus}` }));
    if (context.current_symbol_focus) list.appendChild(el("span", { class: "mini-chip", text: `${es ? "Símbolo" : "Symbol"}: ${context.current_symbol_focus}` }));
    if (context.current_artifact_focus) list.appendChild(el("span", { class: "mini-chip", text: `${es ? "Artefacto" : "Artifact"}: ${context.current_artifact_focus}` }));
    if (context.next_tool) list.appendChild(el("span", { class: "mini-chip", text: `${es ? "Tool" : "Tool"}: ${context.next_tool}` }));
    if (stopReason) list.appendChild(el("span", { class: "mini-chip subtle", text: `${es ? "Stop" : "Stop"}: ${stopReason}` }));
    if (loopMetrics.iterationsCompleted != null) {
      const maxIt = loopMetrics.maxIterations != null ? `/${loopMetrics.maxIterations}` : "";
      list.appendChild(
        el("span", { class: "mini-chip subtle", text: `${es ? "Iteraciones" : "Iterations"}: ${loopMetrics.iterationsCompleted}${maxIt}` })
      );
    }
    if (loopMetrics.totalToolCalls != null) {
      const maxTools = loopMetrics.maxTotalToolCalls != null ? `/${loopMetrics.maxTotalToolCalls}` : "";
      list.appendChild(
        el("span", { class: "mini-chip subtle", text: `${es ? "Tools" : "Tools"}: ${loopMetrics.totalToolCalls}${maxTools}` })
      );
    }
    if (loopMetrics.budgetExhausted) {
      list.appendChild(el("span", { class: "mini-chip warn", text: es ? "Presupuesto agotado" : "Budget exhausted" }));
    }
    if (context.llm_required === false) {
      list.appendChild(el("span", { class: "mini-chip", text: "LLM: bypassed" }));
    } else if (context.llm_required === true) {
      list.appendChild(el("span", { class: "mini-chip", text: "LLM: required" }));
    }
    const candidates = Array.isArray(context.tool_candidates) ? context.tool_candidates : [];
    if (candidates.length) {
      list.appendChild(el("span", { class: "mini-chip", text: `${es ? "Candidatas" : "Candidates"}: ${candidates.slice(0, 3).join(", ")}` }));
    }
    const toolRisks = context.tool_risks && typeof context.tool_risks === "object" ? context.tool_risks : null;
    if (toolRisks) {
      const pairs = Object.entries(toolRisks)
        .map(([k, v]) => `${k}:${String(v || "")}`)
        .filter(Boolean)
        .slice(0, 3);
      if (pairs.length) {
        list.appendChild(el("span", { class: "mini-chip subtle", text: `${es ? "Riesgo" : "Risk"}: ${pairs.join(", ")}` }));
      }
    }
    const approvals = Array.isArray(context.approval_required) ? context.approval_required : [];
    if (approvals.length) {
      list.appendChild(el("span", { class: "mini-chip warn", text: `${es ? "Requiere approval" : "Approval required"}: ${approvals.slice(0, 3).join(", ")}` }));
    }
    const pending = context.pending_approval && typeof context.pending_approval === "object" ? context.pending_approval : null;
    if (pending && pending.tool) {
      list.appendChild(el("span", { class: "mini-chip warn", text: `${es ? "Approval pendiente" : "Pending approval"}: ${pending.tool}` }));
    }
    card.appendChild(list);
    const origins = Array.isArray(context.source_origin) ? context.source_origin : [];
    if (origins.length) {
      card.appendChild(el("div", { class: "project-summary-text subtle", text: `${es ? "Origen usado" : "Origin used"}: ${origins.map(prettyOriginLabel).join(", ")}` }));
    }
    if (context.next_step) {
      card.appendChild(el("div", { class: "project-summary-text", text: `${es ? "Siguiente paso" : "Next step"}: ${context.next_step}` }));
    }
    if (Array.isArray(context.missing_evidence) && context.missing_evidence.length) {
      card.appendChild(
        el("div", {
          class: "project-summary-text",
          text: `${es ? "Falta evidencia" : "Missing evidence"}: ${context.missing_evidence.join(", ")}`,
        })
      );
    }
    if (Array.isArray(context.web_findings) && context.web_findings.length) {
      card.appendChild(
        el("div", {
          class: "project-summary-text subtle",
          text: `${es ? "Hallazgos web" : "Web findings"}: ${context.web_findings.slice(0, 3).join(" • ")}`,
        })
      );
    }
    if (Array.isArray(context.recent_tool_failures) && context.recent_tool_failures.length) {
      const recent = context.recent_tool_failures
        .slice(-2)
        .map((item) => String(item || "").trim())
        .filter(Boolean);
      if (recent.length) {
        card.appendChild(
          el("div", {
            class: "project-summary-text subtle danger",
            text: `${es ? "Fallos recientes" : "Recent failures"}: ${recent.join(" | ")}`,
          })
        );
      }
    }

    if (candidates.length) {
      const actions = el("div", { class: "mini-list" });
      candidates.slice(0, 5).forEach((toolName) => {
        const name = String(toolName || "").trim();
        if (!name) return;
        const btn = el("button", { class: "icon-btn small", text: `▶ ${name}`, attrs: { type: "button" } });
        btn.addEventListener("click", () => runProjectQuickTool(name, context));
        actions.appendChild(btn);
      });
      card.appendChild(actions);
    }

    const action = buildPlannerAction(context);
    if (action) {
      const actions = el("div", { class: "mini-list" });
      const btn = el("button", { class: "icon-btn small", text: action.label, attrs: { type: "button" } });
      btn.addEventListener("click", action.run);
      actions.appendChild(btn);
      card.appendChild(actions);
    }
    return card;
  };

  if (!state.activeProjectId || !detail) {
    const manualRoot = String(state.manualProjectRoot || "").trim();
    const wrap = el("div", { class: "project-meta-grid" });
    const infoCard = el("div", { class: "project-meta-card" });
    infoCard.appendChild(el("strong", { text: es ? "Contexto local" : "Local context" }));
    infoCard.appendChild(
      el("div", {
        class: "project-summary-text",
        text: manualRoot
          ? (es
              ? `Root manual activo: ${manualRoot}. Registra o activa un proyecto para ver resumen, entrypoints, dependencias y configs.`
              : `Manual root active: ${manualRoot}. Register or activate a project to view summary, entrypoints, dependencies, and configs.`)
          : (es
              ? "Selecciona un proyecto activo o un root manual para empezar."
              : "Select an active project or a manual root to begin."),
      })
    );
    wrap.appendChild(infoCard);
    wrap.appendChild(buildProjectActivityCard());
    if (state.showProjectAdvanced && capabilityItems.length) {
      const capCard = el("div", { class: "project-meta-card" });
      capCard.appendChild(el("strong", { text: es ? "Capabilities" : "Capabilities" }));
      const list = el("div", { class: "mini-list" });
      capabilityItems.forEach((item) => {
        list.appendChild(el("span", { class: `mini-chip ${capabilityChipClass(item) || (!item.ok ? "warn" : "")}`, text: `${item.label}: ${item.value}` }));
      });
      capCard.appendChild(list);
      wrap.appendChild(capCard);
    }
    if (state.showProjectAdvanced && validationItems) {
      const validationCard = el("div", { class: "project-meta-card" });
      validationCard.appendChild(el("strong", { text: es ? "Validación" : "Validation" }));
      const list = el("div", { class: "mini-list" });
      list.appendChild(
        el("span", {
          class: `mini-chip ${validationItems.browserSmokeStrictDefault ? "" : "warn"}`,
          text: `${es ? "Browser gate" : "Browser gate"}: ${validationItems.browserSmokeStrictDefault ? "strict" : "soft"}`,
        })
      );
      list.appendChild(
        el("span", {
          class: `mini-chip ${validationItems.contractModeDefault === "full" ? "" : "warn"}`,
          text: `${es ? "Contrato startup" : "Startup contract"}: ${validationItems.contractModeDefault}`,
        })
      );
      if (validationItems.startupGate.length) {
        list.appendChild(el("span", { class: "mini-chip", text: `${es ? "Startup" : "Startup"}: ${validationItems.startupGate.join(" → ")}` }));
      }
      if (validationItems.verifyFull.length) {
        list.appendChild(el("span", { class: "mini-chip", text: `verify_full: ${validationItems.verifyFull.join(" → ")}` }));
      }
      const startupRun = validationItems.lastRuns?.startup_gate || null;
      const verifyRun = validationItems.lastRuns?.verify_full || null;
      if (startupRun?.status) {
        list.appendChild(el("span", { class: `mini-chip ${validationFlowStatus(startupRun)}`, text: `${es ? "Último startup" : "Last startup"}: ${startupRun.status}` }));
      }
      if (verifyRun?.status) {
        list.appendChild(el("span", { class: `mini-chip ${validationFlowStatus(verifyRun)}`, text: `verify_full: ${verifyRun.status}` }));
      }
      validationCard.appendChild(list);
      if (validationItems.lastUpdatedMs) {
        validationCard.appendChild(
          el("div", {
            class: "project-summary-text",
            text: `${es ? "Última validación" : "Last validation"}: ${formatAgo(validationItems.lastUpdatedMs)}`,
          })
        );
      }
      wrap.appendChild(validationCard);
    }
    const plannerCard = buildPlannerCard();
    if (plannerCard) wrap.appendChild(plannerCard);
    dom.projectMeta.appendChild(wrap);
    return;
  }

  const summaryText = detail.summary || detail.context?.project_summary || "—";
  const grid = el("div", { class: "project-meta-grid" });

  const summaryCard = el("div", { class: "project-meta-card" });
  summaryCard.appendChild(el("strong", { text: es ? "Resumen" : "Summary" }));
  summaryCard.appendChild(el("div", { class: "project-summary-text", text: summaryText }));
  const projectStatus = String(detail?.project_status || detail?.project?.status || "").trim().toLowerCase();
  if (projectStatus && !["ingested", "ready", "indexed"].includes(projectStatus)) {
    summaryCard.appendChild(
      el("div", {
        class: "project-summary-text subtle",
        text: es
          ? `Estado del proyecto: ${projectStatus}. Ejecuta ingest para habilitar entrypoints/dependencias/configs.`
          : `Project status: ${projectStatus}. Run ingest to enable entrypoints/dependencies/configs.`,
      })
    );
  }
  grid.appendChild(summaryCard);
  grid.appendChild(buildProjectActivityCard());

  const ideaRows = Array.isArray(detail.ideas) ? detail.ideas : [];
  if (state.showProjectAdvanced && ideaRows.length) {
    const ideasCard = el("div", { class: "project-meta-card" });
    ideasCard.appendChild(el("strong", { text: es ? "Ideas de mejora" : "Improvement ideas" }));
    ideaRows.slice(0, 6).forEach((item) => {
      if (!item || typeof item !== "object") return;
      const priority = String(item.priority || "").trim().toUpperCase();
      const title = String(item.title || "").trim();
      const detailText = String(item.detail || "").trim();
      const row = el("div", { class: "project-idea-row" });
      const text = el("div", { class: "project-summary-text" });
      text.textContent = [priority ? `[${priority}]` : "", title, detailText].filter(Boolean).join(" ");
      row.appendChild(text);
      if (isIdeaStarterSupported(item)) {
        const applyBtn = el("button", {
          class: "action-btn",
          text: es ? "Aplicar" : "Apply",
          attrs: { type: "button" },
        });
        applyBtn.addEventListener("click", () => {
          void applyProjectIdeaStarter(item.id);
        });
        row.appendChild(applyBtn);
      }
      ideasCard.appendChild(row);
    });
    grid.appendChild(ideasCard);
  }

  const intelligence = detail.intelligence && typeof detail.intelligence === "object" ? detail.intelligence : null;
  if (state.showProjectAdvanced && intelligence) {
    const intelligenceCard = el("div", { class: "project-meta-card" });
    intelligenceCard.appendChild(el("strong", { text: es ? "Inteligencia del proyecto" : "Project intelligence" }));
    const list = el("div", { class: "mini-list" });
    list.appendChild(
      el("span", {
        class: "mini-chip",
        text: `${es ? "Archivos" : "Files"}: ${Number(intelligence.files_scanned || 0)}`,
      })
    );
    list.appendChild(
      el("span", {
        class: "mini-chip",
        text: `${es ? "Relaciones" : "Links"}: ${Number(intelligence.internal_edge_count || 0)}`,
      })
    );
    list.appendChild(
      el("span", {
        class: "mini-chip",
        text: `${es ? "Hotspots" : "Hotspots"}: ${Array.isArray(intelligence.hotspots) ? intelligence.hotspots.length : 0}`,
      })
    );
    list.appendChild(
      el("span", {
        class: "mini-chip",
        text: `${es ? "Rutas" : "Routes"}: ${Number(intelligence.route_count || 0)}`,
      })
    );
    if (Array.isArray(intelligence.mutual_edges) && intelligence.mutual_edges.length) {
      list.appendChild(
        el("span", {
          class: "mini-chip warn",
          text: `${es ? "Ciclos simples" : "Simple cycles"}: ${intelligence.mutual_edges.length}`,
        })
      );
    }
    if (Array.isArray(intelligence.shared_symbol_clusters) && intelligence.shared_symbol_clusters.length) {
      list.appendChild(
        el("span", {
          class: "mini-chip",
          text: `${es ? "Símbolos repetidos" : "Shared symbols"}: ${intelligence.shared_symbol_clusters.length}`,
        })
      );
    }
    intelligenceCard.appendChild(list);

    const hotspotRows = Array.isArray(intelligence.hotspots) ? intelligence.hotspots.slice(0, 4) : [];
    if (hotspotRows.length) {
      intelligenceCard.appendChild(
        el("div", {
          class: "project-summary-text subtle",
          text: es ? "Archivos más conectados" : "Most connected files",
        })
      );
      const hotspotList = el("div", { class: "mini-list" });
      hotspotRows.forEach((item) => {
        hotspotList.appendChild(
          el("span", {
            class: "mini-chip",
            text: `${item.path} (${es ? "in" : "in"}:${Number(item.inbound_refs || 0)} ${es ? "out" : "out"}:${Number(item.outbound_refs || 0)})`,
          })
        );
      });
      intelligenceCard.appendChild(hotspotList);
    }

    const clusterRows = Array.isArray(intelligence.shared_symbol_clusters) ? intelligence.shared_symbol_clusters.slice(0, 3) : [];
    if (clusterRows.length) {
      intelligenceCard.appendChild(
        el("div", {
          class: "project-summary-text subtle",
          text: es ? "Símbolos compartidos que merecen revisión" : "Shared symbols worth reviewing",
        })
      );
      const clusterList = el("div", { class: "mini-list" });
      clusterRows.forEach((item) => {
        clusterList.appendChild(
          el("span", {
            class: "mini-chip subtle",
            text: `${item.symbol} (${Number(item.count || 0)})`,
          })
        );
      });
      intelligenceCard.appendChild(clusterList);
    }

    const symbolHotspots = Array.isArray(intelligence.symbol_hotspots) ? intelligence.symbol_hotspots.slice(0, 3) : [];
    if (symbolHotspots.length) {
      intelligenceCard.appendChild(
        el("div", {
          class: "project-summary-text subtle",
          text: es ? "Símbolos con mayor alcance" : "Highest-reach symbols",
        })
      );
      const symbolList = el("div", { class: "mini-list" });
      symbolHotspots.forEach((item) => {
        symbolList.appendChild(
          el("span", {
            class: "mini-chip",
            text: `${item.symbol} (${es ? "refs" : "refs"}:${Number(item.reference_count || 0)})`,
          })
        );
      });
      intelligenceCard.appendChild(symbolList);
    }

    const publicApiSymbols = Array.isArray(intelligence.public_api_symbols) ? intelligence.public_api_symbols.slice(0, 3) : [];
    if (publicApiSymbols.length) {
      intelligenceCard.appendChild(
        el("div", {
          class: "project-summary-text subtle",
          text: es ? "Superficie pública detectada" : "Detected public surface",
        })
      );
      const publicApiList = el("div", { class: "mini-list" });
      publicApiSymbols.forEach((item) => {
        publicApiList.appendChild(
          el("span", {
            class: "mini-chip",
            text: `${item.symbol}@${item.path} [${(item.reasons || []).join("/")}]`,
          })
        );
      });
      intelligenceCard.appendChild(publicApiList);
    }

    const symbolCallHotspots = Array.isArray(intelligence.symbol_call_hotspots) ? intelligence.symbol_call_hotspots.slice(0, 3) : [];
    if (symbolCallHotspots.length) {
      intelligenceCard.appendChild(
        el("div", {
          class: "project-summary-text subtle",
          text: es ? "Símbolos con llamadas detectadas" : "Symbols with detected calls",
        })
      );
      const callList = el("div", { class: "mini-list" });
      symbolCallHotspots.forEach((item) => {
        callList.appendChild(
          el("span", {
            class: "mini-chip",
            text: `${item.symbol} (${es ? "calls" : "calls"}:${Number(item.call_edge_count || 0)})`,
          })
        );
      });
      intelligenceCard.appendChild(callList);
    }

    const routeHotspots = Array.isArray(intelligence.route_hotspots) ? intelligence.route_hotspots.slice(0, 3) : [];
    if (routeHotspots.length) {
      intelligenceCard.appendChild(
        el("div", {
          class: "project-summary-text subtle",
          text: es ? "Superficie API detectada" : "Detected API surface",
        })
      );
      const routeList = el("div", { class: "mini-list" });
      routeHotspots.forEach((item) => {
        const routePreview = Array.isArray(item.routes)
          ? item.routes.slice(0, 2).map((row) => `${row.method} ${row.resolved_route || row.route}`).join(", ")
          : "";
        routeList.appendChild(
          el("span", {
            class: "mini-chip",
            text: `${item.path} (${Number(item.route_count || 0)})${routePreview ? ` - ${routePreview}` : ""}`,
          })
        );
      });
      intelligenceCard.appendChild(routeList);
    }

    const runtimeSurfaceHotspots = Array.isArray(intelligence.runtime_surface_hotspots) ? intelligence.runtime_surface_hotspots.slice(0, 3) : [];
    if (runtimeSurfaceHotspots.length) {
      intelligenceCard.appendChild(
        el("div", {
          class: "project-summary-text subtle",
          text: es ? "Superficies runtime detectadas" : "Detected runtime surfaces",
        })
      );
      const runtimeList = el("div", { class: "mini-list" });
      runtimeSurfaceHotspots.forEach((item) => {
        const appNames = Array.isArray(item.apps) ? item.apps.map((app) => app.app_name).filter(Boolean).join(", ") : "";
        runtimeList.appendChild(
          el("span", {
            class: "mini-chip",
            text: `${item.path}${appNames ? `#${appNames}` : ""} (${Number(item.served_route_count || 0)})`,
          })
        );
      });
      intelligenceCard.appendChild(runtimeList);
    }

    const envVarHotspots = Array.isArray(intelligence.env_var_hotspots) ? intelligence.env_var_hotspots.slice(0, 3) : [];
    if (envVarHotspots.length) {
      intelligenceCard.appendChild(
        el("div", {
          class: "project-summary-text subtle",
          text: es ? "Contrato de entorno detectado" : "Detected environment contract",
        })
      );
      const envList = el("div", { class: "mini-list" });
      envVarHotspots.forEach((item) => {
        envList.appendChild(
          el("span", {
            class: "mini-chip",
            text: `${item.env} (${es ? "files" : "files"}:${Number(item.file_count || 0)})`,
          })
        );
      });
      intelligenceCard.appendChild(envList);
    }

    const duplicateLogicClusters = Array.isArray(intelligence.duplicate_logic_clusters) ? intelligence.duplicate_logic_clusters.slice(0, 3) : [];
    if (duplicateLogicClusters.length) {
      intelligenceCard.appendChild(
        el("div", {
          class: "project-summary-text subtle",
          text: es ? "Lógica duplicada detectada" : "Detected duplicate logic",
        })
      );
      const duplicateList = el("div", { class: "mini-list" });
      duplicateLogicClusters.forEach((item) => {
        duplicateList.appendChild(
          el("span", {
            class: "mini-chip warn",
            text: `${(item.symbols || []).join("/") || item.fingerprint} (${Number(item.path_count || 0)})`,
          })
        );
      });
      intelligenceCard.appendChild(duplicateList);
    }

    const refactorRows = Array.isArray(intelligence.refactor_candidates) ? intelligence.refactor_candidates.slice(0, 3) : [];
    if (refactorRows.length) {
      intelligenceCard.appendChild(
        el("div", {
          class: "project-summary-text subtle",
          text: es ? "Candidatas de refactor" : "Refactor candidates",
        })
      );
      const refactorList = el("div", { class: "mini-list" });
      refactorRows.forEach((item) => {
        refactorList.appendChild(
          el("span", {
            class: "mini-chip warn",
            text: `${item.symbol} (${es ? "defs" : "defs"}:${Number(item.definition_count || 0)} ${es ? "refs" : "refs"}:${Number(item.reference_count || 0)})`,
          })
        );
      });
      intelligenceCard.appendChild(refactorList);
    }

    const isolatedSymbols = Array.isArray(intelligence.isolated_symbol_candidates) ? intelligence.isolated_symbol_candidates.slice(0, 3) : [];
    if (isolatedSymbols.length) {
      intelligenceCard.appendChild(
        el("div", {
          class: "project-summary-text subtle",
          text: es ? "Símbolos aislados" : "Isolated symbols",
        })
      );
      const isolatedList = el("div", { class: "mini-list" });
      isolatedSymbols.forEach((item) => {
        isolatedList.appendChild(
          el("span", {
            class: "mini-chip subtle",
            text: `${item.symbol}@${item.path} (${item.confidence})`,
          })
        );
      });
      intelligenceCard.appendChild(isolatedList);
    }
    grid.appendChild(intelligenceCard);
  }

  const impact = state.activeProjectImpact && typeof state.activeProjectImpact === "object" ? state.activeProjectImpact : null;
  if (state.showProjectAdvanced && impact && String(impact.query || "").trim()) {
    const impactCard = el("div", { class: "project-meta-card" });
    impactCard.appendChild(el("strong", { text: es ? "Impacto del foco actual" : "Current focus impact" }));
    impactCard.appendChild(
      el("div", {
        class: "project-summary-text",
        text: `${es ? "Consulta" : "Query"}: ${String(impact.query || "").trim()}`,
      })
    );
    const touched = Array.isArray(impact.likely_touched_files) ? impact.likely_touched_files.slice(0, 8) : [];
    if (touched.length) {
      const touchedList = el("div", { class: "mini-list" });
      touched.forEach((item) => touchedList.appendChild(el("span", { class: "mini-chip", text: String(item) })));
      impactCard.appendChild(touchedList);
    }
    const importedBy = Array.isArray(impact.imported_by) ? impact.imported_by : [];
    if (importedBy.length) {
      impactCard.appendChild(
        el("div", {
          class: "project-summary-text subtle",
          text: `${es ? "Consumido por" : "Imported by"}: ${importedBy.map((item) => item.path).join(", ")}`,
        })
      );
    }
    const importsTo = Array.isArray(impact.imports_to) ? impact.imports_to : [];
    if (importsTo.length) {
      impactCard.appendChild(
        el("div", {
          class: "project-summary-text subtle",
          text: `${es ? "Depende de" : "Imports"}: ${importsTo.map((item) => item.path).join(", ")}`,
        })
      );
    }
    const neighbors = Array.isArray(impact.same_symbol_neighbors) ? impact.same_symbol_neighbors : [];
    if (neighbors.length) {
      impactCard.appendChild(
        el("div", {
          class: "project-summary-text subtle",
          text: `${es ? "Símbolos relacionados" : "Related symbols"}: ${neighbors.join(", ")}`,
        })
      );
    }
    const definedIn = Array.isArray(impact.defined_in) ? impact.defined_in : [];
    if (definedIn.length) {
      impactCard.appendChild(
        el("div", {
          class: "project-summary-text subtle",
          text: `${es ? "Definido en" : "Defined in"}: ${definedIn.map((item) => `${item.path}:${item.line_start}`).join(", ")}`,
        })
      );
    }
    const referencedByFiles = Array.isArray(impact.referenced_by_files) ? impact.referenced_by_files : [];
    if (referencedByFiles.length) {
      impactCard.appendChild(
        el("div", {
          class: "project-summary-text subtle",
          text: `${es ? "Referenciado por símbolo" : "Symbol referenced by"}: ${referencedByFiles.map((item) => `${item.path} (${item.count})`).join(", ")}`,
        })
      );
    }
    const callEdgesTo = Array.isArray(impact.call_edges_to) ? impact.call_edges_to : [];
    if (callEdgesTo.length) {
      impactCard.appendChild(
        el("div", {
          class: "project-summary-text subtle",
          text: `${es ? "Llamado desde" : "Called from"}: ${callEdgesTo.map((item) => `${item.from_path} (${item.count})`).join(", ")}`,
        })
      );
    }
    const callEdgesFrom = Array.isArray(impact.call_edges_from) ? impact.call_edges_from : [];
    if (callEdgesFrom.length) {
      impactCard.appendChild(
        el("div", {
          class: "project-summary-text subtle",
          text: `${es ? "Llama a" : "Calls into"}: ${callEdgesFrom.map((item) => `${item.to_path}:${item.symbol}`).join(", ")}`,
        })
      );
    }
    const envVarsInScope = Array.isArray(impact.env_vars_in_scope) ? impact.env_vars_in_scope : [];
    if (envVarsInScope.length) {
      impactCard.appendChild(
        el("div", {
          class: "project-summary-text subtle",
          text: `${es ? "Variables de entorno" : "Environment variables"}: ${envVarsInScope.map((item) => `${item.env}@${item.path}`).join(", ")}`,
        })
      );
    }
    const routesInScope = Array.isArray(impact.routes_in_scope) ? impact.routes_in_scope : [];
    if (routesInScope.length) {
      impactCard.appendChild(
        el("div", {
          class: "project-summary-text subtle",
          text: `${es ? "Rutas en foco" : "Routes in scope"}: ${routesInScope.map((item) => `${item.method} ${item.resolved_route || item.route}@${item.path}${item.handler ? `#${item.handler}` : ""}`).join(", ")}`,
        })
      );
    }
    const runtimeSurfacesInScope = Array.isArray(impact.runtime_surfaces_in_scope) ? impact.runtime_surfaces_in_scope : [];
    if (runtimeSurfacesInScope.length) {
      impactCard.appendChild(
        el("div", {
          class: "project-summary-text subtle",
          text: `${es ? "Runtime owner" : "Runtime owner"}: ${runtimeSurfacesInScope.map((item) => `${item.path}#${item.app_name} (${Number(item.served_route_count || 0)})`).join(", ")}`,
        })
      );
    }
    const publicApiSymbolsInScope = Array.isArray(impact.public_api_symbols_in_scope) ? impact.public_api_symbols_in_scope : [];
    if (publicApiSymbolsInScope.length) {
      impactCard.appendChild(
        el("div", {
          class: "project-summary-text subtle",
          text: `${es ? "Símbolos públicos en foco" : "Public symbols in scope"}: ${publicApiSymbolsInScope.map((item) => `${item.symbol}@${item.path}[${(item.reasons || []).join("/")}]`).join(", ")}`,
        })
      );
    }
    const isolatedSymbolsInScope = Array.isArray(impact.isolated_symbols_in_scope) ? impact.isolated_symbols_in_scope : [];
    if (isolatedSymbolsInScope.length) {
      impactCard.appendChild(
        el("div", {
          class: "project-summary-text subtle",
          text: `${es ? "Símbolos aislados" : "Isolated symbols"}: ${isolatedSymbolsInScope.map((item) => `${item.symbol}@${item.path}`).join(", ")}`,
        })
      );
    }
    const refactorCandidates = Array.isArray(impact.refactor_candidates) ? impact.refactor_candidates : [];
    if (refactorCandidates.length) {
      impactCard.appendChild(
        el("div", {
          class: "project-summary-text subtle",
          text: `${es ? "Refactor sugerido" : "Suggested refactor"}: ${refactorCandidates.map((item) => `${item.symbol} (${item.definition_count}/${item.reference_count})`).join(", ")}`,
        })
      );
    }
    const duplicateLogicNeighbors = Array.isArray(impact.duplicate_logic_neighbors) ? impact.duplicate_logic_neighbors : [];
    if (duplicateLogicNeighbors.length) {
      impactCard.appendChild(
        el("div", {
          class: "project-summary-text subtle",
          text: `${es ? "Vecinos con lógica duplicada" : "Duplicate-logic neighbors"}: ${duplicateLogicNeighbors.map((item) => `${(item.symbols || []).join("/") || item.fingerprint} (${item.path_count})`).join(", ")}`,
        })
      );
    }
    const renameScope = impact.rename_scope && typeof impact.rename_scope === "object" ? impact.rename_scope : null;
    if (renameScope?.safety) {
      const safety = renameScope.safety;
      impactCard.appendChild(
        el("div", {
          class: `project-summary-text subtle${String(safety.level || "") === "low" ? " danger" : String(safety.level || "") === "medium" ? " warn" : ""}`,
          text: `${es ? "Seguridad de rename" : "Rename safety"}: ${String(safety.level || "").toUpperCase()} (${Number(safety.score || 0)})`,
        })
      );
      if (Array.isArray(safety.warnings) && safety.warnings.length) {
        impactCard.appendChild(
          el("div", {
            class: "project-summary-text subtle",
            text: `${es ? "Warnings" : "Warnings"}: ${safety.warnings.join(", ")}`,
          })
        );
      }
    }
    const renameSymbol = String((impact.matched_symbols?.[0]?.symbol) || (refactorCandidates?.[0]?.symbol) || "").trim();
    if (renameSymbol) {
      const actions = el("div", { class: "mini-list" });
      const renameBtn = el("button", {
        class: "icon-btn small",
        text: es ? `Renombrar ${renameSymbol}` : `Rename ${renameSymbol}`,
        attrs: { type: "button" },
      });
      renameBtn.addEventListener("click", () => {
        void prepareSymbolRenamePlan(renameSymbol);
      });
      actions.appendChild(renameBtn);
      impactCard.appendChild(actions);
    }
    grid.appendChild(impactCard);
  }

  const sections = [
    { label: es ? "Entrypoints" : "Entrypoints", items: detail.entrypoints || [] },
    { label: es ? "Dependencias" : "Dependencies", items: detail.dependencies || [] },
    { label: es ? "Configs" : "Configs", items: detail.configs || [] },
  ];
  if (state.showProjectAdvanced) sections.forEach((section) => {
    const rows = Array.isArray(section.items) ? section.items : [];
    if (!rows.length) return;
    const card = el("div", { class: "project-meta-card" });
    card.appendChild(el("strong", { text: section.label }));
    const list = el("div", { class: "mini-list" });
    rows.slice(0, 8).forEach((item) => list.appendChild(el("span", { class: "mini-chip", text: String(item) })));
    card.appendChild(list);
    grid.appendChild(card);
  });

  if (state.showProjectAdvanced && capabilityItems.length) {
    const capCard = el("div", { class: "project-meta-card" });
    capCard.appendChild(el("strong", { text: es ? "Capabilities" : "Capabilities" }));
    const list = el("div", { class: "mini-list" });
    capabilityItems.forEach((item) => {
      list.appendChild(el("span", { class: `mini-chip ${capabilityChipClass(item) || (!item.ok ? "warn" : "")}`, text: `${item.label}: ${item.value}` }));
    });
    capCard.appendChild(list);
    grid.appendChild(capCard);
  }

  if (state.showProjectAdvanced && validationItems) {
    const validationCard = el("div", { class: "project-meta-card" });
    validationCard.appendChild(el("strong", { text: es ? "Validación" : "Validation" }));
    const list = el("div", { class: "mini-list" });
    list.appendChild(
      el("span", {
        class: `mini-chip ${validationItems.browserSmokeStrictDefault ? "" : "warn"}`,
        text: `${es ? "Browser gate" : "Browser gate"}: ${validationItems.browserSmokeStrictDefault ? "strict" : "soft"}`,
      })
    );
    if (validationItems.startupGate.length) {
      list.appendChild(el("span", { class: "mini-chip", text: `${es ? "Startup" : "Startup"}: ${validationItems.startupGate.join(" → ")}` }));
    }
    if (validationItems.verifyFull.length) {
      list.appendChild(el("span", { class: "mini-chip", text: `verify_full: ${validationItems.verifyFull.join(" → ")}` }));
    }
    const startupRun = validationItems.lastRuns?.startup_gate || null;
    const verifyRun = validationItems.lastRuns?.verify_full || null;
    if (startupRun?.status) {
      list.appendChild(el("span", { class: `mini-chip ${validationFlowStatus(startupRun)}`, text: `${es ? "Último startup" : "Last startup"}: ${startupRun.status}` }));
    }
    if (verifyRun?.status) {
      list.appendChild(el("span", { class: `mini-chip ${validationFlowStatus(verifyRun)}`, text: `verify_full: ${verifyRun.status}` }));
    }
    validationCard.appendChild(list);
    if (validationItems.lastUpdatedMs) {
      validationCard.appendChild(
        el("div", {
          class: "project-summary-text",
          text: `${es ? "Última validación" : "Last validation"}: ${formatAgo(validationItems.lastUpdatedMs)}`,
        })
      );
    }
    grid.appendChild(validationCard);
  }

  const plannerCard = buildPlannerCard();
  if (plannerCard) grid.appendChild(plannerCard);

  dom.projectMeta.appendChild(grid);
}

function buildPlannerAction(context = null) {
  if (!context || typeof context !== "object") return null;
  const es = state.lang === LANG.ES;
  const nextTool = String(context.next_tool || "").trim();
  if (!nextTool) return null;

  if (nextTool === "web_search") {
    return {
      label: es ? "Usar prefijo web:" : "Use web: prefix",
      run: () => {
        const current = String(dom.msgInput?.value || "").trim();
        const draft = current.toLowerCase().startsWith("web:") ? current : `web: ${current}`.trim();
        if (dom.msgInput) {
          dom.msgInput.value = draft;
          autoSizeTextarea(dom.msgInput);
        }
        dom.msgInput?.focus();
      },
    };
  }

  if (["project_manifest", "project_files", "project_symbols", "project_excerpt", "file_search"].includes(nextTool)) {
    return {
      label: es ? "Abrir proyecto" : "Open project",
      run: async () => {
        activateTab("files");
        if (!state.sidebarVisible) toggleSidebarVisibility();
        if (state.activeProjectId) {
          await loadActiveProjectDetail(state.activeProjectId);
        }
        await loadProjectTree();
      },
    };
  }

  if (nextTool === "agent_continue") {
    return {
      label: es ? "Continuar agente" : "Continue agent",
      run: async () => {
        if (!state.conversationId) return;
        await handleAgentContinue({ useWeb: state.mode === MODES.WEB, synthesize: true });
      },
    };
  }

  if (nextTool === "ingest_log") {
    return {
      label: es ? "Ver log de ingesta" : "Open ingest log",
      run: () => {
        activateTab("files");
        dom.ingestLogBtn?.click();
      },
    };
  }

  if (nextTool === "clamav_status") {
    return {
      label: es ? "Abrir snapshot" : "Open snapshot",
      run: () => loadSnapshot(),
    };
  }

  return null;
}

async function runProjectQuickTool(toolName, context = null) {
  const es = state.lang === LANG.ES;
  const tool = String(toolName || "").trim();
  if (!tool) return;

  if (tool === "delete_project") {
    if (!state.activeProjectId) {
      appendBubble(es ? "No hay proyecto activo." : "No active project.", "error");
      return;
    }
    // Always require explicit user confirmation for sensitive actions.
    const ok = window.confirm(es ? "Esto eliminará el proyecto (requiere aprobación). ¿Continuar?" : "This will delete the project (requires approval). Continue?");
    if (!ok) return;
    if (state.conversationId) {
      await executeConversationTool("delete_project", { project_id: state.activeProjectId }, { autoApprove: false });
    } else {
      await deleteProject();
    }
    await loadRegisteredProjects();
    await setActiveProject("", { bindConversation: false, loadDetail: true });
    loadProjectTree();
    return;
  }

  if (tool === "web_search") {
    if (state.chatOnlyExperience) {
      const current = String(dom.msgInput?.value || "").trim();
      if (dom.msgInput && !current.toLowerCase().startsWith("web:")) {
        dom.msgInput.value = `web: ${current}`.trim();
        autoSizeTextarea(dom.msgInput);
      }
    } else {
      setMode(MODES.WEB);
    }
    dom.msgInput?.focus();
    return;
  }

  if (tool === "ingest_log") {
    // Prefer agent-style tool execution (records a turn) when conversation exists.
    if (state.conversationId) {
      await executeConversationTool("ingest_log", {}, { title: es ? "Ingest log" : "Ingest log" });
      return;
    }
    activateTab("files");
    if (!state.sidebarVisible) toggleSidebarVisibility();
    dom.ingestLogBtn?.click();
    return;
  }

  if (tool === "clamav_status") {
    if (state.conversationId) {
      await executeConversationTool("clamav_status", {}, { title: "ClamAV" });
      return;
    }
    await loadSnapshot();
    return;
  }

  // Project-scoped tools
  if (!state.activeProjectId) {
    appendBubble(es ? "No hay proyecto activo." : "No active project.", "error");
    return;
  }

  if (tool === "project_manifest" || tool === "project_files") {
    if (state.conversationId && tool === "project_files") {
      const q = prompt(es ? "Buscar archivo (ej: auth.py, deps.py, main) :" : "File search (e.g. auth.py, deps.py, main):", String(context?.current_file_focus || "").trim());
      if (!q) return;
      await executeConversationTool("project_files", { project_id: state.activeProjectId, q, limit: 80 }, { title: es ? `Files: ${q}` : `Files: ${q}` });
      return;
    }
    activateTab("files");
    if (!state.sidebarVisible) toggleSidebarVisibility();
    await loadActiveProjectDetail(state.activeProjectId);
    await loadProjectTree();
    return;
  }

  if (tool === "project_symbols") {
    const q = prompt(es ? "Buscar símbolo (ej: auth, login, SessionLocal) :" : "Symbol search (e.g. auth, login, SessionLocal):", String(context?.current_symbol_focus || "").trim());
    if (!q) return;
    if (state.conversationId) {
      await executeConversationTool("project_symbols", { project_id: state.activeProjectId, q, limit: 80 }, { title: es ? `Symbols: ${q}` : `Symbols: ${q}` });
      return;
    }
    try {
      const url = new URL(endpoints.filesProjectSymbols(state.activeProjectId), location.origin);
      url.searchParams.set("q", q);
      url.searchParams.set("limit", "80");
      const res = await fetchWithTimeout(url.toString(), { headers: { Accept: "application/json" } }, { timeout: 20000, retries: 0 });
      const data = await safeJson(res);
      if (!res.ok) throw new Error(data?.detail || `HTTP ${res.status}`);
      renderSimpleList(data, es ? `Symbols: ${q}` : `Symbols: ${q}`);
    } catch (err) {
      console.error(err);
      appendBubble(es ? "No se pudo buscar símbolos." : "Could not search symbols.", "error");
    }
    return;
  }

  if (tool === "file_search") {
    const q = prompt(es ? "Buscar archivo (ej: auth.py, deps.py, main) :" : "File search (e.g. auth.py, deps.py, main):", String(context?.current_file_focus || "").trim());
    if (!q) return;
    if (state.conversationId) {
      await executeConversationTool("project_files", { project_id: state.activeProjectId, q, limit: 80 }, { title: es ? `Files: ${q}` : `Files: ${q}` });
      return;
    }
    try {
      const url = new URL(endpoints.filesProjectFiles(state.activeProjectId), location.origin);
      url.searchParams.set("q", q);
      url.searchParams.set("limit", "80");
      const res = await fetchWithTimeout(url.toString(), { headers: { Accept: "application/json" } }, { timeout: 20000, retries: 0 });
      const data = await safeJson(res);
      if (!res.ok) throw new Error(data?.detail || `HTTP ${res.status}`);
      renderSimpleList(data, es ? `Files: ${q}` : `Files: ${q}`);
    } catch (err) {
      console.error(err);
      appendBubble(es ? "No se pudo buscar archivos." : "Could not search files.", "error");
    }
    return;
  }
}

function renderProjectList() {
  if (!dom.projectList) return;
  dom.projectList.innerHTML = "";
  const es = state.lang === LANG.ES;
  const counts = getProjectRecordCounts();
  const visibleProjects = getVisibleProjectRecords();

  if (!state.projectRecords.length) {
    dom.projectList.textContent = es ? "Sin proyectos cargados." : "No projects loaded.";
    updateProjectListVisibility();
    renderActiveProjectBadge();
    renderProjectMeta();
    return;
  }

  if (!visibleProjects.length) {
    dom.projectList.textContent = counts.hiddenTemp
      ? (es ? `No hay proyectos visibles. ${counts.hiddenTemp} temporales/test están ocultos.` : `No visible projects. ${counts.hiddenTemp} temp/test projects are hidden.`)
      : (es ? "Sin proyectos visibles." : "No visible projects.");
    updateProjectListVisibility();
    renderActiveProjectBadge();
    renderProjectMeta();
    return;
  }

  visibleProjects.forEach((project) => {
    const id = String(project.project_id || "");
    const rootPath = String(project.root_path || "");
    const card = el("div", { class: `project-list-card ${id === state.activeProjectId ? "active" : ""}` });
    card.addEventListener("click", () => setActiveProject(id, { rootPath }));

    const head = el("div", { class: "project-list-head" });
    head.appendChild(el("div", { class: "project-list-id", text: id || "project" }));
    const status = el("span", { class: "origin-pill local", text: String(project.ready_state || project.status || "uploaded") });
    head.appendChild(status);
    card.appendChild(head);

    const meta = el("div", { class: "project-list-meta" });
    meta.appendChild(el("span", { text: `${es ? "Fuente" : "Source"}: ${project.source || "-"}` }));
    meta.appendChild(el("span", { text: `${es ? "Chunks" : "Chunks"}: ${project.chunk_count ?? 0}` }));
    card.appendChild(meta);

    if (rootPath) {
      card.appendChild(el("div", { class: "project-list-path", text: rootPath }));
    }
    dom.projectList.appendChild(card);
  });
  updateProjectListVisibility();
  renderActiveProjectBadge();
  renderProjectMeta();
}

async function bindConversationProject(projectId) {
  if (!state.conversationId) return;
  const payload = { project_id: projectId || null };
  const res = await fetchWithTimeout(endpoints.bindConversationProject(state.conversationId), {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(payload),
  }, { timeout: 10000, retries: 0 });
  if (!res.ok) {
    const data = await safeJson(res);
    throw new Error(data?.detail || "bind failed");
  }
}

function isAbsoluteProjectRootPath(path) {
  const p = String(path || "").trim();
  if (!p) return false;
  if (p.startsWith("/")) return true;
  return /^[A-Za-z]:[\\/]/.test(p);
}

async function ensureCurrentRootRegistered() {
  const rootPath = String(state.manualProjectRoot || "").trim();
  if (!rootPath) throw new Error("missing root");
  if (!isAbsoluteProjectRootPath(rootPath)) {
    clearManualProjectRoot({ syncSelect: true });
    throw new Error("manual-root-must-be-absolute");
  }
  const existing = state.projectRecords.find((item) => String(item?.root_path || "") === rootPath);
  if (existing?.project_id) {
    if (String(existing.project_id) !== state.activeProjectId) {
      await setActiveProject(String(existing.project_id), {
        rootPath,
        bindConversation: false,
        loadDetail: false,
      });
    }
    return { project_id: String(existing.project_id), path: rootPath };
  }

  const res = await fetchWithTimeout(endpoints.filesRegisterRoot, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ path: rootPath }),
  }, { timeout: 15000, retries: 0 });
  const data = await safeJson(res);
  if (!res.ok) {
    if (res.status === 400) {
      clearManualProjectRoot({ syncSelect: true });
    }
    throw new Error(data?.detail || "register-root failed");
  }
  if (data?.project_id) {
    await loadRegisteredProjects();
    await setActiveProject(String(data.project_id), {
      rootPath: String(data.path || rootPath),
      bindConversation: false,
      loadDetail: true,
    });
  }
  if (syncAutoIngestJob(data?.auto_ingest || data)) {
    appendBubble(
      state.lang === LANG.ES ? `Indexando proyecto en background (job ${state.ingestJobId}).` : `Project indexing in background (job ${state.ingestJobId}).`,
      "bot"
    );
  }
  return data;
}

async function syncConversationState(convId) {
  if (!convId) return;
  try {
    const res = await fetchWithTimeout(endpoints.conversationState(convId), { headers: { Accept: "application/json" } }, { timeout: 10000, retries: 0 });
    const data = await safeJson(res);
    if (!res.ok) {
      if (res.status === 404) {
        handleMissingConversation(convId, { source: "state" });
        return false;
      }
      throw new Error(data?.detail || `HTTP ${res.status}`);
    }
    const remoteProjectId = String(data?.state?.active_project_id || "");
    state.activeProjectId = remoteProjectId;
    if (remoteProjectId) localStorage.setItem("aegis_active_project_id", remoteProjectId);
    else localStorage.removeItem("aegis_active_project_id");
    if (remoteProjectId) clearManualProjectRoot({ syncSelect: false });
    renderActiveProjectSelect();
    renderProjectList();
    renderActiveProjectBadge();
    if (remoteProjectId) await loadActiveProjectDetail(remoteProjectId);
    else {
      state.activeProjectDetail = null;
      state.activeProjectImpact = null;
      renderProjectMeta();
    }
    return true;
  } catch (err) {
    if (String(err?.message || "").includes("HTTP 404")) {
      handleMissingConversation(convId, { source: "state" });
      return false;
    }
    console.error("conversation-state-sync-error", err);
    return false;
  }
}

function clearChatTranscript() {
  if (dom.chat) dom.chat.innerHTML = "";
}

async function restoreConversationTranscript(convId, { force = false } = {}) {
  const targetConvId = String(convId || "").trim();
  if (!targetConvId) return false;
  if (!force && state.lastTranscriptConversationId === targetConvId) return true;
  if (!hasAuthForScope("main")) return false;

  try {
    const url = new URL(endpoints.conversationBundle(targetConvId), location.origin);
    url.searchParams.set("limit", "200");
    const res = await fetchWithTimeout(url.toString(), { headers: { Accept: "application/json" } }, { timeout: 12000, retries: 0 });
    const data = await safeJson(res);
    if (!res.ok) {
      if (res.status === 404) {
        handleMissingConversation(targetConvId, { source: "bundle" });
        return false;
      }
      throw new Error(data?.detail || `HTTP ${res.status}`);
    }

    const turns = Array.isArray(data?.turns) ? data.turns : [];
    clearChatTranscript();
    if (!turns.length) {
      state.lastTranscriptConversationId = targetConvId;
      try {
        localStorage.setItem("aegis_last_transcript_conv", targetConvId);
      } catch {}
      return false;
    }

    turns.forEach((turn) => {
      const userMessage = String(turn?.user_message || "").trim();
      const assistantMessage = String(turn?.assistant_message || "").trim();
      if (userMessage) appendBubble(userMessage, "user");
      if (assistantMessage) appendBubble(assistantMessage, "bot", true, turn?.response_context || null);
    });

    state.lastTranscriptConversationId = targetConvId;
    try {
      localStorage.setItem("aegis_last_transcript_conv", targetConvId);
    } catch {}
    return true;
  } catch (err) {
    if (String(err?.message || "").includes("HTTP 404")) {
      handleMissingConversation(targetConvId, { source: "bundle" });
      return false;
    }
    console.error("conversation-transcript-restore-error", err);
    return false;
  }
}

async function loadActiveProjectDetail(projectId) {
  if (!projectId) {
    state.activeProjectDetail = null;
    state.activeProjectImpact = null;
    renderProjectMeta();
    return;
  }
  if (!hasAuthForScope("files")) {
    state.activeProjectDetail = null;
    state.activeProjectImpact = null;
    renderProjectMeta();
    return;
  }
  try {
    const detailRes = await fetchWithTimeout(
      new URL(endpoints.filesProjectDetail(projectId), location.origin).toString() + `?lang=${state.lang}`,
      {},
      { timeout: 12000, retries: 0 }
    );
    const detailData = await safeJson(detailRes);
    if (!detailRes.ok) throw new Error(detailData?.detail || "detail failed");

    const projectStatus = String(detailData?.ready_state || detailData?.project?.ready_state || detailData?.project?.status || "").trim().toLowerCase();
    const manifestReady =
      ["ingested", "ready", "indexed"].includes(projectStatus)
      || !!detailData?.manifest_ready
      || !!(detailData?.manifest && typeof detailData.manifest === "object");

    let entryData = { items: [] };
    let depsData = { items: [] };
    let cfgData = { items: [] };
    let ideasData = { items: [] };

    if (manifestReady) {
      const [entryRes, depsRes, cfgRes, ideasRes] = await Promise.all([
        fetchWithTimeout(endpoints.filesProjectEntrypoints(projectId), {}, { timeout: 12000, retries: 0 }),
        fetchWithTimeout(endpoints.filesProjectDependencies(projectId), {}, { timeout: 12000, retries: 0 }),
        fetchWithTimeout(endpoints.filesProjectConfigs(projectId), {}, { timeout: 12000, retries: 0 }),
        fetchWithTimeout(new URL(endpoints.filesProjectIdeas(projectId), location.origin).toString() + `?lang=${state.lang}`, {}, { timeout: 12000, retries: 0 }),
      ]);
      const [entryJson, depsJson, cfgJson, ideasJson] = await Promise.all([
        safeJson(entryRes),
        safeJson(depsRes),
        safeJson(cfgRes),
        safeJson(ideasRes),
      ]);
      if (entryRes.ok && entryJson && typeof entryJson === "object") entryData = entryJson;
      if (depsRes.ok && depsJson && typeof depsJson === "object") depsData = depsJson;
      if (cfgRes.ok && cfgJson && typeof cfgJson === "object") cfgData = cfgJson;
      if (ideasRes.ok && ideasJson && typeof ideasJson === "object") ideasData = ideasJson;
    }

    state.activeProjectDetail = {
      ...(detailData || {}),
      entrypoints: Array.isArray(entryData?.items) ? entryData.items : [],
      dependencies: Array.isArray(depsData?.items) ? depsData.items : [],
      configs: Array.isArray(cfgData?.items) ? cfgData.items : [],
      ideas: Array.isArray(ideasData?.items) ? ideasData.items : [],
      intelligence: detailData?.intelligence && typeof detailData.intelligence === "object"
        ? detailData.intelligence
        : null,
      manifest_ready: manifestReady,
      project_status: projectStatus,
    };
    const resolvedRoot = getEffectiveProjectRoot();
    if (resolvedRoot) syncProjectSelectValue(resolvedRoot);
    void loadProjectImpact();
  } catch (err) {
    console.error("active-project-detail-error", err);
    state.activeProjectDetail = null;
    state.activeProjectImpact = null;
  }
  renderProjectMeta();
}

async function setActiveProject(projectId, { rootPath = null, bindConversation = true, loadDetail = true } = {}) {
  const nextProjectId = String(projectId || "");
  if (nextProjectId !== String(state.activeProjectId || "") && !confirmDiscardFileEdits()) {
    return false;
  }

  state.activeProjectId = nextProjectId;
  if (state.activeProjectId) localStorage.setItem("aegis_active_project_id", state.activeProjectId);
  else localStorage.removeItem("aegis_active_project_id");
  if (state.activeProjectId) {
    // Canonical identity: once project_id is active, manual root must not remain persisted.
    clearManualProjectRoot({ syncSelect: false });
  }
  state.treeSelectionPath = "";
  state.treeSelectionIsDir = false;
  if (!state.activeProjectId) {
    setFileViewerContent(
      "",
      state.lang === LANG.ES ? "Selecciona un archivo en Archivos" : "Select a file in Files"
    );
  }

  const project = getActiveProjectRecord();
  const nextRoot = rootPath || project?.root_path || null;
  if (nextRoot) syncProjectSelectValue(String(nextRoot));
  else if (!state.manualProjectRoot) syncProjectSelectValue("");

  renderActiveProjectSelect();
  renderProjectList();
  renderSourceOriginBar(state.lastChatContext);

  if (loadDetail) await loadActiveProjectDetail(state.activeProjectId);
  else if (!state.activeProjectId) {
    state.activeProjectDetail = null;
    state.activeProjectImpact = null;
  }
  loadProjectTree();
  if (bindConversation && state.conversationId) {
    try {
      await bindConversationProject(state.activeProjectId || null);
    } catch (err) {
      console.error("bind-project-error", err);
    }
  }
  return true;
}

function trimAttachmentAnalysis(text, maxChars = 2400) {
  const raw = String(text || "").trim();
  if (!raw) return "";
  if (raw.length <= maxChars) return raw;
  return `${raw.slice(0, maxChars)}\n… [truncated]`;
}

function updateChatAttachmentBar() {
  if (!dom.chatAttachmentBar || !dom.chatAttachmentLabel) return;
  const es = state.lang === LANG.ES;
  const a = state.chatAttachment && typeof state.chatAttachment === "object" ? state.chatAttachment : null;
  if (!a) {
    dom.chatAttachmentBar.hidden = true;
    return;
  }
  const kind = String(a.kind || "attachment").trim();
  const name = String(a.name || "attachment").trim();
  const kindLabel = kind === "image"
    ? (es ? "imagen" : "image")
    : (es ? "archivo" : "file");
  dom.chatAttachmentBar.hidden = false;
  dom.chatAttachmentLabel.textContent = es
    ? `Adjunto ${kindLabel}: ${name}`
    : `Attached ${kindLabel}: ${name}`;
  if (dom.chatAttachmentAutoWeb) dom.chatAttachmentAutoWeb.checked = !!state.chatAttachmentAutoWeb;
}

function setChatAttachment(attachment) {
  if (!attachment || typeof attachment !== "object") return;
  const analysis = trimAttachmentAnalysis(attachment.analysis || "");
  if (!analysis) return;
  state.chatAttachment = {
    kind: String(attachment.kind || "attachment").trim() || "attachment",
    name: String(attachment.name || "attachment").trim() || "attachment",
    analysis,
  };
  updateChatAttachmentBar();
}

function clearChatAttachment({ clearImageRef = false } = {}) {
  state.chatAttachment = null;
  if (clearImageRef) state.imageReferenceFile = null;
  updateChatAttachmentBar();
}

function messageTargetsAttachmentContext(text) {
  const lower = String(text || "").trim().toLowerCase();
  if (!lower) return false;
  if (looksLocalSocialMessage(lower)) return false;
  if (looksProjectScopedMessage(lower) || looksExplicitLocalOnlyMessage(lower)) return false;

  const normalized = lower.replace(/[!?.,;:]+/g, " ").replace(/\s+/g, " ").trim();
  if ([
    "this",
    "that",
    "it",
    "this image",
    "that image",
    "this file",
    "that file",
    "this document",
    "that document",
    "esto",
    "eso",
    "esta imagen",
    "ese archivo",
    "este archivo",
    "este documento",
    "ese documento",
  ].includes(normalized)) {
    return true;
  }

  return [
    "attachment",
    "attached",
    "adjunto",
    "adjunta",
    "image",
    "imagen",
    "photo",
    "foto",
    "screenshot",
    "captura",
    "file",
    "archivo",
    "document",
    "documento",
    "pdf",
    "html",
    "text",
    "texto",
    "ocr",
    "code",
    "codigo",
    "código",
    "what is this",
    "what is that",
    "what's this",
    "what's that",
    "whats this",
    "whats that",
    "what does it say",
    "what does this say",
    "describe",
    "explain",
    "summarize",
    "summary",
    "resume",
    "resumen",
    "analiza",
    "analyze",
    "extract",
    "extrae",
    "read",
    "lee",
    "que es",
    "qué es",
    "que dice",
    "qué dice",
    "explica",
  ].some((kw) => lower.includes(kw));
}

function buildMessageWithAttachment(message, mode = "general") {
  const base = String(message || "").trim();
  const modeValue = String(mode || "").trim().toLowerCase();
  const a = state.chatAttachment && typeof state.chatAttachment === "object" ? state.chatAttachment : null;
  if (!base || !a || !a.analysis) return base;
  if (modeValue === "url" || modeValue === "crypto") return base;
  if (/\[(?:attached|adjunto)\s+/i.test(base)) return base;
  if (!messageTargetsAttachmentContext(base)) return base;

  const es = state.lang === LANG.ES;
  const head = es
    ? `[Contexto de adjunto ${a.kind || "archivo"}: ${a.name || "attachment"}]`
    : `[Attachment context ${a.kind || "file"}: ${a.name || "attachment"}]`;
  const block = [head, a.analysis].filter(Boolean).join("\n");
  return `${base}\n\n${block}`;
}

function updateImageQuickBar() {
  if (!dom.imageQuickBar) return;
  const show = state.mode === MODES.IMAGE;
  dom.imageQuickBar.hidden = !show;
  if (dom.imageModeGuide) dom.imageModeGuide.hidden = !show;
  updateAttachmentButtonUI();
}

function updateAttachmentButtonUI() {
  if (!dom.attachBtn) return;
  const es = state.lang === LANG.ES;
  const imageMode = state.mode === MODES.IMAGE;
  dom.attachBtn.hidden = false;
  dom.attachBtn.setAttribute("aria-hidden", "false");
  dom.attachBtn.setAttribute("aria-pressed", String(imageMode));
  dom.attachBtn.classList.toggle("active", imageMode);
  dom.attachBtn.title = imageMode
    ? (es ? "Subir imagen de referencia para analizar" : "Upload reference image for analysis")
    : (es ? "Adjuntar archivo, documento o imagen al chat" : "Attach file, document, or image to chat");
  dom.attachBtn.setAttribute("aria-label", dom.attachBtn.title);
}

function normalizeCryptoScopeSymbol(raw) {
  const token = String(raw || "").trim().toUpperCase();
  if (!token) return "";
  if (CRYPTO_SEARCH_SYMBOLS.includes(token)) return token;
  if (/^[A-Z]{2,10}USD$/.test(token)) return `${token.slice(0, -3)}USDT`;
  if (/^[A-Z]{2,10}(USDT|USDC|BUSD|FDUSD|TUSD|BTC|ETH)$/.test(token)) return token;
  const base = token.replace(/[^A-Z]/g, "");
  if (!base) return "";
  if (CRYPTO_SEARCH_SYMBOLS.includes(`${base}USDT`)) return `${base}USDT`;
  if (["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "AVAX", "DOT", "TRX"].includes(base)) return `${base}USDT`;
  return "";
}

function extractCryptoSymbolFromText(text) {
  const raw = String(text || "");
  const pair = raw.match(/\b([A-Za-z]{2,10})(?:\/)?(USDT|USD|USDC|BUSD|FDUSD|TUSD|BTC|ETH)\b/i);
  if (pair) return normalizeCryptoScopeSymbol(`${pair[1]}${pair[2]}`);
  const lone = raw.match(/\b([A-Za-z]{2,10})\b/i);
  if (!lone) return "";
  return normalizeCryptoScopeSymbol(lone[1]);
}

function extractCryptoHorizonFromText(text) {
  const raw = String(text || "");
  const patterns = [
    /\b(?:h|horizon)\s*[:=]?\s*(\d{1,5})\s*m\b/i,
    /\b(?:next|for the next|for next)\s+(\d{1,5})\s*(?:m|min|mins|minute|minutes)\b/i,
    /\b(?:proximos|próximos|proximo|próximo)\s+(\d{1,5})\s*(?:m|min|mins|minuto|minutos)\b/i,
    /\b(\d{1,5})\s*(?:m|min|mins|minute|minutes|minuto|minutos)\b/i,
  ];
  for (const pattern of patterns) {
    const match = raw.match(pattern);
    if (!match) continue;
    const value = parseInt(match[1], 10);
    if (Number.isFinite(value) && value >= 1 && value <= 10080) return value;
  }
  return null;
}

function buildCryptoScopedMessage(text) {
  const raw = String(text || "").trim();
  if (!raw) return raw;
  const explicitSymbol = extractCryptoSymbolFromText(raw);
  const explicitHorizon = extractCryptoHorizonFromText(raw);
  const panelSymbol = normalizeCryptoScopeSymbol(dom.chartSymbol?.value || state.chartSymbol || "BTCUSDT") || "BTCUSDT";
  const panelHorizon = parseInt(dom.cryptoHorizon?.value || state.lastPrediction?.horizon || "15", 10);
  const prefix = [];
  if (!explicitSymbol && panelSymbol) prefix.push(panelSymbol);
  if (!explicitHorizon && Number.isFinite(panelHorizon) && panelHorizon > 0) prefix.push(`H=${panelHorizon}m`);
  if (!prefix.length) return raw;
  return `${prefix.join(" ")} ${raw}`.trim();
}

function syncCryptoPanelScopeFromText(text) {
  const raw = String(text || "").trim();
  if (!raw) return false;

  let changed = false;
  const explicitSymbol = extractCryptoSymbolFromText(raw);
  const explicitHorizon = extractCryptoHorizonFromText(raw);

  if (explicitSymbol) {
    state.chartSymbol = explicitSymbol;
    if (dom.chartSymbol) dom.chartSymbol.value = explicitSymbol;
    changed = true;
  }

  if (Number.isFinite(explicitHorizon) && explicitHorizon > 0) {
    if (dom.cryptoHorizon) dom.cryptoHorizon.value = String(explicitHorizon);
    if (state.lastPrediction && typeof state.lastPrediction === "object") {
      state.lastPrediction.horizon = explicitHorizon;
    }
    changed = true;
  }

  if (changed) {
    loadSymbolsList(dom.chartSymbol?.value || state.chartSymbol || "");
  }
  return changed;
}

/* ------------------------- SEND / CHAT ------------------------- */

async function onSend() {
  if (state.pending) return;
  if (!ensureApiKeyOrPrompt({ action: "chat" })) return;
  const raw = (dom.msgInput?.value || "").trim();
  if (!raw) return;
  const explicitWebPrefix = /^web:\s*/i.test(raw);
  const explicitLocalPrefix = /^local:\s*/i.test(raw);

  // auto prefix routing
  let modeForThis = state.mode;
  let text = raw;

  if (/^web:\s*/i.test(raw)) { modeForThis = MODES.WEB; text = raw.replace(/^web:\s*/i, "").trim(); }
  if (/^url:\s*/i.test(raw)) { modeForThis = MODES.URL; text = raw.replace(/^url:\s*/i, "").trim(); }
  if (/^local:\s*/i.test(raw)) { modeForThis = MODES.CHAT; text = raw.replace(/^local:\s*/i, "").trim(); }

  // image generation shortcut in any mode
  if (await tryHandleImageCommand(raw)) {
    dom.msgInput.value = "";
    autoSizeTextarea(dom.msgInput);
    return;
  }

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
  appendTyping(getPendingBubbleLabel(modeForThis, text));

  const t0 = performance.now();
  try {
    if (modeForThis === MODES.WEB) {
      if ((!explicitWebPrefix || explicitLocalPrefix) && shouldKeepLocalInWebMode(text, "web")) {
        await handleChat(text, { mode: "general" });
      } else {
        await handleWeb(text);
      }
    } else if (modeForThis === MODES.URL) {
      await handleUrl(text);
    } else if (modeForThis === MODES.CRYPTO) {
      await handleChat(text, { mode: "crypto" });
    } else {
      await handleChat(text, { mode: "general" });
    }
  } catch (err) {
    appendBubble(formatNetworkError(err), "error");
    console.error(err);
  } finally {
    removeTyping();
    setPending(false);
    state.lastLatencyMs = performance.now() - t0;
  }
}

function formatNetworkError(err) {
  const es = state.lang === LANG.ES;
  const msg = String(err?.message || "").toLowerCase();
  const backend = (() => {
    try {
      return `${window.location.protocol}//${window.location.hostname}:${window.location.port || "8000"}`;
    } catch {
      return "http://127.0.0.1:8000";
    }
  })();
  if (err?.name === "AbortError") {
    if (state.cancelledByUser) {
      state.cancelledByUser = false;
      return es ? "Solicitud cancelada." : "Request cancelled.";
    }
    return es ? "Timeout: la petición tardó demasiado." : "Timeout: request took too long.";
  }
  if (msg.includes("failed to fetch") || msg.includes("networkerror")) {
    return es
      ? `Error de conexión al backend (${backend}). No es un fallo del modo web: el servidor está caído o no es alcanzable.`
      : `Backend connection error (${backend}). This is not a web-mode issue: server is down or unreachable.`;
  }
  return es ? "Error de red." : "Network error.";
}

function looksProjectScopedMessage(text) {
  if (!state.activeProjectId) return false;
  const lower = String(text || "").toLowerCase();
  return [
    "project",
    "proyecto",
    "repo",
    "repository",
    "ingested",
    "ingest",
    "file",
    "files",
    "folder",
    "folders",
    "directory",
    "directories",
    "archivo",
    "archivos",
    "carpeta",
    "carpetas",
    "directorio",
    "directorios",
    "path",
    "ruta",
    "symbol",
    "símbolo",
    "dependency",
    "dependencia",
    "entrypoint",
    "config",
    "architecture",
    "arquitectura",
    "codebase",
    "this code",
    "este codigo",
    "este código",
  ].some((kw) => lower.includes(kw));
}

function looksExplicitLocalOnlyMessage(text) {
  const lower = String(text || "").trim().toLowerCase();
  if (!lower) return false;
  if (/^local:\s*/i.test(lower)) return true;
  return [
    "local only",
    "solo local",
    "sin web",
    "without web",
    "use local",
    "usa local",
    "responde con local",
    "respuesta local",
    "reply with local",
    "reply locally",
    "no uses web",
    "no usar web",
    "do not use web",
    "dont use web",
    "don't use web",
    "no necesitas web",
  ].some((kw) => lower.includes(kw));
}

function looksLocalSocialMessage(text) {
  const lower = String(text || "").trim().toLowerCase();
  if (!lower) return false;
  const normalized = lower.replace(/[!?.,;:]+/g, " ").replace(/\s+/g, " ").trim();
  if (["ok", "okay", "okey", "thanks", "thank you", "ok thanks", "thanks ok", "gracias", "vale", "dale", "cool", "nice"].includes(normalized)) {
    return true;
  }
  return [
    "hello",
    "hi",
    "hey",
    "hola",
    "buenas",
    "how are you",
    "who are you",
    "what are you",
    "what is your name",
    "what's your name",
    "whats your name",
    "what can you do",
    "what u can do",
    "how can you help",
    "access to internet",
    "internet access",
    "browse the internet",
    "browse internet",
    "browse the web",
    "browse web",
    "can you browse",
    "can u browse",
    "do you have access",
    "u have access to internet",
    "you have access to internet",
    "quien eres",
    "quién eres",
    "como estas",
    "cómo estás",
    "que puedes hacer",
    "qué puedes hacer",
    "tienes acceso a internet",
    "tienes acceso al internet",
    "puedes navegar en internet",
    "puedes navegar por internet",
  ].some((kw) => lower.includes(kw));
}

function messageNeedsFreshWeb(text) {
  const lower = String(text || "").trim().toLowerCase();
  if (!lower) return false;
  return [
    "latest",
    "current",
    "today",
    "news",
    "release notes",
    "source",
    "sources",
    "link",
    "links",
    "docs",
    "documentation",
    "recent",
    "fresh",
    "fuente",
    "fuentes",
    "enlace",
    "enlaces",
    "documentacion",
    "documentación",
    "reciente",
    "actual",
  ].some((kw) => lower.includes(kw));
}

function attachmentKeepsLocalRouting(text, mode = "general") {
  const modeValue = String(mode || "").trim().toLowerCase();
  if (modeValue === "crypto" || modeValue === "url") return false;
  const attachment = state.chatAttachment && typeof state.chatAttachment === "object" ? state.chatAttachment : null;
  if (!attachment) return false;
  if (!messageTargetsAttachmentContext(text)) return false;
  const kind = String(attachment.kind || "").trim().toLowerCase();
  if (looksProjectScopedMessage(text)) return true;
  if (kind === "image") return true;
  if (messageNeedsFreshWeb(text)) return false;
  return true;
}

function projectKeepsLocalRouting(text, mode = "general") {
  const modeValue = String(mode || "").trim().toLowerCase();
  if (modeValue === "crypto" || modeValue === "url") return false;
  if (!looksProjectScopedMessage(text)) return false;
  return !messageNeedsFreshWeb(text);
}

function shouldKeepLocalInWebMode(text, mode = "general") {
  return looksExplicitLocalOnlyMessage(text) || looksLocalSocialMessage(text) || projectKeepsLocalRouting(text, mode) || attachmentKeepsLocalRouting(text, mode);
}

function shouldAutoUseWebForMessage(text, mode = "general") {
  const modeValue = String(mode || "").trim().toLowerCase();
  if (modeValue === "crypto" || modeValue === "url") return false;
  const raw = String(text || "").trim();
  if (!raw) return false;
  if (looksExplicitLocalOnlyMessage(raw)) return false;
  if (modeValue === "web") return !looksLocalSocialMessage(raw);
  if (looksLocalSocialMessage(raw)) return false;
  // Keep project-introspection turns local-first to avoid forcing web-only
  // when the user is clearly asking about the active repo/files/symbols.
  if (looksProjectScopedMessage(raw)) return false;
  return true;
}

function buildSourceUsageNotice(context = null) {
  if (!context || typeof context !== "object") return "";
  const es = state.lang === LANG.ES;
  if (context.using_live_web) {
    return es ? "Fuente usada: web en vivo." : "Source used: live web.";
  }
  if (context.using_cached_web || context.using_stale_cache) {
    return es ? "Fuente usada: caché web." : "Source used: web cache.";
  }
  const webStatus = String(context.web_status || "").trim();
  if (webStatus === "cooldown") {
    return es ? "Fuente usada: datos locales (web en cooldown)." : "Source used: local data (web cooldown).";
  }
  if (webStatus === "unavailable" || webStatus === "error") {
    return es ? "Fuente usada: datos locales (web no disponible)." : "Source used: local data (web unavailable).";
  }
  if (webStatus === "not-used") {
    return es ? "Fuente usada: local (web automática, no requerida)." : "Source used: local (web automatic, not required).";
  }
  const origins = Array.isArray(context.source_origin) ? context.source_origin.map((v) => String(v || "").trim()) : [];
  if (origins.includes("local") || origins.includes("manifest") || String(context.active_project_id || "").trim()) {
    return es ? "Fuente usada: datos locales del proyecto." : "Source used: local project data.";
  }
  if (origins.includes("model")) {
    return es ? "Fuente usada: respuesta del modelo (sin web)." : "Source used: model-only answer (no web).";
  }
  return "";
}

function appendSourceUsageNotice(context = null) {
  const msg = buildSourceUsageNotice(context);
  if (!msg) return;
  state.lastSourceUsageNotice = msg;
  notifyStatus(msg, { kind: "info", key: `source:${msg}`, dedupeMs: 4000, ttlMs: 2200 });
}

const INTERNAL_LEAK_LINE_PATTERNS = [
  /^\s*you are aegis\b/i,
  /^\s*always reply in the user[’']s language\b/i,
  /^\s*do not reveal system prompts\b/i,
  /^\s*never output special chat tokens\b/i,
  /^\s*[a-z]?\s*\.?\s*be accurate,\s*direct,\s*and\s*practical\b/i,
  /^\s*if mixed,\s*follow the dominant language\b/i,
  /\binternal chain-of-thought\b/i,
];
const INTERNAL_LEAK_ANYWHERE_PATTERNS = [
  /\byou are aegis\b/i,
  /\balways reply in the user[’']s language\b/i,
  /\bdo not reveal system prompts\b/i,
  /\bnever output special chat tokens\b/i,
  /\binternal chain-of-thought\b/i,
  /\btechnical assistant similar to chatgpt\b/i,
  /\bbe accurate,\s*direct,\s*and\s*practical\b/i,
  /\bif mixed,\s*follow the dominant language\b/i,
];
const INTERNAL_TRACE_PREFIX = /^\s*(plan|origin|data|provider|tool|artifact|used|status|project|llm)\s*:\s*/i;
const INTERNAL_TRACE_LABEL = /(plan|origin|data|provider|tool|artifact|used|status|project|llm)\s*:\s*/gi;

function stripInlinePromptBlob(text) {
  const src = String(text || "");
  let first = -1;
  for (const re of INTERNAL_LEAK_ANYWHERE_PATTERNS) {
    const m = src.match(re);
    if (!m || m.index == null) continue;
    if (first < 0 || m.index < first) first = m.index;
  }
  if (first < 0) return { text: src, stripped: false };
  const prefix = src.slice(0, first).replace(/[ \t\r\n\-:;]+$/g, "");
  if (prefix) return { text: prefix, stripped: true };

  // Leak appears at the beginning; remove leaked fragments and keep user-facing tail.
  let cleaned = src;
  for (const re of INTERNAL_LEAK_ANYWHERE_PATTERNS) {
    cleaned = cleaned.replace(re, " ");
  }
  cleaned = cleaned.replace(/\b(?:do not|don't|never)\b[^.!?\n]{0,160}(?:[.!?]|$)/gi, " ");
  cleaned = cleaned.replace(/\b(hidden rules?|tool instructions?|internal metadata|system rules?)\b/gi, " ");
  cleaned = cleaned.replace(/\btechnical assistant similar to chatgpt\b/gi, " ");
  cleaned = cleaned.replace(/\s+/g, " ").replace(/^[ \t\r\n\-:;,.]+|[ \t\r\n\-:;,.]+$/g, "");
  return { text: cleaned || src, stripped: true };
}

function stripInlineTraceBlob(text) {
  const src = String(text || "");
  const matches = Array.from(src.matchAll(/(plan|origin|data|provider|tool|artifact|used|status|project|llm)\s*:\s*/gi));
  if (matches.length < 2) return { text: src, stripped: false };
  const first = Number(matches[0]?.index ?? -1);
  const second = Number(matches[1]?.index ?? -1);
  const closeCluster = first >= 0 && second >= 0 && (second - first) <= 120;
  if (matches.length >= 3 || closeCluster) {
    return { text: src.slice(0, Math.max(0, first)).replace(/[ \t\r\n\-:;]+$/g, ""), stripped: true };
  }
  return { text: src, stripped: false };
}

function formatDisplayQuery(text) {
  const raw = String(text || "").replace(/[\u0000-\u001f\u007f]+/g, " ").trim();
  if (!raw) return "";
  const withoutPromptBlob = stripInlinePromptBlob(raw).text;
  const withoutTraceBlob = stripInlineTraceBlob(withoutPromptBlob).text;
  const attachmentSplit = withoutTraceBlob.split(/\n\s*\[(?:attachment|adjunto)\s+context[^\]]*\]/i)[0].trim();
  const compact = attachmentSplit.replace(/\s+/g, " ").trim();
  return compact.length > 240 ? `${compact.slice(0, 240)}…` : compact;
}

function sanitizeAssistantAnswerText(rawText) {
  const es = state.lang === LANG.ES;
  let text = String(rawText || "").trim();
  if (!text) return "";

  const inlinePrompt = stripInlinePromptBlob(text);
  text = inlinePrompt.text;
  const inlineTrace = stripInlineTraceBlob(text);
  text = inlineTrace.text;

  const lines = text.split(/\r?\n/);
  const kept = [];
  let stripped = false;
  for (const raw of lines) {
    const line = String(raw || "");
    const norm = line.trim();
    if (!norm) {
      kept.push(line);
      continue;
    }
    if (INTERNAL_TRACE_PREFIX.test(norm) || INTERNAL_LEAK_LINE_PATTERNS.some((re) => re.test(norm))) {
      stripped = true;
      continue;
    }
    kept.push(line);
  }
  text = kept.join("\n").replace(/\n{3,}/g, "\n\n").trim();
  if (INTERNAL_LEAK_ANYWHERE_PATTERNS.some((re) => re.test(text))) {
    return es
      ? "No puedo mostrar instrucciones internas. Reformula en una frase concreta y te respondo limpio."
      : "I can’t expose internal instructions. Rephrase your request in one clear sentence and I’ll answer cleanly.";
  }
  const traceCount = Array.from(text.matchAll(INTERNAL_TRACE_LABEL)).length;
  if (traceCount >= 3) {
    return es
      ? "No puedo mostrar trazas internas en la respuesta. Reformula en una frase concreta y te respondo limpio."
      : "I can’t expose internal traces in the answer. Rephrase your request in one clear sentence and I’ll answer cleanly.";
  }
  if (!text && (stripped || inlinePrompt.stripped || inlineTrace.stripped)) {
    return es
      ? "Respuesta sanitizada por seguridad. Reformula en una frase concreta y te respondo limpio."
      : "Response sanitized for safety. Rephrase your request in one clear sentence and I’ll answer cleanly.";
  }
  return text;
}

async function onAgentStep(evt = null) {
  if (state.pending) return;
  if (!ensureApiKeyOrPrompt({ action: "agent" })) return;
  const es = state.lang === LANG.ES;
  const raw = (dom.msgInput?.value || "").trim();
  if (!raw) return;
  if (!state.conversationId) {
    appendBubble(es ? "No hay conversación activa. Envía un mensaje primero." : "No active conversation. Send a message first.", "error");
    return;
  }

  appendBubble(raw, "user");
  dom.msgInput.value = "";
  autoSizeTextarea(dom.msgInput);

  setPending(true);
  appendTyping(getWorkPendingLabel("agent"));
  const t0 = performance.now();
  try {
    const msgWithAttachment = buildMessageWithAttachment(raw, "agent");
    const useWeb = state.mode === MODES.WEB;
    const wantsRun = !!(evt && typeof evt === "object" && evt.shiftKey);
    if (wantsRun) {
      await handleAgentRun(msgWithAttachment, { useWeb, synthesize: true, maxIterations: 4, maxTotalToolCalls: 10 });
    } else {
      await handleAgentStep(msgWithAttachment, { useWeb, synthesize: true });
    }
  } catch (err) {
    appendBubble(formatNetworkError(err), "error");
    console.error(err);
  } finally {
    removeTyping();
    setPending(false);
    state.lastLatencyMs = performance.now() - t0;
  }
}

async function onAgentRun(evt = null) {
  if (state.pending) return;
  if (!ensureApiKeyOrPrompt({ action: "agent_run" })) return;
  const es = state.lang === LANG.ES;
  const raw = (dom.msgInput?.value || "").trim();
  if (!raw) return;
  if (!state.conversationId) {
    appendBubble(es ? "No hay conversación activa. Envía un mensaje primero." : "No active conversation. Send a message first.", "error");
    return;
  }

  appendBubble(raw, "user");
  dom.msgInput.value = "";
  autoSizeTextarea(dom.msgInput);

  setPending(true);
  appendTyping(getWorkPendingLabel("agent"));
  const t0 = performance.now();
  try {
    const msgWithAttachment = buildMessageWithAttachment(raw, "agent");
    const useWeb = state.mode === MODES.WEB;
    await handleAgentRun(msgWithAttachment, { useWeb, synthesize: true, maxIterations: 6, maxTotalToolCalls: 16 });
  } catch (err) {
    appendBubble(formatNetworkError(err), "error");
    console.error(err);
  } finally {
    removeTyping();
    setPending(false);
    state.lastLatencyMs = performance.now() - t0;
  }
}

async function handleAgentContinue({ useWeb = false, synthesize = true } = {}) {
  const es = state.lang === LANG.ES;
  const convId = state.conversationId;
  if (!convId) throw new Error("missing conversation");

  const res = await fetchWithTimeout(endpoints.conversationAgentContinue(convId), {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      lang: state.lang,
      use_web: !!useWeb,
      max_iterations: 2,
      max_total_tool_calls: 6,
      synthesize: !!synthesize,
    }),
  }, { timeout: 0, retries: 0 });

  const data = await safeJson(res);
  if (!res.ok) {
    const msg = data?.detail || data?.error || `HTTP ${res.status}`;
    appendBubble(String(msg), "error");
    return;
  }

  const ctx = deriveContextFromAgentStep(data);
  ctx.source_plan = "tool-first-continue";
  const answer = sanitizeAssistantAnswerText(data?.response || "");
  if (answer) appendBubble(answer, "bot", true, ctx);
  else appendBubble(es ? "Sin respuesta del agente." : "Agent returned empty response.", "error");
  appendSourceUsageNotice(ctx);

  state.lastChatContext = ctx;
  updateModeIndicator();

  const sources = normalizeWebResults(data?.sources || []);
  renderResponseSources("continue", sources, ctx, data);
  loadConversationTurns({ force: true });
  loadConversationEvents({ force: true });
}

async function handleChat(text, { mode = "general" } = {}) {
  const modeValue = String(mode || "general").trim().toLowerCase();
  const scopedText = modeValue === "crypto" ? buildCryptoScopedMessage(text) : text;
  const autoByMessage = shouldAutoUseWebForMessage(scopedText, modeValue);
  const localFirstTurn = shouldKeepLocalInWebMode(scopedText, modeValue);
  const attachmentPrefersWeb = !!(
    state.chatAttachment
    && state.chatAttachmentAutoWeb
    && modeValue !== "url"
    && modeValue !== "crypto"
    && !localFirstTurn
    && messageNeedsFreshWeb(scopedText)
  );
  const autoUseWeb = !localFirstTurn && (modeValue === "web" || autoByMessage || attachmentPrefersWeb);
  const effectiveMode = localFirstTurn
    ? "general"
    : ((modeValue === "web" || autoByMessage) ? "web" : modeValue);
  const messageForBackend = buildMessageWithAttachment(scopedText, effectiveMode);
  const payload = {
    message: messageForBackend,
    lang: state.lang,
    mode: effectiveMode,
    use_web: autoUseWeb,
    active_project_id: state.activeProjectId || "",
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

  const context = data?.context && typeof data.context === "object" ? data.context : null;
  const answer = sanitizeAssistantAnswerText(data?.response ?? data?.answer ?? data?.text ?? data?.message ?? "");
  if (answer) appendBubble(String(answer), "bot", true, context);
  appendSourceUsageNotice(context);

  state.lastChatContext = context;
  updateModeIndicator();
  if (context?.active_project_id != null) {
    const nextProject = String(context.active_project_id || "");
    if (nextProject !== state.activeProjectId) {
      state.activeProjectId = nextProject;
      if (nextProject) localStorage.setItem("aegis_active_project_id", nextProject);
      else localStorage.removeItem("aegis_active_project_id");
      renderActiveProjectSelect();
      renderProjectList();
      if (nextProject) await loadActiveProjectDetail(nextProject);
      else renderProjectMeta();
    }
  }

  // if backend returns sources, show them
  const sources = normalizeWebResults(data?.sources || data?.results || data?.web_results || data?.items || null);
  renderResponseSources(scopedText, sources, context, data);

  // crypto side-effects
  if (effectiveMode === "crypto") {
    syncCryptoPanelScopeFromText(text);
    loadChartData(state.chartSymbol);
    loadCryptoPrediction({ force: true });
    loadCryptoState({ force: true });
    loadPredictionComparison(state.chartSymbol, { force: true });
  }

  return { context, sources, data };
}

function mergePrefetchedWebContext(prefetchedContext, currentContext, prefetchedResults = [], currentSources = []) {
  const prefetched = prefetchedContext && typeof prefetchedContext === "object" ? prefetchedContext : null;
  const current = currentContext && typeof currentContext === "object" ? currentContext : null;
  const prefetchedList = Array.isArray(prefetchedResults) ? prefetchedResults : [];
  const currentList = Array.isArray(currentSources) ? currentSources : [];

  if (!prefetched) return current;

  const prefetchedHasWebEvidence = !!(
    prefetched.using_live_web
    || prefetched.using_cached_web
    || prefetched.using_stale_cache
    || prefetchedList.length
  );
  if (!prefetchedHasWebEvidence) return current || prefetched;

  const currentHasWebEvidence = !!(
    current
    && (
      current.using_live_web
      || current.using_cached_web
      || current.using_stale_cache
      || Number(current.web_results || 0) > 0
      || currentList.length > 0
    )
  );
  if (currentHasWebEvidence) return current;

  const merged = { ...(current || {}) };
  const mergedOrigins = [];
  const seenOrigins = new Set();
  for (const origin of [...(prefetched.source_origin || []), ...(merged.source_origin || [])]) {
    const cleanOrigin = String(origin || "").trim();
    if (!cleanOrigin || seenOrigins.has(cleanOrigin)) continue;
    seenOrigins.add(cleanOrigin);
    mergedOrigins.push(cleanOrigin);
  }

  merged.source_origin = mergedOrigins;
  merged.source_plan = prefetched.source_plan || merged.source_plan;
  merged.active_project_id = merged.active_project_id || prefetched.active_project_id || null;
  merged.web_status = prefetched.web_status || merged.web_status || "";
  merged.web_source = prefetched.web_source || merged.web_source || "";
  merged.web_provider = prefetched.web_provider || merged.web_provider || "";
  merged.web_results = Math.max(Number(merged.web_results || 0), Number(prefetched.web_results || 0), prefetchedList.length);
  merged.using_live_web = !!prefetched.using_live_web;
  merged.using_cached_web = !!prefetched.using_cached_web;
  merged.using_stale_cache = !!prefetched.using_stale_cache;
  merged.data_notice = prefetched.data_notice || merged.data_notice || "";
  return merged;
}

function normalizeEvidence(items) {
  if (!Array.isArray(items)) return [];
  return items
    .filter((it) => it && typeof it === "object")
    .map((it) => ({
      origin: String(it.origin || "").trim(),
      kind: String(it.kind || "").trim(),
      project_id: String(it.project_id || "").trim(),
      path: String(it.path || "").trim(),
      title: String(it.title || "").trim(),
      text: typeof it.text === "string" ? it.text : "",
      meta: it.meta && typeof it.meta === "object" ? it.meta : {},
    }))
    .filter((it) => it.origin || it.kind || it.path || it.title || it.text);
}

function deriveContextFromAgentStep(step) {
  const evidence = normalizeEvidence(step?.evidence || []);
  const origins = Array.from(new Set(evidence.map((e) => e.origin).filter(Boolean)));
  const webMeta = step?.web_meta && typeof step.web_meta === "object" ? step.web_meta : {};
  const plan = step?.plan && typeof step.plan === "object" ? step.plan : {};
  const actions = Array.isArray(plan?.actions) ? plan.actions : [];

  const ctx = {
    source_plan: "tool-first",
    source_origin: origins,
    effective_tool: String(plan?.effective_tool || plan?.tool || "").trim() || null,
    effective_tool_status: String(plan?.tool_status || "").trim() || null,
    next_tool: String(plan?.next_tool || "").trim() || null,
    next_step: String(plan?.next_step || "").trim() || null,
    tool_candidates: Array.isArray(plan?.tool_candidates) ? plan.tool_candidates : [],
    tool_risks: plan?.tool_risks && typeof plan.tool_risks === "object" ? plan.tool_risks : null,
    approval_required: Array.isArray(plan?.approval_required) ? plan.approval_required : [],
    actions,
    web_status: String(webMeta?.status || webMeta?.source || "").trim() || "",
    web_source: String(webMeta?.source || "").trim() || "",
    web_provider: String(webMeta?.provider || "").trim() || "",
    using_live_web: webMeta?.source === "live",
    using_cached_web: webMeta?.source === "cache",
    using_stale_cache: webMeta?.source === "stale-cache",
    stop_reason: String(step?.stop_reason || "").trim() || null,
    budget_exhausted: !!step?.budget_exhausted,
    total_tool_calls: Number(step?.total_tool_calls || 0),
    iterations_completed: Number(step?.iterations_completed || 0),
  };

  // keep existing project summary context when present
  if (state.activeProjectDetail && typeof state.activeProjectDetail === "object") {
    ctx.project_summary = String(state.activeProjectDetail.summary || "").trim();
    ctx.entrypoints = state.activeProjectDetail.entrypoints || [];
    ctx.dependencies = state.activeProjectDetail.dependencies || [];
    ctx.configs = state.activeProjectDetail.configs || [];
  }
  return ctx;
}

async function handleAgentStep(text, { useWeb = false, synthesize = true } = {}) {
  const es = state.lang === LANG.ES;
  const convId = state.conversationId;
  if (!convId) throw new Error("missing conversation");

  const payload = {
    message: String(text || "").trim(),
    lang: state.lang,
    use_web: !!useWeb,
    max_tool_calls: 3,
    synthesize: !!synthesize,
  };

  const res = await fetchWithTimeout(endpoints.conversationAgentStep(convId), {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(payload),
  }, { timeout: 0, retries: 0 });

  const data = await safeJson(res);
  if (!res.ok) {
    const msg = data?.detail || data?.error || `HTTP ${res.status}`;
    appendBubble(String(msg), "error");
    return;
  }

  const ctx = deriveContextFromAgentStep(data);
  const answer = sanitizeAssistantAnswerText(data?.response || "");
  if (answer) appendBubble(answer, "bot", true, ctx);
  else appendBubble(es ? "Sin respuesta del agente." : "Agent returned empty response.", "error");
  appendSourceUsageNotice(ctx);

  state.lastChatContext = ctx;
  updateModeIndicator();

  const sources = normalizeWebResults(data?.sources || []);
  renderResponseSources(text, sources, ctx, data);

  // refresh session/turns view so you can inspect the trace immediately
  loadConversationTurns({ force: true });
  loadConversationEvents({ force: true });
}

async function handleAgentRun(text, { useWeb = false, synthesize = true, maxIterations = 4, maxTotalToolCalls = 10 } = {}) {
  const es = state.lang === LANG.ES;
  const convId = state.conversationId;
  if (!convId) throw new Error("missing conversation");

  const payload = {
    message: String(text || "").trim(),
    lang: state.lang,
    use_web: !!useWeb,
    max_iterations: Number(maxIterations || 3),
    max_total_tool_calls: Number(maxTotalToolCalls || 8),
    synthesize: !!synthesize,
  };

  const res = await fetchWithTimeout(endpoints.conversationAgentRun(convId), {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(payload),
  }, { timeout: 0, retries: 0 });

  const data = await safeJson(res);
  if (!res.ok) {
    const msg = data?.detail || data?.error || `HTTP ${res.status}`;
    appendBubble(String(msg), "error");
    return;
  }

  const ctx = deriveContextFromAgentStep(data);
  ctx.source_plan = "tool-first-run";
  ctx.next_step = String(data?.iterations?.slice(-1)?.[0]?.plan?.next_step || ctx.next_step || "").trim() || ctx.next_step;
  ctx.stop_reason =
    String(data?.stop_reason || "").trim()
    || String(data?.iterations?.slice(-1)?.[0]?.stop_candidate || "").trim()
    || null;
  const answer = sanitizeAssistantAnswerText(data?.response || "");
  if (answer) appendBubble(answer, "bot", true, ctx);
  else appendBubble(es ? "Sin respuesta del agente." : "Agent returned empty response.", "error");
  appendSourceUsageNotice(ctx);

  state.lastChatContext = ctx;
  updateModeIndicator();

  const sources = normalizeWebResults(data?.sources || []);
  renderResponseSources(text, sources, ctx, data);

  loadConversationTurns({ force: true });
  loadConversationEvents({ force: true });
}

async function handleWeb(query) {
  // Try /websearch for sources (best-effort). Even if it fails or returns 0 items,
  // we still want to surface "web unavailable → using local" to avoid confusion.
  let results = [];
  let meta = null;
  try {
    const res = await webSearch(query);
    results = Array.isArray(res?.results) ? res.results : [];
    meta = res?.meta && typeof res.meta === "object" ? res.meta : null;
  } catch (err) {
    meta = { status: "unavailable", source: "unavailable", provider: "", results: 0 };
    console.warn("webSearch failed; continuing in backend web mode", err);
  }

  const ctx = {
    source_plan: state.activeProjectId ? "local+web" : "web_only",
    source_origin: state.activeProjectId ? ["local", "web"] : ["web"],
    active_project_id: state.activeProjectId || null,
    web_status: meta?.status || (results.length ? "live" : "unavailable"),
    web_source: meta?.source || (results.length ? "live" : "not-used"),
    web_provider: meta?.provider || "",
    web_results: meta?.results || results.length,
    using_live_web: meta?.source === "live",
    using_cached_web: meta?.source === "cache",
    using_stale_cache: meta?.source === "stale-cache",
    data_notice: buildDataNoticeFromMeta(meta, !!state.activeProjectId),
    project_summary: state.activeProjectDetail?.summary || "",
    entrypoints: state.activeProjectDetail?.entrypoints || [],
    dependencies: state.activeProjectDetail?.dependencies || [],
    configs: state.activeProjectDetail?.configs || [],
  };

  state.lastChatContext = ctx;
  updateModeIndicator();
  renderSourceOriginBar(state.lastChatContext);
  renderResponseSources(query, results, ctx, null);

  if (results.length) {
    // Keep chat bubbles clean; source discovery is already visible in the sources panel.
    if (state.debugTraceEnabled) {
      appendBubble(
        state.lang === LANG.ES
          ? `Encontré ${results.length} fuentes. Ahora te respondo con contexto.`
          : `Found ${results.length} sources. Now answering with context.`,
        "bot"
      );
    }
  }
  // Then ask backend chat in web mode (so it can answer)
  const chatResult = await handleChat(query, { mode: "web" });
  const mergedContext = mergePrefetchedWebContext(ctx, chatResult?.context, results, chatResult?.sources || []);
  if (mergedContext && mergedContext !== chatResult?.context) {
    state.lastChatContext = mergedContext;
    updateModeIndicator();
    renderSourceOriginBar(state.lastChatContext);
    renderResponseSources(query, results, mergedContext, null);
  }
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
  return {
    results: normalizeWebResults(data),
    meta: data?.meta && typeof data.meta === "object" ? data.meta : null,
  };
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
  renderResponseSources(url, [{ url, title, snippet }], {
    source_plan: "web_only",
    source_origin: ["web"],
    active_project_id: state.activeProjectId || null,
    project_summary: state.activeProjectDetail?.summary || "",
  }, data);

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

function prettySourcePlan(plan) {
  const es = state.lang === LANG.ES;
  const value = String(plan || "").trim();
  if (value === "local+web") return es ? "híbrido" : "hybrid";
  if (value === "local_only") return es ? "local" : "local";
  if (value === "web_only") return es ? "web" : "web";
  return value || (es ? "desconocido" : "unknown");
}

function prettyOriginLabel(origin) {
  const es = state.lang === LANG.ES;
  const value = String(origin || "").trim();
  const labels = {
    manifest: es ? "manifiesto" : "manifest",
    local: es ? "local" : "local",
    web: es ? "web" : "web",
    log: es ? "logs" : "logs",
    model: es ? "modelo" : "model",
  };
  return labels[value] || value;
}

function prettyWebStatusLabel(context) {
  const es = state.lang === LANG.ES;
  const source = String(context?.web_source || "").trim();
  const status = String(context?.web_status || "").trim();
  const labels = {
    live: es ? "web en vivo" : "live web",
    cache: es ? "web en caché" : "cached web",
    "stale-cache": es ? "caché web vieja" : "stale web cache",
    cooldown: es ? "web en cooldown" : "web cooldown",
    unavailable: es ? "solo local (web no disponible)" : "local only (web unavailable)",
    error: es ? "solo local (error web)" : "local only (web error)",
    "not-used": es ? "web auto (solo local)" : "web auto (local only)",
  };
  return labels[source || status] || labels[status] || "";
}

function formatCryptoPredictionRef(ref, options = {}) {
  if (!ref || typeof ref !== "object") return "";
  const es = !!options.es;
  const includeSource = options.includeSource !== false;
  const includeId = options.includeId !== false;
  const symbol = String(ref.symbol || "").trim().toUpperCase();
  const horizon = Number(ref.horizon_minutes || ref.horizon || 0);
  const logId = String(ref.log_id || ref.id || "").trim();
  const ts = Number(ref.ts || ref.timestamp || 0);
  const source = String(ref.source || "").trim().toLowerCase();
  const parts = [];
  if (symbol) parts.push(symbol);
  if (Number.isFinite(horizon) && horizon > 0) parts.push(`H=${Math.trunc(horizon)}m`);
  if (includeId && logId) parts.push(logId.slice(0, 12));
  if (Number.isFinite(ts) && ts > 0) {
    const ms = ts > 1e12 ? ts : ts * 1000;
    try {
      parts.push(new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
    } catch (_err) {
      // Ignore invalid timestamps in UI formatting.
    }
  }
  if (includeSource && source) {
    const sourceLabel =
      source === "fresh" ? (es ? "nueva" : "fresh")
      : source === "history" ? (es ? "guardada" : "saved")
      : source;
    parts.push(sourceLabel);
  }
  return parts.join(" • ");
}

function formatCryptoOutcomeRefMetrics(ref, options = {}) {
  if (!ref || typeof ref !== "object") return "";
  const es = !!options.es;
  const deltaPct = Number(ref.delta_pct);
  const grossReturnPct = Number(ref.gross_return_pct);
  const netReturnPct = Number(ref.net_return_pct);
  const probabilityError = Number(ref.probability_error);
  const brierComponent = Number(ref.brier_component);
  const confidenceBucket = String(ref.confidence_bucket || "").trim().toLowerCase();
  const parts = [];
  if (Number.isFinite(deltaPct)) parts.push(`Δ ${formatPct(deltaPct, 2)}`);
  if (Number.isFinite(grossReturnPct)) parts.push(`${es ? "Bruto" : "Gross"} ${formatPct(grossReturnPct, 2)}`);
  if (Number.isFinite(netReturnPct)) parts.push(`${es ? "Neto" : "Net"} ${formatPct(netReturnPct, 2)}`);
  if (Number.isFinite(probabilityError)) parts.push(`${es ? "Error prob" : "Prob err"} ${formatPct(probabilityError, 2)}`);
  if (Number.isFinite(brierComponent)) parts.push(`Brier ${brierComponent.toFixed(3)}`);
  if (confidenceBucket) parts.push(`${es ? "Conf" : "Conf"} ${confidenceBucket}`);
  return parts.join(" • ");
}

function buildDataNoticeFromMeta(meta, hasLocalProject = false) {
  const es = state.lang === LANG.ES;
  const source = String(meta?.source || "").trim();
  const status = String(meta?.status || "").trim();
  if (source === "live") return es ? "Usando fuentes web en vivo." : "Using live web sources.";
  if (source === "cache") return es ? "Usando fuentes web en caché." : "Using cached web sources.";
  if (source === "stale-cache") return es ? "La web en vivo no estuvo disponible; usando caché almacenada." : "Live web was unavailable; using stored cache.";
  if (status === "cooldown") {
    if (hasLocalProject) {
      return es ? "La web está en cooldown; respondiendo con datos locales del proyecto (y/o caché)." : "Web is in cooldown; answering with local project data (and/or cache).";
    }
    return es ? "La web está en cooldown; respondiendo con datos locales almacenados (y/o caché)." : "Web is in cooldown; answering with local stored data (and/or cache).";
  }
  if (status === "unavailable" || status === "error") {
    if (hasLocalProject) {
      return es ? "La web no estuvo disponible; respondiendo con datos locales del proyecto." : "Web was unavailable; answering with local project data.";
    }
    return es ? "La web no estuvo disponible; respondiendo con datos locales almacenados." : "Web was unavailable; answering with local stored data.";
  }
  if (hasLocalProject) return es ? "Respondiendo con datos locales del proyecto." : "Answering with local project data.";
  return es ? "Respondiendo con datos locales almacenados." : "Answering with local stored data.";
}

function formatModeRuntimeHint(context) {
  if (!context || typeof context !== "object") return "";
  const es = state.lang === LANG.ES;
  if (context.using_live_web) return es ? "web en vivo" : "live web";
  if (context.using_cached_web) return es ? "web en caché" : "cached web";
  if (context.using_stale_cache) return es ? "caché web" : "web cache";
  if (String(context.web_status || "") === "cooldown") {
    return es ? "cooldown → local" : "cooldown → local";
  }
  if (String(context.web_status || "") === "unavailable") {
    return es ? "web no disp. → local" : "web unavailable → local";
  }
  if (String(context.web_status || "") === "not-used" && context.active_project_id) {
    return es ? "web auto → proyecto local" : "web auto → local project";
  }
  if (String(context.web_status || "") === "not-used") {
    return es ? "web auto → local" : "web auto → local";
  }
  return "";
}

function renderSourceOriginBar(context = null) {
  if (!dom.sourceOriginBar) return;
  dom.sourceOriginBar.innerHTML = "";
  const es = state.lang === LANG.ES;
  const debugMode = !!state.debugTraceEnabled;
  if (!context || typeof context !== "object") return;

  const addPill = (className, label, value) => {
    const text = String(value || "").trim();
    if (!text) return;
    dom.sourceOriginBar.appendChild(el("span", { class: `origin-pill ${className}`, text: `${label}: ${text}` }));
  };

  const addNote = (text) => {
    const value = String(text || "").trim();
    if (!value) return;
    dom.sourceOriginBar.appendChild(el("div", { class: "origin-note", text: value }));
  };

  if (debugMode && context.source_plan) {
    dom.sourceOriginBar.appendChild(el("span", { class: "origin-pill plan", text: `${es ? "Plan" : "Plan"}: ${prettySourcePlan(context.source_plan)}` }));
  }
  const origins = Array.isArray(context.source_origin) ? context.source_origin : [];
  origins.forEach((origin) => {
    dom.sourceOriginBar.appendChild(el("span", { class: `origin-pill ${origin}`, text: prettyOriginLabel(origin) }));
  });
  const webStatusLabel = prettyWebStatusLabel(context);
  if (webStatusLabel) {
    const webStatusClass =
      context.using_live_web ? "web-live" :
      context.using_cached_web ? "web-cache" :
      context.using_stale_cache ? "web-stale" :
      String(context.web_status || "") === "unavailable" ? "web-unavailable" :
      "web-local";
    dom.sourceOriginBar.appendChild(el("span", { class: `origin-pill ${webStatusClass}`, text: webStatusLabel }));
  }
  if (debugMode && context.web_provider) {
    dom.sourceOriginBar.appendChild(el("span", { class: "origin-pill provider", text: `${es ? "Provider" : "Provider"}: ${context.web_provider}` }));
  }
  if (debugMode) {
    addPill("plan", es ? "Tarea" : "Task", context.current_task);
    addPill("plan", es ? "Subtarea" : "Subtask", context.current_subtask);
    addPill("focus", es ? "Archivo" : "File", context.current_file_focus);
    addPill("focus", es ? "Símbolo" : "Symbol", context.current_symbol_focus);
    addPill("focus", es ? "Artefacto" : "Artifact", context.current_artifact_focus);
    addPill("provider", es ? "Tool usada" : "Used tool", context.effective_tool);
    addPill("provider", es ? "Estado tool" : "Tool status", context.effective_tool_status);
    addPill("provider", es ? "Siguiente tool" : "Next tool", context.next_tool);
    addPill("plan", es ? "Siguiente paso" : "Next step", context.next_step);
    addPill("plan", es ? "Stop" : "Stop", plannerStopReason(context));
    if (Array.isArray(context.tool_candidates) && context.tool_candidates.length) {
      addNote(`${es ? "Tools candidatas" : "Tool candidates"}: ${context.tool_candidates.slice(0, 4).join(", ")}`);
    }
    addPill(context.llm_required ? "provider" : "plan", es ? "LLM" : "LLM", context.llm_required ? "required" : "bypassed");
  }
  if (context.active_project_id) {
    dom.sourceOriginBar.appendChild(
      el("span", { class: "project-badge project-badge-active", text: `${es ? "Proyecto" : "Project"}: ${context.active_project_id}` })
    );
  }
  if (context.crypto_prediction_ref) {
    addPill("focus", es ? "Pred" : "Pred", formatCryptoPredictionRef(context.crypto_prediction_ref, { es }));
  }
  if (context.data_notice) {
    addNote(context.data_notice);
  }
  if (debugMode && Array.isArray(context.missing_evidence) && context.missing_evidence.length) {
    addNote(`${es ? "Falta evidencia" : "Missing evidence"}: ${context.missing_evidence.join(", ")}`);
  }
  if (debugMode && Array.isArray(context.recent_tool_failures) && context.recent_tool_failures.length) {
    const recent = context.recent_tool_failures
      .slice(-2)
      .map((item) => {
        if (!item || typeof item !== "object") return "";
        const tool = String(item.tool || item.kind || "").trim();
        const reason = String(item.reason || item.status || "").trim();
        return [tool, reason].filter(Boolean).join(" -> ");
      })
      .filter(Boolean);
    if (recent.length) {
      addNote(`${es ? "Fallos recientes" : "Recent tool failures"}: ${recent.join(" | ")}`);
    }
  }
  if (debugMode && context.web_query) {
    const displayQuery = formatDisplayQuery(context.web_query);
    if (displayQuery) {
      dom.sourceOriginBar.appendChild(el("div", { class: "origin-query", text: `${es ? "Query" : "Query"}: ${displayQuery}` }));
    }
  }
}

function renderBubbleTrace(node, context = null) {
  if (!node || !context || typeof context !== "object") return;
  const es = state.lang === LANG.ES;
  const wrap = el("div", { class: "bubble-trace" });

  const addTracePill = (className, label, value) => {
    const text = String(value || "").trim();
    if (!text) return;
    wrap.appendChild(el("span", { class: `bubble-trace-pill ${className}`.trim(), text: `${label}: ${text}` }));
  };

  if (context.source_plan) addTracePill("plan", es ? "Plan" : "Plan", prettySourcePlan(context.source_plan));
  const origins = Array.isArray(context.source_origin) ? context.source_origin : [];
  if (origins.length) addTracePill("origin", es ? "Origen" : "Origin", origins.map(prettyOriginLabel).join(", "));

  const webLabel = prettyWebStatusLabel(context);
  if (webLabel) addTracePill("web", es ? "Datos" : "Data", webLabel);
  if (context.web_provider) addTracePill("provider", "Provider", context.web_provider);
  if (context.next_tool) addTracePill("tool", es ? "Tool" : "Tool", context.next_tool);
  const stopReason = plannerStopReason(context);
  if (stopReason) addTracePill("plan", es ? "Stop" : "Stop", stopReason);
  if (context.current_artifact_focus) addTracePill("focus", es ? "Artefacto" : "Artifact", context.current_artifact_focus);
  if (context.effective_tool) addTracePill("tool", es ? "Usada" : "Used", context.effective_tool);
  if (context.effective_tool_status) addTracePill("provider", es ? "Estado" : "Status", context.effective_tool_status);
  if (context.active_project_id) addTracePill("project", es ? "Proyecto" : "Project", context.active_project_id);
  if (context.crypto_prediction_ref) addTracePill("focus", es ? "Pred" : "Pred", formatCryptoPredictionRef(context.crypto_prediction_ref, { es }));
  addTracePill("llm", "LLM", context.llm_required ? "required" : "bypassed");

  if (context.data_notice) {
    wrap.appendChild(el("div", { class: "bubble-trace-note", text: context.data_notice }));
  }

  if (wrap.childNodes.length) {
    node.appendChild(wrap);
  }
}

function renderResponseSources(query, results, context = null, raw = null) {
  if (!dom.sourcesContent) return;
  renderSourceOriginBar(context);

  const seen = new Set();
  const rows = [];
  for (const r of results || []) {
    const u = (r?.url || "").trim();
    if (!u || seen.has(u)) continue;
    seen.add(u);
    rows.push({ url: u, title: (r?.title || "").trim(), snippet: (r?.snippet || "").trim() });
  }

  dom.sourcesContent.innerHTML = "";

  const es = state.lang === LANG.ES;
  const displayQuery = formatDisplayQuery(query || context?.web_query || "");
  const label = rows.length
    ? (es ? `Fuentes para: "${displayQuery}"` : `Sources for: "${displayQuery}"`)
    : (es ? "Contexto de respuesta" : "Response context");
  const header = el("div", { text: label });
  header.style.marginBottom = "6px";
  header.style.fontWeight = "600";
  dom.sourcesContent.appendChild(header);

  if (state.mode === MODES.WEB && context && typeof context === "object") {
    const src = String(context.web_source || context.web_status || "").trim();
    const esWarn = (msgEs, msgEn) => (es ? msgEs : msgEn);
    let warn = "";
    if (src === "unavailable" || src === "error") {
      warn = esWarn(
        "Web no disponible ahora mismo; respondiendo con datos locales/caché.",
        "Web is unavailable right now; answering with local/cache data."
      );
    } else if (src === "stale-cache") {
      warn = esWarn(
        "Web en vivo no estuvo disponible; usando caché almacenada.",
        "Live web was unavailable; using stored cache."
      );
    } else if (src === "not-used" && !context.using_live_web && !context.using_cached_web) {
      warn = esWarn(
        "Estás en modo Web, pero no se usó web en esta respuesta.",
        "You are in Web mode, but web was not used for this response."
      );
    }
    if (warn) dom.sourcesContent.appendChild(el("div", { class: "notice-warn", text: warn }));
  }

  if (context && typeof context === "object") {
    const debugMode = !!state.debugTraceEnabled;
    const evidenceCard = el("div", { class: "project-meta-card" });
    const evidenceHead = el("div", { class: "project-meta-head" });
    evidenceHead.appendChild(el("strong", { text: es ? "Evidencia usada" : "Evidence used" }));
    if (AGENT_UI_ENABLED && state.conversationId) {
      const btn = el("button", { class: "icon-btn small", text: es ? "Ver turn" : "View turn" });
      btn.type = "button";
      btn.title = es ? "Abrir el último turn (traza del agente)" : "Open latest turn (agent trace)";
      btn.addEventListener("click", () => openLatestTurnDetail());
      evidenceHead.appendChild(btn);
    }
    evidenceCard.appendChild(evidenceHead);
    const list = el("div", { class: "mini-list" });
    if (debugMode && context.source_plan) {
      list.appendChild(el("span", { class: "mini-chip", text: `${es ? "Plan" : "Plan"}: ${prettySourcePlan(context.source_plan)}` }));
    }
    const origins = Array.isArray(context.source_origin) ? context.source_origin : [];
    if (debugMode && origins.length) {
      list.appendChild(el("span", { class: "mini-chip", text: `${es ? "Origen" : "Origin"}: ${origins.map(prettyOriginLabel).join(", ")}` }));
    }
    if (debugMode && context.web_provider) {
      list.appendChild(el("span", { class: "mini-chip", text: `Provider: ${context.web_provider}` }));
    }
    if (debugMode && context.effective_tool) {
      list.appendChild(el("span", { class: "mini-chip", text: `${es ? "Tool usada" : "Used tool"}: ${context.effective_tool}` }));
    }
    if (debugMode && context.effective_tool_status) {
      list.appendChild(el("span", { class: "mini-chip", text: `${es ? "Estado tool" : "Tool status"}: ${context.effective_tool_status}` }));
    }
    if (debugMode && context.current_file_focus) {
      list.appendChild(el("span", { class: "mini-chip", text: `${es ? "Archivo" : "File"}: ${context.current_file_focus}` }));
    }
    if (debugMode && context.current_symbol_focus) {
      list.appendChild(el("span", { class: "mini-chip", text: `${es ? "Símbolo" : "Symbol"}: ${context.current_symbol_focus}` }));
    }
    if (debugMode && context.current_artifact_focus) {
      list.appendChild(el("span", { class: "mini-chip", text: `${es ? "Artefacto" : "Artifact"}: ${context.current_artifact_focus}` }));
    }
    if (context.crypto_prediction_ref) {
      list.appendChild(
        el("span", {
          class: "mini-chip",
          text: `${es ? "Pred usada" : "Prediction used"}: ${formatCryptoPredictionRef(context.crypto_prediction_ref, { es })}`,
        })
      );
    }
    if (debugMode && context.next_tool) {
      list.appendChild(el("span", { class: "mini-chip", text: `${es ? "Tool" : "Tool"}: ${context.next_tool}` }));
    }
    const stopReason = debugMode ? plannerStopReason(context) : "";
    if (debugMode && stopReason) {
      list.appendChild(el("span", { class: "mini-chip subtle", text: `${es ? "Stop" : "Stop"}: ${stopReason}` }));
    }
    if (debugMode && context.llm_required === false) {
      list.appendChild(el("span", { class: "mini-chip", text: "LLM: bypassed" }));
    } else if (debugMode && context.llm_required === true) {
      list.appendChild(el("span", { class: "mini-chip", text: "LLM: required" }));
    }
    if (debugMode && list.childNodes.length) {
      evidenceCard.appendChild(list);
    }
    if (debugMode && context.next_step) {
      evidenceCard.appendChild(el("div", { class: "project-summary-text", text: `${es ? "Siguiente paso" : "Next step"}: ${context.next_step}` }));
    }
    if (debugMode && Array.isArray(context.missing_evidence) && context.missing_evidence.length) {
      evidenceCard.appendChild(el("div", { class: "project-summary-text subtle", text: `${es ? "Falta evidencia" : "Missing evidence"}: ${context.missing_evidence.join(", ")}` }));
    }
    if (debugMode && Array.isArray(context.web_findings) && context.web_findings.length) {
      evidenceCard.appendChild(el("div", { class: "project-summary-text subtle", text: `${es ? "Hallazgos web" : "Web findings"}: ${context.web_findings.slice(0, 3).join(" • ")}` }));
    }

    // Codex-like: big CTA for pending approvals (sensitive tools).
    const pending = context.pending_approval && typeof context.pending_approval === "object" ? context.pending_approval : null;
    if (AGENT_UI_ENABLED && pending && pending.tool && state.conversationId) {
      const toolName = String(pending.tool || "").trim();
      if (toolName) {
        const btn = el("button", {
          class: "action-btn danger",
          text: es ? `Aprobar y ejecutar: ${toolName}` : `Approve & run: ${toolName}`,
          attrs: { type: "button" },
        });
        btn.title = es ? "Ejecuta la acción sensible con aprobación explícita." : "Runs the sensitive action with explicit approval.";
        btn.addEventListener("click", async () => {
          if (state.pending) return;
          const args = {};
          if (toolName === "delete_project" && state.activeProjectId) args.project_id = state.activeProjectId;
          try {
            setPending(true);
            appendTyping(getWorkPendingLabel("action"));
            const resp = await executeConversationTool(toolName, args, {
              autoApprove: true,
              title: toolName,
              continueAfter: true,
              continueUseWeb: state.mode === MODES.WEB,
              continueSynthesize: true,
              continueMaxIterations: 2,
              continueMaxTotalToolCalls: 6,
              continueMaxToolRetries: 1,
              continueToolRetryBackoffMs: 150,
            });
            const execCtx = resp && typeof resp === "object" && resp.context && typeof resp.context === "object"
              ? resp.context
              : (state.lastChatContext && typeof state.lastChatContext === "object" ? state.lastChatContext : null);
            if (!resp?.continued && (execCtx?.next_step || execCtx?.next_tool)) {
              await handleAgentContinue({ useWeb: state.mode === MODES.WEB, synthesize: true });
            }
          } catch (err) {
            console.error(err);
          } finally {
            removeTyping();
            setPending(false);
            updateStatusCenter();
          }
        });
        evidenceCard.appendChild(btn);
      }
    }

    // Codex-like: suggested actions from the backend plan (1-click tools + optional continue).
    const actions = Array.isArray(context.actions) ? context.actions : [];
    if (AGENT_UI_ENABLED && actions.length && state.conversationId) {
      const actionWrap = el("div", { class: "mini-actions" });
      const needsProjectId = new Set([
        "project_files",
        "project_symbols",
        "project_excerpt",
        "project_entrypoints",
        "project_dependencies",
        "project_configs",
        "project_architecture",
        "delete_project",
      ]);

      const labelFor = (a) => {
        const raw = es ? a?.label_es : a?.label_en;
        return String(raw || a?.tool || "tool").trim();
      };

      const pickNextSafeAction = (ctx) => {
        const items = Array.isArray(ctx?.actions) ? ctx.actions : [];
        return items.find((a) => {
          const tool = String(a?.tool || "").trim();
          const risk = String(a?.risk || "").trim().toLowerCase();
          if (!tool) return false;
          if (risk === "sensitive") return false;
          if (tool === "delete_project") return false;
          return true;
        }) || null;
      };

      const autoRunSafeChain = async (maxSteps = 3) => {
        if (state.pending) return;
        if (!state.conversationId) return;
        setPending(true);
        appendTyping(getWorkPendingLabel("action"));
        try {
          for (let i = 0; i < maxSteps; i++) {
            const ctx = state.lastChatContext && typeof state.lastChatContext === "object" ? state.lastChatContext : null;
            if (!ctx) break;
            if (ctx.pending_approval) {
              appendBubble(es ? "Hay una aprobación pendiente. Ejecuta la acción sensible manualmente." : "There is a pending approval. Run the sensitive action manually.", "error");
              break;
            }
            const next = pickNextSafeAction(ctx);
            if (!next) {
              appendBubble(es ? "No hay más acciones seguras para ejecutar." : "No more safe actions to run.", "bot");
              break;
            }
            // Reuse the existing single-action path (it keeps project UI in sync + continues when needed).
            await runSuggestedAction(next);
            // If the last continue produced another approval gate, stop here.
            const after = state.lastChatContext && typeof state.lastChatContext === "object" ? state.lastChatContext : null;
            if (after?.pending_approval) break;
          }
        } finally {
          removeTyping();
          setPending(false);
          updateStatusCenter();
        }
      };

      const runSuggestedAction = async (a) => {
        const tool = String(a?.tool || "").trim();
        if (!tool) return;
        if (state.pending) return;
        if (!state.conversationId) return;
        if (needsProjectId.has(tool) && !state.activeProjectId) {
          appendBubble(es ? "No hay proyecto activo para ejecutar esa tool." : "No active project for that tool.", "error");
          return;
        }
        const baseArgs = (a?.args && typeof a.args === "object") ? a.args : {};
        const args = { ...baseArgs };
        if (needsProjectId.has(tool) && !args.project_id) {
          args.project_id = state.activeProjectId;
        }

        setPending(true);
        appendTyping(getWorkPendingLabel("action"));
        try {
          const shouldContinueRequested =
            tool === "delete_project"
            || !!(state.lastChatContext && state.lastChatContext.next_step)
            || !!(state.lastChatContext && state.lastChatContext.next_tool);
          const toolResp = await executeConversationTool(tool, args, {
            autoApprove: false,
            title: labelFor(a),
            continueAfter: shouldContinueRequested,
            continueUseWeb: state.mode === MODES.WEB,
            continueSynthesize: true,
            continueMaxIterations: 2,
            continueMaxTotalToolCalls: 6,
            continueMaxToolRetries: 1,
            continueToolRetryBackoffMs: 150,
          });
          // Keep UI in sync after side-effect tools.
          if (tool === "delete_project") {
            await setActiveProject("", { bindConversation: false, loadDetail: true });
            setManualProjectRoot("");
            await loadRegisteredProjects();
            loadProjectTree();
          } else if (state.activeProjectId) {
            await loadActiveProjectDetail(state.activeProjectId);
          }
          scheduleSnapshot(700);

          const execCtx = toolResp && typeof toolResp === "object" && toolResp.context && typeof toolResp.context === "object"
            ? toolResp.context
            : (state.lastChatContext && typeof state.lastChatContext === "object" ? state.lastChatContext : null);
          const shouldContinue =
            tool === "delete_project"
            || !!execCtx?.next_step
            || !!execCtx?.next_tool;
          const alreadyContinued = !!(toolResp && typeof toolResp === "object" && toolResp.continued);
          if ((shouldContinue || shouldContinueRequested) && !alreadyContinued && !(execCtx && execCtx.pending_approval)) {
            await handleAgentContinue({ useWeb: state.mode === MODES.WEB, synthesize: true });
          }
        } catch (err) {
          if (err?.name === "AbortError") return;
          console.error(err);
        } finally {
          removeTyping();
          setPending(false);
          updateStatusCenter();
        }
      };

      // Primary CTA: run the next safe action (reduces clicks in long dev sessions).
      const nextSafe = actions.find((a) => {
        const tool = String(a?.tool || "").trim();
        const risk = String(a?.risk || "").trim().toLowerCase();
        if (!tool) return false;
        if (risk === "sensitive") return false;
        if (tool === "delete_project") return false;
        return true;
      });
      if (nextSafe) {
        const btn = el("button", { class: "action-btn", text: es ? "Ejecutar siguiente (safe)" : "Run next (safe)" });
        btn.type = "button";
        btn.title = es ? "Ejecuta la siguiente acción segura y continúa el agente" : "Run the next safe action and continue the agent";
        btn.addEventListener("click", () => runSuggestedAction(nextSafe));
        actionWrap.appendChild(btn);

        const autoBtn = el("button", { class: "action-btn", text: es ? "Auto-run safe ×3" : "Auto-run safe ×3" });
        autoBtn.type = "button";
        autoBtn.title = es
          ? "Ejecuta hasta 3 acciones seguras + continuar agente automáticamente."
          : "Runs up to 3 safe actions + auto-continues the agent.";
        autoBtn.addEventListener("click", () => autoRunSafeChain(3));
        actionWrap.appendChild(autoBtn);
      }

      actions.slice(0, 5).forEach((a) => {
        const tool = String(a?.tool || "").trim();
        if (!tool) return;
        const risk = String(a?.risk || "").trim().toLowerCase();
        const btn = el("button", { class: `action-btn ${risk === "sensitive" ? "danger" : ""}`, text: labelFor(a) });
        btn.type = "button";
        btn.title = es ? `Ejecutar tool: ${tool}` : `Run tool: ${tool}`;
        btn.addEventListener("click", () => runSuggestedAction(a));
        actionWrap.appendChild(btn);
      });

      evidenceCard.appendChild(el("div", { class: "project-summary-text", text: es ? "Acciones sugeridas:" : "Suggested actions:" }));
      evidenceCard.appendChild(actionWrap);
    }

    if (AGENT_UI_ENABLED && context.next_step && state.conversationId) {
      const btn = el("button", { class: "action-btn", text: es ? "Continuar agente" : "Continue agent" });
      btn.type = "button";
      btn.title = es ? "Continuar desde next_step (tool-first)" : "Continue from next_step (tool-first)";
      btn.addEventListener("click", async () => {
        if (state.pending) return;
        try {
          setPending(true);
          appendTyping(getWorkPendingLabel("agent"));
          await handleAgentContinue({ useWeb: state.mode === MODES.WEB, synthesize: true });
        } finally {
          removeTyping();
          setPending(false);
        }
      });
      evidenceCard.appendChild(btn);
    }

    const toolOut = debugMode ? String(context.effective_tool_output || "").trim() : "";
    if (debugMode && toolOut) {
      evidenceCard.appendChild(el("div", { class: "project-summary-text", text: es ? "Salida de tool:" : "Tool output:" }));
      evidenceCard.appendChild(el("pre", { class: "tool-output-pre", text: toolOut }));
    }

    // Agent step evidence ledger (when available).
    const rawEvidence = debugMode && raw && typeof raw === "object" ? normalizeEvidence(raw?.evidence || []) : [];
    const rawIterations = debugMode && raw && typeof raw === "object" && Array.isArray(raw?.iterations) ? raw.iterations : [];
    if (debugMode && AGENT_UI_ENABLED && rawEvidence.length) {
      evidenceCard.appendChild(el("div", { class: "project-summary-text", text: es ? "Ledger de evidencia:" : "Evidence ledger:" }));
      const evList = el("div", { class: "mini-list" });
      rawEvidence.slice(0, 10).forEach((ev) => {
        const origin = ev.origin ? prettyOriginLabel(ev.origin) : "local";
        const head = [origin, ev.kind].filter(Boolean).join(" • ");
        const tail = ev.path || ev.title || "";
        const label = tail ? `${head}: ${tail}` : head;
        evList.appendChild(el("span", { class: `mini-chip ${ev.origin === "web" ? "warn" : ""}`, text: label }));
      });
      evidenceCard.appendChild(evList);
      const firstText = rawEvidence.find((ev) => (ev.text || "").trim())?.text || "";
      if (firstText) {
        evidenceCard.appendChild(el("pre", { class: "tool-output-pre", text: String(firstText).trim().slice(0, 1200) }));
      }
    }
    if (debugMode && AGENT_UI_ENABLED && rawIterations.length) {
      evidenceCard.appendChild(el("div", { class: "project-summary-text", text: es ? "Iteraciones:" : "Iterations:" }));
      const itList = el("div", { class: "mini-list" });
      rawIterations.slice(0, 8).forEach((it) => {
        const n = Number(it?.iteration || 0) || 0;
        const toolCalls = Number(it?.tool_calls || 0) || 0;
        const newEv = Number(it?.new_evidence || 0) || 0;
        const nextTool = String(it?.plan?.next_tool || "").trim();
        const missing = Array.isArray(it?.plan?.missing_evidence) ? it.plan.missing_evidence : [];
        const label = [
          n ? `#${n}` : "#",
          nextTool ? `next:${nextTool}` : "",
          `tools:${toolCalls}`,
          `+ev:${newEv}`,
          missing.length ? `missing:${missing.slice(0, 2).join("|")}` : "",
        ].filter(Boolean).join(" • ");
        itList.appendChild(el("span", { class: "mini-chip", text: label }));
      });
      evidenceCard.appendChild(itList);
    }
    dom.sourcesContent.appendChild(evidenceCard);
  }

  const sourcePlan = String(context?.source_plan || "").trim();
  const showProjectContext = sourcePlan === "local_only";

  const summary = showProjectContext ? String(context?.project_summary || "").trim() : "";
  if (summary) {
    const summaryCard = el("div", { class: "project-meta-card" });
    summaryCard.appendChild(el("strong", { text: es ? "Proyecto activo" : "Active project" }));
    summaryCard.appendChild(el("div", { class: "project-summary-text", text: summary }));
    dom.sourcesContent.appendChild(summaryCard);
  }

  const architectureSummary = showProjectContext ? String(context?.architecture_summary || "").trim() : "";
  if (architectureSummary) {
    const architectureCard = el("div", { class: "project-meta-card" });
    architectureCard.appendChild(el("strong", { text: es ? "Arquitectura" : "Architecture" }));
    architectureCard.appendChild(el("div", { class: "project-summary-text", text: architectureSummary }));
    dom.sourcesContent.appendChild(architectureCard);
  }

  const sections = [
    { label: es ? "Entrypoints" : "Entrypoints", items: showProjectContext ? (context?.entrypoints || []) : [] },
    { label: es ? "Dependencias" : "Dependencies", items: showProjectContext ? (context?.dependencies || []) : [] },
    { label: es ? "Configs" : "Configs", items: showProjectContext ? (context?.configs || []) : [] },
    { label: es ? "Hallazgos web" : "Web findings", items: context?.web_findings || [] },
  ];
  if (sections.some((section) => Array.isArray(section.items) && section.items.length)) {
    const grid = el("div", { class: "project-meta-grid" });
    sections.forEach((section) => {
      if (!Array.isArray(section.items) || !section.items.length) return;
      const card = el("div", { class: "project-meta-card" });
      card.appendChild(el("strong", { text: section.label }));
      const list = el("div", { class: "mini-list" });
      section.items.slice(0, 8).forEach((item) => list.appendChild(el("span", { class: "mini-chip", text: String(item) })));
      card.appendChild(list);
      grid.appendChild(card);
    });
    dom.sourcesContent.appendChild(grid);
  }

  if (!rows.length) {
    dom.sourcesContent.appendChild(el("div", { text: es ? "Sin URLs adicionales." : "No additional URLs." }));
    if (state.debugTraceEnabled && raw != null) {
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
    const icon = el("i", { class: "fa-solid fa-up-right-from-square", attrs: { "aria-hidden": "true" } });
    a.appendChild(icon);
    a.appendChild(document.createTextNode(" "));
    a.appendChild(document.createTextNode(r.title ? String(r.title) : String(r.url)));
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

function renderWebSources(query, results, raw = null) {
  renderResponseSources(query, results, state.lastChatContext, raw);
}

/* ------------------------- IMAGE OCR ------------------------- */

async function analyzeAttachment(file, { showPreview = false } = {}) {
  const es = state.lang === LANG.ES;
  const filename = String(file?.name || "").trim() || "attachment";
  appendBubble(
    es ? `Extrayendo contexto del adjunto: ${filename}...` : `Extracting attachment context: ${filename}...`,
    "bot"
  );

  setPending(true);
  appendTyping(getWorkPendingLabel("attachment"));
  try {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("lang", state.lang);

    const res = await fetchWithTimeout(endpoints.analyzeAttachment, {
      method: "POST",
      body: fd,
    }, { timeout: 90000, retries: 0 });

    const data = await safeJson(res);
    if (!res.ok) {
      const msg = data?.detail || data?.error || (es ? "Falló extracción de contexto del adjunto." : "Attachment context extraction failed.");
      appendBubble(String(msg), "error");
      return;
    }

    const description = String(
      data?.description
      || data?.text
      || data?.ocr
      || data?.result
      || ""
    ).trim() || JSON.stringify(data, null, 2);

    const kind = String(data?.kind || (String(file.type || "").startsWith("image/") ? "image" : "document")).trim();
    const isImage = kind === "image";
    const isImageMode = state.mode === MODES.IMAGE;

    if (isImage && isImageMode) {
      state.imageReferenceFile = file;
      if (showPreview) {
        appendImageBubble({
          localFile: file,
          caption: es
            ? `Imagen de referencia${filename ? `: ${filename}` : ""}`
            : `Reference image${filename ? `: ${filename}` : ""}`,
        });
      }
      appendBubble(
        es
          ? `Imagen de referencia lista: ${filename}. La usaré en modo imagen.`
          : `Reference image ready: ${filename}. I’ll use it in image mode.`,
        "bot"
      );
      return;
    }

    setChatAttachment({
      kind,
      name: filename,
      analysis: description,
    });

    if (showPreview && isImage) {
      appendImageBubble({
        localFile: file,
        caption: es
          ? `Imagen adjunta${filename ? `: ${filename}` : ""}`
          : `Attached image${filename ? `: ${filename}` : ""}`,
      });
    }

    appendBubble(
      es
        ? `Archivo adjunto: ${filename}. Lo usare como contexto en chat. Puedes preguntar "que es esta imagen?", "explica este archivo" o "resume el texto".`
        : `File attached: ${filename}. I will use it as chat context. You can ask "what is this image?", "explain this file", or "summarize the text".`,
      "bot"
    );
  } finally {
    removeTyping();
    setPending(false);
  }
}

/* ------------------------- CRYPTO: MODELS / PREDICT / TRADE ------------------------- */

function tokenizeCommandArgs(input) {
  const src = String(input || "");
  const out = [];
  const re = /"([^"\\]*(?:\\.[^"\\]*)*)"|'([^'\\]*(?:\\.[^'\\]*)*)'|(\S+)/g;
  let m;
  while ((m = re.exec(src)) !== null) {
    out.push((m[1] ?? m[2] ?? m[3] ?? "").replace(/\\(["'])/g, "$1"));
  }
  return out.filter(Boolean);
}

function parseImageCommand(rawText, { allowNatural = false } = {}) {
  const raw = String(rawText || "").trim();
  if (!raw) return null;
  let style3d = false;
  let matched =
    raw.match(/^\/img3d\b\s*(.*)$/i)
    || raw.match(/^\/(?:img|image)\b\s*(.*)$/i)
    || raw.match(/^img:\s*(.*)$/i)
    || raw.match(/^image:\s*(.*)$/i)
    || raw.match(/^generate\s+image:\s*(.*)$/i);
  if (raw.match(/^\/img3d\b/i)) style3d = true;
  if (!matched && allowNatural) {
    matched =
      raw.match(/^(?:generate|create|draw|make)\s+(?:an?\s+)?(?:image\s+(?:of\s+)?)?(.+)$/i)
      || raw.match(/^(?:genera|crea|dibuja|haz)\s+(?:una?\s+)?(?:imagen\s+(?:de\s+)?)?(.+)$/i);
  }
  if (!matched && allowNatural) {
    const looksDirectivePrefix = /^(?:web|url)\s*:|^\/(?!img(?:3d)?\b|image\b)/i.test(raw);
    if (!looksDirectivePrefix && !isImageQuestionPrompt(raw)) {
      matched = [raw, raw];
    }
  }
  if (!matched) return null;

  const tail = String(matched[1] || "").trim();
  const tokens = tokenizeCommandArgs(tail);
  if (!tokens.length) {
    return {
      prompt: "",
      steps: 24,
      seed: null,
      cfg: 7.0,
      width: 512,
      height: 512,
      negative: "",
      style3d,
    };
  }

  const promptTokens = [];
  let steps = 24;
  let seed = null;
  let cfg = 7.0;
  let width = 512;
  let height = 512;
  let negative = "";
  for (let i = 0; i < tokens.length; i += 1) {
    const token = String(tokens[i] || "");
    const next = String(tokens[i + 1] || "");
    const lower = token.toLowerCase();

    if ((lower === "--steps" || lower === "-s") && next) {
      const v = Number.parseInt(next, 10);
      if (Number.isFinite(v)) steps = Math.max(1, Math.min(50, v));
      i += 1;
      continue;
    }
    if (lower === "--seed" && next) {
      const v = Number.parseInt(next, 10);
      if (Number.isFinite(v)) seed = v;
      i += 1;
      continue;
    }
    if (lower === "--cfg" && next) {
      const v = Number.parseFloat(next);
      if (Number.isFinite(v)) cfg = Math.max(1, Math.min(20, v));
      i += 1;
      continue;
    }
    if ((lower === "--width" || lower === "-w") && next) {
      const v = Number.parseInt(next, 10);
      if (Number.isFinite(v)) width = Math.max(256, Math.min(1024, v));
      i += 1;
      continue;
    }
    if ((lower === "--height" || lower === "-h") && next) {
      const v = Number.parseInt(next, 10);
      if (Number.isFinite(v)) height = Math.max(256, Math.min(1024, v));
      i += 1;
      continue;
    }
    if ((lower === "--negative" || lower === "--neg" || lower === "-n") && next) {
      negative = next;
      i += 1;
      continue;
    }
    promptTokens.push(token);
  }

  return {
    prompt: promptTokens.join(" ").trim(),
    steps,
    seed,
    cfg,
    width,
    height,
    negative: String(negative || "").trim(),
    style3d,
  };
}

async function tryHandleImageCommand(text) {
  const cmd = parseImageCommand(text, { allowNatural: state.mode === MODES.IMAGE });
  if (!cmd) return false;
  const es = state.lang === LANG.ES;
  if (!cmd.prompt) {
    appendBubble(
      es
        ? "Falta prompt para imagen. Ejemplo: /img ciudad futurista --steps 28 --seed 42 o /img3d robot en ciudad neon"
        : "Image prompt is missing. Example: /img futuristic city --steps 28 --seed 42 or /img3d robot in neon city",
      "error"
    );
    return true;
  }

  appendBubble(text, "user");
  appendBubble(es ? "Generando imagen..." : "Generating image...", "bot");

  setPending(true);
  try {
    const finalPrompt = cmd.style3d
      ? `high-detail 3d render, cinematic lighting, physically based shading, ${cmd.prompt}`
      : cmd.prompt;
    const hasReference = state.imageReferenceFile instanceof File;
    let res;
    if (hasReference) {
      const fd = new FormData();
      fd.append("prompt", finalPrompt);
      fd.append("lang", state.lang);
      fd.append("include_ocr", "1");
      fd.append("steps", String(cmd.steps));
      fd.append("cfg", String(cmd.cfg));
      fd.append("width", String(cmd.width));
      fd.append("height", String(cmd.height));
      if (cmd.seed != null) fd.append("seed", String(cmd.seed));
      if (cmd.negative) fd.append("negative_prompt", cmd.negative);
      fd.append("file", state.imageReferenceFile, state.imageReferenceFile.name || "reference.png");
      res = await fetchWithTimeout(endpoints.imageGenerateWithReference, {
        method: "POST",
        body: fd,
      }, { timeout: 0, retries: 0 });
    } else {
      const body = {
        prompt: finalPrompt,
        negative_prompt: cmd.negative || undefined,
        steps: cmd.steps,
        cfg: cmd.cfg,
        width: cmd.width,
        height: cmd.height,
        seed: cmd.seed,
      };
      res = await fetchWithTimeout(endpoints.imageGenerate, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }, { timeout: 0, retries: 0 });
    }

    const data = await safeJson(res);
    if (!res.ok) {
      const msg = data?.detail || data?.error || `HTTP ${res.status}`;
      appendBubble(String(msg), "error");
      return true;
    }

    const imagePath = String(data?.image_path || "").trim();
    const backendOk = !!data?.backend_ok;
    const fallbackUsed = !!data?.fallback_used;
    const seedUsed = data?.seed != null ? String(data.seed) : (cmd.seed != null ? String(cmd.seed) : "rnd");
    const metaBits = [
      `steps:${cmd.steps}`,
      `seed:${seedUsed}`,
      cmd.style3d ? "style:3d" : "",
      fallbackUsed ? (es ? "fallback local" : "local fallback") : (backendOk ? "backend" : ""),
      data?.checkpoint_selected ? `ckpt:${String(data.checkpoint_selected).slice(0, 28)}` : "",
    ].filter(Boolean);

    const shown = appendImageBubble({
      imagePath,
      caption: es ? "Imagen generada" : "Generated image",
      meta: metaBits.join(" • "),
    });
    if (!shown) {
      appendBubble(
        es
          ? `Imagen generada. Ruta: ${imagePath || "desconocida"}`
          : `Image generated. Path: ${imagePath || "unknown"}`,
        "bot"
      );
    }
    return true;
  } catch (err) {
    console.error(err);
    appendBubble(es ? "No se pudo generar la imagen." : "Could not generate image.", "error");
    return true;
  } finally {
    setPending(false);
  }
}

function setTradeStatus(text, isError = false) {
  if (!dom.tradeStatus) return;
  dom.tradeStatus.textContent = text || "";
  dom.tradeStatus.style.color = isError ? "#fca5a5" : "var(--muted)";
}

async function loadCryptoModels() {
  try {
    const [modelsRes, registryRes] = await Promise.all([
      fetchWithTimeout(endpoints.cryptoModels, { headers: { Accept: "application/json" } }, { timeout: 8000, retries: 0 }),
      fetchWithTimeout(endpoints.cryptoModelsRegistry, { headers: { Accept: "application/json" } }, { timeout: 8000, retries: 0 }).catch(() => null),
    ]);
    const data = await safeJson(modelsRes);
    if (modelsRes.ok && data) {
      const available = data.available || data.models || ["ensemble"];
      state.cryptoModelsMeta.available = Array.isArray(available) ? available : ["ensemble"];
      state.cryptoModelsMeta.default = data.default || state.cryptoModelsMeta.available[0] || "ensemble";
    }
    if (registryRes) {
      const registryData = await safeJson(registryRes);
      if (registryRes.ok && Array.isArray(registryData)) {
        state.cryptoModelRegistry = registryData;
      }
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

const chartHoverGuidePlugin = {
  id: "chartHoverGuide",
  afterDatasetsDraw(chart, _args, pluginOptions) {
    const active = chart?.tooltip?.getActiveElements?.() || [];
    if (!active.length) return;
    const x = active[0]?.element?.x;
    const area = chart?.chartArea;
    if (!Number.isFinite(x) || !area) return;

    const ctx = chart.ctx;
    ctx.save();
    ctx.beginPath();
    if (ctx.setLineDash) ctx.setLineDash([5, 4]);
    ctx.lineWidth = pluginOptions?.lineWidth || 1;
    ctx.strokeStyle = pluginOptions?.color || "rgba(148, 163, 184, 0.35)";
    ctx.moveTo(x, area.top);
    ctx.lineTo(x, area.bottom);
    ctx.stroke();
    ctx.restore();
  },
};

function normalizeTimestampMs(ts) {
  if (ts == null) return NaN;
  if (typeof ts === "number" && Number.isFinite(ts)) return ts < 1e12 ? ts * 1000 : ts;
  if (typeof ts === "string") {
    const trimmed = ts.trim();
    if (!trimmed) return NaN;
    const asNum = Number(trimmed);
    if (Number.isFinite(asNum)) return asNum < 1e12 ? asNum * 1000 : asNum;
    const parsed = Date.parse(trimmed);
    return Number.isFinite(parsed) ? parsed : NaN;
  }
  const fallback = Number(ts);
  if (!Number.isFinite(fallback)) return NaN;
  return fallback < 1e12 ? fallback * 1000 : fallback;
}

function getPriceDigits(value) {
  const n = Math.abs(Number(value));
  if (!Number.isFinite(n)) return 2;
  if (n >= 1000) return 2;
  if (n >= 1) return 3;
  return 5;
}

function formatPrice(value, { compact = false } = {}) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  const locale = state.lang === LANG.ES ? "es-CO" : "en-US";
  if (compact) {
    return new Intl.NumberFormat(locale, {
      notation: "compact",
      maximumFractionDigits: 2,
    }).format(n);
  }
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: 0,
    maximumFractionDigits: getPriceDigits(n),
  }).format(n);
}

function formatChartTooltipTime(ts) {
  const n = normalizeTimestampMs(ts);
  if (!Number.isFinite(n)) return "—";
  const locale = state.lang === LANG.ES ? "es-CO" : "en-US";
  return new Date(n).toLocaleString(locale, {
    hour12: false,
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function clampChartWindow(start, end, total, minSpan = 12) {
  const safeTotal = Math.max(1, Number(total) || 1);
  let s = Math.max(0, Math.min(safeTotal - 1, Math.floor(Number(start) || 0)));
  let e = Math.max(0, Math.min(safeTotal - 1, Math.floor(Number(end) || 0)));
  if (s > e) [s, e] = [e, s];

  const spanTarget = Math.min(Math.max(2, minSpan), safeTotal);
  const currentSpan = e - s + 1;
  if (currentSpan < spanTarget) {
    const missing = spanTarget - currentSpan;
    s = Math.max(0, s - Math.floor(missing / 2));
    e = Math.min(safeTotal - 1, s + spanTarget - 1);
    s = Math.max(0, e - spanTarget + 1);
  }
  return { start: s, end: e };
}

function getAutoChartWindow(points) {
  const total = points.length;
  if (!total) return { start: 0, end: 0, mode: "empty" };
  if (state.chartRangeMinutes > 0) {
    const lastTs = points[total - 1].t;
    const cutoff = lastTs - state.chartRangeMinutes * 60_000;
    let start = points.findIndex((p) => p.t >= cutoff);
    if (start < 0) start = 0;
    return { start, end: total - 1, mode: "range" };
  }
  return { start: 0, end: total - 1, mode: "all" };
}

function getEffectiveChartWindow(points) {
  const total = points.length;
  if (!total) return { start: 0, end: 0, mode: "empty" };
  if (state.chartViewMode === "manual" && state.chartWindow) {
    const manual = clampChartWindow(state.chartWindow.start, state.chartWindow.end, total);
    state.chartWindow = manual;
    return { ...manual, mode: "manual" };
  }
  return getAutoChartWindow(points);
}

function updateChartRangeButtons() {
  const activeMinutes = state.chartRangeMinutes > 0 ? state.chartRangeMinutes : 0;
  dom.chartRangeButtons?.forEach((btn) => {
    const minutes = Number(btn.getAttribute("data-chart-range") || "0");
    const isActive = state.chartViewMode !== "manual" && minutes === activeMinutes;
    btn.classList.toggle("active", isActive);
    btn.setAttribute("aria-pressed", String(isActive));
  });
  if (dom.chartResetZoom) {
    const isManual = state.chartViewMode === "manual";
    dom.chartResetZoom.classList.toggle("active", isManual);
    dom.chartResetZoom.setAttribute("aria-pressed", String(isManual));
    dom.chartResetZoom.title = state.lang === LANG.ES
      ? (isManual ? "Volver al rango automático" : "Reset zoom/pan")
      : (isManual ? "Return to auto range" : "Reset zoom/pan");
  }
}

function setChartRangePreset(minutes, { rerender = false } = {}) {
  const value = Number(minutes);
  state.chartRangeMinutes = Number.isFinite(value) && value > 0 ? Math.floor(value) : 0;
  state.chartViewMode = "auto";
  state.chartWindow = null;
  localStorage.setItem("aegis_chart_range_minutes", String(state.chartRangeMinutes));
  updateChartRangeButtons();
  if (rerender && state.lastPoints?.length) renderChart(state.lastPoints);
}

function resetChartZoom({ rerender = false } = {}) {
  state.chartViewMode = "auto";
  state.chartWindow = null;
  updateChartRangeButtons();
  if (rerender && state.lastPoints?.length) renderChart(state.lastPoints);
}

function handleChartWheel(event) {
  if (!state.lastPoints?.length || !state.chartInstance || !dom.priceChart) return;
  if (!event.ctrlKey && !event.shiftKey && !event.altKey) return;
  event.preventDefault();

  const points = state.lastPoints;
  const total = points.length;
  if (total < 6) return;

  const current = getEffectiveChartWindow(points);
  const currentSpan = Math.max(2, current.end - current.start + 1);
  let nextStart = current.start;
  let nextEnd = current.end;

  if (event.shiftKey || event.altKey) {
    const step = Math.max(1, Math.round(currentSpan * 0.12));
    const delta = event.deltaY > 0 ? step : -step;
    nextStart += delta;
    nextEnd += delta;
  } else {
    const zoomFactor = event.deltaY < 0 ? 0.84 : 1.18;
    const minSpan = Math.min(20, total);
    const nextSpan = Math.max(minSpan, Math.min(total, Math.round(currentSpan * zoomFactor)));
    const rect = dom.priceChart.getBoundingClientRect();
    const rel = rect.width > 0 ? (event.clientX - rect.left) / rect.width : 0.5;
    const ratio = Math.max(0, Math.min(1, rel));
    const focusIdx = Math.round(current.start + ratio * (currentSpan - 1));
    nextStart = Math.round(focusIdx - ratio * (nextSpan - 1));
    nextEnd = nextStart + nextSpan - 1;
  }

  const clamped = clampChartWindow(nextStart, nextEnd, total);
  state.chartViewMode = "manual";
  state.chartWindow = clamped;
  updateChartRangeButtons();
  renderChart(points);
}

function updateChartModeHint({
  tradeCount = 0,
  newsCount = 0,
  compareCount = 0,
  windowSize = 0,
  totalSize = 0,
  viewMode = "auto",
} = {}) {
  if (!dom.chartModeHint) return;
  const es = state.lang === LANG.ES;
  const parts = [es ? "Precio" : "Price"];
  if (tradeCount > 0) parts.push(`Trades ${tradeCount}`);
  if (newsCount > 0) parts.push(es ? `Noticias ${newsCount}` : `News ${newsCount}`);
  if (compareCount > 0) parts.push(es ? `Comparación ${compareCount}` : `Compare ${compareCount}`);
  if (windowSize > 0 && totalSize > 0 && windowSize < totalSize) {
    parts.push(es ? `Ventana ${windowSize}/${totalSize}` : `Window ${windowSize}/${totalSize}`);
  }
  if (viewMode === "manual") {
    parts.push(es ? "manual" : "manual");
  } else if (state.chartRangeMinutes > 0) {
    parts.push(`${state.chartRangeMinutes}m`);
  }
  const text = parts.join(" • ");
  dom.chartModeHint.textContent = text;
  dom.chartModeHint.title = es
    ? "Línea de precio con marcadores de trades/comparación y noticias opcionales. Ctrl+rueda: zoom, Shift+rueda: pan."
    : "Price line with trade/compare markers and optional news. Ctrl+wheel: zoom, Shift+wheel: pan.";
}

function parseOhlcv(raw) {
  if (!raw) return [];
  const rows = Array.isArray(raw) ? raw : raw.candles || raw.klines || raw.items || [];
  const byTs = new Map();
  rows.forEach((r) => {
    if (Array.isArray(r)) {
      const ts = normalizeTimestampMs(r[0]);
      const close = parseFloat(r[4] ?? r[1]);
      if (Number.isFinite(close) && Number.isFinite(ts)) byTs.set(ts, { t: ts, c: close });
      return;
    }
    const ts = normalizeTimestampMs(r.close_time ?? r.time ?? r.timestamp ?? r.t ?? r.ts);
    const close = parseFloat(r.close ?? r.c ?? r.price);
    if (Number.isFinite(close) && Number.isFinite(ts)) byTs.set(ts, { t: ts, c: close });
  });
  return Array.from(byTs.values()).sort((a, b) => a.t - b.t);
}

function renderChart(points) {
  state.lastPoints = points || [];
  if (!dom.priceChart || typeof Chart === "undefined") return;
  if (!points.length) {
    if (state.chartInstance) {
      state.chartInstance.destroy();
      state.chartInstance = null;
    }
    updateChartModeHint();
    setTradeStatus(state.lang === LANG.ES ? "Sin datos de precio." : "No price data.", true);
    return;
  }

  const chartWindow = getEffectiveChartWindow(points);
  const chartWindowSize = Math.max(1, chartWindow.end - chartWindow.start + 1);
  const windowStartTs = points[Math.max(0, chartWindow.start)]?.t ?? points[0]?.t;
  const windowEndTs = points[Math.max(0, chartWindow.end)]?.t ?? points[points.length - 1]?.t;
  const spanMinutes = Math.max(1, Math.round((windowEndTs - windowStartTs) / 60000));
  const labelOpts = getChartLabelOptions(spanMinutes);
  const windowPoints = points.slice(Math.max(0, chartWindow.start), Math.min(points.length, chartWindow.end + 1));
  const labels = points.map((p) => formatTimeLabel(p.t, labelOpts));
  const pointByLabel = new Map();
  points.forEach((p, idx) => {
    const ref = { idx, label: labels[idx], price: p.c, t: p.t };
    pointByLabel.set(labels[idx], ref);
  });
  const mainData = points.map((p) => p.c);
  const windowCloses = windowPoints.map((p) => Number(p.c)).filter((v) => Number.isFinite(v));
  const minClose = windowCloses.length ? Math.min(...windowCloses) : null;
  const maxClose = windowCloses.length ? Math.max(...windowCloses) : null;
  const spread = Number.isFinite(minClose) && Number.isFinite(maxClose) ? Math.max(0, maxClose - minClose) : 0;
  const pad = Number.isFinite(maxClose)
    ? Math.max(spread * 0.22, maxClose * 0.0015, 0.5)
    : 0.5;
  const ySuggestedMin = Number.isFinite(minClose) ? Math.max(0, minClose - pad) : undefined;
  const ySuggestedMax = Number.isFinite(maxClose) ? maxClose + pad : undefined;
  const nearestPoint = (targetTs) => {
    const normalized = normalizeTimestampMs(targetTs);
    if (!Number.isFinite(normalized)) return { idx: points.length - 1, label: labels[points.length - 1], price: mainData[points.length - 1], t: points[points.length - 1].t };
    let nearestIdx = points.length - 1;
    let bestDiff = Number.POSITIVE_INFINITY;
    points.forEach((p, idx) => {
      const diff = Math.abs(p.t - normalized);
      if (diff < bestDiff) {
        bestDiff = diff;
        nearestIdx = idx;
      }
    });
    return { idx: nearestIdx, label: labels[nearestIdx], price: mainData[nearestIdx], t: points[nearestIdx].t };
  };

  const tradePoints = (state.tradesOnChart || []).map((tr) => {
    const nearest = nearestPoint(tr.t || Date.now());
    return { x: nearest.label, y: tr.price ?? nearest.price, side: tr.side, t: nearest.t };
  });

  const newsPoints =
    state.showNewsMarkers && state.newsFeed?.length
      ? state.newsFeed.map((n) => {
          const nearest = nearestPoint(n.ts || Date.now());
          return { x: nearest.label, y: nearest.price, title: n.title, sentiment: n.sentiment, t: nearest.t };
        })
      : [];

  const comparePoints =
    state.compareMarkers?.length
      ? state.compareMarkers.map((m) => {
          const markerTs = normalizeTimestampMs(m.t);
          const fromLabel = pointByLabel.get(m.x);
          const nearest = Number.isFinite(markerTs)
            ? nearestPoint(markerTs)
            : (fromLabel || nearestPoint(Date.now()));
          return {
            x: nearest.label,
            y: Number.isFinite(m.y) ? m.y : nearest.price,
            pairId: m.pairId,
            kind: m.kind,
            color: m.color,
            t: nearest.t,
            r: state.compareHighlightId && state.compareHighlightId === m.pairId ? 6 : 4,
          };
        })
      : [];

  if (state.chartInstance) state.chartInstance.destroy();
  updateChartModeHint({
    tradeCount: tradePoints.length,
    newsCount: newsPoints.length,
    compareCount: comparePoints.length,
    windowSize: chartWindowSize,
    totalSize: points.length,
    viewMode: chartWindow.mode,
  });
  updateChartRangeButtons();
  const showLegend = tradePoints.length > 0 || newsPoints.length > 0 || comparePoints.length > 0;

  state.chartInstance = new Chart(dom.priceChart, {
    type: "line",
    plugins: [chartHoverGuidePlugin],
    data: {
      labels,
      datasets: [
        {
          label: state.chartSymbol,
          data: mainData,
          borderColor: "#22d3ee",
          borderWidth: 2,
          backgroundColor: (ctx) => {
            const area = ctx?.chart?.chartArea;
            if (!area) return "rgba(34, 211, 238, 0.10)";
            const gradient = ctx.chart.ctx.createLinearGradient(0, area.top, 0, area.bottom);
            gradient.addColorStop(0, "rgba(34, 211, 238, 0.16)");
            gradient.addColorStop(1, "rgba(15, 23, 42, 0.00)");
            return gradient;
          },
          tension: 0.12,
          fill: true,
          pointRadius: 0,
          pointHoverRadius: 0,
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
        ...(comparePoints.length ? [{
          type: "scatter",
          label: "Compare",
          data: comparePoints,
          pointRadius: (ctx) => ctx.raw?.r || 4,
          pointHoverRadius: (ctx) => (ctx.raw?.r || 4) + 1,
          pointBackgroundColor: (ctx) => ctx.raw?.color || "#38bdf8",
          pointStyle: (ctx) => (ctx.raw?.kind === "base" ? "rectRot" : "circle"),
          showLine: false,
        }] : []),
      ],
    },
      options: {
        normalized: true,
        interaction: { mode: "nearest", axis: "x", intersect: false },
        layout: { padding: { left: 4, right: 10, top: 2, bottom: 2 } },
        plugins: {
          chartHoverGuide: { color: "rgba(148, 163, 184, 0.35)", lineWidth: 1 },
          tooltip: {
            enabled: true,
            displayColors: true,
          callbacks: {
            title(items) {
              const first = items?.[0];
              if (!first) return "";
              const rawTs = normalizeTimestampMs(first.raw?.t);
              if (Number.isFinite(rawTs)) return formatChartTooltipTime(rawTs);
              const idx = Number(first.dataIndex);
              return Number.isInteger(idx) && points[idx] ? formatChartTooltipTime(points[idx].t) : String(first.label || "");
            },
            label(ctx) {
              const ds = ctx.dataset?.label || state.chartSymbol;
              const value = Number(ctx.parsed?.y ?? ctx.raw?.y ?? ctx.raw);
              if (ds === "Trades") return `${ctx.raw?.side || "TRADE"} • ${formatPrice(value)}`;
              if (ds === "News") return `${state.lang === LANG.ES ? "Precio noticia" : "News price"} • ${formatPrice(value)}`;
              if (ds === "Compare") {
                const kind = ctx.raw?.kind === "base" ? (state.lang === LANG.ES ? "Base" : "Base") : (state.lang === LANG.ES ? "Resultado" : "Outcome");
                return `${kind} • ${formatPrice(value)}`;
              }
              return `${state.chartSymbol} • ${formatPrice(value)}`;
            },
            afterLabel(ctx) {
              if (ctx.dataset?.label === "News" && ctx.raw?.title) {
                const lead = state.lang === LANG.ES ? "Titular" : "Headline";
                return `${lead}: ${String(ctx.raw.title).slice(0, 96)}`;
              }
              if (ctx.dataset?.label === "News" && Number.isFinite(ctx.raw?.sentiment)) {
                const lead = state.lang === LANG.ES ? "Sentimiento" : "Sentiment";
                const sentiment = Number(ctx.raw.sentiment);
                return `${lead}: ${sentiment > 0 ? "+" : ""}${sentiment.toFixed(2)}`;
              }
              if (ctx.dataset?.label === "Compare" && ctx.raw?.pairId) {
                return `ID: ${ctx.raw.pairId}`;
              }
              return "";
            },
          },
        },
        legend: {
          display: showLegend,
          position: "top",
          labels: {
            color: "#cbd5e1",
            usePointStyle: true,
            boxWidth: 10,
            boxHeight: 10,
            font: { size: 11, weight: "600" },
          },
        },
      },
      scales: {
        x: {
          min: chartWindow.start,
          max: chartWindow.end,
          grid: { color: "rgba(148,163,184,0.10)" },
          border: { color: "rgba(148,163,184,0.18)" },
          ticks: {
            color: "#cbd5e1",
            font: { size: 11, weight: "600" },
            maxRotation: 0,
            autoSkip: true,
            maxTicksLimit: Math.min(10, Math.max(4, Math.round(chartWindowSize / 14))),
            padding: 6,
          },
        },
        y: {
          position: "right",
          suggestedMin: ySuggestedMin,
          suggestedMax: ySuggestedMax,
          grid: { color: "rgba(148,163,184,0.10)" },
          border: { color: "rgba(148,163,184,0.18)" },
          ticks: {
            color: "#cbd5e1",
            font: { size: 11, weight: "600" },
            padding: 8,
            callback: (v) => formatPrice(v, { compact: false }),
          },
        },
      },
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      elements: {
        line: { borderWidth: 2.4 },
        point: { hitRadius: 12, radius: 0, hoverRadius: 4, borderWidth: 1.25 },
      },
   },
 });
}

async function loadChartData(symbolInput) {
  const requestedSymbol = (symbolInput || state.chartSymbol || "BTCUSDT").trim().toUpperCase();
  if (state.chartInFlight) {
    state.chartQueued = true;
    state.chartQueuedSymbol = requestedSymbol || state.chartSymbol || "BTCUSDT";
    return;
  }
  state.chartInFlight = true;

  const symbol = requestedSymbol || state.chartSymbol || "BTCUSDT";
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
    await loadNews(state.chartSymbol);
    if (state.chartVisible) {
      if (state.mode === MODES.CRYPTO) {
        await loadCryptoPrediction();
      }
      loadPredictionComparison(state.chartSymbol, { force: false });
    }
  } catch (err) {
    console.error(err);
    setTradeStatus(state.lang === LANG.ES ? "No se pudo cargar el gráfico." : "Could not load chart.", true);
  } finally {
    state.chartInFlight = false;
    if (state.chartQueued) {
      const queuedSymbol = state.chartQueuedSymbol || state.chartSymbol;
      state.chartQueued = false;
      state.chartQueuedSymbol = "";
      setTimeout(() => loadChartData(queuedSymbol), 0);
    }
  }
}

function startLiveChart() {
  stopLiveChart();
  if (!state.chartVisible && state.mode !== MODES.CRYPTO) {
    updateStatusCenter();
    return;
  }
  state.liveTimer = setInterval(() => {
    if (document.hidden) return;
    if (!state.chartVisible && state.mode !== MODES.CRYPTO) return;
    loadChartData(state.chartSymbol);
  }, 60000);
  updateStatusCenter();
}
function stopLiveChart() {
  if (state.liveTimer) clearInterval(state.liveTimer);
  state.liveTimer = null;
  updateStatusCenter();
}

function toggleChartExpand() {
  if (!dom.chartPanel) return;
  dom.chartPanel.classList.toggle("expanded");
  if (state.lastPoints?.length) renderChart(state.lastPoints);
}

async function loadCryptoPrediction(options = {}) {
  const force = options.force === true;
  if (state.mode !== MODES.CRYPTO && !state.chartVisible) return;

  const symbol = (dom.chartSymbol?.value || state.chartSymbol || "BTCUSDT").trim().toUpperCase();
  const horizon = parseInt(dom.cryptoHorizon?.value || "15", 10);
  const model = dom.cryptoModelSelect?.value || state.selectedCryptoModel || "ensemble";
  const reqKey = `${symbol}|${horizon}|${model}|${state.savePredictions ? 1 : 0}`;
  const now = Date.now();

  // Avoid repeated identical predict calls from rapid UI refresh loops.
  if (!force && state.lastCryptoPredictionKey === reqKey && (now - Number(state.lastCryptoPredictionAt || 0)) < 12000) {
    return;
  }
  if (state.cryptoPredictionInFlight) {
    state.cryptoPredictionQueued = true;
    return;
  }
  state.cryptoPredictionInFlight = true;
  state.lastCryptoPredictionKey = reqKey;
  state.lastCryptoPredictionAt = now;

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
    updateSignalBar(decision, prob);

    const px = data?.current_price ?? data?.price ?? "—";
    const probText = typeof prob === "number" ? `${(prob * 100).toFixed(1)}%` : "—";

    state.lastPrediction = {
      symbol,
      horizon,
      model,
      engine: data?.additional_info?.engine || "demo",
      prob,
      px,
      current_price: data?.current_price ?? data?.price ?? null,
      predicted_price: data?.predicted_price ?? data?.target_price ?? null,
      decision,
      model_decision: data?.additional_info?.model_decision || data?.raw?.model_decision || decision,
      action_decision: data?.additional_info?.action_decision || data?.raw?.action_decision || decision,
      actionable: !!data?.additional_info?.actionable,
      credibility_status: data?.additional_info?.credibility_status || null,
      credibility_score: data?.additional_info?.credibility_score ?? null,
      credibility_reasons: Array.isArray(data?.additional_info?.credibility_reasons) ? data.additional_info.credibility_reasons : [],
      execution_margin: data?.additional_info?.execution_margin ?? data?.raw?.execution_margin ?? null,
      threshold_edge: data?.additional_info?.threshold_edge ?? data?.raw?.threshold_edge ?? null,
      execution_gate_reason: data?.additional_info?.execution_gate_reason || data?.raw?.execution_gate_reason || null,
      consensus: data?.additional_info?.consensus || data?.raw?.consensus || null,
      credibility: data?.raw?.credibility || null,
      news_sentiment: data?.additional_info?.news_sentiment ?? null,
      news_count: data?.additional_info?.n_news_used ?? null,
      p_base: data?.additional_info?.probability_base ?? null,
      p_final: prob,
      regime: data?.additional_info?.regime || data?.raw?.regime || null,
      trained_at: data?.raw?.trained_at || null,
      dataset_hash: data?.raw?.dataset_hash || null,
      validation_mode: data?.raw?.validation_mode || null,
      interval_minutes: data?.raw?.interval_minutes || null,
      buy_threshold: data?.additional_info?.buy_threshold ?? data?.raw?.buy_threshold ?? null,
      sell_threshold: data?.additional_info?.sell_threshold ?? data?.raw?.sell_threshold ?? null,
      threshold_strategy: data?.raw?.threshold_strategy || null,
    };

    setTradeStatus(
      state.lang === LANG.ES
        ? `Señal: ${state.lastPrediction.action_decision || decision} • p=${probText} • px=${px}`
        : `Signal: ${state.lastPrediction.action_decision || decision} • p=${probText} • px=${px}`
    );
    const priceSource = data?.additional_info?.price_source || data?.price_source || "demo";
    const context = data?.additional_info?.context || null;
    updateCryptoBadges({
      priceSource,
      model,
      horizon,
      probText,
      px,
      context,
    });
    updatePredictionTooltipText();
    loadPredictionComparison(symbol, { force: true });
    loadCryptoState({ force: true });
  } catch {
  } finally {
    state.cryptoPredictionInFlight = false;
    if (state.cryptoPredictionQueued) {
      state.cryptoPredictionQueued = false;
      setTimeout(() => loadCryptoPrediction(), 0);
    }
  }
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

function updateSignalBar(decision, prob) {
  if (!dom.signalBar) return;
  const pct = typeof prob === "number" ? Math.max(0, Math.min(1, prob)) * 100 : 0;
  const buyThreshold = Number(state.lastPrediction?.buy_threshold);
  const sellThreshold = Number(state.lastPrediction?.sell_threshold);
  const buyText = Number.isFinite(buyThreshold) ? `${(buyThreshold * 100).toFixed(1)}%` : "63.0%";
  const sellText = Number.isFinite(sellThreshold) ? `${(sellThreshold * 100).toFixed(1)}%` : "37.0%";
  dom.signalBar.style.setProperty("--signal-width", `${pct}%`);
  const fill = dom.signalBar.querySelector(".signal-fill");
  if (fill) fill.style.width = `${pct}%`;
  dom.signalBar.setAttribute("data-decision", decision || "HOLD");
  dom.signalBar.setAttribute("title",
    state.lang === LANG.ES
      ? `Confianza ${pct.toFixed(1)}% • Regla: BUY si >=${buyText}, SELL si <=${sellText}, HOLD en medio`
      : `Confidence ${pct.toFixed(1)}% • Rule: BUY if >=${buyText}, SELL if <=${sellText}, HOLD otherwise`
  );
}

function updateCryptoBadges({ priceSource, model, horizon, probText, px, context }) {
  if (dom.priceSourceBadge) {
    dom.priceSourceBadge.textContent = (priceSource || "demo").toUpperCase();
    dom.priceSourceBadge.classList.toggle("pill-live", priceSource === "binance" || priceSource === "coingecko");
    dom.priceSourceBadge.classList.toggle("pill-demo", !(priceSource === "binance" || priceSource === "coingecko"));
    dom.priceSourceBadge.title = state.lang === LANG.ES
      ? `Fuente de precio: ${priceSource || "demo"}`
      : `Price source: ${priceSource || "demo"}`;
  }
  if (dom.cryptoContextPill) {
    const sent = state.lastPrediction?.news_sentiment ?? null;
    const newsCount = state.lastPrediction?.news_count ?? null;
    const pBase = state.lastPrediction?.p_base;
    const pFinal = state.lastPrediction?.p_final ?? null;
    const executionMode = normalizeCryptoExecutionMode(
      state.cryptoExecutionMode || state.cryptoState?.execution?.mode || state.cryptoState?.execution?.requested_mode || "simulated"
    );
    const regime = state.lastPrediction?.regime ? ` • ${state.lastPrediction.regime}` : "";
    const engine = state.lastPrediction?.engine ? ` • ${String(state.lastPrediction.engine).toUpperCase()}` : "";
    const modelDecision = state.lastPrediction?.model_decision || null;
    const actionDecision = state.lastPrediction?.action_decision || null;
    const credibilityStatus = state.lastPrediction?.credibility_status || null;
    const executionMargin = Number(state.lastPrediction?.execution_margin);
    const thresholdEdge = Number(state.lastPrediction?.threshold_edge);
    const gateReason = state.lastPrediction?.execution_gate_reason || null;
    const consensus = state.lastPrediction?.consensus || null;
    let txt = context || `${executionMode.toUpperCase()} • ${model || "ensemble"}${engine} • H=${horizon || "-"} • p=${probText || "—"} • px=${px ?? "—"}${regime}`;
    if (pBase != null && pFinal != null && Math.abs(pFinal - pBase) > 0.005) {
      txt += ` • p_adj ${formatProb(pBase)}→${formatProb(pFinal)}`;
    }
    const buyThreshold = Number(state.lastPrediction?.buy_threshold);
    const sellThreshold = Number(state.lastPrediction?.sell_threshold);
    if (Number.isFinite(buyThreshold) && Number.isFinite(sellThreshold)) {
      txt += ` • T ${formatProb(buyThreshold)}/${formatProb(sellThreshold)}`;
    }
    if (modelDecision && actionDecision && modelDecision !== actionDecision) {
      txt += state.lang === LANG.ES
        ? ` • modelo ${modelDecision} → ejecutable ${actionDecision}`
        : ` • model ${modelDecision} → executable ${actionDecision}`;
    }
    if (credibilityStatus) {
      txt += ` • ${state.lang === LANG.ES ? "credibilidad" : "credibility"} ${credibilityStatus}`;
    }
    if (Number.isFinite(executionMargin) && Number.isFinite(thresholdEdge)) {
      txt += state.lang === LANG.ES
        ? ` • edge ${formatPct(thresholdEdge, 1)} / req ${formatPct(executionMargin, 1)}`
        : ` • edge ${formatPct(thresholdEdge, 1)} / req ${formatPct(executionMargin, 1)}`;
    }
    if (gateReason) {
      txt += state.lang === LANG.ES
        ? ` • gate ${gateReason}`
        : ` • gate ${gateReason}`;
    }
    if (consensus && Number.isFinite(Number(consensus.support_ratio)) && Number.isFinite(Number(consensus.spread))) {
      txt += ` • consensus ${formatPct(Number(consensus.support_ratio), 0)} / spread ${formatPct(Number(consensus.spread), 1)}`;
    }
    dom.cryptoContextPill.textContent = txt;
    if (sent !== null && dom.cryptoContextPill.querySelector) {
      let badge = dom.cryptoContextPill.querySelector(".pill-sentiment");
      if (!badge) {
        badge = document.createElement("span");
        badge.className = "pill-sentiment neutral";
        dom.cryptoContextPill.appendChild(badge);
      }
      badge.classList.remove("pos", "neg", "neutral");
      const cls = sent > 0.05 ? "pos" : sent < -0.05 ? "neg" : "neutral";
      badge.classList.add(cls);
      badge.textContent = `${sent > 0.05 ? "+" : sent < -0.05 ? "-" : "0"}${newsCount ? ` (${newsCount})` : ""}`;
    }
    dom.cryptoContextPill.title = txt;
  }
}

function normalizeCryptoExecutionMode(mode) {
  const raw = String(mode || "").trim().toLowerCase();
  if (raw === "test" || raw === "paper") return "simulated";
  if (raw === "testnet" || raw === "live" || raw === "simulated") return raw;
  return "simulated";
}

function updateCryptoExecutionButtons() {
  if (!dom.cryptoExecutionGroup) return;
  const cryptoState = state.cryptoState && typeof state.cryptoState === "object" ? state.cryptoState : {};
  const execution = cryptoState.execution && typeof cryptoState.execution === "object" ? cryptoState.execution : {};
  const selectedMode = normalizeCryptoExecutionMode(
    state.cryptoExecutionMode || execution.requested_mode || execution.mode || "simulated"
  );
  state.cryptoExecutionMode = selectedMode;
  localStorage.setItem("aegis_crypto_execution_mode", selectedMode);

  const readyByMode = {
    simulated: true,
    testnet: !!execution.credentials_present,
    live: !!execution.live_enabled,
  };
  dom.cryptoExecutionGroup.querySelectorAll("[data-execution-mode]").forEach((btn) => {
    const mode = normalizeCryptoExecutionMode(btn.dataset.executionMode || btn.getAttribute("data-execution-mode"));
    const active = mode === selectedMode;
    btn.classList.toggle("active", active);
    btn.classList.toggle("disabled", !readyByMode[mode] && mode !== "simulated");
    btn.setAttribute("aria-pressed", String(active));
    const readyText = readyByMode[mode]
      ? (state.lang === LANG.ES ? "listo" : "ready")
      : (state.lang === LANG.ES ? "requiere keys" : "needs keys");
    const scopeText = cryptoState?.scope?.symbol ? ` • ${cryptoState.scope.symbol}` : "";
    const horizonText = Number.isFinite(Number(cryptoState?.scope?.horizon_minutes))
      ? ` • H=${Number(cryptoState.scope.horizon_minutes)}m`
      : "";
    btn.title = `${mode.toUpperCase()}${scopeText}${horizonText} • ${readyText}`;
  });
}

function renderCryptoExecutionSummary() {
  if (!dom.cryptoExecutionMeta) return;
  const es = state.lang === LANG.ES;
  const cryptoState = state.cryptoState && typeof state.cryptoState === "object" ? state.cryptoState : {};
  const execution = cryptoState.execution && typeof cryptoState.execution === "object" ? cryptoState.execution : {};
  const scope = cryptoState.scope && typeof cryptoState.scope === "object" ? cryptoState.scope : getCurrentCryptoScope();
  const summary = cryptoState.summary && typeof cryptoState.summary === "object" ? cryptoState.summary : {};
  const orderBook = cryptoState.order_book && typeof cryptoState.order_book === "object" ? cryptoState.order_book : {};
  const riskGate = state.cryptoTradePreview?.risk_gate && typeof state.cryptoTradePreview.risk_gate === "object"
    ? state.cryptoTradePreview.risk_gate
    : state.lastTradeQuote?.risk_gate && typeof state.lastTradeQuote.risk_gate === "object"
      ? state.lastTradeQuote.risk_gate
      : null;
  const selected = normalizeCryptoExecutionMode(state.cryptoExecutionMode || execution.requested_mode || execution.mode || "simulated");
  const selectedLabel = selected.toUpperCase();
  const readiness = selected === "live"
    ? (execution.live_enabled
      ? (es ? "live listo" : "live ready")
      : (es ? "live bloqueado" : "live locked"))
    : selected === "testnet"
      ? (execution.credentials_present
        ? (es ? "testnet listo" : "testnet ready")
        : (es ? "testnet bloqueado" : "testnet locked"))
      : (es ? "solo demo" : "demo only");
  const credentials = execution.credentials_present
    ? (es ? "keys ok" : "keys ok")
    : (es ? "sin keys" : "no keys");
  const counts = `${Number(summary.predictions_count || 0)}/${Number(summary.outcomes_count || 0)}/${Number(summary.trades_count || 0)}`;
  const liveMode = execution.mode || selected;
  const streamState = state.cryptoStateStreamActive
    ? (state.cryptoStateStreamFallbackActive ? (es ? "live + fallback" : "live + fallback") : (es ? "live" : "live"))
    : (state.cryptoStateStreamFallbackActive ? (es ? "fallback" : "fallback") : (es ? "poll" : "poll"));
  const heartbeat = state.cryptoStateStreamLastHeartbeatAt ? ` • ${formatAgo(state.cryptoStateStreamLastHeartbeatAt)}` : "";
  const parts = [
    `${es ? "Selección" : "Selected"}: ${selectedLabel}`,
    `${es ? "Backend" : "Backend"}: ${String(liveMode || "simulated").toUpperCase()} • ${readiness}`,
    `${es ? "Auth" : "Auth"}: ${credentials}`,
    `${es ? "Scope" : "Scope"}: ${scope.symbol || "—"} • ${Number.isFinite(Number(scope.horizon_minutes || scope.horizon))
      ? `${Number(scope.horizon_minutes || scope.horizon)}m`
      : "—"}`,
    `${es ? "Pred/Out/Trades" : "Pred/Out/Trades"}: ${counts}`,
    `${es ? "Stream" : "Stream"}: ${streamState}${heartbeat}`,
  ];
  if (state.lastTradeQuote?.execution_note) {
    parts.push(String(state.lastTradeQuote.execution_note));
  }
  if (state.lastTradeQuote?.fill_price) {
    parts.push(`${es ? "Fill" : "Fill"}: ${formatPrice(Number(state.lastTradeQuote.fill_price))}`);
  }
  if (Number.isFinite(Number(orderBook?.spread_bps)) && Number.isFinite(Number(orderBook?.imbalance))) {
    parts.push(
      `${es ? "Book" : "Book"}: ${formatPrice(Number(orderBook.spread_bps), { compact: true })}bps • ${(
        Number(orderBook.imbalance) * 100
      ).toFixed(1)}% bid`
    );
  }
  if (riskGate) {
    parts.push(
      riskGate.allowed
        ? `${es ? "Risk gate" : "Risk gate"}: OK`
        : `${es ? "Risk gate" : "Risk gate"}: ${es ? "bloqueado" : "blocked"} • ${String(riskGate.reason || "risk").replace(/_/g, " ")}`
    );
    const calibrationSizing = formatCryptoCalibrationSizing(riskGate, { es, includeStatus: true });
    if (calibrationSizing) parts.push(calibrationSizing);
  }
  dom.cryptoExecutionMeta.textContent = parts.join(" • ");
}

function formatCryptoQuantityValue(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "";
  if (Math.abs(number) >= 100) return number.toFixed(2);
  if (Math.abs(number) >= 1) return number.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
  return number.toFixed(8).replace(/0+$/, "").replace(/\.$/, "");
}

function formatCryptoCalibrationSizing(riskGate, { es = false, includeStatus = false } = {}) {
  const gate = riskGate && typeof riskGate === "object" ? riskGate : null;
  if (!gate) return "";
  const controls = gate.calibration_controls && typeof gate.calibration_controls === "object"
    ? gate.calibration_controls
    : null;
  if (!controls) return "";
  const status = String(gate?.operator_guidance?.status || controls.status || "").trim().toLowerCase();
  const action = String(controls.action || "").trim().toLowerCase();
  const maxOrderNotional = Number(controls.max_order_notional);
  const maxQuantity = Number(controls.max_quantity);
  const reductionPct = Number(controls.recommended_reduction_pct);
  const sizingBasis = String(controls.sizing_basis || "").trim().toLowerCase();
  const parts = [];
  if (includeStatus && status) {
    parts.push(`${es ? "Calibración" : "Calibration"} ${status.replace(/_/g, " ")}`);
  }
  if (includeStatus && action) {
    parts.push(`${es ? "acción" : "action"} ${action.replace(/_/g, " ")}`);
  }
  if (Number.isFinite(maxOrderNotional)) {
    parts.push(`${es ? "máx notional" : "max notional"} ${formatPrice(maxOrderNotional, { compact: true })}`);
  }
  if (Number.isFinite(maxQuantity)) {
    parts.push(`${es ? "máx qty" : "max qty"} ${formatCryptoQuantityValue(maxQuantity)}`);
  }
  if (Number.isFinite(reductionPct) && reductionPct > 0) {
    parts.push(`${es ? "recorta" : "cut"} ${formatPct(reductionPct, 1)}`);
  }
  if (sizingBasis === "visible_liquidity_notional") {
    parts.push(es ? "base liquidez visible" : "basis visible liquidity");
  } else if (sizingBasis === "order_size_pct") {
    parts.push(es ? "base % orden" : "basis order %");
  }
  return parts.join(" • ");
}

function getCryptoCalibrationSuggestedQuantity(riskGate, currentQty = NaN) {
  const gate = riskGate && typeof riskGate === "object" ? riskGate : null;
  const controls = gate?.calibration_controls && typeof gate.calibration_controls === "object"
    ? gate.calibration_controls
    : null;
  const maxQuantity = Number(controls?.max_quantity);
  const qty = Number(currentQty);
  if (!Number.isFinite(maxQuantity) || maxQuantity <= 0) return NaN;
  if (Number.isFinite(qty) && qty > 0 && maxQuantity >= qty) return NaN;
  return maxQuantity;
}

async function applyCryptoSuggestedQuantity(riskGate, { side = state.cryptoPreviewSide || "BUY" } = {}) {
  const suggestedQty = getCryptoCalibrationSuggestedQuantity(riskGate, Number.parseFloat(dom.chatTradeQty?.value || "0"));
  if (!dom.chatTradeQty || !Number.isFinite(suggestedQty) || suggestedQty <= 0) return false;
  const formattedQty = formatCryptoQuantityValue(suggestedQty);
  dom.chatTradeQty.value = formattedQty;
  state.cryptoTradePreviewArmed = true;
  setTradeStatus(
    state.lang === LANG.ES
      ? `Aplicando qty calibrada ${formattedQty}...`
      : `Applying calibrated qty ${formattedQty}...`
  );
  const preview = await loadCryptoTradePreview({
    side: normalizeCryptoTradeSide(side),
    force: true,
    arm: true,
  });
  return !!preview;
}

function updateCryptoExecutionUI() {
  updateCryptoExecutionButtons();
  renderCryptoExecutionSummary();
  renderCryptoTradePreview();
}

function normalizeCryptoTradeSide(side) {
  return String(side || "").trim().toUpperCase() === "SELL" ? "SELL" : "BUY";
}

const CRYPTO_RISK_INPUT_KEYS = {
  stopLossPct: "aegis_crypto_stop_loss_pct",
  takeProfitPct: "aegis_crypto_take_profit_pct",
  maxExposureQuote: "aegis_crypto_max_exposure_quote",
  maxOrderSizePct: "aegis_crypto_max_order_size_pct",
};

function parseOptionalPositiveNumber(value) {
  const n = Number.parseFloat(String(value ?? "").trim());
  return Number.isFinite(n) && n > 0 ? n : null;
}

function hydrateCryptoRiskInputs() {
  const pairs = [
    [dom.cryptoStopLossPct, CRYPTO_RISK_INPUT_KEYS.stopLossPct],
    [dom.cryptoTakeProfitPct, CRYPTO_RISK_INPUT_KEYS.takeProfitPct],
    [dom.cryptoMaxExposureQuote, CRYPTO_RISK_INPUT_KEYS.maxExposureQuote],
    [dom.cryptoMaxOrderSizePct, CRYPTO_RISK_INPUT_KEYS.maxOrderSizePct],
  ];
  pairs.forEach(([input, key]) => {
    if (!input) return;
    const stored = localStorage.getItem(key);
    if (stored !== null && stored !== undefined) {
      input.value = stored;
    }
  });
}

function persistCryptoRiskInput(input, key) {
  if (!input) return;
  const raw = String(input.value || "").trim();
  if (raw) localStorage.setItem(key, raw);
  else localStorage.removeItem(key);
}

function getCryptoRiskControlValues() {
  return {
    stopLossPct: parseOptionalPositiveNumber(dom.cryptoStopLossPct?.value),
    takeProfitPct: parseOptionalPositiveNumber(dom.cryptoTakeProfitPct?.value),
    maxExposureQuote: parseOptionalPositiveNumber(dom.cryptoMaxExposureQuote?.value),
    maxOrderSizePct: parseOptionalPositiveNumber(dom.cryptoMaxOrderSizePct?.value),
  };
}

function formatCryptoRiskControlSummary(controls, { es = state.lang === LANG.ES } = {}) {
  if (!controls || typeof controls !== "object") return "";
  const parts = [];
  if (Number.isFinite(controls.stopLossPct)) {
    parts.push(`${es ? "Stop loss" : "Stop loss"} ${formatPct(controls.stopLossPct / 100, 2)}`);
  }
  if (Number.isFinite(controls.takeProfitPct)) {
    parts.push(`${es ? "Take profit" : "Take profit"} ${formatPct(controls.takeProfitPct / 100, 2)}`);
  }
  if (Number.isFinite(controls.maxExposureQuote)) {
    parts.push(`${es ? "Max exposure" : "Max exposure"} ${formatPrice(controls.maxExposureQuote, { compact: true })}`);
  }
  if (Number.isFinite(controls.maxOrderSizePct)) {
    parts.push(`${es ? "Max order" : "Max order"} ${formatPct(controls.maxOrderSizePct / 100, 2)}`);
  }
  return parts.length ? `${es ? "Guardrails" : "Guardrails"} • ${parts.join(" • ")}` : "";
}

function buildCryptoTradeDraft(side = state.cryptoPreviewSide || "BUY") {
  const normalizedSide = normalizeCryptoTradeSide(side);
  const symbol = normalizeCryptoScopeSymbol(dom.chartSymbol?.value || state.chartSymbol || "BTCUSDT") || "BTCUSDT";
  const rawQty = Number.parseFloat(dom.chatTradeQty?.value || "0");
  const quantity = Number.isFinite(rawQty) && rawQty > 0 ? rawQty : NaN;
  const horizonRaw = parseInt(dom.cryptoHorizon?.value || state.lastPrediction?.horizon || "15", 10);
  const horizon = Number.isFinite(horizonRaw) && horizonRaw > 0 ? horizonRaw : 15;
  const executionMode = normalizeCryptoExecutionMode(
    state.cryptoExecutionMode || state.cryptoState?.execution?.requested_mode || state.cryptoState?.execution?.mode || "simulated"
  );
  const regime = String(state.lastPrediction?.regime || state.cryptoState?.scope?.regime || "").trim().toLowerCase() || null;
  const riskControls = getCryptoRiskControlValues();
  return {
    side: normalizedSide,
    symbol,
    quantity,
    horizon,
    regime,
    executionMode,
    test: executionMode !== "live",
    ...riskControls,
  };
}

function getCryptoTradeDraftKey(draft) {
  if (!draft) return "";
  return [
    draft.symbol || "",
    draft.side || "",
    Number.isFinite(Number(draft.quantity)) ? Number(draft.quantity).toFixed(8) : "0",
    draft.executionMode || "simulated",
    Number.isFinite(Number(draft.horizon)) ? Number(draft.horizon) : 15,
    draft.regime || "",
    Number.isFinite(Number(draft.stopLossPct)) ? Number(draft.stopLossPct).toFixed(4) : "",
    Number.isFinite(Number(draft.takeProfitPct)) ? Number(draft.takeProfitPct).toFixed(4) : "",
    Number.isFinite(Number(draft.maxExposureQuote)) ? Number(draft.maxExposureQuote).toFixed(2) : "",
    Number.isFinite(Number(draft.maxOrderSizePct)) ? Number(draft.maxOrderSizePct).toFixed(4) : "",
  ].join("|");
}

function scheduleCryptoTradePreviewRefresh({ side = null, force = false } = {}) {
  if (side) {
    const normalizedSide = normalizeCryptoTradeSide(side);
    state.cryptoPreviewSide = normalizedSide;
    localStorage.setItem("aegis_crypto_preview_side", normalizedSide);
  }
  if (state.cryptoTradePreviewTimer) {
    clearTimeout(state.cryptoTradePreviewTimer);
  }
  state.cryptoTradePreviewTimer = setTimeout(() => {
    state.cryptoTradePreviewTimer = null;
    loadCryptoTradePreview({
      side: side || state.cryptoPreviewSide || "BUY",
      force,
      arm: state.cryptoTradePreviewArmed,
    }).catch(() => {});
  }, 220);
}

function requestCryptoTradePreview(side) {
  const normalizedSide = normalizeCryptoTradeSide(side);
  state.cryptoPreviewSide = normalizedSide;
  localStorage.setItem("aegis_crypto_preview_side", normalizedSide);
  state.cryptoTradePreviewArmed = true;
  if (!state.chartVisible) {
    showCryptoPanelFromToolbar();
  }
  setTradeStatus(
    state.lang === LANG.ES
      ? `Generando preview ${normalizedSide}...`
      : `Generating ${normalizedSide} preview...`
  );
  return loadCryptoTradePreview({ side: normalizedSide, force: true, arm: true });
}

async function loadCryptoTradePreview({ side = null, force = false, arm = null } = {}) {
  const draft = buildCryptoTradeDraft(side || state.cryptoPreviewSide || "BUY");
  state.cryptoPreviewSide = draft.side;
  localStorage.setItem("aegis_crypto_preview_side", draft.side);
  const shouldArm = arm === true || (arm !== false && state.cryptoTradePreviewArmed);

  if (!draft.symbol || !Number.isFinite(draft.quantity) || draft.quantity <= 0) {
    state.cryptoTradePreview = null;
    state.cryptoTradePreviewPendingOrder = null;
    state.cryptoTradePreviewArmed = false;
    renderCryptoTradePreview();
    return null;
  }

  const requestKey = getCryptoTradeDraftKey(draft);
  const now = Date.now();
  if (!force && state.lastCryptoTradePreviewKey === requestKey && (now - Number(state.lastCryptoTradePreviewAt || 0)) < 10000) {
    state.cryptoTradePreviewArmed = shouldArm;
    state.cryptoTradePreviewPendingOrder = shouldArm ? draft : null;
    renderCryptoTradePreview();
    return state.cryptoTradePreview;
  }
  if (state.cryptoTradePreviewInFlight) {
    state.cryptoTradePreviewQueued = true;
    return state.cryptoTradePreview;
  }

  state.cryptoTradePreviewInFlight = true;
  state.lastCryptoTradePreviewAt = now;
  state.lastCryptoTradePreviewKey = requestKey;
  try {
    const url = new URL(endpoints.cryptoTradePreview, location.origin);
    url.searchParams.set("horizon_minutes", String(draft.horizon));
    if (draft.regime) url.searchParams.set("regime", draft.regime);
    const res = await fetchWithTimeout(
      url.toString(),
      {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          symbol: draft.symbol,
          side: draft.side,
          quantity: draft.quantity,
          test: draft.test,
          execution_mode: draft.executionMode,
          stop_loss_pct: draft.stopLossPct,
          take_profit_pct: draft.takeProfitPct,
          max_exposure_quote: draft.maxExposureQuote,
          max_order_size_pct: draft.maxOrderSizePct,
        }),
      },
      { timeout: 12000, retries: 0 }
    );
    const data = await safeJson(res);
    if (!res.ok || !data || typeof data !== "object") {
      throw new Error(`HTTP ${res.status}`);
    }
    state.cryptoTradePreview = data;
    state.cryptoTradePreviewArmed = shouldArm;
    state.cryptoTradePreviewPendingOrder = shouldArm ? draft : null;
    updateCryptoExecutionUI();
    const blockedByRisk = data?.risk_gate && data.risk_gate.allowed === false;
    const calibrationSizing = formatCryptoCalibrationSizing(data?.risk_gate, { es: state.lang === LANG.ES, includeStatus: false });
    const suggestedQty = getCryptoCalibrationSuggestedQuantity(data?.risk_gate, draft.quantity);
    const suggestedQtyText = Number.isFinite(suggestedQty)
      ? `${state.lang === LANG.ES ? "usa qty" : "use qty"} ${formatCryptoQuantityValue(suggestedQty)}`
      : "";
    setTradeStatus(
      blockedByRisk
        ? (state.lang === LANG.ES
          ? `Preview bloqueado por risk gate • ${String(data?.risk_gate?.reason || "risk").replace(/_/g, " ")}${calibrationSizing ? ` • ${calibrationSizing}` : ""}${suggestedQtyText ? ` • ${suggestedQtyText}` : ""}`
          : `Preview blocked by risk gate • ${String(data?.risk_gate?.reason || "risk").replace(/_/g, " ")}${calibrationSizing ? ` • ${calibrationSizing}` : ""}${suggestedQtyText ? ` • ${suggestedQtyText}` : ""}`)
        : (state.lang === LANG.ES
          ? `Preview ${draft.side} listo • ${draft.symbol} • qty=${draft.quantity}`
          : `${draft.side} preview ready • ${draft.symbol} • qty=${draft.quantity}`),
      !!blockedByRisk
    );
    return data;
  } catch (err) {
    console.error("crypto-trade-preview", err);
    state.cryptoTradePreview = null;
    state.cryptoTradePreviewPendingOrder = null;
    state.cryptoTradePreviewArmed = false;
    renderCryptoTradePreview();
    setTradeStatus(
      state.lang === LANG.ES
        ? "No pude generar el preview de la orden."
        : "Could not generate the order preview.",
      true
    );
    return null;
  } finally {
    state.cryptoTradePreviewInFlight = false;
    if (state.cryptoTradePreviewQueued) {
      state.cryptoTradePreviewQueued = false;
      setTimeout(() => loadCryptoTradePreview({ side: state.cryptoPreviewSide || "BUY", force: true }), 0);
    }
  }
}

async function confirmCryptoTrade() {
  const draft = state.cryptoTradePreviewPendingOrder || buildCryptoTradeDraft(state.cryptoPreviewSide || "BUY");
  const currentKey = getCryptoTradeDraftKey(draft);
  if (!state.cryptoTradePreview || state.lastCryptoTradePreviewKey !== currentKey) {
    await loadCryptoTradePreview({ side: draft.side || "BUY", force: true });
    setTradeStatus(
      state.lang === LANG.ES
        ? "Preview refrescado. Confirma otra vez."
        : "Preview refreshed. Confirm again.",
      false
    );
    return false;
  }
  const ok = await submitTrade(draft.side, {
    symbol: draft.symbol,
    quantity: draft.quantity,
    executionMode: draft.executionMode,
    horizon: draft.horizon,
    regime: draft.regime,
    stopLossPct: draft.stopLossPct,
    takeProfitPct: draft.takeProfitPct,
    maxExposureQuote: draft.maxExposureQuote,
    maxOrderSizePct: draft.maxOrderSizePct,
  });
  if (ok) {
    state.cryptoTradePreviewArmed = false;
    state.cryptoTradePreviewPendingOrder = null;
    renderCryptoTradePreview();
  }
  return ok;
}

function renderCryptoTradePreview() {
  if (!dom.cryptoTradePreview) return;
  const es = state.lang === LANG.ES;
  const preview = state.cryptoTradePreview && typeof state.cryptoTradePreview === "object" ? state.cryptoTradePreview : null;
  dom.cryptoTradePreview.innerHTML = "";

  const head = el("div", { class: "preview-head" });
  head.appendChild(el("div", { class: "preview-title", text: es ? "Trade preview" : "Trade preview" }));
  const side = normalizeCryptoTradeSide(state.cryptoPreviewSide || preview?.side || state.lastPrediction?.action_decision || "BUY");
  head.appendChild(el("span", { class: `pill ${side === "BUY" ? "buy" : "sell"}`, text: side }));
  dom.cryptoTradePreview.appendChild(head);

  if (!preview) {
    dom.cryptoTradePreview.appendChild(el("div", {
      class: "preview-hint",
      text: es
        ? "Mueve Qty, símbolo, modo o controles de riesgo para generar un preview antes de enviar la orden."
        : "Change Qty, symbol, mode or risk controls to generate a preview before sending the order.",
    }));
    const guardrailsSummary = formatCryptoRiskControlSummary(getCryptoRiskControlValues(), { es });
    if (guardrailsSummary) {
      dom.cryptoTradePreview.appendChild(el("div", { class: "preview-note preview-guardrails", text: guardrailsSummary }));
    }
    dom.cryptoTradePreview.appendChild(el("div", {
      class: "preview-note",
      text: es
        ? "La idea es simular la fricción real del libro: spread, slippage y tamaño afectan el fill."
        : "The idea is to simulate real order-book friction: spread, slippage and size affect the fill.",
    }));
    return;
  }

  const risk = preview.risk && typeof preview.risk === "object" ? preview.risk : {};
  const riskGate = preview.risk_gate && typeof preview.risk_gate === "object" ? preview.risk_gate : null;
  const calibrationSizing = formatCryptoCalibrationSizing(riskGate, { es, includeStatus: true });
  const direction = String(preview.signal_decision || risk.decision || side).toUpperCase();
  const mode = String(preview.execution_mode || preview.requested_mode || state.cryptoExecutionMode || "simulated").toUpperCase();
  const tradeLabel = `${side} ${preview.symbol || state.chartSymbol || "BTCUSDT"}`;
  const qty = Number(preview.quantity ?? dom.chatTradeQty?.value ?? 0);
  const entry = Number(preview.fill_price ?? preview.price ?? preview.mid_price ?? risk.entry_price);
  const target = Number(preview.target_price ?? risk.target_price);
  const stop = Number(preview.stop_price ?? risk.stop_price);
  const gain = Number(preview.expected_gain_quote);
  const loss = Number(preview.expected_loss_quote);
  const rr = Number(preview.risk_reward ?? risk.risk_reward);
  const spread = Number(preview.spread_bps);
  const slippage = Number(preview.slippage_bps);
  const executionDrag = Number(preview.execution_drag_pct ?? risk.execution_drag_pct);
  const liquidity = String(preview.liquidity_bucket || risk.liquidity_bucket || "").trim() || null;
  const signalProb = Number(preview.signal_probability_up ?? risk.probability_up);
  const projectedMove = Number(preview.projected_move_pct ?? risk.projected_move_pct);
  const netAfterCostsPct = Number(preview.net_expected_profit_after_costs_pct ?? risk.net_expected_profit_after_costs_pct);
  const netAfterCostsQuote = Number(preview.net_expected_profit_after_costs_quote ?? risk.net_expected_profit_after_costs_quote);
  const orderNotional = Number(preview.order_notional ?? risk.order_notional);
  const visibleLiquidity = Number(preview.visible_liquidity_notional ?? risk.visible_liquidity_notional);
  const sideLiquidity = Number(preview.side_liquidity_notional ?? risk.side_liquidity_notional);
  const orderSizePct = Number(preview.order_size_pct ?? risk.order_size_pct);
  const bookConsumptionPct = Number(preview.book_consumption_pct ?? risk.book_consumption_pct);
  const participationPct = Number(preview.participation_pct ?? risk.participation_pct);
  const othersPct = Number(preview.others_pct ?? risk.others_pct);
  const remainingLiquidity = Number(preview.remaining_liquidity ?? risk.remaining_liquidity);
  const preTradePrice = Number(preview.pre_trade_price ?? risk.pre_trade_price);
  const postTradeEstimate = Number(preview.post_trade_estimate ?? risk.post_trade_estimate);
  const impactScore = Number(preview.impact_score ?? risk.impact_score);
  const suggestedQty = getCryptoCalibrationSuggestedQuantity(riskGate, qty);

  const row = el("div", { class: "preview-body" });
  row.appendChild(el("span", { class: "pill neutral", text: tradeLabel }));
  row.appendChild(el("span", { class: `pill ${direction === "BUY" ? "buy" : direction === "SELL" ? "sell" : "neutral"}`, text: `${es ? "Señal" : "Signal"} ${direction}` }));
  if (Number.isFinite(signalProb)) row.appendChild(el("span", { class: "pill muted", text: `${formatProb(signalProb)}` }));
  if (Number.isFinite(qty) && qty > 0) row.appendChild(el("span", { class: "pill neutral", text: `${es ? "Qty" : "Qty"} ${qty}` }));
  if (Number.isFinite(entry)) row.appendChild(el("span", { class: "pill success", text: `${es ? "Fill" : "Fill"} ${formatPrice(entry)}` }));
  if (Number.isFinite(target)) row.appendChild(el("span", { class: "pill positive", text: `${es ? "Objetivo" : "Target"} ${formatPrice(target)}` }));
  if (Number.isFinite(stop)) row.appendChild(el("span", { class: "pill danger", text: `${es ? "Stop" : "Stop"} ${formatPrice(stop)}` }));
  if (Number.isFinite(rr)) row.appendChild(el("span", { class: "pill success", text: `R:R ${rr.toFixed(2)}` }));
  if (Number.isFinite(spread)) row.appendChild(el("span", { class: "pill muted", text: `${es ? "Spread" : "Spread"} ${spread.toFixed(1)}bps` }));
  if (Number.isFinite(slippage)) row.appendChild(el("span", { class: "pill muted", text: `${es ? "Slippage" : "Slippage"} ${slippage.toFixed(1)}bps` }));
  if (Number.isFinite(executionDrag)) row.appendChild(el("span", { class: "pill muted", text: `${es ? "Drag" : "Drag"} ${formatPct(executionDrag, 2)}` }));
  if (liquidity) row.appendChild(el("span", { class: "pill neutral", text: liquidity }));
  if (Number.isFinite(projectedMove)) row.appendChild(el("span", { class: "pill muted", text: `${es ? "Move" : "Move"} ${formatPct(projectedMove, 2)}` }));
  if (Number.isFinite(orderSizePct)) row.appendChild(el("span", { class: "pill success", text: `${es ? "Mi %" : "My %"} ${formatPct(orderSizePct / 100, 2)}` }));
  if (Number.isFinite(participationPct)) row.appendChild(el("span", { class: "pill neutral", text: `${es ? "Yo / otros" : "Me / others"} ${formatPct(participationPct / 100, 1)} / ${formatPct((othersPct || 0) / 100, 1)}` }));
  if (Number.isFinite(bookConsumptionPct)) row.appendChild(el("span", { class: "pill muted", text: `${es ? "Consume libro" : "Book use"} ${formatPct(bookConsumptionPct / 100, 1)}` }));
  if (Number.isFinite(impactScore)) row.appendChild(el("span", { class: "pill warn", text: `${es ? "Impacto" : "Impact"} ${impactScore.toFixed(0)}/100` }));
  if (Number.isFinite(netAfterCostsQuote)) row.appendChild(el("span", {
    class: `pill ${netAfterCostsQuote >= 0 ? "positive" : "negative"}`,
    text: `${es ? "Neto después de costos" : "Net after costs"} ${netAfterCostsQuote >= 0 ? "+" : "-"}${formatPrice(Math.abs(netAfterCostsQuote))}`,
  }));
  if (Number.isFinite(netAfterCostsPct)) row.appendChild(el("span", {
    class: `pill ${netAfterCostsPct >= 0 ? "positive" : "negative"}`,
    text: `${es ? "Neto %" : "Net %"} ${formatPct(netAfterCostsPct, 2)}`,
  }));
  if (Number.isFinite(remainingLiquidity)) row.appendChild(el("span", { class: "pill muted", text: `${es ? "Liquidez rem." : "Remaining liq."} ${formatPrice(remainingLiquidity, { compact: true })}` }));
  if (Number.isFinite(visibleLiquidity)) row.appendChild(el("span", { class: "pill muted", text: `${es ? "Liquidez visible" : "Visible liq."} ${formatPrice(visibleLiquidity, { compact: true })}` }));
  if (riskGate) {
    row.appendChild(el("span", {
      class: `pill ${riskGate.allowed ? "success" : "danger"}`,
      text: riskGate.allowed
        ? (es ? "Risk gate OK" : "Risk gate OK")
        : `${es ? "Bloqueado" : "Blocked"} • ${String(riskGate.reason || "risk").replace(/_/g, " ")}`,
    }));
  }
  dom.cryptoTradePreview.appendChild(row);

  const comparison = el("div", { class: "preview-note" });
  const preTradeText = Number.isFinite(preTradePrice) ? formatPrice(preTradePrice) : "—";
  const postTradeText = Number.isFinite(postTradeEstimate) ? formatPrice(postTradeEstimate) : "—";
  comparison.textContent = es
    ? `Pre-trade ${preTradeText} → post-trade ${postTradeText}${Number.isFinite(orderNotional) ? ` • order ${formatPrice(orderNotional, { compact: true })}` : ""}${Number.isFinite(sideLiquidity) ? ` • side depth ${formatPrice(sideLiquidity, { compact: true })}` : ""}`
    : `Pre-trade ${preTradeText} → post-trade ${postTradeText}${Number.isFinite(orderNotional) ? ` • order ${formatPrice(orderNotional, { compact: true })}` : ""}${Number.isFinite(sideLiquidity) ? ` • side depth ${formatPrice(sideLiquidity, { compact: true })}` : ""}`;
  dom.cryptoTradePreview.appendChild(comparison);

  if (calibrationSizing) {
    dom.cryptoTradePreview.appendChild(el("div", {
      class: `preview-note ${riskGate && riskGate.allowed === false ? "preview-guardrails" : ""}`.trim(),
      text: `${es ? "Sizing calibrado" : "Calibrated sizing"}: ${calibrationSizing}`,
    }));
  }

  const guardrailsSummary = formatCryptoRiskControlSummary(getCryptoRiskControlValues(), { es });
  if (guardrailsSummary) {
    dom.cryptoTradePreview.appendChild(el("div", { class: "preview-note preview-guardrails", text: guardrailsSummary }));
  }

  const noteText = preview.execution_note
    ? String(preview.execution_note)
    : (es
      ? "El preview aplica fricción de libro: más tamaño = más impacto."
      : "The preview applies order-book friction: larger size means more impact.");
  const marketStyle = es
    ? "Flujo tipo STP/ECN: spread + slippage + impacto aproximan fills con LPs o market makers."
    : "STP/ECN-style flow: spread + slippage + impact approximate LP / market-maker fills.";
  dom.cryptoTradePreview.appendChild(el("div", { class: "preview-note", text: `${noteText} • ${marketStyle}${mode ? ` • ${mode}` : ""}` }));

  const footer = el("div", { class: "preview-footer" });
  const pendingKey = getCryptoTradeDraftKey(state.cryptoTradePreviewPendingOrder);
  const currentKey = getCryptoTradeDraftKey(buildCryptoTradeDraft(side));
  const canConfirm = !!preview && !!state.cryptoTradePreviewArmed && !!state.cryptoTradePreviewPendingOrder && pendingKey === currentKey && (!riskGate || riskGate.allowed !== false);
  if (canConfirm) {
    const confirmBtn = el("button", {
      class: "preview-confirm-btn",
      type: "button",
      text: es ? "Confirmar orden" : "Confirm order",
    });
    confirmBtn.addEventListener("click", () => {
      confirmCryptoTrade().catch((err) => console.error("crypto-confirm", err));
    });
    footer.appendChild(confirmBtn);
    footer.appendChild(el("span", {
      class: "preview-footer-note",
      text: es
        ? "Revisa fill, spread, slippage y modo antes de confirmar."
        : "Review fill, spread, slippage and mode before confirming.",
    }));
  } else {
    if (Number.isFinite(suggestedQty)) {
      const adjustBtn = el("button", {
        class: "preview-confirm-btn preview-adjust-btn",
        type: "button",
        text: es
          ? `Usar qty máx ${formatCryptoQuantityValue(suggestedQty)}`
          : `Use max qty ${formatCryptoQuantityValue(suggestedQty)}`,
      });
      adjustBtn.addEventListener("click", () => {
        applyCryptoSuggestedQuantity(riskGate, { side }).catch((err) => console.error("crypto-apply-suggested-qty", err));
      });
      footer.appendChild(adjustBtn);
    }
    footer.appendChild(el("span", {
      class: "preview-footer-note",
      text: riskGate && riskGate.allowed === false
        ? (es
          ? `Bloqueado por risk gate: ${String(riskGate.reason || "risk").replace(/_/g, " ")}${calibrationSizing ? ` • ${calibrationSizing}` : ""}${Number.isFinite(suggestedQty) ? ` • usa qty ${formatCryptoQuantityValue(suggestedQty)}` : ""}`
          : `Blocked by risk gate: ${String(riskGate.reason || "risk").replace(/_/g, " ")}${calibrationSizing ? ` • ${calibrationSizing}` : ""}${Number.isFinite(suggestedQty) ? ` • use qty ${formatCryptoQuantityValue(suggestedQty)}` : ""}`)
        : (es
          ? "Preview vivo actualizado con Qty, símbolo, modo y controles de riesgo actuales. Pulsa Buy/Sell para armar la orden."
          : "Live preview updated from current Qty, symbol, mode and risk controls. Click Buy/Sell to arm the order."),
    }));
  }
  dom.cryptoTradePreview.appendChild(footer);
}

function getCryptoOrderBookSummary() {
  const cryptoState = state.cryptoState && typeof state.cryptoState === "object" ? state.cryptoState : {};
  const book = cryptoState.order_book && typeof cryptoState.order_book === "object" ? cryptoState.order_book : null;
  if (!book) {
    return { ready: false, raw: null };
  }

  const bids = Array.isArray(book.bids)
    ? book.bids.slice(0, 5).map((row) => ({
        price: Number(row?.price),
        qty: Number(row?.qty),
        notional: Number(row?.notional),
      }))
    : [];
  const asks = Array.isArray(book.asks)
    ? book.asks.slice(0, 5).map((row) => ({
        price: Number(row?.price),
        qty: Number(row?.qty),
        notional: Number(row?.notional),
      }))
    : [];
  const spreadBps = Number.isFinite(Number(book.spread_bps))
    ? Number(book.spread_bps)
    : Number.isFinite(Number(book.best_bid)) && Number.isFinite(Number(book.best_ask)) && Number(book.mid_price)
      ? Math.max(0, ((Number(book.best_ask) - Number(book.best_bid)) / Number(book.mid_price)) * 10000)
      : NaN;
  const imbalance = Number.isFinite(Number(book.imbalance)) ? Number(book.imbalance) : 0.5;
  const bestBid = Number(book.best_bid);
  const bestAsk = Number(book.best_ask);
  const mid = Number.isFinite(Number(book.mid_price))
    ? Number(book.mid_price)
    : Number.isFinite(bestBid) && Number.isFinite(bestAsk)
      ? (bestBid + bestAsk) / 2
      : NaN;
  const maxNotional = Math.max(
    1,
    ...bids.map((row) => (Number.isFinite(row.notional) ? row.notional : 0)),
    ...asks.map((row) => (Number.isFinite(row.notional) ? row.notional : 0))
  );
  return {
    ready: true,
    raw: book,
    source: String(book.source || "").trim() || null,
    liquidityBucket: String(book.liquidity_bucket || "").trim() || null,
    spreadBps,
    spread: Number(book.spread),
    imbalance,
    bestBid,
    bestAsk,
    mid,
    bidNotional: Number(book.bid_notional),
    askNotional: Number(book.ask_notional),
    bids,
    asks,
    maxNotional,
    note: String(book.note || "").trim() || null,
    levels: Number(book.levels || 5),
  };
}

function renderDepthSide(side, levels, maxNotional) {
  const sideClass = side === "bids" ? "buy" : "sell";
  const es = state.lang === LANG.ES;
  const card = el("div", { class: `depth-side ${sideClass}` });
  const header = el("div", { class: "depth-side-header" });
  header.appendChild(el("div", { class: "depth-side-title", text: side === "bids" ? (es ? "Compras" : "Bids") : (es ? "Ventas" : "Asks") }));
  const totalNotional = levels.reduce((acc, row) => acc + (Number.isFinite(row.notional) ? row.notional : 0), 0);
  header.appendChild(el("span", { class: "pill neutral", text: `${formatPrice(totalNotional, { compact: true })}` }));
  card.appendChild(header);

  const rows = el("div", { class: "depth-rows" });
  if (!levels.length) {
    rows.appendChild(el("div", { class: "depth-empty", text: es ? "Sin datos." : "No data." }));
  } else {
    levels.forEach((row) => {
      const notional = Number.isFinite(row.notional) ? row.notional : 0;
      const widthPct = Math.max(6, Math.min(100, (notional / Math.max(maxNotional, 1)) * 100));
      const line = el("div", { class: `depth-row ${sideClass}` });
      line.appendChild(el("span", { class: "depth-fill" }));
      line.lastChild.style.width = `${widthPct}%`;
      const content = el("div", { class: "depth-row-content" });
      content.appendChild(el("span", { class: "depth-price", text: formatPrice(row.price) }));
      content.appendChild(el("span", { class: "depth-qty", text: `${formatPrice(row.qty, { compact: true })}` }));
      content.appendChild(el("span", { class: "depth-notional", text: `${formatPrice(notional, { compact: true })}` }));
      line.appendChild(content);
      rows.appendChild(line);
    });
  }
  card.appendChild(rows);
  return card;
}

function renderCryptoOrderBook() {
  if (!dom.cryptoOrderBook) return;
  const es = state.lang === LANG.ES;
  const summary = getCryptoOrderBookSummary();
  dom.cryptoOrderBook.innerHTML = "";

  const head = el("div", { class: "preview-head" });
  head.appendChild(el("div", { class: "preview-title", text: es ? "Libro / Liquidez" : "Order book / Liquidity" }));
  if (!summary.ready) {
    dom.cryptoOrderBook.appendChild(head);
    dom.cryptoOrderBook.appendChild(el("div", {
      class: "preview-hint",
      text: es
        ? "Sin order book aún. Cambia símbolo o modo para cargar profundidad real/sintética."
        : "No order book yet. Change symbol or mode to load real/synthetic depth.",
    }));
    return;
  }

  head.appendChild(el("span", { class: `pill ${summary.source === "binance" ? "success" : "muted"}`, text: summary.source || "—" }));
  if (summary.liquidityBucket) {
    head.appendChild(el("span", { class: "pill neutral", text: summary.liquidityBucket }));
  }
  dom.cryptoOrderBook.appendChild(head);

  const summaryRow = el("div", { class: "depth-summary-row" });
  summaryRow.appendChild(el("span", { class: "pill buy", text: `${es ? "Bid" : "Bid"} ${formatPrice(summary.bestBid)}` }));
  summaryRow.appendChild(el("span", { class: "pill sell", text: `${es ? "Ask" : "Ask"} ${formatPrice(summary.bestAsk)}` }));
  summaryRow.appendChild(el("span", { class: "pill muted", text: `${es ? "Spread" : "Spread"} ${formatPrice(summary.spreadBps, { compact: true })} bps` }));
  summaryRow.appendChild(el("span", { class: "pill neutral", text: `${es ? "Imbalance" : "Imbalance"} ${(Number(summary.imbalance) * 100).toFixed(1)}%` }));
  dom.cryptoOrderBook.appendChild(summaryRow);

  const imbalanceWrap = el("div", { class: "depth-imbalance" });
  const imbalanceLabel = el("div", { class: "depth-imbalance-label" });
  imbalanceLabel.appendChild(el("span", { text: es ? "Presión compra" : "Buy pressure" }));
  imbalanceLabel.appendChild(el("span", { text: `${(Number(summary.imbalance) * 100).toFixed(1)}%` }));
  const imbalanceBar = el("div", { class: "depth-imbalance-bar" });
  const imbalanceFill = el("div", { class: "depth-imbalance-fill" });
  imbalanceFill.style.width = `${Math.max(0, Math.min(100, Number(summary.imbalance) * 100))}%`;
  imbalanceBar.appendChild(imbalanceFill);
  imbalanceWrap.appendChild(imbalanceLabel);
  imbalanceWrap.appendChild(imbalanceBar);
  dom.cryptoOrderBook.appendChild(imbalanceWrap);

  if (summary.note) {
    dom.cryptoOrderBook.appendChild(el("div", { class: "preview-note", text: summary.note }));
  }

  const grid = el("div", { class: "depth-grid" });
  grid.appendChild(renderDepthSide("bids", summary.bids || [], summary.maxNotional || 1));
  grid.appendChild(renderDepthSide("asks", summary.asks || [], summary.maxNotional || 1));
  dom.cryptoOrderBook.appendChild(grid);
}

function updateCryptoTradePreviewUI() {
  renderCryptoTradePreview();
  renderCryptoOrderBook();
}

function getCryptoStateRequestKey(scope = getCurrentCryptoScope(), executionMode = state.cryptoExecutionMode) {
  const normalizedScope = scope && typeof scope === "object" ? scope : getCurrentCryptoScope();
  const mode = normalizeCryptoExecutionMode(executionMode || state.cryptoExecutionMode || "simulated");
  const rawHorizon = normalizedScope.horizon ?? normalizedScope.horizon_minutes;
  const horizon = Number.isFinite(Number(rawHorizon)) ? Number(rawHorizon) : 15;
  return [
    normalizedScope.symbol || "",
    horizon,
    normalizedScope.regime || "",
    mode,
  ].join("|");
}

function applyCryptoStateSnapshot(data, { source = "poll", refreshPreview = true } = {}) {
  if (!data || typeof data !== "object") return null;
  state.cryptoState = data;
  const exec = data.execution && typeof data.execution === "object" ? data.execution : {};
  const selected = normalizeCryptoExecutionMode(exec.requested_mode || exec.mode || state.cryptoExecutionMode || "simulated");
  state.cryptoExecutionMode = selected;
  localStorage.setItem("aegis_crypto_execution_mode", selected);
  state.lastCryptoStateAt = Date.now();
  state.lastCryptoStateKey = getCryptoStateRequestKey(data.scope || getCurrentCryptoScope(), selected);
  state.cryptoStateQueued = false;
  updateCryptoExecutionUI();
  if (refreshPreview && (state.chartVisible || state.mode === MODES.CRYPTO)) {
    scheduleCryptoTradePreviewRefresh({ side: state.cryptoPreviewSide || "BUY", force: false });
  }
  if (source !== "stream") {
    scheduleSnapshot();
  }
  updateCryptoStatePolling();
  return data;
}

function parseCryptoStreamBlock(rawBlock) {
  const block = String(rawBlock || "").trim();
  if (!block) return null;
  const lines = block.split(/\r?\n/);
  let eventName = "message";
  const dataLines = [];
  for (const line of lines) {
    if (!line || line.startsWith(":")) continue;
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim() || "message";
      continue;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).replace(/^\s/, ""));
    }
  }
  const dataText = dataLines.join("\n").trim();
  let payload = null;
  if (dataText) {
    try {
      payload = JSON.parse(dataText);
    } catch {
      payload = { raw: dataText };
    }
  }
  return { eventName, payload };
}

function handleCryptoStreamEvent(eventName, payload) {
  if (eventName === "crypto_state") {
    const snapshot = payload && typeof payload === "object" && payload.snapshot && typeof payload.snapshot === "object"
      ? payload.snapshot
      : payload;
    if (snapshot && typeof snapshot === "object") {
      applyCryptoStateSnapshot(snapshot, { source: "stream", refreshPreview: true });
    }
    state.cryptoStateStreamLastHeartbeatAt = Date.now();
    return true;
  }
  if (eventName === "heartbeat") {
    state.cryptoStateStreamLastHeartbeatAt = Date.now();
    if (payload && typeof payload === "object" && payload.scope && payload.scope.symbol) {
      const nextSymbol = String(payload.scope.symbol || "").trim().toUpperCase();
      if (nextSymbol && nextSymbol !== state.chartSymbol) {
        state.chartSymbol = nextSymbol;
      }
    }
    updateCryptoExecutionUI();
    return true;
  }
  return false;
}

function stopCryptoStateLiveStream({ fallback = false } = {}) {
  if (state.cryptoStateStreamReconnectTimer) {
    clearTimeout(state.cryptoStateStreamReconnectTimer);
    state.cryptoStateStreamReconnectTimer = null;
  }
  const controller = state.cryptoStateStreamController;
  state.cryptoStateStreamController = null;
  state.cryptoStateStreamActive = false;
  state.cryptoStateStreamInFlight = false;
  state.cryptoStateStreamLastHeartbeatAt = 0;
  state.cryptoStateStreamFallbackActive = !!fallback;
  if (controller) {
    try {
      controller.abort();
    } catch {}
    unregisterAbortController(controller);
  }
  updateStatusCenter();
}

function scheduleCryptoStateStreamReconnect(delayMs = 5000) {
  if (state.cryptoStateStreamReconnectTimer) {
    clearTimeout(state.cryptoStateStreamReconnectTimer);
  }
  if (document.hidden || !(state.chartVisible || state.mode === MODES.CRYPTO)) return;
  state.cryptoStateStreamReconnectTimer = setTimeout(() => {
    state.cryptoStateStreamReconnectTimer = null;
    if (document.hidden || !(state.chartVisible || state.mode === MODES.CRYPTO)) return;
    startCryptoStateLiveStream({ force: true }).catch(() => {});
  }, Math.max(1000, Number(delayMs) || 5000));
}

async function startCryptoStateLiveStream({ force = false } = {}) {
  if (document.hidden || !(state.chartVisible || state.mode === MODES.CRYPTO)) {
    stopCryptoStateLiveStream();
    stopCryptoStatePolling();
    return false;
  }
  const streamKey = getCryptoStateRequestKey();
  if (!force && state.cryptoStateStreamActive && state.cryptoStateStreamKey === streamKey) {
    return true;
  }
  if (state.cryptoStateStreamInFlight) return false;
  if (state.cryptoStateStreamController && state.cryptoStateStreamKey !== streamKey) {
    stopCryptoStateLiveStream();
  }

  state.cryptoStateStreamInFlight = true;
  state.cryptoStateStreamKey = streamKey;
  state.cryptoStateStreamFallbackActive = false;
  state.cryptoStateStreamFailures = force ? 0 : Number(state.cryptoStateStreamFailures || 0);
  updateStatusCenter();

  const controller = registerAbortController(new AbortController());
  state.cryptoStateStreamController = controller;

  try {
    await ensureAccessToken();
    const scope = getCurrentCryptoScope();
    const executionMode = normalizeCryptoExecutionMode(
      state.cryptoExecutionMode || state.cryptoState?.execution?.requested_mode || state.cryptoState?.execution?.mode || "simulated"
    );
    const url = new URL(endpoints.cryptoStateStream, location.origin);
    url.searchParams.set("symbol", scope.symbol);
    url.searchParams.set("engine", "all");
    url.searchParams.set("horizon_minutes", String(scope.horizon));
    url.searchParams.set("execution_mode", executionMode);
    if (scope.regime) url.searchParams.set("regime", scope.regime);

    const headers = withJsonHeaders({ Accept: "text/event-stream", "Cache-Control": "no-cache" }, "main");
    let res = await fetch(url.toString(), { headers, signal: controller.signal, credentials: "include" });
    if (res.status === 401 || res.status === 403) {
      if (await tryRefreshAccessToken()) {
        const retryHeaders = withJsonHeaders({ Accept: "text/event-stream", "Cache-Control": "no-cache" }, "main");
        res = await fetch(url.toString(), { headers: retryHeaders, signal: controller.signal, credentials: "include" });
      }
      if (res.status === 401 || res.status === 403) {
        await markAuthFailure(url, res, { scope: authScopeForUrl(url), keyToUse: cleanKey(state.apiKey) });
        throw new Error(`HTTP ${res.status}`);
      }
    }
    if (!res.ok || !res.body) {
      throw new Error(`HTTP ${res.status}`);
    }

    state.cryptoStateStreamActive = true;
    state.cryptoStateStreamFailures = 0;
    state.cryptoStateStreamLastHeartbeatAt = Date.now();
    stopCryptoStatePolling();
    updateCryptoExecutionUI();

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      if (controller.signal.aborted || document.hidden || !(state.chartVisible || state.mode === MODES.CRYPTO)) break;
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const parsed = parseCryptoStreamBlock(block);
        if (parsed) handleCryptoStreamEvent(parsed.eventName, parsed.payload);
        boundary = buffer.indexOf("\n\n");
      }
    }
    if (buffer.trim()) {
      const parsed = parseCryptoStreamBlock(buffer);
      if (parsed) handleCryptoStreamEvent(parsed.eventName, parsed.payload);
    }
    return true;
  } catch (err) {
    if (!controller.signal.aborted) {
      console.error("crypto-state-stream-error", err);
      state.cryptoStateStreamFailures = Number(state.cryptoStateStreamFailures || 0) + 1;
      state.cryptoStateStreamFallbackActive = true;
      startCryptoStatePolling();
      const backoff = Math.min(20000, 4000 + (state.cryptoStateStreamFailures * 2500));
      scheduleCryptoStateStreamReconnect(backoff);
    }
    return false;
  } finally {
    state.cryptoStateStreamInFlight = false;
    state.cryptoStateStreamActive = false;
    if (state.cryptoStateStreamController === controller) {
      state.cryptoStateStreamController = null;
    }
    unregisterAbortController(controller);
    updateCryptoExecutionUI();
    updateStatusCenter();
  }
}

function getCryptoRiskSummary() {
  const cryptoState = state.cryptoState && typeof state.cryptoState === "object" ? state.cryptoState : {};
  const risk = cryptoState.risk && typeof cryptoState.risk === "object" ? cryptoState.risk : {};
  const prediction = state.lastPrediction && typeof state.lastPrediction === "object" ? state.lastPrediction : {};
  const trade = state.lastTradeQuote && typeof state.lastTradeQuote === "object" ? state.lastTradeQuote : {};
  const decision = String(risk.decision || prediction.action_decision || prediction.decision || "HOLD").trim().toUpperCase() || "HOLD";
  const tradeable = risk.tradeable !== undefined ? !!risk.tradeable : decision === "BUY" || decision === "SELL";

  const entry = Number.isFinite(Number(risk.entry_price))
    ? Number(risk.entry_price)
    : Number.isFinite(Number(trade.fill_price))
      ? Number(trade.fill_price)
      : Number.isFinite(Number(trade.price))
        ? Number(trade.price)
        : Number.isFinite(Number(prediction.current_price))
          ? Number(prediction.current_price)
          : Number.isFinite(Number(cryptoState.current_price))
            ? Number(cryptoState.current_price)
            : NaN;
  const target = Number.isFinite(Number(risk.target_price))
    ? Number(risk.target_price)
    : Number.isFinite(Number(prediction.predicted_price))
      ? Number(prediction.predicted_price)
      : NaN;
  const stop = Number.isFinite(Number(risk.stop_price)) ? Number(risk.stop_price) : NaN;
  const projectedMovePct = Number.isFinite(Number(risk.projected_move_pct))
    ? Number(risk.projected_move_pct)
    : Number.isFinite(entry) && Number.isFinite(target) && entry > 0
      ? Math.abs((target - entry) / entry)
      : NaN;
  const netEdgePct = Number.isFinite(Number(risk.net_edge_pct))
    ? Number(risk.net_edge_pct)
    : Number.isFinite(projectedMovePct)
      ? projectedMovePct
      : NaN;
  const netAfterCostsPct = Number.isFinite(Number(risk.net_expected_profit_after_costs_pct))
    ? Number(risk.net_expected_profit_after_costs_pct)
    : netEdgePct;
  const stopLossPct = Number.isFinite(Number(risk.stop_loss_pct)) ? Number(risk.stop_loss_pct) : NaN;
  const takeProfitPct = Number.isFinite(Number(risk.take_profit_pct))
    ? Number(risk.take_profit_pct)
    : Number.isFinite(projectedMovePct)
      ? projectedMovePct
      : NaN;
  const executionDragPct = Number.isFinite(Number(risk.execution_drag_pct)) ? Number(risk.execution_drag_pct) : 0;
  const riskReward = Number.isFinite(Number(risk.risk_reward))
    ? Number(risk.risk_reward)
    : Number.isFinite(takeProfitPct) && Number.isFinite(stopLossPct) && stopLossPct > 0
      ? takeProfitPct / stopLossPct
      : NaN;
  const qty = Number.parseFloat(dom.chatTradeQty?.value || trade.quantity || "0");
  const gainQuote = tradeable && Number.isFinite(qty) && qty > 0 && Number.isFinite(entry) && Number.isFinite(netEdgePct)
    ? qty * entry * Math.max(0, netEdgePct)
    : NaN;
  const netAfterCostsQuote = tradeable && Number.isFinite(qty) && qty > 0 && Number.isFinite(entry) && Number.isFinite(netAfterCostsPct)
    ? qty * entry * netAfterCostsPct
    : Number.isFinite(Number(risk.net_expected_profit_after_costs_quote))
      ? Number(risk.net_expected_profit_after_costs_quote)
      : NaN;
  const lossQuote = tradeable && Number.isFinite(qty) && qty > 0 && Number.isFinite(entry) && Number.isFinite(stopLossPct)
    ? qty * entry * (stopLossPct + executionDragPct)
    : NaN;
  const projectedQuote = Number.isFinite(qty) && qty > 0 && Number.isFinite(entry) && Number.isFinite(projectedMovePct)
    ? qty * entry * projectedMovePct
    : NaN;
  const signalLabel = tradeable ? decision : "WATCH";
  const mode = String(risk.execution_mode || cryptoState.execution?.mode || state.cryptoExecutionMode || "simulated").trim().toLowerCase() || "simulated";
  const liquidity = String(risk.liquidity_bucket || trade.liquidity_bucket || "").trim() || null;
  const livePrice = Number.isFinite(Number(cryptoState.current_price)) ? Number(cryptoState.current_price) : entry;

  return {
    ready: Number.isFinite(entry) && Number.isFinite(target),
    decision,
    tradeable,
    signalLabel,
    entry,
    target,
    stop,
    projectedMovePct,
    netEdgePct,
    netAfterCostsPct,
    stopLossPct,
    takeProfitPct,
    executionDragPct,
    riskReward,
    gainQuote,
    netAfterCostsQuote,
    lossQuote,
    projectedQuote,
    qty: Number.isFinite(qty) && qty > 0 ? qty : NaN,
    mode,
    liquidity,
    livePrice,
    raw: risk,
  };
}

function startCryptoStatePolling() {
  if (state.cryptoStateTimer) return;
  if (state.cryptoStateStreamActive || state.cryptoStateStreamInFlight) return;
  const tick = () => {
    if (document.hidden) return;
    if (!(state.chartVisible || state.mode === MODES.CRYPTO)) return;
    loadCryptoState();
  };
  state.cryptoStateTimer = setInterval(tick, 30000);
  tick();
}

function stopCryptoStatePolling() {
  if (state.cryptoStateTimer) clearInterval(state.cryptoStateTimer);
  state.cryptoStateTimer = null;
}

function updateCryptoStatePolling() {
  if (document.hidden) {
    stopCryptoStateLiveStream();
    stopCryptoStatePolling();
    return;
  }
  if (state.chartVisible || state.mode === MODES.CRYPTO) {
    stopCryptoStatePolling();
    startCryptoStateLiveStream().catch((err) => console.error("crypto-stream-start", err));
  } else {
    stopCryptoStateLiveStream();
    stopCryptoStatePolling();
  }
}

async function loadCryptoState({ force = false } = {}) {
  const scope = getCurrentCryptoScope();
  const executionMode = normalizeCryptoExecutionMode(state.cryptoExecutionMode);
  const requestKey = `${scope.symbol}|${scope.horizon}|${scope.regime || ""}|${executionMode}`;
  const now = Date.now();
  if (!force && state.lastCryptoStateKey === requestKey && (now - Number(state.lastCryptoStateAt || 0)) < 12000) {
    return state.cryptoState;
  }
  if (state.cryptoStateInFlight) {
    state.cryptoStateQueued = true;
    return state.cryptoState;
  }
  state.cryptoStateInFlight = true;
  state.lastCryptoStateKey = requestKey;
  state.lastCryptoStateAt = now;
  try {
    const url = new URL(endpoints.cryptoState, location.origin);
    url.searchParams.set("symbol", scope.symbol);
    url.searchParams.set("engine", "all");
    url.searchParams.set("horizon_minutes", String(scope.horizon));
    url.searchParams.set("execution_mode", executionMode);
    if (scope.regime) url.searchParams.set("regime", scope.regime);
    const res = await fetchWithTimeout(url.toString(), { headers: { Accept: "application/json" } }, { timeout: 10000, retries: 0 });
    const data = await safeJson(res);
    if (res.ok && data && typeof data === "object") {
      applyCryptoStateSnapshot(data, { source: "poll", refreshPreview: true });
    }
  } catch (err) {
    console.error("crypto-state-error", err);
  } finally {
    state.cryptoStateInFlight = false;
    if (state.cryptoStateQueued) {
      state.cryptoStateQueued = false;
      setTimeout(() => loadCryptoState({ force: true }), 0);
    }
  }
  return state.cryptoState;
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
  if (dom.chartSymbol) dom.chartSymbol.value = cmd.symbol;
  state.chartSymbol = cmd.symbol;
  if (dom.chatTradeQty) dom.chatTradeQty.value = String(cmd.quantity);
  state.cryptoPreviewSide = cmd.side;
  state.cryptoTradePreviewArmed = true;
  localStorage.setItem("aegis_crypto_preview_side", cmd.side);
  if (!state.chartVisible) {
    showCryptoPanelFromToolbar();
  }
  appendBubble(
    state.lang === LANG.ES
      ? `Preview ${cmd.side} cargado para ${cmd.symbol} qty=${cmd.quantity}. Confirma desde el panel de Cripto.`
      : `${cmd.side} preview loaded for ${cmd.symbol} qty=${cmd.quantity}. Confirm from the Crypto panel.`,
    "bot"
  );
  loadCryptoPrediction({ force: true }).catch(() => {});
  loadCryptoState({ force: true }).catch(() => {});
  loadCryptoTradePreview({ side: cmd.side, force: true, arm: true }).catch(() => {});
  return true;
}

async function submitTrade(side, overrides = {}) {
  const symbol = String(overrides.symbol || dom.chartSymbol?.value || state.chartSymbol || "").trim().toUpperCase();
  const qtyRaw = overrides.quantity ?? dom.chatTradeQty?.value ?? "0";
  const qty = parseFloat(qtyRaw);
  const selectedMode = normalizeCryptoExecutionMode(overrides.executionMode || overrides.execution_mode || state.cryptoExecutionMode);
  const riskControls = getCryptoRiskControlValues();

  if (!symbol) return setTradeStatus(state.lang === LANG.ES ? "Escribe un símbolo." : "Enter a symbol.", true);
  if (!Number.isFinite(qty) || qty <= 0) return setTradeStatus(state.lang === LANG.ES ? "Cantidad inválida." : "Invalid quantity.", true);

  setTradeStatus(
    state.lang === LANG.ES
      ? `Enviando orden ${side}...`
      : `Sending ${side} order...`
  );
  try {
    const payload = {
      symbol,
      side,
      quantity: qty,
      test: selectedMode !== "live",
      execution_mode: selectedMode,
      stop_loss_pct: overrides.stopLossPct ?? overrides.stop_loss_pct ?? riskControls.stopLossPct,
      take_profit_pct: overrides.takeProfitPct ?? overrides.take_profit_pct ?? riskControls.takeProfitPct,
      max_exposure_quote: overrides.maxExposureQuote ?? overrides.max_exposure_quote ?? riskControls.maxExposureQuote,
      max_order_size_pct: overrides.maxOrderSizePct ?? overrides.max_order_size_pct ?? riskControls.maxOrderSizePct,
    };
    const res = await fetchWithTimeout(endpoints.cryptoTrade, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload),
    }, { timeout: 15000, retries: 0 });

    const data = await safeJson(res);
    if (!res.ok) throw new Error("HTTP " + res.status);
    if (data?.status === "REJECTED") {
      state.lastTradeQuote = data || null;
      state.cryptoTradePreviewArmed = false;
      state.cryptoTradePreviewPendingOrder = null;
      updateCryptoExecutionUI();
      setTradeStatus(
        state.lang === LANG.ES
          ? `Orden bloqueada: ${data?.message || "risk gate"}`
          : `Order blocked: ${data?.message || "risk gate"}`,
        true
      );
      return false;
    }

    const tradePrice = parseFloat(data?.fill_price ?? data?.price ?? data?.executedPrice ?? data?.avgPrice ?? data?.lastPrice ?? data?.current_price);
    state.lastTradeQuote = data || null;
    state.cryptoTradePreviewArmed = false;
    state.cryptoTradePreviewPendingOrder = null;
    updateCryptoExecutionUI();
    setTradeStatus(
      state.lang === LANG.ES
        ? `Orden ${side} enviada (${qty}). ${data?.status || ""}${data?.execution_note ? ` • ${data.execution_note}` : ""}`.trim()
        : `${side} order sent (${qty}). ${data?.status || ""}${data?.execution_note ? ` • ${data.execution_note}` : ""}`.trim(),
      false
    );

    if (Number.isFinite(tradePrice)) {
      state.tradesOnChart.push({ t: Date.now(), price: tradePrice, side });
      if (state.lastPoints?.length) renderChart(state.lastPoints);
    }
    loadCryptoState({ force: true });
    return true;
  } catch (err) {
    console.error(err);
    setTradeStatus(state.lang === LANG.ES ? "Fallo la orden." : "Order failed.", true);
    return false;
  }
}

/* ------------------------- NEWS ------------------------- */

async function loadNews(symbolInput, { force = false } = {}) {
  if (state.newsInFlight) {
    if (force) state.newsForceQueued = true;
    return;
  }
  state.newsInFlight = true;
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
    state.newsProvider = data.provider || null;

    renderNewsList(state.newsFeed, state.newsMomentum);

    if (state.lastPoints?.length) renderChart(state.lastPoints);
  } catch (err) {
    if (err?.name !== "AbortError") console.error(err);
  } finally {
    state.newsInFlight = false;
    if (state.newsForceQueued) {
      state.newsForceQueued = false;
      setTimeout(() => loadNews(state.chartSymbol, { force: true }), 0);
    }
  }
}

function renderNewsList(items, momentum) {
  if (!dom.newsList) return;
  dom.newsList.innerHTML = "";
  if (dom.newsMomentum) dom.newsMomentum.textContent = momentum == null ? "—" : String(momentum);
  if (dom.newsProvider) {
    dom.newsProvider.textContent = state.newsProvider || "—";
    dom.newsProvider.style.display = state.newsProvider ? "inline-flex" : "none";
  }
  dom.newsList.classList.toggle("compact", !!dom.newsCompactToggle?.checked);

  if (!items?.length) {
    dom.newsList.appendChild(el("div", { class: "news-card", text: state.lang === LANG.ES ? "Sin noticias." : "No news." }));
    return;
  }

  items.slice(0, 20).forEach((n) => {
    const card = el("div", { class: "news-card" });
    const header = el("header");
    const title = el("div", { text: n.title || n.headline || "—" });
    title.style.fontWeight = "700";

    const badges = el("div", { class: "news-badges" });
    const src = n.source || n.domain || "";
    const ts = Number(n.ts || 0);
    const tsMs = ts > 1e12 ? ts : ts * 1000;

    const makeBadge = (text, cls = "") => el("span", { class: `news-badge${cls ? " " + cls : ""}`, text });
    if (src) badges.appendChild(makeBadge(src));
    if (ts) badges.appendChild(makeBadge(formatAgo(tsMs)));
    if (Number.isFinite(n.trust)) badges.appendChild(makeBadge(`trust ${Number(n.trust).toFixed(2)}`));
    if (Array.isArray(n.impact)) {
      n.impact.slice(0, 3).forEach((tag) => badges.appendChild(makeBadge(tag)));
    }

    const sent = n.sentiment ?? 0;
    const pill = el("span", {
      class: `sentiment-pill ${sent > 0.15 ? "sentiment-pos" : sent < -0.15 ? "sentiment-neg" : "sentiment-neutral"}`,
      text: sent > 0.15 ? "POS" : sent < -0.15 ? "NEG" : "NEU",
    });

    header.appendChild(title);
    header.appendChild(pill);
    card.appendChild(header);
    if (badges.childNodes.length) card.appendChild(badges);

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
  const es = state.lang === LANG.ES;
  const scope = getCurrentCryptoScope();
  const pred = state.lastPrediction || {};
  const decision = String(pred.action_decision || pred.model_decision || pred.decision || "HOLD").toUpperCase();
  const prob = Number.isFinite(Number(pred.p_final ?? pred.prob ?? pred.probability_up))
    ? Number(pred.p_final ?? pred.prob ?? pred.probability_up)
    : null;
  const pText = Number.isFinite(prob) ? formatProb(prob) : "—";
  const buyThreshold = Number.isFinite(Number(pred.buy_threshold)) ? Number(pred.buy_threshold) : 0.63;
  const sellThreshold = Number.isFinite(Number(pred.sell_threshold)) ? Number(pred.sell_threshold) : 0.37;
  const priceSource = String(pred.price_source || dom.priceSourceBadge?.textContent || "demo").toLowerCase();
  const credibility = pred.credibility_status ? String(pred.credibility_status).toUpperCase() : null;
  const credibilityScore = Number.isFinite(Number(pred.credibility_score)) ? `${(Number(pred.credibility_score) * 100).toFixed(0)}%` : "—";
  const model = String(pred.model || state.selectedCryptoModel || "ensemble").toUpperCase();
  const horizon = Number.isFinite(Number(scope.horizon)) ? `${scope.horizon}m` : "—";
  const signalRule = es
    ? `BUY si p ≥ ${formatProb(buyThreshold)} · SELL si p ≤ ${formatProb(sellThreshold)} · HOLD en medio`
    : `BUY if p ≥ ${formatProb(buyThreshold)} · SELL if p ≤ ${formatProb(sellThreshold)} · HOLD otherwise`;
  const signalFields = es
    ? [
        `Señal actual: <strong>${decision}</strong>`,
        `Símbolo / horizonte: <strong>${scope.symbol}</strong> · <strong>${horizon}</strong>`,
        `Probabilidad usada: <strong>${pText}</strong>`,
        `Modelo: <strong>${model}</strong>`,
        `Fuente: <strong>${priceSource}</strong>`,
        credibility ? `Credibilidad: <strong>${credibility}</strong> • score ${credibilityScore}` : "",
      ].filter(Boolean)
    : [
      `Current signal: <strong>${decision}</strong>`,
      `Symbol / horizon: <strong>${scope.symbol}</strong> · <strong>${horizon}</strong>`,
      `Probability used: <strong>${pText}</strong>`,
      `Model: <strong>${model}</strong>`,
      `Source: <strong>${priceSource}</strong>`,
      credibility ? `Credibility: <strong>${credibility}</strong> • score ${credibilityScore}` : "",
    ].filter(Boolean);
  const keyFields = es
    ? [
        "Signal: BUY/SELL/HOLD + p% + H.",
        "p%: prob. estimada de subida.",
        "H: minutos hasta medir el resultado.",
        "Base price: precio cuando se emitió la señal.",
        "Actual price: precio al cerrar H.",
        "Δ%: cambio real tras H.",
        "Regla: BUY gana si Δ > 0; SELL si Δ < 0; HOLD si |Δ| < 1%.",
      ]
    : [
        "Signal: BUY/SELL/HOLD + p% + H.",
        "p%: estimated probability up.",
        "H: minutes until the result is measured.",
        "Base price: price when the signal fired.",
        "Actual price: price at horizon close.",
        "Δ%: real move after H.",
        "Rule: BUY wins if Δ > 0; SELL if Δ < 0; HOLD if |Δ| < 1%.",
      ];

  const tooltip = dom.predictionCompareTooltip;
  tooltip.innerHTML = "";

  tooltip.appendChild(el("strong", { text: es ? "Cómo leer la comparación post-horizonte" : "How to read the post-horizon comparison" }));
  tooltip.appendChild(el("p", { text: signalRule }));

  const scopeLine = el("p");
  scopeLine.appendChild(document.createTextNode(es ? "Ahora mismo el scope activo es " : "The active scope is "));
  scopeLine.appendChild(el("strong", { text: scope.symbol }));
  scopeLine.appendChild(document.createTextNode(es ? " con horizonte " : " with horizon "));
  scopeLine.appendChild(el("strong", { text: horizon }));
  scopeLine.appendChild(document.createTextNode("."));
  tooltip.appendChild(scopeLine);

  const fieldsLine = el("p");
  fieldsLine.appendChild(document.createTextNode(
    es
      ? `Señal actual: ${decision} · Probabilidad usada: ${pText} · Modelo: ${model} · Fuente: ${priceSource}${credibility ? ` · Credibilidad: ${credibility} • score ${credibilityScore}` : ""}`
      : `Current signal: ${decision} · Probability used: ${pText} · Model: ${model} · Source: ${priceSource}${credibility ? ` · Credibility: ${credibility} • score ${credibilityScore}` : ""}`
  ));
  tooltip.appendChild(fieldsLine);

  tooltip.appendChild(
    el("p", {
      text: es
        ? "Flujo cripto: escribe “BTCUSDT H=2m” o usa el panel Cripto. /crypto/predictions/evaluate fuerza el cierre del horizonte."
        : "Crypto flow: type “BTCUSDT H=2m” or use the Crypto panel. /crypto/predictions/evaluate forces the horizon close.",
    })
  );
  tooltip.appendChild(
    el("p", {
      text: es
        ? "Esta vista compara la señal contra el precio real cuando vence H. No es consejo financiero."
        : "This view compares the signal against the actual price when H expires. Not financial advice.",
    })
  );
  tooltip.appendChild(el("p", { text: es ? "Campos usados por el panel:" : "Fields used by this panel:" }));

  const list = el("ul");
  list.style.margin = "6px 0 4px 14px";
  list.style.lineHeight = "1.35";
  keyFields.forEach((item) => {
    list.appendChild(el("li", { text: item }));
  });
  tooltip.appendChild(list);

  tooltip.appendChild(
    el("p", {
      text: es ? "Chequeo rápido: BUY quiere Δ↑, SELL Δ↓ y HOLD Δ≈0." : "Quick check: BUY wants Δ↑, SELL wants Δ↓ and HOLD wants Δ≈0.",
    })
  );
}

function formatPct(v, digits = 2) {
  if (!Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}
function formatProb(v) {
  if (!Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(1)}%`;
}
function getChartLabelOptions(spanMinutes) {
  const span = Number(spanMinutes);
  if (!Number.isFinite(span) || span <= 0) return { withDate: false, withSeconds: false };
  if (span <= 90) return { withDate: false, withSeconds: true };
  if (span <= 24 * 60) return { withDate: false, withSeconds: false };
  return { withDate: true, withSeconds: false };
}

function formatTimeLabel(ts, { withDate = false, withSeconds = false } = {}) {
  if (ts == null) return "—";
  let n = Number(ts);
  if (Number.isFinite(n) && n < 1e12) n *= 1000; // allow seconds
  try {
    const locale = state.lang === LANG.ES ? "es-CO" : "en-US";
    const base = { hour12: false, hour: "2-digit", minute: "2-digit" };
    if (withSeconds) {
      base.second = "2-digit";
    }
    if (withDate) {
      return new Date(n).toLocaleString(locale, {
        ...base,
        month: "short",
        day: "2-digit",
      });
    }
    return new Date(n).toLocaleTimeString(locale, base);
  } catch {
    return "—";
  }
}

async function loadPredictionComparison(symbolInput, { force = false } = {}) {
  if (!dom.predictionCompareBody) return;
  const symbol = (symbolInput || state.chartSymbol || "").trim().toUpperCase();
  const horizon = parseInt(dom.cryptoHorizon?.value || state.lastPrediction?.horizon || "15", 10);
  const title = state.lang === LANG.ES ? "Comparación post-horizonte" : "Post-horizon comparison";
  const titleScope = symbol
    ? `${title} • ${symbol}${Number.isFinite(horizon) && horizon > 0 ? ` • H=${horizon}m` : ""}`
    : title;
  if (dom.predictionCompareTitle) dom.predictionCompareTitle.textContent = titleScope;

  dom.predictionCompareBody.textContent = state.lang === LANG.ES ? "Cargando..." : "Loading...";

  // These endpoints must exist in your backend; if not, it will show a friendly message
  const predsUrl = new URL("/crypto/predictions", location.origin);
  predsUrl.searchParams.set("limit", "20");
  if (symbol) predsUrl.searchParams.set("symbol", symbol);
  if (Number.isFinite(horizon) && horizon > 0) predsUrl.searchParams.set("horizon_minutes", String(horizon));

  const outsUrl = new URL("/crypto/predictions/outcomes", location.origin);
  outsUrl.searchParams.set("limit", "40");
  if (symbol) outsUrl.searchParams.set("symbol", symbol);
  if (Number.isFinite(horizon) && horizon > 0) outsUrl.searchParams.set("horizon_minutes", String(horizon));

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
      .map((p, idx) => ({ p, o: outMap.get(p.id), idx }))
      .filter((x) => x.o);

    joined.sort((a, b) => (b.o?.ts || 0) - (a.o?.ts || 0));

    dom.predictionCompareBody.innerHTML = "";
    state.compareMarkers = [];
    state.compareHighlightId = null;

    if (!joined.length) {
      dom.predictionCompareBody.appendChild(el("div", { text: state.lang === LANG.ES ? "Aún no hay resultados." : "No results yet." }));
      renderChart(state.lastPoints);
      return;
    }

    const ES = state.lang === LANG.ES;
    const cards = [];

    const markers = [];
    const maxCards = 10;

    joined.slice(0, maxCards).forEach(({ p, o, idx }) => {
      const pairId = o.id || o.log_id || p.id || idx;
      const baseTs = p.ts || p.timestamp || p.created_at || Date.now();
      const actualTs = o.ts || (baseTs + (Number(p.horizon_minutes) || 0) * 60000);
      const baseLabel = formatTimeLabel(baseTs);
      const actualLabel = formatTimeLabel(actualTs);
      const delta = o.delta_pct;

      const isBuy = (p.decision || "").toUpperCase() === "BUY";
      const isSell = (p.decision || "").toUpperCase() === "SELL";
      const isHold = (p.decision || "").toUpperCase() === "HOLD";
      const threshold = 0.01; // 1%
      let status = "neutral";
      if (Number.isFinite(delta)) {
        if (isBuy && delta > 0) status = "success";
        else if (isSell && delta < 0) status = "success";
        else if (isHold && Math.abs(delta) < threshold) status = "success";
        else status = "fail";
      }

      const actualColor = status === "success" ? "#22c55e" : status === "fail" ? "#f87171" : "#94a3b8";
      const nearestLabel = (ts) => {
        if (!state.lastPoints?.length) return formatTimeLabel(ts);
        let nearestIdx = 0;
        let bestDiff = Number.POSITIVE_INFINITY;
        state.lastPoints.forEach((p, idx) => {
          const diff = Math.abs(Number(p.t) - Number(ts));
          if (diff < bestDiff) { bestDiff = diff; nearestIdx = idx; }
        });
        return formatTimeLabel(state.lastPoints[nearestIdx].t);
      };
      const baseX = nearestLabel(baseTs);
      const actualX = nearestLabel(actualTs);

      markers.push({ x: baseX, y: p.current_price, pairId, kind: "base", color: "#38bdf8", t: normalizeTimestampMs(baseTs) });
      markers.push({ x: actualX, y: o.actual_price, pairId, kind: "actual", color: actualColor, t: normalizeTimestampMs(actualTs) });

      const card = el("div", { class: "compare-row", "data-pair-id": pairId });
      const left = el("div", { class: "compare-metric" });
      const right = el("div", { class: "compare-metric" });

      left.appendChild(el("div", { class: "compare-label", text: ES ? "Señal" : "Signal" }));
      const decisionText = `${p.decision || "HOLD"} • p=${formatProb(p.probability_up)} • H=${p.horizon_minutes || "?"}m`;
      left.appendChild(el("div", { class: "compare-value", text: decisionText }));
      if (p.quantity || p.qty) {
        left.appendChild(el("div", { class: "compare-badge", text: `Qty ${p.quantity ?? p.qty}` }));
      }
      if (p.model || p.model_name) {
        left.appendChild(el("div", { class: "compare-badge", text: p.model || p.model_name }));
      }
      left.appendChild(el("div", { class: "compare-label", text: ES ? "Precio base" : "Base price" }));
      left.appendChild(el("div", { class: "compare-value", text: `${p.current_price ?? "—"} • ${baseLabel}` }));

      right.appendChild(el("div", { class: "compare-label", text: ES ? "Resultado" : "Outcome" }));
      right.appendChild(
        el("span", {
          class: `compare-pill ${status}`,
          text: `Δ ${formatPct(delta)}`,
        })
      );
      right.appendChild(el("div", { class: "compare-label", text: ES ? "Precio real" : "Actual price" }));
      right.appendChild(el("div", { class: "compare-value", text: `${o.actual_price ?? "—"} • ${actualLabel}` }));

      card.appendChild(left);
      card.appendChild(right);

      card.addEventListener("mouseenter", () => {
        card.classList.add("compare-highlight");
      });
      card.addEventListener("mouseleave", () => {
        card.classList.remove("compare-highlight");
      });
      card.addEventListener("click", () => {
        state.compareHighlightId = state.compareHighlightId === pairId ? null : pairId;
        renderChart(state.lastPoints);
      });

      cards.push(card);
      dom.predictionCompareBody.appendChild(card);
    });

    state.compareMarkers = markers;
    renderChart(state.lastPoints);
  } catch (err) {
    console.error(err);
    dom.predictionCompareBody.textContent = state.lang === LANG.ES ? "Error al cargar comparación." : "Error loading comparison.";
  }
}

function scheduleSnapshot(delay = 700) {
  if (!state.autoSnapshotEnabled) return;
  if (document.hidden) return;
  if (state.snapshotTimer) clearTimeout(state.snapshotTimer);
  state.snapshotTimer = setTimeout(() => {
    if (document.hidden) return;
    loadSnapshot({ renderInSources: false, source: "auto" });
  }, delay);
}

function disableAutoSnapshot() {
  // Snapshot is intentionally fixed ON in this UX contract.
  state.autoSnapshotEnabled = true;
  localStorage.setItem("aegis_auto_snapshot", "1");
  updateSnapshotToggleUI();
}

function enableAutoSnapshot() {
  state.autoSnapshotEnabled = true;
  localStorage.setItem("aegis_auto_snapshot", "1");
  updateSnapshotToggleUI();
}

function startReadyzPolling() {
  if (state.readyzTimer) return;
  const pollMs = 45000;

  const tick = async () => {
    if (document.hidden) return;
    if (state.readyzInFlight) return;
    if (!hasAuthForScope("main")) {
      state.lastReadyz = null;
      updateStatusCenter();
      updateModeIndicator();
      return;
    }
    state.readyzInFlight = true;
    try {
      const res = await fetchWithTimeout(
        endpoints.systemReadyz,
        { headers: { Accept: "application/json" } },
        { timeout: 7000, retries: 0 }
      );
      const data = await safeJson(res);
      if (res.ok && data && typeof data === "object") {
        state.lastReadyz = data;
        syncLlmProviderFromReadyz(data);
      } else if (res.status === 401 || res.status === 403) {
        state.lastReadyz = null;
      }
    } catch (err) {
      // ignore network errors; keep previous state
    } finally {
      state.readyzInFlight = false;
      updateStatusCenter();
      updateModeIndicator();
    }
  };

  setTimeout(tick, 800);
  state.readyzTimer = setInterval(tick, pollMs);
}

function updateSnapshotToggleUI() {
  const es = state.lang === LANG.ES;
  if (dom.globalSnapshotBtn) {
    dom.globalSnapshotBtn.classList.add("active");
    dom.globalSnapshotBtn.title = es
      ? "Snapshot automático activo (clic para refrescar vista)"
      : "Auto snapshot active (click to refresh view)";
  }
}

async function loadRecentPredictions() {
  const url = new URL("/crypto/predictions", location.origin);
  url.searchParams.set("limit", "30");
  try {
    const res = await fetchWithTimeout(url.toString(), {}, { timeout: 9000, retries: 0 });
    const data = await safeJson(res);
    if (!res.ok) throw new Error();
    renderPredictionsList(Array.isArray(data) ? data : data?.items || []);
    scheduleSnapshot();
  } catch {
    renderErrorInSources(state.lang === LANG.ES ? "No disponible." : "Unavailable.");
  }
}

function normalizeCryptoStatsEngine(engine) {
  const raw = String(engine || "").trim().toLowerCase();
  return raw === "trained" || raw === "demo" ? raw : "all";
}

function getCurrentCryptoScope() {
  const symbol = String(dom.chartSymbol?.value || state.chartSymbol || "BTCUSDT").trim().toUpperCase() || "BTCUSDT";
  const horizonRaw = parseInt(dom.cryptoHorizon?.value || state.lastPrediction?.horizon || "15", 10);
  const horizon = Number.isFinite(horizonRaw) && horizonRaw > 0 ? horizonRaw : 15;
  const regime = String(state.lastPrediction?.regime || "").trim().toLowerCase() || null;
  return { symbol, horizon, regime };
}

function buildCryptoStatsUrl({ exportMode = false, limit = 200, engine = state.cryptoStatsEngine } = {}) {
  const normalizedEngine = normalizeCryptoStatsEngine(engine);
  const url = new URL(exportMode ? endpoints.cryptoPredictionStatsExport : "/crypto/predictions/stats", location.origin);
  const scope = getCurrentCryptoScope();
  url.searchParams.set("limit", String(limit));
  if (scope.symbol) url.searchParams.set("symbol", scope.symbol);
  if (Number.isFinite(scope.horizon) && scope.horizon > 0) {
    url.searchParams.set("horizon_minutes", String(scope.horizon));
  }
  if (normalizedEngine !== "all") {
    url.searchParams.set("engine", normalizedEngine);
  }
  return url;
}

function buildCryptoThresholdsUrl({ limit = 1000, minTrades = 8 } = {}) {
  const scope = getCurrentCryptoScope();
  const url = new URL(endpoints.cryptoPredictionThresholds, location.origin);
  url.searchParams.set("limit", String(limit));
  url.searchParams.set("engine", "trained");
  url.searchParams.set("symbol", scope.symbol);
  url.searchParams.set("horizon_minutes", String(scope.horizon));
  url.searchParams.set("min_trades", String(minTrades));
  if (scope.regime) url.searchParams.set("regime", scope.regime);
  return url;
}

function buildCryptoCredibilityUrl() {
  const scope = getCurrentCryptoScope();
  const url = new URL(endpoints.cryptoPredictionCredibility, location.origin);
  url.searchParams.set("engine", "trained");
  url.searchParams.set("symbol", scope.symbol);
  url.searchParams.set("horizon_minutes", String(scope.horizon));
  if (scope.regime) url.searchParams.set("regime", scope.regime);
  return url;
}

function buildCryptoLeaderboardUrl({ limit = 2000, minTrades = 8, topN = 6 } = {}) {
  const url = new URL(endpoints.cryptoPredictionLeaderboard, location.origin);
  url.searchParams.set("limit", String(limit));
  url.searchParams.set("engine", "trained");
  url.searchParams.set("min_trades", String(minTrades));
  url.searchParams.set("top_n", String(topN));
  return url;
}

function getRegistryEntriesForCurrentScope() {
  const scope = getCurrentCryptoScope();
  const rows = Array.isArray(state.cryptoModelRegistry) ? state.cryptoModelRegistry : [];
  const exact = rows.filter((row) => String(row?.symbol || "").toUpperCase() === scope.symbol && Number(row?.horizon_minutes) === scope.horizon);
  if (exact.length) return exact;
  const sameSymbol = rows.filter((row) => String(row?.symbol || "").toUpperCase() === scope.symbol);
  return sameSymbol.length ? sameSymbol : rows.slice(0, 6);
}

async function exportCryptoStats(format = "json") {
  const es = state.lang === LANG.ES;
  const formatRaw = String(format || "json").trim().toLowerCase();
  const normalizedFormat = formatRaw === "csv" ? "csv" : formatRaw === "md" ? "md" : "json";
  const engine = normalizeCryptoStatsEngine(state.cryptoStatsEngine);
  const url = buildCryptoStatsUrl({ exportMode: true, limit: 200, engine });
  url.searchParams.set("format", normalizedFormat);
  try {
    const res = await fetchWithTimeout(
      url.toString(),
      {
        headers: {
          Accept: normalizedFormat === "csv" ? "text/csv" : normalizedFormat === "md" ? "text/markdown" : "application/json",
        },
      },
      { timeout: 9000, retries: 0 }
    );
    if (!res.ok) throw new Error("stats export failed");
    const blob = await res.blob();
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const symbol = (state.chartSymbol || "all").toUpperCase();
    link.href = objectUrl;
    link.download = `crypto_stats_${symbol}_${engine}.${normalizedFormat}`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(objectUrl);
  } catch (err) {
    console.error(err);
    appendBubble(
      es ? "No se pudo exportar el reporte cripto." : "Could not export the crypto report.",
      "bot"
    );
  }
}

async function loadStats() {
  const url = buildCryptoStatsUrl({ exportMode: false, limit: 200, engine: state.cryptoStatsEngine });
  const thresholdsUrl = buildCryptoThresholdsUrl({ limit: 1000, minTrades: 8 });
  const credibilityUrl = buildCryptoCredibilityUrl();
  const leaderboardUrl = buildCryptoLeaderboardUrl({ limit: 2000, minTrades: 8, topN: 6 });
  try {
    const [statsRes, thresholdRes, credibilityRes, leaderboardRes, registryRes] = await Promise.all([
      fetchWithTimeout(url.toString(), {}, { timeout: 9000, retries: 0 }),
      fetchWithTimeout(thresholdsUrl.toString(), {}, { timeout: 9000, retries: 0 }).catch(() => null),
      fetchWithTimeout(credibilityUrl.toString(), {}, { timeout: 9000, retries: 0 }).catch(() => null),
      fetchWithTimeout(leaderboardUrl.toString(), {}, { timeout: 9000, retries: 0 }).catch(() => null),
      fetchWithTimeout(endpoints.cryptoModelsRegistry, {}, { timeout: 9000, retries: 0 }).catch(() => null),
    ]);
    const data = await safeJson(statsRes);
    if (!statsRes.ok) throw new Error();
    const thresholdData = thresholdRes ? await safeJson(thresholdRes) : null;
    const credibilityData = credibilityRes ? await safeJson(credibilityRes) : null;
    const leaderboardData = leaderboardRes ? await safeJson(leaderboardRes) : null;
    const registryData = registryRes ? await safeJson(registryRes) : null;
    if (Array.isArray(registryData)) state.cryptoModelRegistry = registryData;
    state.cryptoThresholdRec = thresholdData?.recommendation || null;
    state.cryptoCredibility = credibilityData?.assessment || null;
    state.cryptoLeaderboard = Array.isArray(leaderboardData) ? leaderboardData : [];
    renderStatsPanel({
      ...(data || {}),
      threshold_scope: thresholdData?.scope || null,
      threshold_recommendation: thresholdData?.recommendation || null,
      credibility_scope: credibilityData?.scope || null,
      credibility_assessment: credibilityData?.assessment || null,
      scope_leaderboard: Array.isArray(leaderboardData) ? leaderboardData : [],
      model_registry: Array.isArray(registryData) ? registryData : state.cryptoModelRegistry,
    });
    scheduleSnapshot();
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
    renderPnlPanel({ pnl, trades });
    scheduleSnapshot();
  } catch {
    renderErrorInSources(state.lang === LANG.ES ? "No disponible." : "Unavailable.");
  }
}

async function loadSnapshot(options = {}) {
  const renderInSources = options.renderInSources !== false;
  const forceToast = options.forceToast === true;
  const source = String(options.source || "manual");
  const hasSourcesPane = !!dom.sourcesContent;
  if (renderInSources && !hasSourcesPane) return;
  if (state.snapshotInFlight) {
    state.snapshotQueued = true;
    return;
  }
  state.snapshotInFlight = true;
  const es = state.lang === LANG.ES;
  if (!hasAuthForScope("main")) {
    if (renderInSources && hasSourcesPane) {
      renderErrorInSources(es ? "Auth requerida para snapshot (🔑)." : "Auth required for snapshot (🔑).");
    }
    state.snapshotInFlight = false;
    return;
  }
  if (renderInSources && hasSourcesPane) {
    dom.sourcesContent.innerHTML = "";
    dom.sourcesContent.appendChild(el("div", { class: "sources-list-item", text: es ? "Cargando snapshot..." : "Loading snapshot..." }));
  }

  try {
    const [snapRes, healthRes, readyRes] = await Promise.all([
      fetchWithTimeout(endpoints.systemSnapshot, {}, { timeout: 9000, retries: 0 }),
      fetchWithTimeout(endpoints.healthz, {}, { timeout: 5000, retries: 0 }).catch(() => null),
      fetchWithTimeout(endpoints.systemReadyz, {}, { timeout: 7000, retries: 0 }).catch(() => null),
    ]);
    const data = await safeJson(snapRes);
    const health = healthRes ? await safeJson(healthRes) : null;
    const readyz = readyRes ? await safeJson(readyRes) : null;
    if (!snapRes.ok || !data) throw new Error("snapshot failed");
    state.lastSnapshot = { snapshot: data, health, readyz };
    renderProjectMeta();
    if (renderInSources && hasSourcesPane) {
      renderSnapshotPanel(data, health, readyz);
    }
    if (forceToast || source === "auto") {
      notifyStatus(
        es ? "Snapshot actualizado." : "Snapshot updated.",
        { kind: "success", key: "snapshot-updated", dedupeMs: 9000, ttlMs: 1800 }
      );
    }
  } catch (err) {
    console.error(err);
    if (renderInSources && hasSourcesPane) {
      renderErrorInSources(es ? "Snapshot no disponible." : "Snapshot unavailable.");
    }
    if (forceToast) {
      notifyStatus(
        es ? "Snapshot no disponible." : "Snapshot unavailable.",
        { kind: "warn", key: "snapshot-unavailable", dedupeMs: 5000, ttlMs: 2000 }
      );
    }
  } finally {
    state.snapshotInFlight = false;
    if (state.snapshotQueued) {
      state.snapshotQueued = false;
      setTimeout(() => loadSnapshot({ renderInSources, forceToast, source }), 0);
    }
  }
}

async function clearCryptoHistory() {
  const es = state.lang === LANG.ES;
  const warn = es
    ? "Esto borrará predicciones, resultados y trades simulados. ¿Continuar?"
    : "This will delete predictions, outcomes, and simulated trades. Continue?";
  if (!confirm(warn)) return;

  try {
    await Promise.all([
      fetchWithTimeout(endpoints.cryptoPredictionsClear, { method: "DELETE" }, { timeout: 8000, retries: 0 }),
      fetchWithTimeout(endpoints.cryptoTradesClear, { method: "DELETE" }, { timeout: 8000, retries: 0 }),
    ]);
    appendBubble(es ? "Historial cripto borrado." : "Crypto history cleared.", "bot");
    state.lastTradeQuote = null;
    loadRecentPredictions();
    loadStats();
    loadPnl();
    loadPredictionComparison(state.chartSymbol, { force: true });
    loadCryptoState({ force: true });
  } catch (err) {
    console.error(err);
    appendBubble(es ? "No se pudo borrar el historial." : "Could not clear history.", "bot");
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

function renderSnapshotPanel(data, health, readyz = null) {
  if (!dom.sourcesContent) return;
  const es = state.lang === LANG.ES;
  const snap = data && typeof data === "object" ? data : {};
  const roots = Array.isArray(data?.ingest_roots) ? data.ingest_roots : [];
  const jobs = Array.isArray(data?.jobs) ? data.jobs : [];
  const process = data?.process || readyz?.process || {};
  const emb = data?.embeddings || { status: "unknown" };
  const llm = data?.llm || { status: "unknown" };
  const web = data?.web_search || { status: "unknown" };
  const image = data?.image || { status: "unknown" };
  const clamav = data?.clamav || { status: "unknown" };
  const validation = data?.validation || readyz?.validation || {};
  const surfaces = data?.api_surfaces || readyz?.api_surfaces || {};
  const healthStatus = health?.status || health?.detail || null;
  const runtimeStatus = readyz?.status || data?.status || "unknown";
  const cryptoState = state.cryptoState || data?.crypto_state || readyz?.crypto_state || {};

  dom.sourcesContent.innerHTML = "";

  const title = el("div", { class: "sources-title-row" });
  title.appendChild(el("div", { text: es ? "Snapshot" : "Snapshot" }));
  title.appendChild(el("span", { class: `pill ${runtimeStatus === "ready" ? "success" : runtimeStatus === "fallback-only" ? "warn" : runtimeStatus === "degraded" ? "neutral" : "danger"}`, text: `${es ? "Runtime" : "Runtime"}: ${runtimeStatus}` }));
  dom.sourcesContent.appendChild(title);

  const capabilityItems = getRuntimeCapabilityItems();
  if (capabilityItems.length) {
    const capabilityCard = el("div", { class: "project-meta-card" });
    capabilityCard.appendChild(el("strong", { text: es ? "Estado de capacidades" : "Capabilities status" }));
    const list = el("div", { class: "mini-list" });
    capabilityItems.forEach((item) => {
      list.appendChild(el("span", { class: `mini-chip ${capabilityChipClass(item) || (!item.ok ? "warn" : "")}`, text: `${item.label}: ${item.value}` }));
    });
    capabilityCard.appendChild(list);
    dom.sourcesContent.appendChild(capabilityCard);
  }

  // API surfaces (helps explain legacy/experimental disconnections)
  if (surfaces && typeof surfaces === "object") {
    const rows = [];
    const add = (label, on) => rows.push({ label, on: !!on });
    add("chat", surfaces.chat_api);
    add("files", true);
    add("system", surfaces.system_api);
    add("auth", surfaces.auth_api);
    add("admin", surfaces.admin_api);
    add("crypto", surfaces.crypto_api);
    add("image", surfaces.image_api);
    add("tools(legacy)", surfaces.tools_api_legacy);
    add("meta", surfaces.meta_api);
    add("shutdown", surfaces.shutdown_endpoint);
    add("inprocess_e2e", surfaces.inprocess_e2e_gate);

    const surfCard = el("div", { class: "project-meta-card" });
    surfCard.appendChild(el("strong", { text: es ? "Superficies API" : "API surfaces" }));
    const list = el("div", { class: "mini-list" });
    rows.forEach((r) => {
      list.appendChild(
        el("span", {
          class: `mini-chip ${r.on ? "" : "warn"}`.trim(),
          text: `${r.label}: ${r.on ? "on" : "off"}`,
        })
      );
    });
    surfCard.appendChild(list);
    dom.sourcesContent.appendChild(surfCard);
  }

  const degraded = Array.isArray(readyz?.degraded_reasons)
    ? readyz.degraded_reasons
    : Array.isArray(snap?.degraded_reasons)
      ? snap.degraded_reasons
      : [];
  if (degraded.length) {
    const mapReason = (r) => {
      const v = String(r || "").trim();
      if (!v) return "";
      const labels = {
        "image:fallback-only": es ? "Imagen: usando fallback (backend caído)" : "Image: fallback-only (backend down)",
        "clamav:missing": es ? "ClamAV: no disponible" : "ClamAV: missing",
        "web:cooldown": es ? "Web: cooldown" : "Web: cooldown",
        "web:degraded": es ? "Web: degradado" : "Web: degraded",
        "web:error": es ? "Web: error" : "Web: error",
      };
      return labels[v] || v;
    };
    const card = el("div", { class: "project-meta-card" });
    card.appendChild(el("strong", { text: es ? "Degradado" : "Degraded" }));
    const ul = el("ul", { class: "mini-ul" });
    degraded.map(mapReason).filter(Boolean).slice(0, 8).forEach((txt) => {
      ul.appendChild(el("li", { text: txt }));
    });
    card.appendChild(ul);
    dom.sourcesContent.appendChild(card);
  }

  const wrap = el("div", { class: "kpi-grid" });

  // Roots
  const rootsCard = el("div", { class: "kpi-card" });
  rootsCard.appendChild(el("div", { class: "kpi-title", text: es ? "Uploads" : "Uploads" }));
  if (!roots.length) {
    rootsCard.appendChild(el("div", { class: "sources-empty", text: es ? "Sin proyectos." : "No projects." }));
  } else {
    roots.slice(0, 6).forEach((r) => {
      const row = el("div", { class: "kpi-item" });
      row.appendChild(el("strong", { text: r.name || r.path || "item" }));
      const meta = [];
      if (r.items) meta.push(`${r.items} items`);
      if (Number.isFinite(r.size)) meta.push(`${(r.size / 1024).toFixed(1)} KB`);
      if (r.modified) meta.push(formatAgo(r.modified));
      if (meta.length) row.appendChild(el("span", { class: "pill muted", text: meta.join(" • ") }));
      rootsCard.appendChild(row);
    });
  }
  wrap.appendChild(rootsCard);

  // Jobs
  const jobsCard = el("div", { class: "kpi-card" });
  jobsCard.appendChild(el("div", { class: "kpi-title", text: es ? "Jobs" : "Jobs" }));
  if (!jobs.length) {
    jobsCard.appendChild(el("div", { class: "sources-empty", text: es ? "Sin jobs." : "No jobs." }));
  } else {
    jobs.slice(0, 6).forEach((j) => {
      const row = el("div", { class: "kpi-row" });
      row.appendChild(el("span", { class: "pill neutral", text: j.kind || "job" }));
      row.appendChild(el("span", { class: `pill ${j.status || "neutral"}`, text: j.status || "?" }));
      if (j.created_at) row.appendChild(el("span", { class: "pill muted", text: formatAgo(j.created_at * 1000) }));
      jobsCard.appendChild(row);
    });
  }
  wrap.appendChild(jobsCard);

  // Embeddings
  const embCard = el("div", { class: "kpi-card" });
  embCard.appendChild(el("div", { class: "kpi-title", text: es ? "Embeddings" : "Embeddings" }));
  embCard.appendChild(el("div", { class: "kpi-item", text: `${emb.model || "n/a"} (${emb.dim || "?"}d)` }));
  embCard.appendChild(el("div", { class: "kpi-item", text: `${es ? "Estado" : "Status"}: ${emb.status || "?"} ${emb.loaded ? "✓" : ""}` }));
  wrap.appendChild(embCard);

  const llmCard = el("div", { class: "kpi-card" });
  llmCard.appendChild(el("div", { class: "kpi-title", text: "LLM" }));
  llmCard.appendChild(el("div", { class: "kpi-item", text: `${llm.model_path || "n/a"}` }));
  llmCard.appendChild(el("div", { class: "kpi-item", text: `${es ? "Estado" : "Status"}: ${llm.status || "?"} ${llm.loaded ? "✓" : ""}` }));
  wrap.appendChild(llmCard);

  const processCard = el("div", { class: "kpi-card" });
  processCard.appendChild(el("div", { class: "kpi-title", text: es ? "Proceso backend" : "Backend process" }));
  processCard.appendChild(el("div", { class: "kpi-item", text: `PID: ${process?.pid || "?"}` }));
  processCard.appendChild(el("div", { class: "kpi-item", text: `${es ? "Host" : "Host"}: ${process?.hostname || "?"}` }));
  if (Number.isFinite(Number(process?.uptime_s))) {
    const uptime = Number(process.uptime_s) || 0;
    processCard.appendChild(el("div", { class: "kpi-item", text: `${es ? "Uptime" : "Uptime"}: ${uptime.toFixed(1)}s` }));
  }
  wrap.appendChild(processCard);

  const cryptoCard = el("div", { class: "kpi-card" });
  const cryptoScope = cryptoState?.scope || {};
  const cryptoExecution = cryptoState?.execution || {};
  const cryptoSummary = cryptoState?.summary || {};
  cryptoCard.appendChild(el("div", { class: "kpi-title", text: es ? "Crypto state" : "Crypto state" }));
  cryptoCard.appendChild(el("div", {
    class: "kpi-item",
    text: `${es ? "Scope" : "Scope"}: ${cryptoScope.symbol || "—"} • ${Number.isFinite(Number(cryptoScope.horizon_minutes)) ? `${Number(cryptoScope.horizon_minutes)}m` : "—"}${cryptoScope.regime ? ` • ${cryptoScope.regime}` : ""}`,
  }));
  cryptoCard.appendChild(el("div", {
    class: "kpi-item",
    text: `${es ? "Mode" : "Mode"}: ${cryptoExecution.mode || "simulated"}${cryptoExecution.live_enabled ? " • live" : cryptoExecution.testnet_enabled ? " • testnet" : " • sim"}`,
  }));
  cryptoCard.appendChild(el("div", {
    class: "kpi-item",
    text: `${es ? "Pred/Out/Trades" : "Pred/Out/Trades"}: ${Number(cryptoSummary.predictions_count || 0)}/${Number(cryptoSummary.outcomes_count || 0)}/${Number(cryptoSummary.trades_count || 0)}`,
  }));
  if (cryptoState?.latest_prediction_ref?.log_id) {
    cryptoCard.appendChild(el("div", {
      class: "kpi-item",
      text: `${es ? "Última pred" : "Latest pred"}: ${formatCryptoPredictionRef(cryptoState.latest_prediction_ref, { es, includeSource: false })}`,
    }));
  }
  if (cryptoState?.latest_outcome_ref?.log_id) {
    cryptoCard.appendChild(el("div", {
      class: "kpi-item",
      text: `${es ? "Último outcome" : "Latest outcome"}: ${formatCryptoPredictionRef(cryptoState.latest_outcome_ref, { es, includeSource: false })}`,
    }));
    const outcomeMetrics = formatCryptoOutcomeRefMetrics(cryptoState.latest_outcome_ref, { es });
    if (outcomeMetrics) {
      cryptoCard.appendChild(el("div", {
        class: "kpi-hint",
        text: outcomeMetrics,
      }));
    }
  }
  if (Number.isFinite(Number(cryptoState?.current_price))) {
    cryptoCard.appendChild(el("div", {
      class: "kpi-item",
      text: `${es ? "Precio" : "Price"}: ${formatPrice(Number(cryptoState.current_price))}`,
    }));
  }
  const snapshotRisk = getCryptoRiskSummary();
  if (snapshotRisk.ready) {
    const gainLabel = Number.isFinite(snapshotRisk.gainQuote)
      ? `${snapshotRisk.gainQuote >= 0 ? "+" : ""}${formatPrice(snapshotRisk.gainQuote)}`
      : "—";
    const lossLabel = Number.isFinite(snapshotRisk.lossQuote)
      ? `-${formatPrice(Math.abs(snapshotRisk.lossQuote))}`
      : "—";
    cryptoCard.appendChild(el("div", {
      class: "kpi-item",
      text: `${es ? "Riesgo" : "Risk"}: ${snapshotRisk.signalLabel} • ${formatPct(snapshotRisk.projectedMovePct, 2)}${Number.isFinite(snapshotRisk.riskReward) ? ` • R:R ${snapshotRisk.riskReward.toFixed(2)}` : ""}`,
    }));
    cryptoCard.appendChild(el("div", {
      class: "kpi-hint",
      text: `${es ? "Entrada" : "Entry"} ${formatPrice(snapshotRisk.entry)} • ${es ? "Objetivo" : "Target"} ${formatPrice(snapshotRisk.target)}${Number.isFinite(snapshotRisk.stop) ? ` • ${es ? "Stop" : "Stop"} ${formatPrice(snapshotRisk.stop)}` : ""} • ${es ? "Ganancia" : "Gain"} ${gainLabel} / ${es ? "Pérdida" : "Loss"} ${lossLabel}`,
    }));
  }
  wrap.appendChild(cryptoCard);

  if (!SNAPSHOT_MINIMAL_VIEW) {
    // Resources + agent internals stay available in debug snapshot mode.
    const resources = snap?.resources || {};
    const agentProfile = snap?.agent_profile || {};
    const resCard = el("div", { class: "kpi-card" });
    resCard.appendChild(el("div", { class: "kpi-title", text: es ? "Recursos" : "Resources" }));
    const cpu = resources?.cpu || {};
    const mem = resources?.mem || {};
    const gpu = resources?.gpu || {};
    const llmCfg = resources?.llm_config || {};
    if (cpu?.count) resCard.appendChild(el("div", { class: "kpi-item", text: `CPU: ${cpu.count}` }));
    if (Number.isFinite(mem?.rss_mb)) resCard.appendChild(el("div", { class: "kpi-item", text: `RSS: ${mem.rss_mb} MB` }));
    if (Number.isFinite(mem?.available_mb) && Number.isFinite(mem?.total_mb)) {
      resCard.appendChild(el("div", { class: "kpi-item", text: `${es ? "RAM" : "RAM"}: ${mem.available_mb}/${mem.total_mb} MB` }));
    }
    if (gpu?.available) {
      resCard.appendChild(el("div", { class: "kpi-item", text: `GPU: ${gpu.device || "cuda"}` }));
      if (Number.isFinite(gpu?.allocated_mb) && Number.isFinite(gpu?.total_vram_mb)) {
        resCard.appendChild(el("div", { class: "kpi-item", text: `VRAM: ${gpu.allocated_mb}/${gpu.total_vram_mb} MB` }));
      }
    } else {
      resCard.appendChild(el("div", { class: "kpi-item", text: `GPU: ${es ? "no" : "no"}` }));
    }
    const llmLine = [
      llmCfg?.ctx ? `ctx=${llmCfg.ctx}` : "",
      llmCfg?.threads ? `thr=${llmCfg.threads}` : "",
      (llmCfg?.gpu_layers ?? null) !== null && llmCfg?.gpu_layers !== undefined ? `gpu_layers=${llmCfg.gpu_layers}` : "",
      llmCfg?.batch ? `batch=${llmCfg.batch}` : "",
    ].filter(Boolean).join(" ");
    if (llmLine) resCard.appendChild(el("div", { class: "kpi-item", text: `LLM: ${llmLine}` }));
    wrap.appendChild(resCard);

    const profCard = el("div", { class: "kpi-card" });
    profCard.appendChild(el("div", { class: "kpi-title", text: es ? "Perfil agente" : "Agent profile" }));
    if (agentProfile?.offline_mode !== undefined) {
      profCard.appendChild(el("div", { class: "kpi-item", text: `offline_mode: ${agentProfile.offline_mode ? "1" : "0"}` }));
    }
    const order = Array.isArray(agentProfile?.tool_routing_order) ? agentProfile.tool_routing_order : [];
    if (order.length) profCard.appendChild(el("div", { class: "kpi-item", text: `${es ? "Orden" : "Order"}: ${order.join(" → ")}` }));
    const budget = agentProfile?.prompt_budget || {};
    if (budget?.max_prompt_chars) profCard.appendChild(el("div", { class: "kpi-item", text: `max_prompt_chars: ${budget.max_prompt_chars}` }));
    if (budget?.max_response_chars) profCard.appendChild(el("div", { class: "kpi-item", text: `max_response_chars: ${budget.max_response_chars}` }));
    wrap.appendChild(profCard);
  }

  const webCard = el("div", { class: "kpi-card" });
  const webSummary = getWebProviderSummary(web, es);
  webCard.appendChild(el("div", { class: "kpi-title", text: es ? "Web search" : "Web search" }));
  webCard.appendChild(el("div", { class: "kpi-item", text: `${es ? "Estado" : "Status"}: ${web.status || "?"}` }));
  webCard.appendChild(el("div", { class: "kpi-item", text: `${es ? "Providers" : "Providers"}: ${web.provider_count ?? 0}` }));
  webCard.appendChild(el("div", { class: "kpi-item", text: `${es ? "Disponibles" : "Available"}: ${webSummary.available}` }));
  webCard.appendChild(el("div", { class: "kpi-item", text: `${es ? "Listos" : "Ready"}: ${webSummary.ready}` }));
  if (webSummary.cooling) {
    webCard.appendChild(el("div", { class: "kpi-item", text: `${es ? "Cooldown" : "Cooldown"}: ${webSummary.cooling}` }));
  }
  if (webSummary.reasons.length) {
    webCard.appendChild(el("div", { class: "kpi-item", text: `${es ? "No disponibles" : "Unavailable"}: ${webSummary.reasons.slice(0, 2).join(" | ")}` }));
  }
  if (web.probe_enabled) webCard.appendChild(el("div", { class: "kpi-item", text: `${es ? "Probe" : "Probe"}: ${web.probe_ok ? "ok" : "fail"}` }));
  wrap.appendChild(webCard);

  const imageCard = el("div", { class: "kpi-card" });
  imageCard.appendChild(el("div", { class: "kpi-title", text: es ? "Imagen" : "Image" }));
  imageCard.appendChild(el("div", { class: "kpi-item", text: `${es ? "Estado" : "Status"}: ${image.status || "?"}` }));
  imageCard.appendChild(el("div", { class: "kpi-item", text: `${es ? "Backend" : "Backend"}: ${image.backend_reachable ? "ok" : "down"}` }));
  if (image.fallback_only || image.recent_fallbacks) {
    imageCard.appendChild(el("div", { class: "kpi-item", text: `${es ? "Fallbacks" : "Fallbacks"}: ${image.recent_fallbacks ?? 0}` }));
  }
  wrap.appendChild(imageCard);

  const avCard = el("div", { class: "kpi-card" });
  avCard.appendChild(el("div", { class: "kpi-title", text: "ClamAV" }));
  avCard.appendChild(el("div", { class: "kpi-item", text: `${es ? "Estado" : "Status"}: ${clamav.status || "?"}` }));
  avCard.appendChild(el("div", { class: "kpi-item", text: `${es ? "Scanner" : "Scanner"}: ${clamav.scanner || "-"}` }));
  if (clamav.latest_event) {
    avCard.appendChild(el("div", { class: "kpi-item", text: `${es ? "Último scan" : "Last scan"}: ${clamav.latest_event.status || "-"}` }));
  }
  wrap.appendChild(avCard);

  // Health
  const healthCard = el("div", { class: "kpi-card" });
  healthCard.appendChild(el("div", { class: "kpi-title", text: es ? "Salud" : "Health" }));
  const healthText = healthStatus || (es ? "Desconocido" : "Unknown");
  const ok = (healthStatus || "").toLowerCase() === "ok";
  healthCard.appendChild(el("div", { class: `pill ${ok ? "success" : "neutral"}`, text: healthText }));
  wrap.appendChild(healthCard);

  const validationCard = el("div", { class: "kpi-card" });
  validationCard.appendChild(el("div", { class: "kpi-title", text: es ? "Validación" : "Validation" }));
  const startupGate = Array.isArray(validation.startup_gate) ? validation.startup_gate : [];
  const verifyFull = Array.isArray(validation.verify_full) ? validation.verify_full : [];
  validationCard.appendChild(
    el("div", {
      class: "kpi-item",
      text: `${es ? "Browser gate" : "Browser gate"}: ${validation.browser_smoke_strict_default ? "strict" : validation.browser_smoke_default ? "soft" : "off"}`,
    })
  );
  validationCard.appendChild(
    el("div", {
      class: "kpi-item",
      text: `${es ? "Contrato startup" : "Startup contract"}: ${validation.contract_mode_default || "full"}`,
    })
  );
  if (startupGate.length) {
    validationCard.appendChild(el("div", { class: "kpi-item", text: `${es ? "Startup" : "Startup"}: ${startupGate.join(" → ")}` }));
  }
  if (verifyFull.length) {
    validationCard.appendChild(el("div", { class: "kpi-item", text: `verify_full: ${verifyFull.join(" → ")}` }));
  }
  const startupRun = validation?.last_runs?.startup_gate || null;
  const verifyRun = validation?.last_runs?.verify_full || null;
  if (startupRun?.status) {
    validationCard.appendChild(el("div", { class: "kpi-item", text: `${es ? "Último startup" : "Last startup"}: ${startupRun.status}` }));
  }
  if (verifyRun?.status) {
    validationCard.appendChild(el("div", { class: "kpi-item", text: `verify_full: ${verifyRun.status}` }));
  }
  wrap.appendChild(validationCard);

  if (!SNAPSHOT_MINIMAL_VIEW) {
    const preds = Array.isArray(data?.predictions) ? data.predictions : [];
    const stats = data?.stats || {};
    const pnl = data?.pnl || {};

    const predsCard = el("div", { class: "kpi-card" });
    predsCard.appendChild(el("div", { class: "kpi-title", text: es ? "Predicciones" : "Predictions" }));
    if (!preds.length) {
      predsCard.appendChild(el("div", { class: "sources-empty", text: es ? "Sin predicciones." : "No predictions." }));
    } else {
      preds.slice(0, 5).forEach((p) => {
        const sideRaw = (p.decision || p.signal || "HOLD").toUpperCase();
        const row = el("div", { class: "kpi-row" });
        row.appendChild(el("span", { class: `pill ${sideRaw === "BUY" ? "buy" : sideRaw === "SELL" ? "sell" : "neutral"}`, text: sideRaw }));
        if (Number.isFinite(p.probability_up)) row.appendChild(el("span", { class: "pill muted", text: formatProb(p.probability_up) }));
        if (p.symbol) row.appendChild(el("span", { class: "pill neutral", text: p.symbol }));
        if (p.outcome && Number.isFinite(p.outcome.delta_pct)) {
          const delta = Number(p.outcome.delta_pct);
          row.appendChild(el("span", { class: `pill ${delta >= 0 ? "positive" : "negative"}`, text: `Δ ${formatPct(delta)}` }));
        }
        predsCard.appendChild(row);
      });
    }
    wrap.appendChild(predsCard);

    const statsCard = el("div", { class: "kpi-card" });
    statsCard.appendChild(el("div", { class: "kpi-title", text: es ? "Stats" : "Stats" }));
    statsCard.appendChild(el("div", { class: "kpi-item", text: `${es ? "Conteo" : "Count"}: ${stats.count ?? 0}` }));
    if (Number.isFinite(stats.accuracy)) statsCard.appendChild(el("div", { class: "kpi-item", text: `${es ? "Accuracy" : "Accuracy"}: ${formatPct(stats.accuracy, 1)}` }));
    if (Number.isFinite(stats.avg_delta_pct)) statsCard.appendChild(el("div", { class: "kpi-item", text: `${es ? "Δ prom" : "Avg Δ"}: ${formatPct(stats.avg_delta_pct, 2)}` }));
    wrap.appendChild(statsCard);

    const pnlCard = el("div", { class: "kpi-card" });
    pnlCard.appendChild(el("div", { class: "kpi-title", text: "P&L" }));
    const perSym = pnl?.per_symbol || {};
    const symbols = Object.keys(perSym);
    if (!symbols.length) {
      pnlCard.appendChild(el("div", { class: "sources-empty", text: es ? "Sin trades." : "No trades." }));
    } else {
      symbols.slice(0, 4).forEach((sym) => {
        const info = perSym[sym] || {};
        const line = el("div", { class: "kpi-row" });
        line.appendChild(el("span", { class: "pill neutral", text: sym }));
        if (Number.isFinite(info.unrealized)) line.appendChild(el("span", { class: info.unrealized >= 0 ? "pill positive" : "pill negative", text: `${info.unrealized.toFixed(4)}` }));
        if (Number.isFinite(info.position)) line.appendChild(el("span", { class: "pill muted", text: `${es ? "Pos" : "Pos"} ${info.position}` }));
        pnlCard.appendChild(line);
      });
    }
    wrap.appendChild(pnlCard);
  }

  dom.sourcesContent.appendChild(wrap);
}

function renderPredictionsList(items) {
  if (!dom.sourcesContent) return;
  const es = state.lang === LANG.ES;
  const list = Array.isArray(items) ? items : [];
  dom.sourcesContent.innerHTML = "";
  const title = el("div", { class: "sources-title-row" });
  title.appendChild(el("div", { text: es ? "Últimas predicciones" : "Recent predictions" }));
  title.appendChild(el("span", { class: "pill neutral", text: `${list.length}` }));
  dom.sourcesContent.appendChild(title);

  if (!list.length) {
    dom.sourcesContent.appendChild(el("div", { class: "sources-empty", text: es ? "Sin predicciones." : "No predictions." }));
    return;
  }

  const grid = el("div", { class: "kpi-grid" });
  list.slice(0, 15).forEach((p) => {
    const sideRaw = (p.decision || p.signal || p.action || "HOLD").toUpperCase();
    const sideCls = sideRaw === "BUY" ? "buy" : sideRaw === "SELL" ? "sell" : "neutral";
    const prob = Number(p.probability_up ?? p.p ?? p.probability);
    const probPct = Number.isFinite(prob) ? (prob > 1 ? prob : prob * 100) : null;
    const h = Number(p.horizon_minutes ?? p.horizon ?? p.h);
    const base = Number(p.current_price ?? p.base_price ?? p.price);
    const px = Number(p.predicted_price ?? p.target_price ?? p.px);
    const qty = Number(p.quantity ?? p.qty ?? state.chatTradeQty?.value);
    const out = p.outcome || {};
    const actual = Number(out.actual_price ?? out.price);
    const delta = Number(out.delta_pct ?? out.delta ?? out.d);
    const deltaPct = Number.isFinite(delta) ? delta : null;
    const hit = out.hit;
    const tsRaw = Number.isFinite(out.ts) ? out.ts : p.ts;
    const ts = Number.isFinite(tsRaw) ? new Date(tsRaw * 1000).toLocaleTimeString() : "";
    const sym = (p.symbol || state.chartSymbol || "BTCUSDT").toUpperCase();

    const card = el("div", { class: "kpi-card" });
    const header = el("div", { class: "kpi-card-head" });
    header.appendChild(el("div", { class: "kpi-title", text: sym }));
    if (ts) header.appendChild(el("span", { class: "pill neutral", text: ts }));
    card.appendChild(header);

    const row = el("div", { class: "kpi-row" });
    row.appendChild(el("span", { class: `pill ${sideCls}`, text: sideRaw || "HOLD" }));
    if (Number.isFinite(probPct)) row.appendChild(el("span", { class: "pill muted", text: `${probPct.toFixed(1)}% p` }));
    if (Number.isFinite(h)) row.appendChild(el("span", { class: "pill muted", text: `${h}m H` }));
    if (Number.isFinite(qty) && qty > 0) row.appendChild(el("span", { class: "pill neutral", text: `${es ? "Qty" : "Qty"} ${qty}` }));
    card.appendChild(row);

    const metrics = el("div", { class: "kpi-metrics" });
    if (Number.isFinite(base)) metrics.appendChild(el("div", { class: "kpi-item", text: `${es ? "Base" : "Base"} ${base}` }));
    if (Number.isFinite(px)) metrics.appendChild(el("div", { class: "kpi-item", text: `${es ? "Px" : "Px"} ${px}` }));
    if (Number.isFinite(actual)) metrics.appendChild(el("div", { class: "kpi-item", text: `${es ? "Actual" : "Actual"} ${actual}` }));
    card.appendChild(metrics);

    const status = el("div", { class: "kpi-row wrap" });
    const hasOutcome = p.outcome && (hit !== undefined || Number.isFinite(actual) || Number.isFinite(deltaPct));
    let statusText = es ? "Pendiente" : "Pending";
    let statusCls = "neutral";
    if (hit === true) {
      statusText = es ? "Acierto" : "Hit";
      statusCls = "success";
    } else if (hit === false) {
      statusText = es ? "Fallo" : "Miss";
      statusCls = "danger";
    } else if (hasOutcome) {
      statusText = es ? "Evaluando" : "Evaluating";
      statusCls = "neutral";
    }
    status.appendChild(el("span", { class: `pill ${statusCls}`, text: statusText }));

    if (Number.isFinite(deltaPct)) {
      const cls = deltaPct > 0 ? "pos" : deltaPct < 0 ? "neg" : "neutral";
      status.appendChild(el("span", { class: `pill ${cls}`, text: `Δ ${formatPct(deltaPct, 2)}` }));
    }

    if (status.childNodes.length) card.appendChild(status);

    // Pre/post notes
    let notePre = "";
    if (sideRaw === "BUY") notePre = es ? "BUY: el modelo ve más subida que bajada." : "BUY: the model sees more upside than downside.";
    else if (sideRaw === "SELL") notePre = es ? "SELL: el modelo ve más bajada que subida." : "SELL: the model sees more downside than upside.";
    else notePre = es ? "HOLD: p en zona neutra." : "HOLD: p in neutral band.";
    const notePost = hasOutcome
      ? (hit === true
        ? (es ? "Resultado: acierto." : "Outcome: hit.")
        : hit === false
          ? (es ? "Resultado: fallo." : "Outcome: miss.")
          : (es ? "Resultado pendiente." : "Outcome pending."))
      : (es ? "Esperando evaluación." : "Awaiting evaluation.");
    card.appendChild(el("div", { class: "kpi-hint", text: `${notePre} ${notePost}` }));

    grid.appendChild(card);
  });

  const foot = el("div", { class: "kpi-foot" });
  foot.textContent = es
    ? "Stats usa estas predicciones + outcomes; P&L simula trades con el mismo histórico. Limpia con 🗑 o cancela procesos con ⛔."
    : "Stats use these predictions + outcomes; P&L replays trades on the same history. Clear with 🗑 or cancel jobs with ⛔.";

  dom.sourcesContent.appendChild(grid);
  dom.sourcesContent.appendChild(foot);
}

function getCryptoSearchSymbols() {
  const fromMeta = Array.isArray(state.cryptoSymbolMeta?.popular_pairs)
    ? state.cryptoSymbolMeta.popular_pairs
    : [];
  const merged = [...fromMeta, ...CRYPTO_SEARCH_SYMBOLS]
    .map((s) => String(s || "").trim().toUpperCase())
    .filter((s) => /^[A-Z0-9]{2,20}$/.test(s));
  return [...new Set(merged)];
}

function loadSymbolsList(filter = "") {
  const cleanFilter = String(filter || "").trim().toUpperCase();
  const allSymbols = getCryptoSearchSymbols();
  const symbols = cleanFilter
    ? allSymbols.filter((sym) => sym.includes(cleanFilter))
    : allSymbols.slice();

  const symbolsDataList = document.getElementById("cryptoSymbolsList");
  if (symbolsDataList) {
    symbolsDataList.innerHTML = "";
    symbols.forEach((sym) => {
      const opt = document.createElement("option");
      opt.value = sym;
      symbolsDataList.appendChild(opt);
    });
  }

  if (!dom.symbolsList) return;
  const grouped = symbols.reduce((rows, sym, idx) => {
    const row = Math.floor(idx / 6);
    rows[row] = rows[row] || [];
    rows[row].push(sym);
    return rows;
  }, []);
  dom.symbolsList.textContent = grouped.length
    ? grouped.map((r) => r.join(", ")).join("\n")
    : (state.lang === LANG.ES ? "Sin resultados." : "No matches.");

  const quotes = Array.isArray(state.cryptoSymbolMeta?.allowed_quote_assets)
    ? state.cryptoSymbolMeta.allowed_quote_assets
    : ["USDT", "USDC", "BUSD", "FDUSD", "TUSD", "BTC", "ETH"];
  const aliases = state.cryptoSymbolMeta?.alias_examples && typeof state.cryptoSymbolMeta.alias_examples === "object"
    ? Object.entries(state.cryptoSymbolMeta.alias_examples)
    : [];
  const aliasPreview = aliases.slice(0, 8).map(([k, v]) => `${String(k).toUpperCase()}→${String(v).toUpperCase()}`).join(", ");
  if (dom.symbolsQuotes) {
    dom.symbolsQuotes.textContent = state.lang === LANG.ES
      ? `Cotizaciones permitidas (quote assets Binance): ${quotes.join(", ")}. Alias soportados: ${aliasPreview || "BTC→BTCUSDT, ETH→ETHUSDT, SOL→SOLUSDT"}.`
      : `Allowed Binance quote assets: ${quotes.join(", ")}. Supported aliases: ${aliasPreview || "BTC→BTCUSDT, ETH→ETHUSDT, SOL→SOLUSDT"}.`;
  }
}

async function loadCryptoSymbolsMeta(force = false) {
  if (!force && state.cryptoSymbolMeta) return state.cryptoSymbolMeta;
  try {
    const res = await fetchWithTimeout(endpoints.cryptoSymbolsMeta, { headers: { Accept: "application/json" } }, { timeout: 8000, retries: 0 });
    const data = await safeJson(res);
    if (res.ok && data && typeof data === "object") {
      state.cryptoSymbolMeta = data;
      return data;
    }
  } catch {}
  return null;
}

function renderStatsPanel(data) {
  if (!dom.sourcesContent) return;
  const es = state.lang === LANG.ES;
  const scope = getCurrentCryptoScope();
  const engineFilter = normalizeCryptoStatsEngine(data.engine_filter || state.cryptoStatsEngine || "all");
  state.cryptoStatsEngine = engineFilter;
  localStorage.setItem("aegis_crypto_stats_engine", engineFilter);
  dom.sourcesContent.innerHTML = "";
  const title = el("div", { class: "sources-title-row" });
  title.appendChild(el("div", { text: es ? "Stats" : "Stats" }));
  const titleActions = el("div", { class: "sources-title-actions" });
  [
    { key: "all", label: es ? "Todo" : "All" },
    { key: "trained", label: es ? "Trained" : "Trained" },
    { key: "demo", label: es ? "Demo" : "Demo" },
  ].forEach((item) => {
    const btn = el("button", {
      class: `mini-chip ${engineFilter === item.key ? "active" : ""}`.trim(),
      text: item.label,
      attrs: { type: "button" },
    });
    btn.addEventListener("click", () => {
      const next = normalizeCryptoStatsEngine(item.key);
      if (state.cryptoStatsEngine === next) return;
      state.cryptoStatsEngine = next;
      localStorage.setItem("aegis_crypto_stats_engine", next);
      loadStats();
    });
    titleActions.appendChild(btn);
  });
  const exportJsonBtn = el("button", {
    class: "icon-btn small",
    text: "JSON",
    attrs: { type: "button", title: es ? "Exportar JSON" : "Export JSON" },
  });
  exportJsonBtn.addEventListener("click", () => exportCryptoStats("json"));
  titleActions.appendChild(exportJsonBtn);
  const exportCsvBtn = el("button", {
    class: "icon-btn small",
    text: "CSV",
    attrs: { type: "button", title: es ? "Exportar CSV" : "Export CSV" },
  });
  exportCsvBtn.addEventListener("click", () => exportCryptoStats("csv"));
  titleActions.appendChild(exportCsvBtn);
  const exportMdBtn = el("button", {
    class: "icon-btn small",
    text: "MD",
    attrs: { type: "button", title: es ? "Exportar reporte Markdown" : "Export Markdown report" },
  });
  exportMdBtn.addEventListener("click", () => exportCryptoStats("md"));
  titleActions.appendChild(exportMdBtn);
  title.appendChild(titleActions);
  dom.sourcesContent.appendChild(title);

  const scopeRow = el("div", { class: "kpi-row wrap crypto-scope-row" });
  scopeRow.appendChild(el("span", { class: "pill neutral", text: `${es ? "Símbolo" : "Symbol"}: ${scope.symbol}` }));
  scopeRow.appendChild(el("span", { class: "pill neutral", text: `${es ? "Horizonte" : "Horizon"}: ${scope.horizon}m` }));
  scopeRow.appendChild(el("span", { class: `pill ${engineFilter === "trained" ? "success" : engineFilter === "demo" ? "warn" : "neutral"}`, text: `${es ? "Engine" : "Engine"}: ${engineFilter}` }));
  if (scope.regime) {
    scopeRow.appendChild(el("span", { class: "pill muted", text: `${es ? "Régimen" : "Regime"}: ${scope.regime}` }));
  }
  dom.sourcesContent.appendChild(scopeRow);

  const acc = Number(data.accuracy ?? data.acc);
  const avg = Number(data.avg_delta_pct ?? data.avg_delta ?? data.avg ?? data.avg_move);
  const wins = Number(data.win_rate ?? data.wins);
  const count = Number(data.count ?? data.samples);
  const accNews = Number(data.with_news_accuracy ?? NaN);
  const accNoNews = Number(data.without_news_accuracy ?? NaN);
  const trained = data?.per_engine?.trained || {};
  const demo = data?.per_engine?.demo || {};
  const trainedAcc = Number(data.trained_accuracy ?? trained.accuracy);
  const demoAcc = Number(data.demo_accuracy ?? demo.accuracy);
  const trainedCount = Number(data.trained_count ?? trained.count);
  const demoCount = Number(data.demo_count ?? demo.count);
  const trainedDelta = Number(trained.avg_delta_pct);
  const demoDelta = Number(demo.avg_delta_pct);
  const netExp = Number(data.net_expectancy_pct);
  const grossExp = Number(data.gross_expectancy_pct);
  const positiveNet = Number(data.positive_net_rate);
  const maxDrawdown = Number(data.max_drawdown_pct);
  const avgProbError = Number(data.avg_probability_error);
  const brierScore = Number(data.brier_score);
  const tradeCount = Number(data.trade_count);
  const holdCount = Number(data.hold_count);
  const roundTripCostBps = Number(data.round_trip_cost_bps);
  const oosStartTs = Number(data.oos_window_start_ts);
  const oosEndTs = Number(data.oos_window_end_ts);
  const oosHours = Number(data.oos_window_hours);
  const thresholdRec = data?.threshold_recommendation && typeof data.threshold_recommendation === "object"
    ? data.threshold_recommendation
    : state.cryptoThresholdRec || null;
  const credibilityAssessment = data?.credibility_assessment && typeof data.credibility_assessment === "object"
    ? data.credibility_assessment
    : state.cryptoCredibility || null;
  const operatorGuidance = data?.operator_guidance && typeof data.operator_guidance === "object"
    ? data.operator_guidance
    : null;
  const credibilityScope = data?.credibility_scope && typeof data.credibility_scope === "object"
    ? data.credibility_scope
    : null;
  const thresholdScope = data?.threshold_scope && typeof data.threshold_scope === "object"
    ? data.threshold_scope
    : null;
  const leaderboardRows = Array.isArray(data?.scope_leaderboard) ? data.scope_leaderboard : (Array.isArray(state.cryptoLeaderboard) ? state.cryptoLeaderboard : []);
  const registryRows = Array.isArray(data?.model_registry) ? data.model_registry : (Array.isArray(state.cryptoModelRegistry) ? state.cryptoModelRegistry : []);
  const currentRegistryRows = getRegistryEntriesForCurrentScope();
  const perModel = data?.per_model && typeof data.per_model === "object" ? data.per_model : {};
  const perConfidence = data?.per_confidence_bucket && typeof data.per_confidence_bucket === "object"
    ? data.per_confidence_bucket
    : {};
  const modelRows = Object.entries(perModel)
    .map(([name, stats]) => ({
      name,
      count: Number(stats?.count),
      accuracy: Number(stats?.accuracy),
    }))
    .sort((a, b) => (b.count || 0) - (a.count || 0) || (b.accuracy || 0) - (a.accuracy || 0))
    .slice(0, 6);
  const confidenceRows = Object.entries(perConfidence)
    .map(([name, stats]) => ({
      name,
      count: Number(stats?.count),
      accuracy: Number(stats?.accuracy),
      avgProbabilityError: Number(stats?.avg_probability_error),
      brierScore: Number(stats?.brier_score),
    }))
    .sort((a, b) => {
      const rank = { high: 0, medium: 1, low: 2 };
      return (rank[a.name] ?? 99) - (rank[b.name] ?? 99) || a.name.localeCompare(b.name);
    });

  const grid = el("div", { class: "kpi-grid" });
  const formatWindowTs = (ts) => (Number.isFinite(ts) && ts > 0 ? new Date(ts * 1000).toLocaleString() : "—");
  const formatGuidanceCode = (value) => String(value || "unknown").replace(/_/g, " ");
  const makeKpi = (label, value, hint, cls = "", badgeText = "", badgeClass = "") => {
    const card = el("div", { class: `kpi-card ${cls}` });
    const head = el("div", { class: "kpi-card-head" });
    head.appendChild(el("div", { class: "kpi-title", text: label }));
    if (badgeText) {
      head.appendChild(el("span", { class: badgeClass || "pill neutral", text: badgeText }));
    }
    card.appendChild(head);
    card.appendChild(el("div", { class: "kpi-value", text: value }));
    if (hint) card.appendChild(el("div", { class: "kpi-hint", text: hint }));
    return card;
  };

  if (Number.isFinite(acc)) grid.appendChild(makeKpi(es ? "Precisión" : "Accuracy", `${(acc * 100).toFixed(1)}%`, es ? "Aciertos/total" : "Hits/total"));
  if (Number.isFinite(wins)) grid.appendChild(makeKpi(es ? "Win rate" : "Win rate", `${(wins * 100).toFixed(1)}%`, es ? "Trades con Δ>0 para BUY / Δ<0 para SELL" : "BUY Δ>0, SELL Δ<0"));
  if (Number.isFinite(avg)) grid.appendChild(makeKpi("Δ avg", formatPct(avg, 2), es ? "Movimiento promedio bruto" : "Average gross move"));
  if (Number.isFinite(count)) grid.appendChild(makeKpi(es ? "Muestras" : "Samples", String(count), es ? "Predicciones evaluadas" : "Evaluated predictions"));
  if (Number.isFinite(accNews)) grid.appendChild(makeKpi(es ? "Precisión con news" : "Accuracy w/news", `${(accNews * 100).toFixed(1)}%`, es ? "Predicciones con ajuste de noticias" : "Predictions with news adjustment"));
  if (Number.isFinite(accNoNews)) grid.appendChild(makeKpi(es ? "Precisión sin news" : "Accuracy no news", `${(accNoNews * 100).toFixed(1)}%`, es ? "Predicciones sin noticias" : "Predictions without news"));
  if (Number.isFinite(netExp)) {
    grid.appendChild(
      makeKpi(
        es ? "Expectativa neta" : "Net expectancy",
        formatPct(netExp, 2),
        es
          ? `Después de ${Number.isFinite(roundTripCostBps) ? roundTripCostBps.toFixed(1) : "—"} bps round-trip`
          : `After ${Number.isFinite(roundTripCostBps) ? roundTripCostBps.toFixed(1) : "—"} bps round-trip`
      )
    );
  }
  if (Number.isFinite(grossExp)) {
    grid.appendChild(makeKpi(es ? "Expectativa bruta" : "Gross expectancy", formatPct(grossExp, 2), es ? "Sin costos" : "Before costs"));
  }
  if (Number.isFinite(positiveNet)) {
    grid.appendChild(
      makeKpi(
        es ? "Net positive rate" : "Net positive rate",
        formatPct(positiveNet, 1),
        es ? "Trades netos > 0 después de costos" : "Trades with net return > 0 after costs"
      )
    );
  }
  if (Number.isFinite(maxDrawdown)) {
    grid.appendChild(
      makeKpi(
        es ? "Max drawdown" : "Max drawdown",
        formatPct(maxDrawdown, 2),
        es ? "Sobre retornos netos acumulados" : "On cumulative net returns"
      )
    );
  }
  if (Number.isFinite(avgProbError)) {
    grid.appendChild(
      makeKpi(
        es ? "Error prob. prom" : "Avg prob error",
        formatPct(avgProbError, 2),
        es ? "Distancia media entre p y resultado real" : "Average distance between p and realized outcome"
      )
    );
  }
  if (Number.isFinite(brierScore)) {
    grid.appendChild(
      makeKpi(
        "Brier",
        brierScore.toFixed(4),
        es ? "Menor es mejor" : "Lower is better"
      )
    );
  }
  if (Number.isFinite(tradeCount) || Number.isFinite(holdCount)) {
    grid.appendChild(
      makeKpi(
        es ? "Trade/Hold" : "Trade/Hold",
        `${Number.isFinite(tradeCount) ? tradeCount : 0}/${Number.isFinite(holdCount) ? holdCount : 0}`,
        es ? "Trades ejecutables vs HOLD" : "Actionable trades vs HOLD"
      )
    );
  }

  if (trainedCount > 0) {
    grid.appendChild(
      makeKpi(
        es ? "Engine trained" : "Trained engine",
        Number.isFinite(trainedAcc) ? `${(trainedAcc * 100).toFixed(1)}%` : "—",
        `${es ? "Muestras" : "Samples"}: ${trainedCount || 0}${Number.isFinite(trainedDelta) ? ` • Δ ${formatPct(trainedDelta, 2)}` : ""}`,
        "engine-trained",
        "trained",
        "pill pill-live"
      )
    );
  }
  if (demoCount > 0) {
    grid.appendChild(
      makeKpi(
        es ? "Engine demo" : "Demo engine",
        Number.isFinite(demoAcc) ? `${(demoAcc * 100).toFixed(1)}%` : "—",
        `${es ? "Muestras" : "Samples"}: ${demoCount || 0}${Number.isFinite(demoDelta) ? ` • Δ ${formatPct(demoDelta, 2)}` : ""}`,
        "engine-demo",
        "demo",
        "pill pill-demo"
      )
    );
  }

  if (!grid.childNodes.length && !modelRows.length && !confidenceRows.length) {
    dom.sourcesContent.appendChild(el("div", { class: "sources-empty", text: es ? "Sin datos de stats." : "No stats data." }));
  } else {
    dom.sourcesContent.appendChild(grid);
    if (Number.isFinite(oosStartTs) || Number.isFinite(oosEndTs)) {
      const windowCard = el("div", { class: "kpi-card engine-mixed" });
      windowCard.appendChild(el("div", { class: "kpi-title", text: es ? "Ventana OOS medida" : "Measured OOS window" }));
      windowCard.appendChild(
        el("div", {
          class: "kpi-hint",
          text: es
            ? "Resultados observados después de que cada predicción venció en runtime."
            : "Observed results after each prediction reached its runtime horizon.",
        })
      );
      const line1 = el("div", { class: "kpi-row wrap" });
      line1.appendChild(el("span", { class: "pill neutral", text: `${es ? "Inicio" : "Start"}: ${formatWindowTs(oosStartTs)}` }));
      line1.appendChild(el("span", { class: "pill neutral", text: `${es ? "Fin" : "End"}: ${formatWindowTs(oosEndTs)}` }));
      if (Number.isFinite(oosHours)) {
        line1.appendChild(el("span", { class: "pill muted", text: `${es ? "Duración" : "Duration"}: ${oosHours.toFixed(1)}h` }));
      }
      windowCard.appendChild(line1);
      dom.sourcesContent.appendChild(windowCard);
    }
    if (modelRows.length) {
      const modelCard = el("div", { class: "kpi-card engine-mixed" });
      modelCard.appendChild(el("div", { class: "kpi-title", text: es ? "Breakdown por modelo" : "Model breakdown" }));
      modelRows.forEach((row) => {
        const line = el("div", { class: "kpi-row" });
        line.appendChild(el("span", { class: "pill neutral", text: row.name }));
        line.appendChild(el("span", { class: "pill muted", text: `${es ? "muestras" : "samples"} ${Number.isFinite(row.count) ? row.count : 0}` }));
        if (Number.isFinite(row.accuracy)) {
          line.appendChild(el("span", { class: "pill success", text: `${(row.accuracy * 100).toFixed(1)}%` }));
        }
        modelCard.appendChild(line);
      });
      dom.sourcesContent.appendChild(modelCard);
    }
    if (confidenceRows.length) {
      const confidenceCard = el("div", { class: "kpi-card engine-mixed" });
      confidenceCard.appendChild(el("div", { class: "kpi-title", text: es ? "Calibración por confianza" : "Confidence calibration" }));
      confidenceRows.forEach((row) => {
        const line = el("div", { class: "kpi-row wrap" });
        line.appendChild(el("span", { class: "pill neutral", text: row.name }));
        line.appendChild(el("span", { class: "pill muted", text: `${es ? "muestras" : "samples"} ${Number.isFinite(row.count) ? row.count : 0}` }));
        if (Number.isFinite(row.accuracy)) {
          line.appendChild(el("span", { class: "pill success", text: `${es ? "acc" : "acc"} ${formatPct(row.accuracy, 1)}` }));
        }
        if (Number.isFinite(row.avgProbabilityError)) {
          line.appendChild(el("span", { class: "pill muted", text: `${es ? "err" : "err"} ${formatPct(row.avgProbabilityError, 2)}` }));
        }
        if (Number.isFinite(row.brierScore)) {
          line.appendChild(el("span", { class: "pill neutral", text: `brier ${row.brierScore.toFixed(4)}` }));
        }
        confidenceCard.appendChild(line);
      });
      dom.sourcesContent.appendChild(confidenceCard);
    }
    const insightGrid = el("div", { class: "kpi-grid crypto-insight-grid" });
    const guidanceCard = el("div", { class: "kpi-card crypto-threshold-card" });
    guidanceCard.appendChild(el("div", { class: "kpi-title", text: es ? "Guía operativa" : "Operating guidance" }));
    if (operatorGuidance) {
      const status = String(operatorGuidance.status || "unknown");
      const action = String(operatorGuidance.action || "unknown");
      const reasons = Array.isArray(operatorGuidance.reasons) ? operatorGuidance.reasons : [];
      const probabilitySamples = Number(operatorGuidance.probability_count);
      const highConfidenceSamples = Number(operatorGuidance.high_confidence_count);
      const focusBucket = String(operatorGuidance.focus_bucket || "");
      const weakestBucket = operatorGuidance?.weakest_bucket && typeof operatorGuidance.weakest_bucket === "object"
        ? operatorGuidance.weakest_bucket
        : null;
      const statusClass = status === "trust" ? "success" : status === "abstain" ? "negative" : status === "downgrade" ? "warn" : "muted";
      const actionClass = action === "keep_trained_scope" ? "positive" : action === "hold_out_until_recalibrated" ? "negative" : "neutral";
      guidanceCard.appendChild(el("div", {
        class: "kpi-value",
        text: formatGuidanceCode(status).toUpperCase(),
      }));
      guidanceCard.appendChild(el("div", {
        class: "kpi-hint",
        text: `${es ? "Acción" : "Action"}: ${formatGuidanceCode(action)}`,
      }));
      const chips = el("div", { class: "kpi-row wrap" });
      chips.appendChild(el("span", { class: `pill ${statusClass}`, text: `${es ? "Estado" : "Status"}: ${formatGuidanceCode(status)}` }));
      chips.appendChild(el("span", { class: `pill ${actionClass}`, text: `${es ? "Ruta" : "Route"}: ${formatGuidanceCode(action)}` }));
      if (Number.isFinite(probabilitySamples)) chips.appendChild(el("span", { class: "pill neutral", text: `${es ? "Muestras p" : "p samples"}: ${probabilitySamples}` }));
      if (Number.isFinite(highConfidenceSamples)) chips.appendChild(el("span", { class: "pill neutral", text: `${es ? "High conf" : "High conf"}: ${highConfidenceSamples}` }));
      if (focusBucket) chips.appendChild(el("span", { class: "pill muted", text: `${es ? "Bucket foco" : "Focus bucket"}: ${focusBucket}` }));
      guidanceCard.appendChild(chips);
      if (reasons.length) {
        guidanceCard.appendChild(el("div", {
          class: "kpi-hint",
          text: `${es ? "Razones" : "Reasons"}: ${reasons.map((reason) => formatGuidanceCode(reason)).join(" • ")}`,
        }));
      }
      if (weakestBucket && (Number.isFinite(Number(weakestBucket.avg_probability_error)) || Number.isFinite(Number(weakestBucket.brier_score)))) {
        guidanceCard.appendChild(el("div", {
          class: "kpi-hint",
          text: `${es ? "Bucket débil" : "Weak bucket"}: ${weakestBucket.name || focusBucket || "—"} • ${es ? "err" : "err"} ${Number.isFinite(Number(weakestBucket.avg_probability_error)) ? formatPct(Number(weakestBucket.avg_probability_error), 2) : "—"} • brier ${Number.isFinite(Number(weakestBucket.brier_score)) ? Number(weakestBucket.brier_score).toFixed(4) : "—"}`,
        }));
      }
    } else {
      guidanceCard.appendChild(el("div", { class: "sources-empty", text: es ? "Sin guía operativa todavía." : "No operating guidance yet." }));
    }
    insightGrid.appendChild(guidanceCard);

    const thresholdCard = el("div", { class: "kpi-card crypto-threshold-card" });
    thresholdCard.appendChild(el("div", { class: "kpi-title", text: es ? "Threshold recomendado" : "Recommended threshold" }));
    if (thresholdRec) {
      const buyThreshold = Number(thresholdRec.buy_threshold);
      const sellThreshold = Number(thresholdRec.sell_threshold);
      const precision = Number(thresholdRec.precision);
      const positiveRate = Number(thresholdRec.positive_net_rate);
      const holdRate = Number(thresholdRec.hold_rate);
      thresholdCard.appendChild(
        el("div", {
          class: "kpi-value",
          text: `${Number.isFinite(buyThreshold) ? formatProb(buyThreshold) : "—"} / ${Number.isFinite(sellThreshold) ? formatProb(sellThreshold) : "—"}`,
        })
      );
      thresholdCard.appendChild(
        el("div", {
          class: "kpi-hint",
          text: thresholdScope?.regime
            ? `${es ? "Scope" : "Scope"}: ${thresholdScope.symbol || scope.symbol} • ${thresholdScope.horizon_minutes || scope.horizon}m • ${thresholdScope.regime}`
            : `${es ? "Scope" : "Scope"}: ${thresholdScope?.symbol || scope.symbol} • ${thresholdScope?.horizon_minutes || scope.horizon}m`,
        })
      );
      const chips = el("div", { class: "kpi-row wrap" });
      chips.appendChild(el("span", { class: "pill success", text: `${es ? "Precisión" : "Precision"}: ${Number.isFinite(precision) ? formatPct(precision, 1) : "—"}` }));
      chips.appendChild(el("span", { class: "pill neutral", text: `${es ? "Trades" : "Trades"}: ${Number.isFinite(Number(thresholdRec.trade_count)) ? Number(thresholdRec.trade_count) : 0}` }));
      if (Number.isFinite(positiveRate)) chips.appendChild(el("span", { class: "pill positive", text: `${es ? "Net +" : "Net +"}: ${formatPct(positiveRate, 1)}` }));
      if (Number.isFinite(holdRate)) chips.appendChild(el("span", { class: "pill muted", text: `${es ? "Hold rate" : "Hold rate"}: ${formatPct(holdRate, 1)}` }));
      thresholdCard.appendChild(chips);
      if (Number.isFinite(Number(thresholdRec.net_expectancy_pct))) {
        thresholdCard.appendChild(el("div", { class: "kpi-hint", text: `${es ? "Expectativa neta" : "Net expectancy"}: ${formatPct(Number(thresholdRec.net_expectancy_pct), 2)}` }));
      }
    } else {
      thresholdCard.appendChild(el("div", { class: "sources-empty", text: es ? "Aún no hay suficiente historial trained para recomendar thresholds." : "Not enough trained history yet to recommend thresholds." }));
    }
    insightGrid.appendChild(thresholdCard);

    const riskView = getCryptoRiskSummary();
    const riskCard = el("div", { class: "kpi-card crypto-risk-card" });
    riskCard.appendChild(el("div", { class: "kpi-title", text: es ? "Riesgo / PnL" : "Risk / PnL" }));
  if (riskView.ready) {
      const directionText = riskView.tradeable
        ? riskView.decision
        : (es ? "OBSERVAR" : "WATCH");
      const primaryPct = riskView.tradeable
        ? riskView.netEdgePct
        : riskView.projectedMovePct;
      const primaryLabel = riskView.tradeable
        ? (es ? "Edge neto" : "Net edge")
        : (es ? "Movimiento" : "Move");
      riskCard.appendChild(el("div", {
        class: "kpi-value",
        text: `${directionText} • ${Number.isFinite(primaryPct) ? formatPct(primaryPct, 2) : "—"}`,
      }));
      const chips = el("div", { class: "kpi-row wrap" });
      chips.appendChild(el("span", { class: "pill neutral", text: `${es ? "Entrada" : "Entry"} ${formatPrice(riskView.entry)}` }));
      if (Number.isFinite(riskView.target)) {
        chips.appendChild(el("span", {
          class: `pill ${riskView.decision === "SELL" ? "sell" : riskView.decision === "BUY" ? "buy" : "neutral"}`,
          text: `${es ? "Objetivo" : "Target"} ${formatPrice(riskView.target)}`,
        }));
      }
      if (Number.isFinite(riskView.stop)) {
        chips.appendChild(el("span", { class: "pill danger", text: `${es ? "Stop" : "Stop"} ${formatPrice(riskView.stop)}` }));
      }
      if (Number.isFinite(riskView.executionDragPct)) {
        chips.appendChild(el("span", { class: "pill muted", text: `${es ? "Drag" : "Drag"} ${formatPct(riskView.executionDragPct, 2)}` }));
      }
      if (Number.isFinite(riskView.riskReward)) {
        chips.appendChild(el("span", { class: "pill success", text: `R:R ${riskView.riskReward.toFixed(2)}` }));
      }
      if (Number.isFinite(riskView.gainQuote)) {
        chips.appendChild(el("span", { class: "pill positive", text: `${es ? "Ganancia" : "Gain"} +${formatPrice(riskView.gainQuote)}` }));
      }
      if (Number.isFinite(riskView.netAfterCostsQuote)) {
        chips.appendChild(el("span", {
          class: `pill ${riskView.netAfterCostsQuote >= 0 ? "positive" : "negative"}`,
          text: `${es ? "Neto después de costos" : "Net after costs"} ${riskView.netAfterCostsQuote >= 0 ? "+" : "-"}${formatPrice(Math.abs(riskView.netAfterCostsQuote))}`,
        }));
      }
      if (Number.isFinite(riskView.lossQuote)) {
        chips.appendChild(el("span", { class: "pill negative", text: `${es ? "Pérdida" : "Loss"} -${formatPrice(Math.abs(riskView.lossQuote))}` }));
      }
      riskCard.appendChild(chips);
      riskCard.appendChild(el("div", {
        class: "kpi-hint",
        text: riskView.tradeable
          ? `${primaryLabel}: ${Number.isFinite(primaryPct) ? formatPct(primaryPct, 2) : "—"} • ${es ? "Qty" : "Qty"} ${Number.isFinite(riskView.qty) ? riskView.qty : "—"} • ${es ? "Modo" : "Mode"} ${riskView.mode.toUpperCase()}`
          : `${es ? "Vista no accionable" : "Watch-only view"} • ${es ? "Movimiento proyectado" : "Projected move"} ${Number.isFinite(primaryPct) ? formatPct(primaryPct, 2) : "—"} • ${es ? "Modo" : "Mode"} ${riskView.mode.toUpperCase()}`,
      }));
    } else {
      riskCard.appendChild(el("div", { class: "sources-empty", text: es ? "Sin señal suficiente para calcular riesgo." : "Not enough signal to calculate risk." }));
    }
    insightGrid.appendChild(riskCard);

    const credibilityCard = el("div", { class: "kpi-card crypto-threshold-card" });
    credibilityCard.appendChild(el("div", { class: "kpi-title", text: es ? "Credibilidad del scope" : "Scope credibility" }));
    if (credibilityAssessment) {
      const status = String(credibilityAssessment.status || "unknown");
      const score = Number(credibilityAssessment.score);
      const reasons = Array.isArray(credibilityAssessment.reasons) ? credibilityAssessment.reasons : [];
      const statusClass = status === "trusted" ? "success" : status === "blocked" ? "negative" : "muted";
      const liveExecutionMargin = Number(state.lastPrediction?.execution_margin);
      const liveThresholdEdge = Number(state.lastPrediction?.threshold_edge);
      const liveGateReason = state.lastPrediction?.execution_gate_reason || null;
      const liveConsensus = state.lastPrediction?.consensus || null;
      credibilityCard.appendChild(
        el("div", {
          class: "kpi-value",
          text: Number.isFinite(score)
            ? `${status.toUpperCase()} • ${(score * 100).toFixed(0)}%`
            : status.toUpperCase(),
        })
      );
      credibilityCard.appendChild(
        el("div", {
          class: "kpi-hint",
          text: credibilityScope?.regime
            ? `${es ? "Scope" : "Scope"}: ${credibilityScope.symbol || scope.symbol} • ${credibilityScope.horizon_minutes || scope.horizon}m • ${credibilityScope.regime}`
            : `${es ? "Scope" : "Scope"}: ${credibilityScope?.symbol || scope.symbol} • ${credibilityScope?.horizon_minutes || scope.horizon}m`,
        })
      );
      const chips = el("div", { class: "kpi-row wrap" });
      chips.appendChild(el("span", { class: `pill ${statusClass}`, text: `${es ? "Estado" : "Status"}: ${status}` }));
      chips.appendChild(el("span", { class: "pill neutral", text: `${es ? "Trades" : "Trades"}: ${Number(credibilityAssessment.trade_count || 0)}` }));
      chips.appendChild(el("span", { class: `pill ${credibilityAssessment.actionable ? "positive" : "negative"}`, text: credibilityAssessment.actionable ? (es ? "Accionable" : "Actionable") : "HOLD" }));
      credibilityCard.appendChild(chips);
      if (reasons.length) {
        credibilityCard.appendChild(el("div", {
          class: "kpi-hint",
          text: `${es ? "Razones" : "Reasons"}: ${reasons.join(", ")}`,
        }));
      }
      if (Number.isFinite(liveExecutionMargin) && Number.isFinite(liveThresholdEdge)) {
        credibilityCard.appendChild(el("div", {
          class: "kpi-hint",
          text: `${es ? "Edge actual" : "Live edge"}: ${formatPct(liveThresholdEdge, 1)} • ${es ? "margen requerido" : "required margin"}: ${formatPct(liveExecutionMargin, 1)}${liveGateReason ? ` • ${liveGateReason}` : ""}`,
        }));
      }
      if (liveConsensus && Number.isFinite(Number(liveConsensus.support_ratio)) && Number.isFinite(Number(liveConsensus.spread))) {
        credibilityCard.appendChild(el("div", {
          class: "kpi-hint",
          text: `${es ? "Consensus" : "Consensus"}: ${formatPct(Number(liveConsensus.support_ratio), 0)} • ${es ? "spread" : "spread"}: ${formatPct(Number(liveConsensus.spread), 1)} • ${es ? "req" : "req"}: ${formatPct(Number(liveConsensus.required_support_ratio), 0)} / ${formatPct(Number(liveConsensus.max_spread), 1)}`,
        }));
      }
    } else {
      credibilityCard.appendChild(el("div", { class: "sources-empty", text: es ? "Sin evaluación de credibilidad aún." : "No credibility assessment yet." }));
    }
    insightGrid.appendChild(credibilityCard);

    const leaderboardCard = el("div", { class: "kpi-card crypto-leaderboard-card" });
    leaderboardCard.appendChild(el("div", { class: "kpi-title", text: es ? "Leaderboard de scopes" : "Scope leaderboard" }));
    if (leaderboardRows.length) {
      leaderboardRows.slice(0, 5).forEach((row, idx) => {
        const line = el("div", { class: "kpi-row wrap crypto-leaderboard-row" });
        line.appendChild(el("span", { class: "pill neutral", text: `#${idx + 1}` }));
        line.appendChild(el("span", { class: "pill success", text: `${row.symbol} • ${row.horizon_minutes}m` }));
        line.appendChild(el("span", { class: "pill muted", text: row.regime || "unknown" }));
        if (Number.isFinite(Number(row.precision))) line.appendChild(el("span", { class: "pill success", text: `${es ? "Prec" : "Prec"} ${formatPct(Number(row.precision), 1)}` }));
        if (Number.isFinite(Number(row.net_expectancy_pct))) line.appendChild(el("span", { class: `pill ${Number(row.net_expectancy_pct) >= 0 ? "positive" : "negative"}`, text: `${es ? "Net" : "Net"} ${formatPct(Number(row.net_expectancy_pct), 2)}` }));
        leaderboardCard.appendChild(line);
      });
    } else {
      leaderboardCard.appendChild(el("div", { class: "sources-empty", text: es ? "Sin leaderboard trained todavía." : "No trained leaderboard yet." }));
    }
    insightGrid.appendChild(leaderboardCard);

    const registryCard = el("div", { class: "kpi-card crypto-registry-card" });
    registryCard.appendChild(el("div", { class: "kpi-title", text: es ? "Bundles entrenados" : "Trained bundles" }));
    if (currentRegistryRows.length) {
      currentRegistryRows.slice(0, 5).forEach((row) => {
        const modelTypes = Array.isArray(row.available_model_types) ? row.available_model_types.join(", ") : "ensemble";
        registryCard.appendChild(el("div", { class: "kpi-item", text: `${row.symbol} • ${row.horizon_minutes}m • ${row.interval_minutes || "?"}m candle` }));
        registryCard.appendChild(el("div", { class: "kpi-hint", text: `${es ? "Modelos" : "Models"}: ${modelTypes}` }));
        if (row.validation_mode || row.trained_at) {
          registryCard.appendChild(el("div", { class: "kpi-hint", text: `${row.validation_mode || "—"}${row.trained_at ? ` • ${row.trained_at}` : ""}` }));
        }
      });
    } else if (registryRows.length) {
      registryCard.appendChild(el("div", { class: "sources-empty", text: es ? "No hay bundle exacto para el símbolo/horizonte actual; mostrando catálogo global en backend." : "No exact bundle for current symbol/horizon; global catalog exists in backend." }));
    } else {
      registryCard.appendChild(el("div", { class: "sources-empty", text: es ? "Sin bundles entrenados detectados." : "No trained bundles detected." }));
    }
    insightGrid.appendChild(registryCard);

    dom.sourcesContent.appendChild(insightGrid);
    updatePredictionTooltipText();
    const foot = el("div", { class: "kpi-foot" });
    const scopeNote = engineFilter === "all"
      ? (trainedCount > 0 && demoCount > 0
        ? (es ? "La vista mezcla resultados trained y demo; usa los filtros o exporta para auditoría limpia." : "This view mixes trained and demo results; use filters or export for clean audit reporting.")
        : (es ? "Vista agregada de todos los engines medidos." : "Aggregated view of all measured engines."))
      : (es ? `Filtro activo: ${engineFilter}.` : `Active filter: ${engineFilter}.`);
    foot.textContent = es
      ? `${scopeNote} La ventana OOS medida usa outcomes observados en runtime; no prueba alpha ni rentabilidad futura.`
      : `${scopeNote} The measured OOS window uses observed runtime outcomes; it does not prove alpha or future profitability.`;
    dom.sourcesContent.appendChild(foot);
  }
}

function renderPnlPanel(payload) {
  if (!dom.sourcesContent) return;
  const es = state.lang === LANG.ES;
  const pnl = payload.pnl || {};
  const trades = Array.isArray(payload.trades) ? payload.trades : [];

  dom.sourcesContent.innerHTML = "";
  const title = el("div", { class: "sources-title-row" });
  title.appendChild(el("div", { text: "P&L" }));
  dom.sourcesContent.appendChild(title);

  const grid = el("div", { class: "kpi-grid" });
  const fmt = (v) => (Number.isFinite(v) ? Number(v).toFixed(4) : "—");
  const total = Number(pnl.total ?? pnl.total_pnl ?? pnl.pnl);
  const realized = Number(pnl.realized ?? pnl.realized_pnl);
  const unreal = Number(pnl.unrealized ?? pnl.unrealized_pnl);
  const nTrades = Number(pnl.trades_count ?? trades.length);
  const maxAbs = Math.max(
    1,
    ...[total, realized, unreal]
      .filter((v) => Number.isFinite(v))
      .map((v) => Math.abs(v))
  );

  const makeCard = (label, valueNum, hint) => {
    const cls = Number.isFinite(valueNum) ? (valueNum > 0 ? "positive" : valueNum < 0 ? "negative" : "neutral") : "neutral";
    const value = fmt(valueNum);
    const card = el("div", { class: "kpi-card" });
    card.appendChild(el("div", { class: "kpi-title", text: label }));
    card.appendChild(el("div", { class: `kpi-value ${cls}`, text: value }));
    if (Number.isFinite(valueNum)) {
      const pct = Math.min(100, (Math.abs(valueNum) / maxAbs) * 100);
      const bar = el("div", { class: "kpi-bar" });
      bar.appendChild(el("span", { class: `kpi-bar-fill ${cls}`, style: `width:${pct.toFixed(1)}%` }));
      card.appendChild(bar);
    }
    if (hint) card.appendChild(el("div", { class: "kpi-hint", text: hint }));
    return card;
  };

  grid.appendChild(
    makeCard(
      es ? "P&L total" : "Total P&L",
      total,
      es ? "Resultado neto simulado" : "Net simulated result"
    )
  );
  grid.appendChild(
    makeCard(
      es ? "Realizado" : "Realized",
      realized,
      es ? "Cerrado (take-profit/stop)" : "Closed (tp/sl)"
    )
  );
  grid.appendChild(
    makeCard(
      es ? "No realizado" : "Unrealized",
      unreal,
      es ? "Abierto aún (marca a mercado)" : "Still open (mark to market)"
    )
  );
  grid.appendChild(
    makeCard(
      es ? "Trades" : "Trades",
      nTrades,
      es ? "Conteo de señales ejecutadas" : "Executed signals count"
    )
  );
  dom.sourcesContent.appendChild(grid);

  const listTitle = el("div", { class: "kpi-subtitle", text: es ? "Últimos trades (demo)" : "Latest trades (demo)" });
  dom.sourcesContent.appendChild(listTitle);

  const list = el("div", { class: "kpi-list" });
  trades.slice(0, 10).forEach((t) => {
    const side = (t.side || t.decision || "").toUpperCase();
    const pnlv = Number(t.pnl ?? t.profit ?? t.delta);
    const li = el("div", { class: "kpi-row" });
    li.appendChild(el("span", { class: `pill ${side === "BUY" ? "buy" : side === "SELL" ? "sell" : "neutral"}`, text: side || "—" }));
    if (t.symbol) li.appendChild(el("span", { class: "pill muted", text: t.symbol }));
    if (Number.isFinite(t.quantity)) li.appendChild(el("span", { class: "pill muted", text: `${t.quantity}` }));
    if (Number.isFinite(pnlv)) {
      li.appendChild(el("span", { class: `pill ${pnlv > 0 ? "buy" : pnlv < 0 ? "sell" : "neutral"}`, text: `${pnlv.toFixed(4)}` }));
    }
    list.appendChild(li);
  });
  if (!list.childNodes.length) list.appendChild(el("div", { class: "sources-empty", text: es ? "Sin trades simulados." : "No simulated trades." }));

  dom.sourcesContent.appendChild(list);

  const foot = el("div", { class: "kpi-foot" });
  foot.textContent = es
    ? "P&L se calcula con trades simulados; se nutre de las señales guardadas."
    : "P&L is computed from simulated trades; it feeds on saved signals.";
  dom.sourcesContent.appendChild(foot);
}

/* ------------------------- SESSIONS ------------------------- */

function closeSessionsModal() {
  // sidebar version: no modal to close; just stop events polling
  stopConversationEventsPolling();
}

function openSessionsModal() {
  if (dom.sessionsIncludeArchived) dom.sessionsIncludeArchived.checked = !!state.conversationsIncludeArchived;
  loadConversationList(state.conversationsIncludeArchived);
  startConversationEventsPolling();
}

async function loadConversationList(includeArchived = false) {
  if (!dom.sessionsList) return;
  if (!hasAuthForScope("main")) {
    dom.sessionsList.innerHTML = `<li class="sessions-empty">${
      state.lang === LANG.ES
        ? "Auth requerida. Configura la clave de arranque (🔑)."
        : "Auth required. Set the bootstrap key (🔑)."
    }</li>`;
    return;
  }
  dom.sessionsList.innerHTML = `<li class="sessions-empty">${state.lang === LANG.ES ? "Cargando..." : "Loading..."}</li>`;
  try {
    const url = new URL(endpoints.conversations, window.location.origin);
    url.searchParams.set("limit", "40");
    if (includeArchived) url.searchParams.set("include_archived", "1");

    const res = await fetchWithTimeout(url.toString(), { headers: { Accept: "application/json" } }, { timeout: 9000, retries: 0 });
    if (!res.ok && isAuthDeniedStatus(res.status)) {
      dom.sessionsList.innerHTML = `<li class="sessions-empty">${
        state.lang === LANG.ES
          ? "Auth requerida (401/403). Configura la clave de arranque (🔑)."
          : "Auth required (401/403). Set the bootstrap key (🔑)."
      }</li>`;
      return;
    }
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

async function selectConversation(convId) {
  if (!convId) return;
  state.conversationId = convId;
  state.useExistingConversation = true;
  localStorage.setItem("aegis_conv", convId);
  localStorage.setItem("aegis_use_existing", "1");
  updateConversationIndicators(convId);
  const synced = await syncConversationState(convId);
  if (!synced || state.conversationId !== convId) return false;
  const restored = await restoreConversationTranscript(convId, { force: true });
  if (!restored && state.conversationId !== convId) return false;
  appendBubble(state.lang === LANG.ES ? `Sesión ${convId} activada.` : `Conversation ${convId} selected.`, "bot");
  closeSessionsModal();
  return true;
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
  const previousConvId = String(state.conversationId || "").trim();
  state.conversationId = null;
  state.useExistingConversation = false;
  state.lastTranscriptConversationId = "";
  localStorage.removeItem("aegis_conv");
  localStorage.removeItem("aegis_use_existing");
  localStorage.removeItem("aegis_last_transcript_conv");
  updateConversationIndicators(null);
  stopConversationEventsPolling();
  resetConversationEvents();
  clearChatTranscript();
  if (previousConvId && state.selectedConversationIds?.has(previousConvId)) {
    state.selectedConversationIds.delete(previousConvId);
    updateConversationBulkActions();
  }
  if (!silent) appendBubble(state.lang === LANG.ES ? "Sesión local borrada." : "Local session cleared.", "bot");
}

function handleMissingConversation(convId, { source = "conversation" } = {}) {
  const missingId = String(convId || state.conversationId || "").trim();
  clearConversation(true);
  if (missingId && Array.isArray(state.conversationList) && state.conversationList.length) {
    const nextList = state.conversationList.filter((item) => String(item?.id || "") !== missingId);
    if (nextList.length !== state.conversationList.length) {
      state.conversationList = nextList;
      renderConversationList(state.conversationList);
    }
  }
  if (hasAuthForScope("main")) {
    void loadConversationList(state.conversationsIncludeArchived);
  }
  console.warn("conversation-missing", { source, conversation_id: missingId });
  return false;
}

function resetConversationEvents() {
  state.convEventsSince = null;
  state.convEventsItems = [];
  if (dom.convEventsList) {
    dom.convEventsList.innerHTML = `<li class="sessions-empty">${state.lang === LANG.ES ? "Sin eventos." : "No events yet."}</li>`;
  }
  state.convTurnsItems = [];
  if (dom.convTurnsList) {
    dom.convTurnsList.innerHTML = `<li class="sessions-empty">${state.lang === LANG.ES ? "Sin turns." : "No turns yet."}</li>`;
  }
}

function renderConversationEvents(items) {
  if (!dom.convEventsList) return;
  if (!items.length) {
    dom.convEventsList.innerHTML = `<li class="sessions-empty">${state.lang === LANG.ES ? "Sin eventos." : "No events yet."}</li>`;
    return;
  }
  dom.convEventsList.innerHTML = "";
  items.slice(-120).forEach((evt) => {
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

function filterConversationTurns(items, rawQuery) {
  const q = String(rawQuery || "").trim();
  if (!q) return items;
  const qLower = q.toLowerCase();

  const take = (val) => String(val || "").toLowerCase();

  const parsePrefix = (prefix) => {
    const re = new RegExp(`^${prefix}\\s*:\\s*`, "i");
    if (!re.test(q)) return null;
    return q.replace(re, "").trim().toLowerCase();
  };

  const idQ = parsePrefix("id");
  const toolQ = parsePrefix("tool");
  const statusQ = parsePrefix("status");

  return (items || []).filter((turn) => {
    const turnId = take(turn?.turn_id);
    if (idQ) return turnId.includes(idQ);

    const mode = take(turn?.mode);
    const sourcePlan = take(turn?.source_plan);
    const status = take(turn?.status);
    if (statusQ) return status.includes(statusQ);

    const userMsg = take(turn?.user_message);
    const asst = take(turn?.assistant_message);
    const effTool = take(turn?.response_context?.effective_tool);
    const effStatus = take(turn?.response_context?.effective_tool_status);

    const itemsList = Array.isArray(turn?.items) ? turn.items : [];
    const toolNames = itemsList
      .filter((it) => it?.kind === "tool_call" || it?.kind === "tool_result")
      .map((it) => take(it?.payload?.tool))
      .filter(Boolean)
      .join(" ");

    if (toolQ) {
      return effTool.includes(toolQ) || toolNames.includes(toolQ);
    }

    const hay = [turnId, mode, sourcePlan, status, userMsg, asst, effTool, effStatus, toolNames].join(" ");
    return hay.includes(qLower);
  });
}

function renderConversationTurns(items) {
  if (!dom.convTurnsList) return;
  const filtered = filterConversationTurns(items || [], state.turnsFilter);
  if (!filtered.length) {
    const es = state.lang === LANG.ES;
    const base = (items || []).length
      ? (es ? "Sin coincidencias para el filtro actual." : "No matches for the current filter.")
      : (es ? "Sin turns." : "No turns yet.");
    dom.convTurnsList.innerHTML = `<li class="sessions-empty">${base}</li>`;
    return;
  }
  const es = state.lang === LANG.ES;
  dom.convTurnsList.innerHTML = "";
  filtered.slice(-20).reverse().forEach((turn) => {
    const li = document.createElement("li");
    li.className = "event-item turn-item";
    li.addEventListener("click", () => openTurnDetail(turn));

    const meta = document.createElement("div");
    meta.className = "event-meta";

    const stage = document.createElement("span");
    stage.className = "event-stage";
    stage.textContent = `${String(turn.mode || "chat")} • ${prettySourcePlan(turn.source_plan || "local_only")}`;

    const status = document.createElement("span");
    status.className = `event-level ${String(turn.status || "info").toLowerCase()}`;
    status.textContent = turn.status || "info";

    meta.appendChild(stage);
    meta.appendChild(status);

    const detail = document.createElement("div");
    detail.className = "event-detail";
    const ts = turn.created_at ? formatAgo(Number(turn.created_at)) : "";
    const msg = String(turn.user_message || "").trim();
    detail.textContent = `${ts}${msg ? ` · ${msg}` : ""}`;

    li.appendChild(meta);
    li.appendChild(detail);

    const itemsList = Array.isArray(turn.items) ? turn.items : [];
    const chips = document.createElement("div");
    chips.className = "turn-summary";

    const sourceItem = itemsList.find((item) => item?.kind === "source_selection");
    const replanItem = itemsList.find((item) => item?.kind === "replan");
    const toolItem = itemsList.find((item) => item?.kind === "tool_call");
    const toolResultItem = itemsList.find((item) => item?.kind === "tool_result");
    const retryItems = itemsList.filter((item) => item?.kind === "llm_retry");

    const addChip = (text) => {
      if (!text) return;
      const span = document.createElement("span");
      span.className = "turn-summary-chip";
      span.textContent = text;
      chips.appendChild(span);
    };

    if (toolItem?.payload?.tool) addChip(`${es ? "Tool" : "Tool"}: ${toolItem.payload.tool}`);
    if (toolResultItem?.payload?.tool) addChip(`${es ? "Resultado" : "Result"}: ${toolResultItem.payload.tool}`);
    if (toolResultItem?.status) addChip(`${es ? "Estado" : "Status"}: ${toolResultItem.status}`);
    if (sourceItem?.payload?.next_tool) addChip(`${es ? "Siguiente" : "Next"}: ${sourceItem.payload.next_tool}`);
    if (replanItem?.payload?.next_tool) addChip(`${es ? "Replan" : "Replan"}: ${replanItem.payload.next_tool}`);
    if (retryItems.length) {
      const reasons = retryItems.map((it) => String(it?.payload?.reason || "").trim()).filter(Boolean);
      const label = es ? "Retry" : "Retry";
      addChip(`${label}: ${reasons.length ? reasons.join(", ") : retryItems.length}`);
    }
    if (turn.response_context?.current_artifact_focus) addChip(`${es ? "Artefacto" : "Artifact"}: ${turn.response_context.current_artifact_focus}`);
    if (turn.response_context?.current_file_focus) addChip(`${es ? "Archivo" : "File"}: ${turn.response_context.current_file_focus}`);
    if (turn.response_context?.current_symbol_focus) addChip(`${es ? "Símbolo" : "Symbol"}: ${turn.response_context.current_symbol_focus}`);
    if (turn.response_context?.crypto_prediction_ref) {
      addChip(`${es ? "Pred" : "Pred"}: ${formatCryptoPredictionRef(turn.response_context.crypto_prediction_ref, { es, includeSource: false })}`);
    }
    if (turn.response_context?.llm_required === false) addChip("LLM: bypassed");
    if (Array.isArray(turn.response_context?.source_origin) && turn.response_context.source_origin.length) {
      addChip(`${es ? "Origen" : "Origin"}: ${turn.response_context.source_origin.map(prettyOriginLabel).join(", ")}`);
    }
    if (Array.isArray(turn.response_context?.missing_evidence) && turn.response_context.missing_evidence.length) {
      addChip(`${es ? "Falta" : "Missing"}: ${turn.response_context.missing_evidence.slice(0, 2).join(", ")}`);
    }

    if (chips.childNodes.length) li.appendChild(chips);
    dom.convTurnsList.appendChild(li);
  });
}

function openTurnDetail(turn) {
  if (!dom.turnDetailModal || !dom.turnDetailBody) return;
  const es = state.lang === LANG.ES;
  const turnId = String(turn?.turn_id || "").trim();
  const mode = String(turn?.mode || "chat").trim();
  if (dom.turnDetailTitle) {
    dom.turnDetailTitle.textContent = turnId
      ? `${es ? "Turn" : "Turn"} ${turnId} · ${mode}`
      : `${es ? "Turn" : "Turn"} · ${mode}`;
  }
  const status = String(turn?.status || "").trim() || "info";
  const sourcePlan = prettySourcePlan(turn?.source_plan || "local_only");
  const started = turn?.created_at ? new Date(Number(turn.created_at)).toLocaleString() : "";
  const finished = turn?.finished_at ? new Date(Number(turn.finished_at)).toLocaleString() : "";
  const effectiveTool = String(turn?.response_context?.effective_tool || "").trim();
  const effectiveToolStatus = String(turn?.response_context?.effective_tool_status || "").trim();
  const activeProjectId = String(turn?.active_project_id || turn?.response_context?.active_project_id || "").trim();
  const origins = Array.isArray(turn?.response_context?.source_origin) ? turn.response_context.source_origin : [];
  const missing = Array.isArray(turn?.response_context?.missing_evidence) ? turn.response_context.missing_evidence : [];
  const retryItems = Array.isArray(turn?.items) ? turn.items.filter((it) => it?.kind === "llm_retry") : [];
  const cryptoPredictionRef = turn?.response_context?.crypto_prediction_ref && typeof turn.response_context.crypto_prediction_ref === "object"
    ? turn.response_context.crypto_prediction_ref
    : null;

  if (dom.turnDetailSummary) {
    const parts = [];
    if (started) parts.push(`${es ? "Inicio" : "Start"}: ${started}`);
    if (finished) parts.push(`${es ? "Fin" : "End"}: ${finished}`);
    parts.push(`${es ? "Modo" : "Mode"}: ${mode}`);
    parts.push(`${es ? "Plan" : "Plan"}: ${sourcePlan}`);
    parts.push(`${es ? "Estado" : "Status"}: ${status}`);
    if (activeProjectId) parts.push(`${es ? "Proyecto" : "Project"}: ${activeProjectId}`);
    if (effectiveTool) parts.push(`${es ? "Tool efectiva" : "Effective tool"}: ${effectiveTool}${effectiveToolStatus ? ` (${effectiveToolStatus})` : ""}`);
    if (cryptoPredictionRef) parts.push(`${es ? "Pred usada" : "Prediction used"}: ${formatCryptoPredictionRef(cryptoPredictionRef, { es })}`);
    if (origins.length) parts.push(`${es ? "Origen" : "Origin"}: ${origins.map(prettyOriginLabel).join(", ")}`);
    if (missing.length) parts.push(`${es ? "Falta evidencia" : "Missing evidence"}: ${missing.slice(0, 6).join(", ")}`);
    if (retryItems.length) {
      const reasons = retryItems.map((it) => String(it?.payload?.reason || "").trim()).filter(Boolean);
      parts.push(`${es ? "Reintentos" : "Retries"}: ${reasons.length ? reasons.join(", ") : retryItems.length}`);
    }
    dom.turnDetailSummary.textContent = parts.join(" · ");
  }

  if (dom.turnDetailToolWrap && dom.turnDetailToolOut) {
    const items = Array.isArray(turn?.items) ? turn.items : [];
    const toolResultItem = items.find((it) => it?.kind === "tool_result");
    const toolOut = String(
      toolResultItem?.payload?.response ||
      turn?.response_context?.effective_tool_output ||
      ""
    );
    const toolName = String(
      toolResultItem?.payload?.tool ||
      turn?.response_context?.effective_tool ||
      ""
    ).trim();

    if (toolOut.trim()) {
      dom.turnDetailToolWrap.style.display = "block";
      if (dom.turnDetailToolLabel) {
        dom.turnDetailToolLabel.textContent = toolName
          ? `${es ? "Salida de tool" : "Tool output"}: ${toolName}`
          : (es ? "Salida de tool" : "Tool output");
      }
      dom.turnDetailToolOut.textContent = toolOut;
      if (dom.turnDetailJsonLabel) dom.turnDetailJsonLabel.textContent = es ? "JSON del turn" : "Turn JSON";
    } else {
      dom.turnDetailToolWrap.style.display = "none";
      dom.turnDetailToolOut.textContent = "";
      if (dom.turnDetailJsonLabel) dom.turnDetailJsonLabel.textContent = es ? "JSON del turn" : "Turn JSON";
    }
  }

  dom.turnDetailBody.textContent = JSON.stringify(turn || {}, null, 2);
  openModal(dom.turnDetailModal);
}

async function openLatestTurnDetail() {
  const convId = state.conversationId;
  if (!convId) return;
  try {
    await loadConversationTurns({ force: true });
    const items = Array.isArray(state.convTurnsItems) ? state.convTurnsItems : [];
    if (!items.length) return;
    openTurnDetail(items[items.length - 1]);
  } catch (err) {
    console.error(err);
  }
}

function isAuthDeniedStatus(status) {
  const n = Number(status || 0);
  return n === 401 || n === 403;
}

function handleConversationPollAuthDenied(status = 401) {
  const es = state.lang === LANG.ES;
  const now = Date.now();
  const msg = es
    ? "Sesión/log pausados por autenticación (401/403). Actualiza la clave de arranque (🔑) y reintenta."
    : "Session/log paused due to authentication (401/403). Update the bootstrap key (🔑) and retry.";

  stopConversationEventsPolling();
  if (dom.convEventsList) {
    dom.convEventsList.innerHTML = `<li class="sessions-empty">${msg}</li>`;
  }
  if (dom.convTurnsList) {
    dom.convTurnsList.innerHTML = `<li class="sessions-empty">${msg}</li>`;
  }

  if (!state.convAuthBlockedAt || (now - Number(state.convAuthBlockedAt)) > 30000) {
    state.convAuthBlockedAt = now;
    appendBubble(
      es
        ? `Auth ${status}: pausé el polling de sesión para evitar ruido 401.`
        : `Auth ${status}: paused session polling to avoid 401 noise.`,
      "error"
    );
  }
}

async function loadConversationTurns({ force = false } = {}) {
  if (!dom.convTurnsList) return;
  if (!state.debugTraceEnabled) return;
  if (state.convTurnsInFlight) {
    if (force) state.convTurnsForceQueued = true;
    return;
  }
  const convId = state.conversationId;
  if (!convId) {
    state.convTurnsItems = [];
    renderConversationTurns([]);
    return;
  }

  state.convTurnsInFlight = true;
  try {
    const url = new URL(endpoints.conversationTurns(convId), location.origin);
    url.searchParams.set("limit", "20");
    const res = await fetchWithTimeout(url.toString(), { headers: { Accept: "application/json" } }, { timeout: 20000, retries: 0 });
    if (res.status === 404) {
      handleMissingConversation(convId, { source: "turns" });
      return;
    }
    if (!res.ok && isAuthDeniedStatus(res.status)) {
      handleConversationPollAuthDenied(res.status);
      return;
    }
    const data = await safeJson(res);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const items = Array.isArray(data?.items) ? data.items : [];
    state.convTurnsItems = force ? items : items;
    renderConversationTurns(state.convTurnsItems);
  } catch (err) {
    if (err?.name === "AbortError") return;
    console.error(err);
  } finally {
    state.convTurnsInFlight = false;
    if (state.convTurnsForceQueued) {
      state.convTurnsForceQueued = false;
      setTimeout(() => loadConversationTurns({ force: true }), 0);
    }
  }
}

async function loadConversationEvents({ force = false } = {}) {
  if (!dom.convEventsList) return;
  if (!state.debugTraceEnabled) return;
  if (state.convEventsInFlight) {
    if (force) state.convEventsForceQueued = true;
    return;
  }
  const convId = state.conversationId;
  if (!convId) {
    resetConversationEvents();
    return;
  }

  state.convEventsInFlight = true;
  try {
    const url = new URL(endpoints.conversationEvents(convId), location.origin);
    if (!force && state.convEventsSince) {
      url.searchParams.set("since", String(state.convEventsSince));
    }
    url.searchParams.set("limit", "120");
    const res = await fetchWithTimeout(url.toString(), { headers: { Accept: "application/json" } }, { timeout: 20000, retries: 0 });
    if (res.status === 404) {
      handleMissingConversation(convId, { source: "events" });
      return;
    }
    if (!res.ok && isAuthDeniedStatus(res.status)) {
      handleConversationPollAuthDenied(res.status);
      return;
    }
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
    if (state.convEventsItems.length > 120) {
      state.convEventsItems = state.convEventsItems.slice(-120);
    }
    if (items.length) {
      state.convEventsSince = items[items.length - 1]?.ts || state.convEventsSince;
    }
    renderConversationEvents(state.convEventsItems);
  } catch (err) {
    if (err?.name === "AbortError") return;
    console.error(err);
  } finally {
    state.convEventsInFlight = false;
    if (state.convEventsForceQueued) {
      state.convEventsForceQueued = false;
      setTimeout(() => loadConversationEvents({ force: true }), 0);
    }
  }
}

function startConversationEventsPolling() {
  if (state.convEventsTimer || state.convTurnsTimer) return;
  if (!state.debugTraceEnabled) return;
  if (!state.chatSideVisible) return;
  if (!hasAuthForScope("main")) return;
  resetConversationEvents();
  loadConversationEvents({ force: true });
  loadConversationTurns({ force: true });
  state.convEventsTimer = setInterval(() => {
    if (document.hidden || !state.chatSideVisible) return;
    loadConversationEvents();
  }, 8000);
  state.convTurnsTimer = setInterval(() => {
    if (document.hidden || !state.chatSideVisible) return;
    loadConversationTurns();
  }, 15000);
  updateStatusCenter();
}

function stopConversationEventsPolling() {
  if (state.convEventsTimer) {
    clearInterval(state.convEventsTimer);
    state.convEventsTimer = null;
  }
  if (state.convTurnsTimer) {
    clearInterval(state.convTurnsTimer);
    state.convTurnsTimer = null;
  }
  updateStatusCenter();
}

/* ------------------------- FILE TREE / CONTENT / INGEST ------------------------- */

function syncFileViewerMode() {
  const editing = !!state.fileViewerEditing;
  const hasProject = !!state.activeProjectId;
  const hasPath = !!state.fileViewerPath;
  const actionTarget = currentWorkspaceActionTarget();
  const hasSelection = !!actionTarget.path;
  const canDeleteSelection = hasSelection && !actionTarget.isDir;
  const showDiff = editing && !!state.fileViewerDiffMode;
  if (dom.fileViewerBody) dom.fileViewerBody.hidden = editing && !showDiff;
  if (dom.fileEditorBody) dom.fileEditorBody.hidden = !editing || showDiff;
  if (dom.fileViewerTitle) dom.fileViewerTitle.hidden = !!state.fileViewerIsNew;
  if (dom.fileEditorPath) dom.fileEditorPath.hidden = !(editing && !!state.fileViewerIsNew);
  if (dom.newFileBtn) dom.newFileBtn.hidden = !hasProject || editing;
  if (dom.newFolderBtn) dom.newFolderBtn.hidden = !hasProject || editing;
  if (dom.movePathBtn) dom.movePathBtn.hidden = editing || !hasSelection;
  if (dom.renameFileBtn) dom.renameFileBtn.hidden = editing || !hasSelection || !!state.fileViewerIsNew;
  if (dom.editFileBtn) dom.editFileBtn.hidden = editing || !hasPath || !!state.fileViewerIsNew;
  if (dom.diffFileBtn) dom.diffFileBtn.hidden = !editing;
  if (dom.deleteFileBtn) dom.deleteFileBtn.hidden = editing || !canDeleteSelection || !!state.fileViewerIsNew;
  if (dom.saveFileBtn) dom.saveFileBtn.hidden = !editing;
  if (dom.cancelFileEditBtn) dom.cancelFileEditBtn.hidden = !editing;
  if (dom.movePathBtn) {
    dom.movePathBtn.title = actionTarget.isDir
      ? (state.lang === LANG.ES ? "Mover o renombrar carpeta" : "Move or rename folder")
      : (state.lang === LANG.ES ? "Mover o renombrar archivo" : "Move or rename file");
  }
  if (dom.renameFileBtn) {
    dom.renameFileBtn.title = actionTarget.isDir
      ? (state.lang === LANG.ES ? "Renombrar carpeta seleccionada" : "Rename selected folder")
      : (state.lang === LANG.ES ? "Renombrar archivo seleccionado" : "Rename selected file");
  }
  if (dom.deleteFileBtn) {
    dom.deleteFileBtn.title = state.lang === LANG.ES
      ? "Eliminar archivo seleccionado"
      : "Delete selected file";
  }
}

function fileViewerHasUnsavedChanges() {
  if (!state.fileViewerEditing) return false;
  const draftContent = String(dom.fileEditorBody?.value || "");
  if (state.fileViewerIsNew) {
    const draftPath = String(dom.fileEditorPath?.value || "").trim();
    return !!draftPath || draftContent.length > 0;
  }
  return draftContent !== String(state.fileViewerContent || "");
}

function confirmDiscardFileEdits() {
  if (!fileViewerHasUnsavedChanges()) return true;
  const es = state.lang === LANG.ES;
  return window.confirm(
    es
      ? "Hay cambios sin guardar en el editor. ¿Descartarlos?"
      : "There are unsaved editor changes. Discard them?"
  );
}

function handleBeforeUnload(event) {
  if (!fileViewerHasUnsavedChanges()) return;
  event.preventDefault();
  event.returnValue = "";
}

function currentProjectImpactQuery() {
  const target = currentWorkspaceActionTarget();
  const path = String(target?.path || state.fileViewerPath || "").trim();
  return path;
}

async function loadProjectImpact() {
  if (!state.activeProjectId) {
    state.activeProjectImpact = null;
    return;
  }
  const query = currentProjectImpactQuery();
  if (!query) {
    state.activeProjectImpact = null;
    renderProjectMeta();
    return;
  }
  const projectId = String(state.activeProjectId || "");
  try {
    const url = new URL(endpoints.filesProjectImpact(projectId), location.origin);
    url.searchParams.set("q", query);
    url.searchParams.set("limit", "8");
    const res = await fetchWithTimeout(url.toString(), {}, { timeout: 12000, retries: 0 });
    const data = await safeJson(res);
    if (!res.ok) throw new Error(data?.detail || `HTTP ${res.status}`);
    if (projectId !== String(state.activeProjectId || "")) return;
    state.activeProjectImpact = data?.report && typeof data.report === "object" ? data.report : null;
  } catch (err) {
    console.error("project-impact-error", err);
    state.activeProjectImpact = null;
  }
  renderProjectMeta();
}

function setTreeSelection(path, isDir) {
  state.treeSelectionPath = String(path || "");
  state.treeSelectionIsDir = !!isDir;
  if (dom.projectTree) {
    dom.projectTree.querySelectorAll(".tree-node.selected").forEach((node) => node.classList.remove("selected"));
    dom.projectTree.querySelectorAll(".tree-node").forEach((node) => {
      if (String(node.dataset.path || "") === state.treeSelectionPath) {
        node.classList.add("selected");
      }
    });
  }
  syncFileViewerMode();
  if (state.activeProjectId) {
    void loadProjectImpact();
  }
}

function setFileViewerContent(path, content, options = {}) {
  const { isNew = false, keepPrevious = false } = options;
  if (!keepPrevious) {
    state.fileViewerPreviousPath = "";
    state.fileViewerPreviousContent = "";
  }
  state.fileViewerPath = String(path || "");
  state.fileViewerContent = String(content ?? "");
  state.fileViewerEditing = false;
  state.fileViewerIsNew = !!isNew;
  state.fileViewerDiffMode = false;
  state.fileViewerDiffText = "";
  if (dom.fileViewerTitle) {
    dom.fileViewerTitle.textContent = state.fileViewerPath || (
      state.lang === LANG.ES ? "Selecciona un archivo en Archivos" : "Select a file in Files"
    );
  }
  if (dom.fileEditorPath) dom.fileEditorPath.value = state.fileViewerPath || "";
  if (dom.fileViewerBody) dom.fileViewerBody.textContent = state.fileViewerContent;
  if (dom.fileEditorBody) dom.fileEditorBody.value = state.fileViewerContent;
  syncFileViewerMode();
  if (state.activeProjectId) {
    void loadProjectImpact();
  }
}

function enterFileEditMode() {
  if (!state.fileViewerPath) return;
  state.fileViewerEditing = true;
  state.fileViewerIsNew = false;
  state.fileViewerDiffMode = false;
  state.fileViewerDiffText = "";
  if (dom.fileEditorBody) {
    dom.fileEditorBody.value = state.fileViewerContent || "";
    try { dom.fileEditorBody.focus(); } catch {}
  }
  syncFileViewerMode();
}

function startNewFileMode() {
  if (!state.activeProjectId) return;
  const actionTarget = currentWorkspaceActionTarget();
  const basePath = actionTarget.isDir
    ? actionTarget.path
    : dirnamePosix(actionTarget.path || state.fileViewerPath);
  const suggestedPath = basePath ? `${basePath}/new_file.txt` : "new_file.txt";
  state.fileViewerPreviousPath = state.fileViewerPath || "";
  state.fileViewerPreviousContent = state.fileViewerContent || "";
  state.fileViewerPath = "";
  state.fileViewerContent = "";
  state.fileViewerEditing = true;
  state.fileViewerIsNew = true;
  state.fileViewerDiffMode = false;
  state.fileViewerDiffText = "";
  if (dom.fileEditorPath) {
    dom.fileEditorPath.value = suggestedPath;
    try { dom.fileEditorPath.focus(); } catch {}
  }
  if (dom.fileEditorBody) dom.fileEditorBody.value = "";
  if (dom.fileViewerBody) {
    dom.fileViewerBody.textContent = state.lang === LANG.ES
      ? "Nuevo archivo."
      : "New file.";
  }
  syncFileViewerMode();
}

function cancelFileEditMode() {
  if (state.fileViewerIsNew) {
    const prevPath = state.fileViewerPreviousPath || "";
    const prevContent = state.fileViewerPreviousContent || "";
    setFileViewerContent(prevPath, prevContent);
    return;
  }
  if (dom.fileEditorBody) dom.fileEditorBody.value = state.fileViewerContent || "";
  state.fileViewerEditing = false;
  state.fileViewerDiffMode = false;
  state.fileViewerDiffText = "";
  if (dom.fileViewerBody) dom.fileViewerBody.textContent = state.fileViewerContent || "";
  syncFileViewerMode();
}

async function toggleFileDiffMode() {
  if (!state.fileViewerEditing || !dom.fileEditorBody) return;
  if (state.fileViewerDiffMode) {
    state.fileViewerDiffMode = false;
    if (dom.fileViewerBody) dom.fileViewerBody.textContent = state.fileViewerContent || "";
    syncFileViewerMode();
    return;
  }
  const path = state.fileViewerIsNew ? String(dom.fileEditorPath?.value || "").trim() : state.fileViewerPath;
  if (!path) {
    appendBubble(state.lang === LANG.ES ? "Define la ruta del archivo primero." : "Set the file path first.", "error");
    return;
  }
  try {
    const res = await fetchWithTimeout(
      endpoints.filesDiffContent,
      {
        method: "POST",
        headers: withJsonHeaders({}, "files"),
        body: JSON.stringify({
          project_id: state.activeProjectId,
          path,
          content: dom.fileEditorBody.value || "",
          create: !!state.fileViewerIsNew,
        }),
      },
      { timeout: 30000, retries: 0 }
    );
    const data = await safeJson(res);
    if (!res.ok) {
      throw new Error(data?.detail || `${res.status} ${res.statusText || ""}`.trim());
    }
    state.fileViewerDiffMode = true;
    state.fileViewerDiffText = String(data?.diff || "");
    if (dom.fileViewerBody) {
      dom.fileViewerBody.textContent = state.fileViewerDiffText || (
        state.lang === LANG.ES ? "Sin cambios." : "No changes."
      );
    }
    syncFileViewerMode();
  } catch (err) {
    console.error(err);
    appendBubble(
      `${state.lang === LANG.ES ? "No se pudo generar el diff." : "Could not generate diff."} ${err?.message || ""}`.trim(),
      "error"
    );
  }
}

async function renameFileViewer() {
  if (!state.activeProjectId || state.fileViewerEditing) return;
  const es = state.lang === LANG.ES;
  const actionTarget = currentWorkspaceActionTarget();
  const currentPath = String(actionTarget.path || "").trim();
  if (!currentPath) {
    appendBubble(es ? "Selecciona un archivo o carpeta primero." : "Select a file or folder first.", "error");
    return;
  }
  const nextPath = window.prompt(
    actionTarget.isDir
      ? (es ? "Nueva ruta de la carpeta" : "New folder path")
      : (es ? "Nueva ruta del archivo" : "New file path"),
    currentPath
  );
  if (nextPath == null) return;
  const trimmed = String(nextPath || "").trim();
  if (!trimmed) {
    appendBubble(es ? "Define una ruta válida." : "Set a valid file path.", "error");
    return;
  }
  try {
    const res = await fetchWithTimeout(
      endpoints.filesMovePath,
      {
        method: "POST",
        headers: withJsonHeaders({}, "files"),
        body: JSON.stringify({
          project_id: state.activeProjectId,
          path: currentPath,
          new_path: trimmed,
        }),
      },
      { timeout: 30000, retries: 0 }
    );
    const data = await safeJson(res);
    if (!res.ok) {
      throw new Error(data?.detail || `${res.status} ${res.statusText || ""}`.trim());
    }
    const nextPathValue = String(data?.new_path || trimmed);
    const movedIsDir = !!data?.is_dir || !!actionTarget.isDir;
    if (!movedIsDir && (state.fileViewerPath === currentPath || actionTarget.source === "viewer")) {
      setFileViewerContent(nextPathValue, state.fileViewerContent || "");
    } else if (movedIsDir && state.fileViewerPath && (state.fileViewerPath === currentPath || state.fileViewerPath.startsWith(`${currentPath}/`))) {
      setFileViewerContent(
        "",
        es ? "La vista del archivo se limpió porque la carpeta se renombró." : "File view was cleared because the folder was renamed."
      );
    }
    setTreeSelection(nextPathValue, movedIsDir);
    appendBubble(
      movedIsDir
        ? (es ? "Carpeta renombrada." : "Folder renamed.")
        : (es ? "Archivo renombrado." : "File renamed."),
      "bot"
    );
    await loadProjectTree();
  } catch (err) {
    console.error(err);
    appendBubble(
      `${actionTarget.isDir ? (es ? "No se pudo renombrar la carpeta." : "Could not rename folder.") : (es ? "No se pudo renombrar el archivo." : "Could not rename file.")} ${err?.message || ""}`.trim(),
      "error"
    );
  }
}

async function deleteFileViewer() {
  if (!state.activeProjectId || state.fileViewerEditing) return;
  const es = state.lang === LANG.ES;
  const actionTarget = currentWorkspaceActionTarget();
  const currentPath = String(actionTarget.path || "").trim();
  if (!currentPath) {
    appendBubble(es ? "Selecciona un archivo primero." : "Select a file first.", "error");
    return;
  }
  if (actionTarget.isDir) {
    appendBubble(es ? "La eliminación de carpetas aún no está habilitada en este flujo." : "Folder deletion is not enabled in this flow yet.", "error");
    return;
  }
  const ok = window.confirm(
    es
      ? `Esto eliminará ${currentPath}. ¿Continuar?`
      : `This will delete ${currentPath}. Continue?`
  );
  if (!ok) return;
  try {
    const res = await fetchWithTimeout(
      endpoints.filesDeleteContent,
      {
        method: "POST",
        headers: withJsonHeaders({}, "files"),
        body: JSON.stringify({
          project_id: state.activeProjectId,
          path: currentPath,
        }),
      },
      { timeout: 30000, retries: 0 }
    );
    const data = await safeJson(res);
    if (!res.ok) {
      throw new Error(data?.detail || `${res.status} ${res.statusText || ""}`.trim());
    }
    setFileViewerContent("", es ? "Archivo eliminado." : "File deleted.");
    setTreeSelection("", false);
    appendBubble(es ? "Archivo eliminado." : "File deleted.", "bot");
    await loadProjectTree();
  } catch (err) {
    console.error(err);
    appendBubble(
      `${es ? "No se pudo eliminar el archivo." : "Could not delete file."} ${err?.message || ""}`.trim(),
      "error"
    );
  }
}

function dirnamePosix(path) {
  const raw = String(path || "").replace(/\\/g, "/").replace(/\/+$/, "");
  if (!raw.includes("/")) return "";
  return raw.split("/").slice(0, -1).join("/");
}

function currentWorkspaceActionTarget() {
  const selectedPath = String(state.treeSelectionPath || "").trim();
  if (selectedPath) {
    return {
      path: selectedPath,
      isDir: !!state.treeSelectionIsDir,
      source: "tree",
    };
  }
  const viewerPath = String(state.fileViewerPath || "").trim();
  if (viewerPath) {
    return {
      path: viewerPath,
      isDir: false,
      source: "viewer",
    };
  }
  return {
    path: "",
    isDir: false,
    source: "none",
  };
}

async function applyBatchWorkspacePlan() {
  if (!state.activeProjectId || !dom.batchApplyInput) return;
  const es = state.lang === LANG.ES;
  if (!batchApplyReviewIsCurrent()) {
    appendBubble(
      es
        ? "Primero genera y revisa el preview actual del lote."
        : "Generate and review the current batch preview first.",
      "error"
    );
    return;
  }
  let payload = null;
  try {
    payload = JSON.parse(String(dom.batchApplyInput.value || "").trim() || "{}");
  } catch (err) {
    appendBubble(es ? "JSON inválido en batch apply." : "Invalid JSON in batch apply.", "error");
    return;
  }
  const operations = Array.isArray(payload) ? payload : payload?.operations;
  if (!Array.isArray(operations) || !operations.length) {
    appendBubble(es ? "No hay operaciones para aplicar." : "No operations to apply.", "error");
    return;
  }
  try {
    const res = await fetchWithTimeout(
      endpoints.filesBatchApply,
      {
        method: "POST",
        headers: withJsonHeaders({}, "files"),
        body: JSON.stringify({
          project_id: state.activeProjectId,
          operations,
          review_token: state.batchApplyReviewToken,
        }),
      },
      { timeout: 45000, retries: 0 }
    );
    const data = await safeJson(res);
    if (!res.ok) {
      throw new Error(batchApplyErrorMessage(data, `${res.status} ${res.statusText || ""}`.trim()));
    }
    clearBatchApplyReview();
    closeModal(dom.batchApplyModal);
    await loadProjectTree();
    appendBubble(
      es
        ? `Cambios aplicados: ${Number(data?.applied_count || 0)}`
        : `Applied changes: ${Number(data?.applied_count || 0)}`,
      "bot"
    );
  } catch (err) {
    console.error(err);
    appendBubble(
      `${es ? "No se pudo aplicar el lote." : "Could not apply batch."} ${err?.message || ""}`.trim(),
      "error"
    );
  }
}

async function previewBatchWorkspacePlan() {
  if (!state.activeProjectId || !dom.batchApplyInput) return;
  const es = state.lang === LANG.ES;
  let payload = null;
  try {
    payload = JSON.parse(batchApplyPayloadText() || "{}");
  } catch (err) {
    appendBubble(es ? "JSON inválido en batch apply." : "Invalid JSON in batch apply.", "error");
    return;
  }
  const operations = Array.isArray(payload) ? payload : payload?.operations;
  if (!Array.isArray(operations) || !operations.length) {
    appendBubble(es ? "No hay operaciones para previsualizar." : "No operations to preview.", "error");
    return;
  }
  try {
    const res = await fetchWithTimeout(
      endpoints.filesBatchPreview,
      {
        method: "POST",
        headers: withJsonHeaders({}, "files"),
        body: JSON.stringify({
          project_id: state.activeProjectId,
          operations,
        }),
      },
      { timeout: 45000, retries: 0 }
    );
    const data = await safeJson(res);
    if (!res.ok) {
      throw new Error(batchApplyErrorMessage(data, `${res.status} ${res.statusText || ""}`.trim()));
    }
    setBatchApplyPreview(data, batchApplyPayloadText());
    appendBubble(
      es
        ? `Preview listo: ${Number(data?.changed_count || 0)} cambios detectados`
        : `Preview ready: ${Number(data?.changed_count || 0)} changes detected`,
      "bot"
    );
  } catch (err) {
    console.error(err);
    clearBatchApplyReview();
    appendBubble(
      `${es ? "No se pudo generar el preview del lote." : "Could not generate batch preview."} ${err?.message || ""}`.trim(),
      "error"
    );
  }
}

function isIdeaStarterSupported(item) {
  const ideaId = String(item?.id || "").trim().toLowerCase();
  return ["tests", "ci", "readme"].includes(ideaId);
}

async function applyProjectIdeaStarter(ideaId) {
  if (!state.activeProjectId) {
    appendBubble(state.lang === LANG.ES ? "No hay proyecto activo." : "No active project.", "error");
    return;
  }
  const es = state.lang === LANG.ES;
  try {
    const url = endpoints.filesApplyIdea(state.activeProjectId, String(ideaId || "").trim());
    const res = await fetchWithTimeout(
      new URL(url, location.origin).toString(),
      {
        method: "POST",
        headers: withJsonHeaders({}, "files"),
      },
      { timeout: 45000, retries: 0 }
    );
    const data = await safeJson(res);
    if (!res.ok) {
      throw new Error(data?.detail || `${res.status} ${res.statusText || ""}`.trim());
    }
    await loadProjectTree();
    appendBubble(
      es
        ? `Idea aplicada: ${String(data?.idea_id || ideaId)} (${Number(data?.applied_count || 0)} cambios)`
        : `Idea applied: ${String(data?.idea_id || ideaId)} (${Number(data?.applied_count || 0)} changes)`,
      "bot"
    );
  } catch (err) {
    console.error(err);
    appendBubble(
      `${es ? "No se pudo aplicar la idea." : "Could not apply idea."} ${err?.message || ""}`.trim(),
      "error"
    );
  }
}

async function createFolderInWorkspace() {
  if (!state.activeProjectId || state.fileViewerEditing) return;
  const es = state.lang === LANG.ES;
  const basePath = state.treeSelectionIsDir
    ? state.treeSelectionPath
    : dirnamePosix(state.treeSelectionPath || state.fileViewerPath);
  const suggestion = basePath ? `${basePath}/new_folder` : "new_folder";
  const folderPath = window.prompt(
    es ? "Ruta de la nueva carpeta" : "New folder path",
    suggestion
  );
  if (folderPath == null) return;
  const trimmed = String(folderPath || "").trim();
  if (!trimmed) {
    appendBubble(es ? "Define una ruta válida." : "Set a valid path.", "error");
    return;
  }
  try {
    const res = await fetchWithTimeout(
      endpoints.filesCreateDir,
      {
        method: "POST",
        headers: withJsonHeaders({}, "files"),
        body: JSON.stringify({
          project_id: state.activeProjectId,
          path: trimmed,
        }),
      },
      { timeout: 30000, retries: 0 }
    );
    const data = await safeJson(res);
    if (!res.ok) {
      throw new Error(data?.detail || `${res.status} ${res.statusText || ""}`.trim());
    }
    await loadProjectTree();
    setTreeSelection(trimmed, true);
    setFileViewerContent(
      "",
      es ? `Carpeta lista: ${trimmed}` : `Folder ready: ${trimmed}`
    );
    appendBubble(
      data?.created
        ? (es ? "Carpeta creada." : "Folder created.")
        : (es ? "La carpeta ya existía." : "Folder already existed."),
      "bot"
    );
  } catch (err) {
    console.error(err);
    appendBubble(
      `${es ? "No se pudo crear la carpeta." : "Could not create folder."} ${err?.message || ""}`.trim(),
      "error"
    );
  }
}

async function moveSelectedWorkspacePath() {
  if (!state.activeProjectId || state.fileViewerEditing) return;
  const es = state.lang === LANG.ES;
  const currentPath = String(state.treeSelectionPath || state.fileViewerPath || "").trim();
  if (!currentPath) {
    appendBubble(es ? "Selecciona un archivo o carpeta primero." : "Select a file or folder first.", "error");
    return;
  }
  const nextPath = window.prompt(
    es ? "Nueva ruta del archivo o carpeta" : "New file or folder path",
    currentPath
  );
  if (nextPath == null) return;
  const trimmed = String(nextPath || "").trim();
  if (!trimmed) {
    appendBubble(es ? "Define una ruta válida." : "Set a valid path.", "error");
    return;
  }
  try {
    const res = await fetchWithTimeout(
      endpoints.filesMovePath,
      {
        method: "POST",
        headers: withJsonHeaders({}, "files"),
        body: JSON.stringify({
          project_id: state.activeProjectId,
          path: currentPath,
          new_path: trimmed,
        }),
      },
      { timeout: 30000, retries: 0 }
    );
    const data = await safeJson(res);
    if (!res.ok) {
      throw new Error(data?.detail || `${res.status} ${res.statusText || ""}`.trim());
    }
    const oldPath = String(data?.path || currentPath);
    const movedPath = String(data?.new_path || trimmed);
    const movedIsDir = !!data?.is_dir;
    if (state.fileViewerPath === oldPath && !movedIsDir) {
      setFileViewerContent(movedPath, state.fileViewerContent || "");
    } else if (
      movedIsDir &&
      state.fileViewerPath &&
      (state.fileViewerPath === oldPath || state.fileViewerPath.startsWith(`${oldPath}/`))
    ) {
      setFileViewerContent(
        "",
        es ? "La vista del archivo se limpió porque la carpeta se movió." : "File view was cleared because the folder moved."
      );
    }
    await loadProjectTree();
    setTreeSelection(movedPath, movedIsDir);
    appendBubble(es ? "Ruta actualizada." : "Path updated.", "bot");
  } catch (err) {
    console.error(err);
    appendBubble(
      `${es ? "No se pudo mover la ruta." : "Could not move path."} ${err?.message || ""}`.trim(),
      "error"
    );
  }
}

async function saveFileViewer() {
  if (!state.activeProjectId || !dom.fileEditorBody) return;
  const path = state.fileViewerIsNew ? String(dom.fileEditorPath?.value || "").trim() : state.fileViewerPath;
  if (!path) {
    appendBubble(state.lang === LANG.ES ? "Define la ruta del archivo." : "Set the file path.", "error");
    return;
  }
  const content = dom.fileEditorBody.value || "";
  try {
    const res = await fetchWithTimeout(
      endpoints.filesSaveContent,
      {
        method: "POST",
        headers: withJsonHeaders({}, "files"),
        body: JSON.stringify({
          project_id: state.activeProjectId,
          path,
          content,
          create: !!state.fileViewerIsNew,
        }),
      },
      { timeout: 30000, retries: 0 }
    );
    const data = await safeJson(res);
    if (!res.ok) {
      throw new Error(data?.detail || `${res.status} ${res.statusText || ""}`.trim());
    }
    const nextPathValue = String(data?.path || path);
    setFileViewerContent(nextPathValue, content);
    await loadProjectTree();
    setTreeSelection(nextPathValue, false);
    appendBubble(
      data?.created
        ? (state.lang === LANG.ES ? "Archivo creado." : "File created.")
        : (state.lang === LANG.ES ? "Archivo guardado." : "File saved."),
      "bot"
    );
  } catch (err) {
    console.error(err);
    appendBubble(
      `${state.lang === LANG.ES ? "No se pudo guardar el archivo." : "Could not save file."} ${err?.message || ""}`.trim(),
      "error"
    );
  }
}

async function loadProjectTree() {
  if (!dom.projectTree) return;
  if (!hasAuthForScope("files")) {
    dom.projectTree.textContent = state.lang === LANG.ES
      ? "Auth requerida para explorar archivos. Configura la clave de arranque (🔑)."
      : "Auth is required to browse files. Set the bootstrap key (🔑).";
    return;
  }
  const effectiveRoot = getEffectiveProjectRoot();
  if (!state.activeProjectId && effectiveRoot) {
    try {
      await ensureCurrentRootRegistered();
    } catch (err) {
      console.warn("ensure-root-registered-failed", err);
    }
  }
  if (!state.activeProjectId && !effectiveRoot) {
    dom.projectTree.textContent = state.lang === LANG.ES
      ? "Selecciona un proyecto activo o un root manual."
      : "Select an active project or a manual root.";
    return;
  }
  if (!state.activeProjectId) {
    dom.projectTree.textContent = state.lang === LANG.ES
      ? "Selecciona un proyecto activo (no se pudo registrar el root manual)."
      : "Select an active project (could not register manual root).";
    return;
  }
  dom.projectTree.textContent = state.lang === LANG.ES ? "Cargando..." : "Loading...";

  try {
    const url = new URL(endpoints.filesTree, location.origin);
    url.searchParams.set("project_id", state.activeProjectId);

    const res = await fetchWithTimeout(url.toString(), {}, { timeout: 20000, retries: 0 });
    const data = await safeJson(res);
    if (!res.ok) {
      const detail = data?.detail || `${res.status} ${res.statusText || ""}`.trim();
      throw new Error(detail);
    }

    dom.projectTree.innerHTML = "";
    const raw = data?.tree ?? data?.items ?? data;
    const tree = Array.isArray(raw) ? raw : raw && typeof raw === "object" ? [raw] : [];

    if (!tree.length) {
      const msg = state.lang === LANG.ES ? "Carpeta vacía o sin nodos." : "Folder is empty or no nodes.";
      dom.projectTree.textContent = msg;
      console.warn("Tree is empty", { root: getEffectiveProjectRoot(), projectId: state.activeProjectId, data });
      return;
    }

    renderTree(tree, dom.projectTree, "");
  } catch (err) {
    console.error(err);
    const msg = state.lang === LANG.ES ? "No se pudo cargar el árbol." : "Could not load tree.";
    dom.projectTree.textContent = `${msg} ${err?.message || ""}`.trim();
    // Hint: if 401/403, probably falta la clave de Files/Tools.
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
    row.dataset.path = path;
    row.dataset.kind = isDir ? "dir" : "file";
    if (state.treeSelectionPath === path) row.classList.add("selected");
    const icon = el("span", { class: "icon", attrs: { "aria-hidden": "true" } });
    icon.textContent = isDir ? "📁" : "📄";
    row.appendChild(icon);
    row.appendChild(el("span", { text: name }));
    container.appendChild(row);

    if (isDir) {
      const childrenWrap = el("div", { class: "tree-children" });
      childrenWrap.style.display = "none";
      container.appendChild(childrenWrap);

      row.addEventListener("click", () => {
        setTreeSelection(path, true);
        const open = childrenWrap.style.display !== "none";
        childrenWrap.style.display = open ? "none" : "block";
      });

      if (Array.isArray(n.children) && n.children.length) {
        renderTree(n.children, childrenWrap, path);
      }
    } else {
      row.addEventListener("click", () => {
        setTreeSelection(path, false);
        loadFileContent(path);
      });
    }
  });
}

async function loadFileContent(path) {
  if (!path) return;
  if ((state.fileViewerIsNew || path !== state.fileViewerPath) && !confirmDiscardFileEdits()) {
    return;
  }
  const effectiveRoot = getEffectiveProjectRoot();
  if (!state.activeProjectId && effectiveRoot) {
    try {
      await ensureCurrentRootRegistered();
    } catch (err) {
      console.warn("ensure-root-registered-failed", err);
    }
  }
  if (!state.activeProjectId && !effectiveRoot) {
    setFileViewerContent(
      "",
      state.lang === LANG.ES
        ? "Selecciona un proyecto activo o un root manual."
        : "Select an active project or a manual root."
    );
    return;
  }
  if (!state.activeProjectId) {
    setFileViewerContent(
      "",
      state.lang === LANG.ES
        ? "Selecciona un proyecto activo (no se pudo registrar el root manual)."
        : "Select an active project (could not register manual root)."
    );
    return;
  }
  setFileViewerContent(path, state.lang === LANG.ES ? "Cargando archivo..." : "Loading file...");

  try {
    const url = new URL(endpoints.filesContent, location.origin);
    url.searchParams.set("path", path);
    url.searchParams.set("project_id", state.activeProjectId);
    const res = await fetchWithTimeout(url.toString(), {}, { timeout: 20000, retries: 0 });
    const data = await safeJson(res);
    if (!res.ok) throw new Error();

    const content = data?.content ?? (typeof data === "string" ? data : JSON.stringify(data, null, 2));
    setFileViewerContent(data?.path || path, String(content ?? ""));
  } catch (err) {
    console.error(err);
    setFileViewerContent(path, state.lang === LANG.ES ? "Error al cargar archivo." : "Error loading file.");
  }
}

async function copyFileViewer() {
  const text = state.fileViewerEditing ? (dom.fileEditorBody?.value || "") : (dom.fileViewerBody?.textContent || "");
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    appendBubble(state.lang === LANG.ES ? "Archivo copiado." : "File copied.", "bot");
  } catch {
    appendBubble(state.lang === LANG.ES ? "No se pudo copiar." : "Could not copy.", "error");
  }
}

function syncAutoIngestJob(autoIngest = null) {
  const payload = autoIngest && typeof autoIngest === "object" ? autoIngest : null;
  const jobId = String(payload?.job_id || "").trim();
  if (!jobId) return false;
  state.ingestJobId = jobId;
  if (state.ingestPollTimer) {
    clearInterval(state.ingestPollTimer);
    state.ingestPollTimer = null;
  }
  state.logJobId = jobId;
  state.logPath = null;
  state.logIsAdmin = false;
  pollIngestStatus();
  loadIngestJobs();
  return true;
}

async function uploadZipProject() {
  const files = Array.from(dom.projectUploadInput?.files || []);
  dom.projectUploadInput.value = "";
  if (!files.length) return;

  appendBubble(
    files.length > 1
      ? (state.lang === LANG.ES ? `Subiendo ${files.length} ZIPs...` : `Uploading ${files.length} ZIPs...`)
      : (state.lang === LANG.ES ? "Subiendo ZIP..." : "Uploading ZIP..."),
    "bot"
  );

  for (const f of files) {
    const fd = new FormData();
    fd.append("file", f);

    try {
      const res = await fetchWithTimeout(endpoints.filesUploadZip, { method: "POST", body: fd }, { timeout: 120000, retries: 0 });
      const data = await safeJson(res);
      if (!res.ok) throw new Error(data?.detail || "upload failed");
      appendBubble(
        files.length > 1
          ? (state.lang === LANG.ES ? `ZIP subido: ${f.name}` : `ZIP uploaded: ${f.name}`)
          : (state.lang === LANG.ES ? "ZIP subido." : "ZIP uploaded."),
        "bot"
      );
      if (data?.path) addUploadedProject(data.path, data?.project_id || null);
      if (data?.project_id) {
        await setActiveProject(String(data.project_id), {
          rootPath: data?.path || null,
          bindConversation: false,
        });
      }
      if (syncAutoIngestJob(data?.auto_ingest || data)) {
        appendBubble(
          state.lang === LANG.ES ? `Indexando proyecto en background (job ${state.ingestJobId}).` : `Project indexing in background (job ${state.ingestJobId}).`,
          "bot"
        );
      }
    } catch (err) {
      console.error(err);
      const detail = String(err?.message || "").trim();
      const suffix = detail ? ` ${detail}` : "";
      appendBubble(
        files.length > 1
          ? (state.lang === LANG.ES ? `No se pudo subir ${f.name}.${suffix}` : `Could not upload ${f.name}.${suffix}`)
          : (state.lang === LANG.ES ? `No se pudo subir el ZIP.${suffix}` : `Could not upload ZIP.${suffix}`),
        "error"
      );
    }
  }
  await loadRegisteredProjects();
  loadProjectTree();
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
      body: JSON.stringify({ repo_url: repo, branch: branch || undefined }),
    }, { timeout: 180000, retries: 0 });

    const data = await safeJson(res);
    if (!res.ok) throw new Error(data?.detail || "clone failed");
    appendBubble(state.lang === LANG.ES ? "Repo clonado." : "Repo cloned.", "bot");
    if (data?.path) addUploadedProject(data.path, data?.project_id || null);
    if (data?.project_id) {
      await setActiveProject(String(data.project_id), {
        rootPath: data?.path || null,
        bindConversation: false,
      });
    }
    if (syncAutoIngestJob(data?.auto_ingest || data)) {
      appendBubble(
        state.lang === LANG.ES ? `Indexando proyecto en background (job ${state.ingestJobId}).` : `Project indexing in background (job ${state.ingestJobId}).`,
        "bot"
      );
    }
    await loadRegisteredProjects();
    loadProjectTree();
  } catch {
    appendBubble(state.lang === LANG.ES ? "No se pudo clonar." : "Clone failed.", "error");
  }
}

async function deleteProject() {
  const es = state.lang === LANG.ES;
  const ok = window.confirm(es ? "¿Eliminar proyecto cargado?" : "Delete uploaded project?");
  if (!ok) return;

  const effectiveRoot = getEffectiveProjectRoot();
  if (!state.activeProjectId && !effectiveRoot) {
    appendBubble(es ? "No hay proyecto seleccionado." : "No project selected.", "error");
    return;
  }

  try {
    // Prefer agent-style execution (records turns + approval gate).
    if (state.conversationId) {
      const data = await executeConversationTool(
        "delete_project",
        { project_id: state.activeProjectId || undefined },
        {
          autoApprove: false,
          continueAfter: true,
          continueUseWeb: false,
          continueSynthesize: true,
          continueMaxIterations: 2,
          continueMaxTotalToolCalls: 6,
          continueMaxToolRetries: 1,
          continueToolRetryBackoffMs: 150,
        },
      );
      if (!data) return;
      const result = data?.result || data;
      appendBubble(
        result?.unregistered_only
          ? (es ? "Proyecto desvinculado del workspace." : "Project unregistered from workspace.")
          : (es ? "Proyecto eliminado." : "Project deleted."),
        "bot",
      );
      // Auto-follow through: after sensitive tool completion, ask the agent to continue using next_step.
      if (!data?.continued) {
        try {
          await handleAgentContinue({ useWeb: false, synthesize: true });
        } catch (err) {
          console.warn("agent-continue-after-delete failed", err);
        }
      }
    } else {
      const res = await fetchWithTimeout(endpoints.filesDeleteProject, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ project_id: state.activeProjectId || undefined, path: state.activeProjectId ? undefined : effectiveRoot }),
      }, { timeout: 30000, retries: 0 });

      const data = await safeJson(res);
      if (!res.ok) throw new Error(data?.detail || "delete failed");
      appendBubble(
        data?.unregistered_only
          ? (es ? "Proyecto desvinculado del workspace." : "Project unregistered from workspace.")
          : (es ? "Proyecto eliminado." : "Project deleted."),
        "bot",
      );
    }

    if (state.ingestPollTimer) {
      clearInterval(state.ingestPollTimer);
      state.ingestPollTimer = null;
    }
    state.ingestJobId = null;
    await setActiveProject("", { bindConversation: false, loadDetail: true });
    setManualProjectRoot("");
    await loadRegisteredProjects();
    loadProjectTree();
  } catch {
    appendBubble(es ? "No se pudo eliminar." : "Could not delete.", "error");
  }
}

async function startIngest() {
  appendBubble(state.lang === LANG.ES ? "Ingestando..." : "Ingesting...", "bot");
  const selection = resolveProjectSelectionState();
  const effectiveRoot = selection.rootPath || getEffectiveProjectRoot();
  const effectiveProjectId = selection.projectId || "";
  if (!effectiveProjectId && !effectiveRoot) {
    appendBubble(
      state.lang === LANG.ES
        ? "Selecciona un proyecto activo, o sube/registra un root válido primero."
        : "Select an active project, or upload/register a valid root first.",
      "error"
    );
    return;
  }
  try {
    if (effectiveProjectId && effectiveProjectId !== state.activeProjectId) {
      await setActiveProject(effectiveProjectId, {
        rootPath: effectiveRoot || null,
        bindConversation: false,
        loadDetail: false,
      });
    } else if (!state.activeProjectId) {
      await ensureCurrentRootRegistered();
    }
    const targetProjectId = String(state.activeProjectId || selection.projectId || "").trim();
    const targetRoot = targetProjectId ? "" : (effectiveRoot || "");
    const res = await fetchWithTimeout(endpoints.filesIngest, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        path: targetProjectId ? undefined : (targetRoot || undefined),
        background: true,
        project_id: targetProjectId || undefined,
      }),
    }, { timeout: 0, retries: 0 });

    const data = await safeJson(res);
    if (!res.ok) throw new Error(data?.detail || "ingest failed");
    if (data?.project_id) {
      await setActiveProject(String(data.project_id), {
        rootPath: targetRoot || effectiveRoot || null,
        bindConversation: false,
        loadDetail: false,
      });
    }

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
      state.logJobId = state.ingestJobId;
      state.logPath = null;
      state.logIsAdmin = false;
      pollIngestStatus();
    } else {
      appendBubble(state.lang === LANG.ES ? "Ingesta completada." : "Ingest finished.", "bot");
    }
    loadIngestJobs();
    await loadRegisteredProjects();
    updateStatusCenter();
  } catch {
    const currentSelection = resolveProjectSelectionState();
    const projectLabel = currentSelection.projectId || currentSelection.rootPath || (state.lang === LANG.ES ? "sin selección" : "no selection");
    appendBubble(
      state.lang === LANG.ES
        ? `No se pudo iniciar ingesta (${projectLabel}).`
        : `Could not start ingest (${projectLabel}).`,
      "error"
    );
  }
}

function pollIngestStatus() {
  if (!state.ingestJobId) return;
  if (state.ingestPollTimer) clearInterval(state.ingestPollTimer);
  loadIngestStatus();
  state.ingestPollTimer = setInterval(() => {
    if (document.hidden) return;
    loadIngestStatus();
  }, 5000);
  updateStatusCenter();
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
      await loadRegisteredProjects();
      if (state.activeProjectId) {
        await loadActiveProjectDetail(state.activeProjectId);
      }
      updateStatusCenter();
      scheduleSnapshot(900);
    }
  } catch {
    clearInterval(state.ingestPollTimer);
    state.ingestPollTimer = null;
    state.ingestJobId = null;
    dom.ingestStatusBtn?.classList.remove("active");
    if (dom.ingestStatusText) dom.ingestStatusText.textContent = state.lang === LANG.ES ? "error" : "error";
    updateStatusCenter();
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
      const status = String(j.status || j.state || "—");
      const stages = Array.isArray(j?.meta?.stages) ? j.meta.stages : [];
      const lastStage = stages.length ? stages[stages.length - 1] : null;
      const stageLabel = lastStage?.name
        ? `${lastStage.name}${lastStage.status ? ` (${lastStage.status})` : ""}`
        : "";
      const header = el("div", { class: "jobs-item-header" });
      header.appendChild(el("span", { text: j.id || "(job)" }));
      const statusToken = String(status).toLowerCase().replace(/[^a-z0-9_-]+/g, "-") || "unknown";
      header.appendChild(el("span", { class: `jobs-status ${statusToken}`, text: status }));
      li.appendChild(header);

      li.appendChild(
        el("div", {
          class: "jobs-meta",
          text: j.updated_at ? new Date(j.updated_at * 1000).toLocaleString() : "",
        })
      );

      if (stageLabel) {
        const stageLine = el("div", { class: "jobs-meta" });
        stageLine.appendChild(document.createTextNode(state.lang === LANG.ES ? "Etapa: " : "Stage: "));
        stageLine.appendChild(el("span", { text: stageLabel }));
        li.appendChild(stageLine);
      }
      li.addEventListener("click", () => {
        const id = j.id || j.job_id;
        if (!id) return;
        state.logJobId = String(id);
        state.logIsAdmin = false;
        state.logPath = null;
        if (dom.logsLiveToggle) dom.logsLiveToggle.checked = true;
        startLogsPolling();
        appendBubble(
          state.lang === LANG.ES ? `Mostrando log de ingesta (${id}).` : `Showing ingest log (${id}).`,
          "bot"
        );
      });
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
      state.logJobId = null;
    } else {
      state.logPath = null;
      state.logIsAdmin = false;
      state.logJobId = null;
    }
    // Stay on files tab so the Files/Jobs/Logs pane is not hidden.
    activateTab("files");
    if (dom.logsLiveToggle) dom.logsLiveToggle.checked = true;
    startLogsPolling();
    updateStatusCenter();
  } catch {
    appendBubble(state.lang === LANG.ES ? "No se pudo iniciar refresh." : "Could not start refresh.", "error");
  }
}

function startLogsPolling() {
  // only start if we have a source (admin log path or ingest job id)
  const hasSource = state.logIsAdmin ? state.logPath : (state.logJobId || state.ingestJobId);
  if (!hasSource) return;
  stopLogsPolling();
  state.logsTimer = setInterval(() => {
    if (document.hidden) return;
    loadLogs();
  }, 6000);
  loadLogs();
  updateStatusCenter();
}
function stopLogsPolling() {
  if (state.logsTimer) clearInterval(state.logsTimer);
  state.logsTimer = null;
  updateStatusCenter();
}

function clearLogsView() {
  stopLogsPolling();
  state.logPath = null;
  state.logIsAdmin = false;
  state.logJobId = null;
  state.ingestJobId = null;
  if (dom.logsLiveToggle) dom.logsLiveToggle.checked = false;
  if (dom.sourcesContent) dom.sourcesContent.textContent = state.lang === LANG.ES ? "Logs ocultados." : "Logs cleared.";
  if (dom.filesLogContent) {
    dom.filesLogContent.textContent = state.lang === LANG.ES
      ? "Selecciona un log (ingest/admin) para verlo aquí."
      : "Select a log (ingest/admin) to view it here.";
  }
  appendBubble(state.lang === LANG.ES ? "Logs ocultados." : "Logs hidden.", "bot");
  updateStatusCenter();
}

async function loadLogs() {
  if (!dom.sourcesContent) return;
  if (!state.logIsAdmin && !state.logJobId && !state.ingestJobId) {
    if (dom.filesLogContent) {
      dom.filesLogContent.textContent = state.lang === LANG.ES ? "Selecciona un log (ingest/admin) para verlo aquí." : "Select a log (ingest/admin) to view it here.";
    }
    return; // nothing to load
  }
  try {
    let url;
    if ((state.logPath && state.logPath.includes("refresh_")) || state.logIsAdmin) {
      url = new URL(endpoints.adminRefreshLog, location.origin);
      if (state.logPath) url.searchParams.set("path", state.logPath);
    } else {
      url = new URL(endpoints.filesIngestLog, location.origin);
      const jobId = state.logJobId || state.ingestJobId;
      if (!jobId) return;
      url.searchParams.set("job_id", jobId);
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
    if (dom.filesLogContent) {
      dom.filesLogContent.textContent = Array.isArray(lines) ? lines.join("") : String(lines ?? "");
    }
  } catch {}
}

function startAlertsPolling() {
  stopAlertsPolling();
  state.alertsTimer = setInterval(() => {
    if (document.hidden) return;
    if (!state.chartVisible && state.mode !== MODES.CRYPTO) return;
    checkAlerts();
  }, 60000);
  checkAlerts();
  updateStatusCenter();
}
function stopAlertsPolling() {
  if (state.alertsTimer) clearInterval(state.alertsTimer);
  state.alertsTimer = null;
  updateStatusCenter();
}

async function checkAlerts() {
  if (document.hidden) return;
  if (!state.chartVisible && state.mode !== MODES.CRYPTO) return;
  if (state.alertsInFlight) return;
  state.alertsInFlight = true;
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
  finally {
    state.alertsInFlight = false;
  }
}
