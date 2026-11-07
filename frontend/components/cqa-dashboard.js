import { api } from "../api.js";

class CqaDashboard extends HTMLElement {
  async connectedCallback() {
    this.innerHTML = `<div class="cqa-page-head"><div><p class="cqa-eyebrow">АНАЛИТИКА КАЧЕСТВА</p><h1 class="cqa-page-title">Обзор</h1><p class="cqa-subtitle">Сводка по диалогам и результатам оценки операторов.</p></div><button class="cqa-btn cqa-btn-primary" id="new-eval">＋ Новая оценка</button></div><div id="dashboard-content"><div class="cqa-empty">Загружаем данные…</div></div>`;
    this.querySelector("#new-eval").addEventListener("click", () => { window.location.hash = "conversations"; });
    try { await this.renderData(); } catch (error) { this.querySelector("#dashboard-content").innerHTML = `<div class="cqa-empty">${error.message}</div>`; }
  }
  async renderData() {
    const dialogs = await api.getDialogs();
    const evaluated = dialogs.filter(d => d.total_score !== null);
    const average = evaluated.length ? (evaluated.reduce((sum,d) => sum + d.total_score,0) / evaluated.length).toFixed(1) : "—";
    const needsReview = evaluated.filter(d => d.evaluation_status === "needs_review").length;
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
          <svg class="cqa-chart" viewBox="0 0 620 210" preserveAspectRatio="none" role="img" aria-label="График демонстрационных оценок">
            <g stroke="#edf0f5" stroke-width="1"><path d="M42 25H606 M42 70H606 M42 115H606 M42 160H606"/></g>
            <g><text x="4" y="28">100</text><text x="12" y="73">75</text><text x="12" y="118">50</text><text x="12" y="163">25</text></g>
            <path d="M42 160 L130 112 L218 92 L306 105 L394 65 L482 80 L570 45 L606 55 L606 184 L42 184Z" fill="#7770ed" opacity=".09"/>
            <path d="M42 160 L130 112 L218 92 L306 105 L394 65 L482 80 L570 45 L606 55" fill="none" stroke="#7067ed" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
            <g fill="#fff" stroke="#7067ed" stroke-width="2"><circle cx="42" cy="160" r="4"/><circle cx="130" cy="112" r="4"/><circle cx="218" cy="92" r="4"/><circle cx="306" cy="105" r="4"/><circle cx="394" cy="65" r="4"/><circle cx="482" cy="80" r="4"/><circle cx="570" cy="45" r="4"/></g>
            <g><text x="35" y="202">Пн</text><text x="123" y="202">Вт</text><text x="211" y="202">Ср</text><text x="299" y="202">Чт</text><text x="387" y="202">Пт</text><text x="475" y="202">Сб</text><text x="563" y="202">Вс</text></g>
          </svg><div class="cqa-legend"><span>Средний балл</span></div>
        </section>
        <section class="cqa-card cqa-panel"><div class="cqa-panel-head"><div><h2 class="cqa-panel-title">Языки диалогов</h2><div class="cqa-panel-sub">Распределение текущей выборки</div></div></div>
          ${["RU","KZ","EN"].map(language => { const count = dialogs.filter(d => d.language === language).length; const percent = dialogs.length ? count/dialogs.length*100 : 0; return `<div class="cqa-bar-row"><span>${language}</span><div class="cqa-bar-track"><div class="cqa-bar-fill" style="width:${percent}%"></div></div><strong>${count}</strong></div>`; }).join("")}
          <div class="cqa-footer-note">Данные на этом экране обновляются из API. В демо-режиме используется небольшой набор фикстур.</div>
        </section>
      </div>
      <section class="cqa-card cqa-panel" style="margin-top:16px"><div class="cqa-panel-head"><div><h2 class="cqa-panel-title">Последние диалоги</h2><div class="cqa-panel-sub">Быстрый переход к транскрипту и оценке</div></div><button class="cqa-btn" id="all-dialogs">Все диалоги →</button></div>
        <div class="cqa-table-wrap"><table class="cqa-table"><thead><tr><th>ДИАЛОГ</th><th>КАНАЛ</th><th>ЯЗЫК</th><th>СООБЩЕНИЯ</th><th>БАЛЛ</th><th>СТАТУС</th><th></th></tr></thead><tbody>${dialogs.map(d => `<tr><td class="cqa-id">${d.conversation_id}</td><td>${d.channel === "voice call" ? "Звонок" : "Чат"}</td><td>${d.language}</td><td>${d.transcript.length}</td><td class="cqa-score">${d.total_score ?? "—"}</td><td><span class="cqa-badge ${d.total_score === null ? "cqa-badge-neutral" : "cqa-badge-success"}">${d.total_score === null ? "Не оценён" : "Оценён"}</span></td><td><button class="cqa-link" data-id="${d.conversation_id}">Открыть</button></td></tr>`).join("")}</tbody></table></div>
      </section>`;
    content.querySelector("#all-dialogs").addEventListener("click", () => window.location.hash = "conversations");
    content.querySelectorAll("[data-id]").forEach(button => button.addEventListener("click", () => window.location.hash = `evaluation/${encodeURIComponent(button.dataset.id)}`));
  }
}
customElements.define("cqa-dashboard", CqaDashboard);
