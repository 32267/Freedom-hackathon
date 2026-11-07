import { api } from "../api.js";

class CqaDashboard extends HTMLElement {
  async connectedCallback() {
    this.innerHTML = `<div class="cqa-page-head"><div><p class="cqa-eyebrow">АНАЛИТИКА КАЧЕСТВА</p><h1 class="cqa-page-title">Обзор</h1><p class="cqa-subtitle">Сводка по диалогам и результатам оценки операторов.</p></div><button class="cqa-btn cqa-btn-primary" id="new-eval">＋ Новая оценка</button></div><div id="dashboard-content"><div class="cqa-empty">Загружаем данные…</div></div>`;
    this.querySelector("#new-eval").addEventListener("click", () => { window.location.hash = "conversations"; });
    try { await this.renderData(); } catch (error) { this.querySelector("#dashboard-content").innerHTML = `<div class="cqa-empty">${error.message}</div>`; }
  }
  escape(value) { return String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;"); }
  async renderData() {
    const dialogs = await api.getDialogs();
    const evaluated = dialogs.filter(d => d.total_score !== null);
    const average = evaluated.length ? (evaluated.reduce((sum,d) => sum + d.total_score,0) / evaluated.length).toFixed(1) : "—";
    const needsReview = evaluated.filter(d => d.needs_review || d.critical_error).length;
    const content = this.querySelector("#dashboard-content");
    content.innerHTML = `
      <div class="cqa-grid cqa-kpis">
        <article class="cqa-card cqa-kpi"><div class="cqa-kpi-top">Всего диалогов <span class="cqa-kpi-icon">▤</span></div><div class="cqa-kpi-value">${dialogs.length}</div><div class="cqa-kpi-note">В доступной выборке</div></article>
        <article class="cqa-card cqa-kpi"><div class="cqa-kpi-top">Средний балл <span class="cqa-kpi-icon">◉</span></div><div class="cqa-kpi-value">${average}<small style="font-size:12px;color:#929bad"> / 100</small></div><div class="cqa-kpi-note">По завершённым оценкам</div></article>
        <article class="cqa-card cqa-kpi"><div class="cqa-kpi-top">Нужна проверка <span class="cqa-kpi-icon">⚑</span></div><div class="cqa-kpi-value">${needsReview}</div><div class="cqa-kpi-note">Расхождения и проблемы валидации</div></article>
        <article class="cqa-card cqa-kpi"><div class="cqa-kpi-top">Оценено <span class="cqa-kpi-icon">✓</span></div><div class="cqa-kpi-value">${evaluated.length}</div><div class="cqa-kpi-note">Из ${dialogs.length} диалогов</div></article>
      </div>
      <div class="cqa-grid cqa-dashboard-grid">
        <section class="cqa-card cqa-panel"><div class="cqa-panel-head"><div><h2 class="cqa-panel-title">Оценки по выборке</h2><div class="cqa-panel-sub">Демонстрационный обзор баллов</div></div><span class="cqa-badge cqa-badge-neutral">Последние диалоги</span></div>
<div class="cqa-empty cqa-chart-empty">График появится после накопления реальных оценок с датами. Сейчас доступна только небольшая демонстрационная выборка.</div><div class="cqa-legend"><span>Средний балл</span></div>
        </section>
        <section class="cqa-card cqa-panel"><div class="cqa-panel-head"><div><h2 class="cqa-panel-title">Языки диалогов</h2><div class="cqa-panel-sub">Распределение текущей выборки</div></div></div>
          ${["RU","KZ","EN"].map(language => { const count = dialogs.filter(d => d.language === language).length; const percent = dialogs.length ? count/dialogs.length*100 : 0; return `<div class="cqa-bar-row"><span>${language}</span><div class="cqa-bar-track"><div class="cqa-bar-fill" style="width:${percent}%"></div></div><strong>${count}</strong></div>`; }).join("")}
          <div class="cqa-footer-note">Данные на этом экране обновляются из API. В демо-режиме используется небольшой набор фикстур.</div>
        </section>
      </div>
      <section class="cqa-card cqa-panel" style="margin-top:16px"><div class="cqa-panel-head"><div><h2 class="cqa-panel-title">Последние диалоги</h2><div class="cqa-panel-sub">Быстрый переход к транскрипту и оценке</div></div><button class="cqa-btn" id="all-dialogs">Все диалоги →</button></div>
        <div class="cqa-table-wrap"><table class="cqa-table"><thead><tr><th>ДИАЛОГ</th><th>КАНАЛ</th><th>ЯЗЫК</th><th>СООБЩЕНИЯ</th><th>БАЛЛ</th><th>СТАТУС</th><th></th></tr></thead><tbody>${dialogs.map(d => `<tr><td class="cqa-id">${this.escape(d.conversation_id)}</td><td>${d.channel === "voice call" ? "Звонок" : "Чат"}</td><td>${this.escape(d.language)}</td><td>${d.transcript.length}</td><td class="cqa-score">${d.total_score ?? "—"}</td><td><span class="cqa-badge ${d.total_score === null ? "cqa-badge-neutral" : "cqa-badge-success"}">${d.total_score === null ? "Не оценён" : "Оценён"}</span></td><td><button class="cqa-link" data-id="${this.escape(d.conversation_id)}">Открыть</button></td></tr>`).join("")}</tbody></table></div>
      </section>`;
    content.querySelector("#all-dialogs").addEventListener("click", () => window.location.hash = "conversations");
    content.querySelectorAll("[data-id]").forEach(button => button.addEventListener("click", () => window.location.hash = `evaluation/${encodeURIComponent(button.dataset.id)}`));
  }
}
customElements.define("cqa-dashboard", CqaDashboard);
