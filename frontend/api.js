// Единственное место с fetch. Живой режим — /api (FastAPI), демо — ?mock=1 (fixtures, только чтение).
const params = new URLSearchParams(window.location.search);
const MOCK_MODE = params.get("mock") === "1";

function apiBase() {
  return document.querySelector("cqa-app")?.getAttribute("api-base") || "/api";
}

async function request(path, options = {}) {
  const response = await fetch(`${apiBase()}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (!response.ok) {
    let detail = "";
    try { detail = (await response.json())?.error || ""; } catch { /* тело не JSON */ }
    const error = new Error(detail || `Ошибка API: ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return response.status === 204 ? null : response.json();
}

const post = (path, body) => request(path, { method: "POST", body: JSON.stringify(body ?? {}) });
const put = (path, body) => request(path, { method: "PUT", body: JSON.stringify(body ?? {}) });
const enc = encodeURIComponent;

// ---------- демо-режим ----------
let mockData;
async function fixture(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Не удалось загрузить демо-данные: ${path}`);
  return response.json();
}
async function mock() {
  if (!mockData) {
    const [chat, call, evChat, evCall, checklist] = await Promise.all([
      fixture("../fixtures/dialog.chat.json"), fixture("../fixtures/dialog.call.json"),
      fixture("../fixtures/evaluation.chat.json"), fixture("../fixtures/evaluation.call.json"),
      fixture("../checklists/default.json"),
    ]);
    mockData = { dialogs: [chat, call], evaluations: [evChat, evCall], checklist };
  }
  return mockData;
}
function demoOnly() {
  throw new Error("В демо-режиме действие недоступно — запустите backend (uvicorn backend.main:app).");
}
function summarize(dialog, ev) {
  return {
    ...dialog,
    transcript: dialog.transcript.map((m, i) => ({ ...m, msg_index: i })),
    turns: dialog.transcript.length,
    evaluation_id: ev?.id ?? null,
    evaluation_status: ev ? "done" : "not_started",
    total_score: ev?.total_score ?? null,
    critical_error: Boolean(ev?.critical_error),
    critical_flags: ev?.critical_flags || [],
    needs_review: Boolean(ev?.needs_review),
  };
}

export const api = {
  isMock: () => MOCK_MODE,

  // диалоги
  async getDialogs(filters = {}) {
    if (!MOCK_MODE) {
      const query = new URLSearchParams(Object.entries(filters).filter(([, v]) => v));
      return request(`/dialogs?${query}`);
    }
    const d = await mock();
    const s = (filters.search || "").toLowerCase();
    return d.dialogs
      .filter(x => (!filters.language || x.language === filters.language) && (!filters.channel || x.channel === filters.channel)
        && (!s || JSON.stringify(x).toLowerCase().includes(s)))
      .map(x => summarize(x, d.evaluations.find(e => e.conversation_id === x.conversation_id)));
  },
  async getDialog(id) {
    if (!MOCK_MODE) return request(`/dialogs/${enc(id)}`);
    const d = await mock();
    const dialog = d.dialogs.find(x => x.conversation_id === id) || d.dialogs[0];
    return summarize(dialog, d.evaluations.find(e => e.conversation_id === dialog.conversation_id));
  },
  uploadDialogs: payload => (MOCK_MODE ? demoOnly() : post("/dialogs/upload", payload)),
  importDataset: groupId => (MOCK_MODE ? demoOnly() : post(`/datasets/${enc(groupId)}/import`)),

  // оценки
  async getLatestEvaluation(conversationId) {
    if (MOCK_MODE) return (await mock()).evaluations.find(e => e.conversation_id === conversationId) || null;
    try {
      return await request(`/dialogs/${enc(conversationId)}/evaluation`);
    } catch (error) {
      if (error.status === 404) return null;
      throw error;
    }
  },
  getEvaluation: id => request(`/evaluations/${enc(id)}`),
  runEvaluation: payload => (MOCK_MODE ? demoOnly() : post("/evaluations", payload)),
  runBatch: payload => (MOCK_MODE ? demoOnly() : post("/evaluations/batch", payload)),
  getJob: id => request(`/jobs/${enc(id)}`),

  // чек-листы
  async getChecklist(id = "default", version = null) {
    if (MOCK_MODE) return (await mock()).checklist;
    return request(`/checklists/${enc(id)}${version ? `?version=${version}` : ""}`);
  },
  saveChecklist: checklist => (MOCK_MODE ? demoOnly() : put(`/checklists/${enc(checklist.id)}`, checklist)),

  // апелляции
  async getAppeals(filters = {}) {
    if (MOCK_MODE) return [];
    const query = new URLSearchParams(Object.entries(filters).filter(([, v]) => v));
    return request(`/appeals?${query}`);
  },
  createAppeal: payload => (MOCK_MODE ? demoOnly() : post("/appeals", payload)),
  decideAppeal: (id, payload) => (MOCK_MODE ? demoOnly() : post(`/appeals/${enc(id)}/decision`, payload)),

  // сводка и оценщики
  async getStats() {
    if (!MOCK_MODE) return request("/stats");
    const d = await mock();
    const scores = d.evaluations.map(e => e.total_score).filter(v => v !== null);
    return {
      dialogs: d.dialogs.length, evaluated: d.evaluations.length,
      average: scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : null,
      needs_review: d.evaluations.filter(e => e.needs_review).length,
      critical: d.evaluations.filter(e => e.critical_error).length, open_appeals: 0,
      groups: d.dialogs.map(x => ({ channel: x.channel, language: x.language, count: 1,
        average: d.evaluations.find(e => e.conversation_id === x.conversation_id)?.total_score ?? 0 })),
      criteria: [], critical_flags: {},
    };
  },
  async getProviders() {
    if (!MOCK_MODE) return request("/llm/providers");
    return {
      providers: [],
      presets: [{ id: "default", label: "Демо-данные", providers: null, samples: null }],
      default: {},
    };
  },
};
