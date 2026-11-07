import { api } from "../api.js";
import { CHANNEL, FLAG_LABEL, critTitle, emit, esc, fmtScore, scoreClass } from "../ui.js";

class CqaDashboard extends HTMLElement {
  async connectedCallback() {
    this.innerHTML = `
      <div class="cqa-page-head"><div><p class="cqa-eyebrow">FREEDOM BROKER · АНАЛИТИКА КАЧЕСТВА</p>
        <h1 class="cqa-page-title">Обзор</h1><p class="cqa-subtitle">Качество работы операторов в чатах и звонках по чек-листу Freedom Broker.</p></div>
        <div class="cqa-row"><a class="cqa-btn" href="#appeals">⚖ Очередь апелляций</a><a class="cqa-btn cqa-btn-primary" href="#conversations">Перейти к диалогам →</a></div></div>
      <div id="body"><div class="cqa-empty">Загружаем данные…</div></div>`;
    try { await this.render(); } catch (e) { this.querySelector("#body").innerHTML = `<div class="cqa-empty">${esc(e.message)}</div>`; }
  }

  async render() {
    const [stats, dialogs, checklist] = await Promise.all([api.getStats(), api.getDialogs(), api.getChecklist()]);
    const crit = new Map(checklist.criteria.map(c => [c.id, c]));
    const failing = (stats.criteria || [])
      .filter(c => crit.get(c.criterion_id)?.answer_type !== "flag")
      .map(c => ({ ...c, rate: c.total - c.na ? c.lost / (c.total - c.na) : 0 }))
      .sort((a, b) => b.rate - a.rate);
    const worst = dialogs.filter(d => d.total_score !== null).sort((a, b) => a.total_score - b.total_score).slice(0, 8);
    const flags = Object.entries(stats.critical_flags || {});

    this.querySelector("#body").innerHTML = `
      <div class="cqa-grid cqa-kpis">
        <article class="cqa-card cqa-kpi accent"><div class="cqa-kpi-top">Средний балл <span>◉</span></div>
          <div class="cqa-kpi-value">${fmtScore(stats.average)}<small> / 100</small></div><div class="cqa-kpi-note">по ${stats.evaluated} оценённым диалогам</div></article>
        <article class="cqa-card cqa-kpi"><div class="cqa-kpi-top">Диалогов <span>☰</span></div>
          <div class="cqa-kpi-value">${stats.dialogs}</div><div class="cqa-kpi-note">оценено ${stats.evaluated} из ${stats.dialogs}</div></article>
        <article class="cqa-card cqa-kpi"><div class="cqa-kpi-top">Грубые ошибки <span>⚠</span></div>
          <div class="cqa-kpi-value ${stats.critical ? "score-bad" : ""}">${stats.critical}</div><div class="cqa-kpi-note">флаг не снижает балл, отмечается отдельно</div></article>
        <article class="cqa-card cqa-kpi"><div class="cqa-kpi-top">На проверку <span>⚑</span></div>
          <div class="cqa-kpi-value">${stats.needs_review}</div><div class="cqa-kpi-note">модели разошлись · апелляций открыто: ${stats.open_appeals}</div></article>
      </div>
      <div class="cqa-grid cqa-two">
        <section class="cqa-card cqa-panel">
          <div class="cqa-panel-head"><div><h2 class="cqa-panel-title">Где операторы теряют баллы</h2>
            <div class="cqa-panel-sub">Доля диалогов с неполным баллом по критерию (без Н/П)</div></div></div>
          ${failing.length ? failing.map(c => `<div class="cqa-bar-row"><span title="${esc(crit.get(c.criterion_id)?.title)}">${esc(critTitle(crit.get(c.criterion_id) || { id: c.criterion_id, title: c.criterion_id }))}</span>
            <div class="cqa-bar-track"><div class="cqa-bar-fill ${c.rate > .5 ? "bad" : c.rate > .25 ? "warn" : ""}" style="width:${Math.round(c.rate * 100)}%"></div></div>
            <strong>${Math.round(c.rate * 100)}%</strong></div>`).join("") : '<div class="cqa-empty">Нет оценённых диалогов</div>'}
        </section>
        <section class="cqa-card cqa-panel">
          <div class="cqa-panel-head"><div><h2 class="cqa-panel-title">Средний балл по каналам и языкам</h2>
            <div class="cqa-panel-sub">Последняя оценка каждого диалога</div></div></div>
          ${(stats.groups || []).map(g => `<div class="cqa-bar-row"><span>${CHANNEL[g.channel] || esc(g.channel)} · ${esc(g.language)} <span class="cqa-faint">(${g.count})</span></span>
            <div class="cqa-bar-track"><div class="cqa-bar-fill ${g.average < 60 ? "bad" : g.average < 85 ? "warn" : ""}" style="width:${g.average}%"></div></div>
            <strong class="${scoreClass(g.average)}">${fmtScore(g.average)}</strong></div>`).join("") || '<div class="cqa-empty">Нет данных</div>'}
          ${flags.length ? `<h3 style="font-size:13px;margin:18px 0 6px">Грубые ошибки по видам</h3>${flags.map(([f, n]) =>
            `<span class="cqa-badge cqa-badge-danger">${esc(FLAG_LABEL[f] || f)}: ${n}</span>`).join(" ")}` : ""}
        </section>
      </div>
      <section class="cqa-card" style="margin-top:16px">
        <div class="cqa-panel cqa-panel-head" style="margin:0"><div><h2 class="cqa-panel-title">Диалоги с самым низким баллом</h2>
          <div class="cqa-panel-sub">Начните разбор с них</div></div><a class="cqa-btn" href="#conversations">Все диалоги →</a></div>
        <div class="cqa-table-wrap"><table class="cqa-table"><thead><tr><th>ДИАЛОГ</th><th>КАНАЛ</th><th>ЯЗЫК</th><th>БАЛЛ</th><th>ОТМЕТКИ</th></tr></thead>
          <tbody>${worst.map(d => `<tr class="clickable" data-open="${esc(d.conversation_id)}"><td class="cqa-id">${esc(d.conversation_id)}</td>
            <td>${CHANNEL[d.channel] || esc(d.channel)}</td><td>${esc(d.language)}</td>
            <td class="cqa-score ${scoreClass(d.total_score)}">${fmtScore(d.total_score)}</td>
            <td>${d.critical_error ? '<span class="cqa-badge cqa-badge-danger">Грубая ошибка</span>' : ""}${d.needs_review ? '<span class="cqa-badge cqa-badge-warn">На проверку</span>' : ""}</td></tr>`).join("")
            || '<tr><td colspan="5"><div class="cqa-empty">Пока нет оценок</div></td></tr>'}</tbody></table></div>
      </section>`;
    this.querySelectorAll("[data-open]").forEach(r => r.addEventListener("click", () => emit(this, "open-dialog", { conversationId: r.dataset.open })));
  }
}
customElements.define("cqa-dashboard", CqaDashboard);
