const params = new URLSearchParams(window.location.search);
const MOCK_MODE = params.get("mock") === "1";
const API_BASE = document.querySelector("cqa-app")?.getAttribute("api-base") || "/api";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options
  });
  if (!response.ok) throw new Error(`Ошибка API: ${response.status}`);
  return response.status === 204 ? null : response.json();
}

async function fixture(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Не удалось загрузить демо-данные: ${path}`);
  return response.json();
}

let mockData;
async function loadMockData() {
  if (!mockData) {
    const [chat, call, evaluation, checklist] = await Promise.all([
      fixture("../fixtures/dialog.chat.json"),
      fixture("../fixtures/dialog.call.json"),
      fixture("../fixtures/evaluation.chat.json"),
      fixture("../checklists/default.json")
    ]);
    const dialogs = [chat, call];
    mockData = { dialogs, evaluations: [evaluation], checklist };
  }
  return mockData;
}

export const api = {
  isMock: () => MOCK_MODE,
  async getChecklist() {
    return MOCK_MODE ? (await loadMockData()).checklist : request("/checklists/default");
  },
  async getDialogs(filters = {}) {
    if (!MOCK_MODE) {
      const query = new URLSearchParams(Object.entries(filters).filter(([,v]) => v));
      return request(`/dialogs?${query}`);
    }
    const data = await loadMockData();
    return data.dialogs.filter(dialog =>
      (!filters.language || dialog.language === filters.language) &&
      (!filters.channel || dialog.channel === filters.channel) &&
      (!filters.search || JSON.stringify(dialog).toLowerCase().includes(filters.search.toLowerCase()))
    ).map(dialog => {
      const evaluation = data.evaluations.find(item => item.conversation_id === dialog.conversation_id);
      return { ...dialog, total_score: evaluation?.total_score ?? null, evaluation_status: evaluation ? "done" : "not_started", critical_error: evaluation?.critical_error ?? false };
    });
  },
  async getDialog(id) {
    if (MOCK_MODE) return (await loadMockData()).dialogs.find(item => item.conversation_id === id) || (await loadMockData()).dialogs[0];
    return request(`/dialogs/${encodeURIComponent(id)}`);
  },
  async getEvaluation(id, conversationId) {
    if (MOCK_MODE) {
      const data = await loadMockData();
      const found = data.evaluations.find(item => item.id === id || item.conversation_id === conversationId);
      return found ? { ...found, conversation_id: conversationId || found.conversation_id } : null;
    }
    return request(`/evaluations/${encodeURIComponent(id)}`);
  },
  async runEvaluation(payload) {
    if (MOCK_MODE) {
      const data = await loadMockData();
      const base = data.evaluations[0];
      return { ...base, id: `ev_demo_${Date.now()}`, conversation_id: payload.conversation_id, status: "done", model: "mock", needs_review: false, results: base.results.map(result => ({ ...result })) };
    }
    return request("/evaluations", { method: "POST", body: JSON.stringify(payload) });
  },
  async getProviders() {
    if (MOCK_MODE) return { providers: [{ id: "claude_cli", label: "Claude", available: false, reason: "Демо-режим" }, { id: "codex_cli", label: "Codex", available: false, reason: "Демо-режим" }, { id: "local", label: "Своя модель", available: false, reason: "Подключение появится позже" }], presets: [{ id: "compare", label: "Сравнить модели", providers: ["claude_cli", "codex_cli"], samples: 3 }] };
    return request("/llm/providers");
  }
};
