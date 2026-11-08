import { api } from "../api.js";
import { CHANNEL, emit, esc, fmtScore, scoreClass } from "../ui.js";

class CqaOperators extends HTMLElement {
  async connectedCallback() {
    this.open = null;
    this.innerHTML = `
      <div class="cqa-page-head"><div><p class="cqa-eyebrow">РЕЙТИНГ</p><h1 class="cqa-page-title">Операторы</h1>
        <p class="cqa-subtitle">Средняя оценка звонков и чатов каждого оператора. Имя берётся из разговора (если оператор представился)
          или задаётся вручную в карточке диалога.</p></div></div>
      <section class="cqa-card"><div class="cqa-table-wrap"><table class="cqa-table">
        <thead><tr><th>#</th><th>ОПЕРАТОР</th><th>ДИАЛОГОВ</th><th style="width:34%">СРЕДНИЙ БАЛЛ</th><th>ГРУБЫЕ ОШИБКИ</th><th>НА ПРОВЕРКУ</th><th>ОТКРЫТЫХ ВОПРОСОВ</th></tr></thead>
        <tbody id="rows"><tr><td colspan="7"><div class="cqa-empty">Загрузка…</div></td></tr></tbody></table></div></section>`;
    try {
      this.rows = await api.getOperators();
      this.render();
    } catch (e) { this.querySelector("#rows").innerHTML = `<tr><td colspan="7"><div class="cqa-empty">${esc(e.message)}</div></td></tr>`; }
  }

  render() {
    const body = this.querySelector("#rows");
    if (!this.rows.length) {
      body.innerHTML = `<tr><td colspan="7"><div class="cqa-empty">${api.isMock() ? "Рейтинг работает с backend." : "Пока нет оценённых диалогов с известным оператором."}</div></td></tr>`;
      return;
    }
    body.innerHTML = this.rows.map(r => `
      <tr class="clickable" data-op="${esc(r.operator)}">
        <td class="cqa-score">${r.rank <= 3 ? ["🥇", "🥈", "🥉"][r.rank - 1] : r.rank}</td>
        <td><b>${esc(r.operator)}</b></td><td>${r.count}</td>
        <td><div class="cqa-row" style="flex-wrap:nowrap"><div class="cqa-bar-track cqa-grow"><div class="cqa-bar-fill ${r.average < 60 ? "bad" : r.average < 85 ? "warn" : ""}" style="width:${r.average}%"></div></div>
          <span class="cqa-score ${scoreClass(r.average)}" style="min-width:48px;text-align:right">${fmtScore(r.average)}</span></div></td>
        <td>${r.critical ? `<span class="cqa-badge cqa-badge-danger">${r.critical}</span>` : "—"}</td>
        <td>${r.review || "—"}</td><td>${r.open_issues || "—"}</td></tr>
      ${this.open === r.operator ? `<tr><td></td><td colspan="6"><div class="cqa-row" style="gap:6px">${r.dialogs.map(d => `
        <button class="cqa-btn cqa-btn-sm" data-dialog="${esc(d.conversation_id)}">${esc(d.conversation_id)} · ${CHANNEL[d.channel] || ""} ·
          <span class="${scoreClass(d.total_score)}">${fmtScore(d.total_score)}</span></button>`).join("")}</div></td></tr>` : ""}`).join("");
    body.querySelectorAll("[data-op]").forEach(tr => tr.addEventListener("click", () => {
      this.open = this.open === tr.dataset.op ? null : tr.dataset.op;
      this.render();
    }));
    body.querySelectorAll("[data-dialog]").forEach(b => b.addEventListener("click", e => {
      e.stopPropagation();
      emit(this, "open-dialog", { conversationId: b.dataset.dialog });
    }));
  }
}
customElements.define("cqa-operators", CqaOperators);
