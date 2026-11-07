import { api } from "../api.js";
import { ROLE, answerLabel, critTitle, currentLang, emit, esc, fmtScore, stepLabel, toast } from "../ui.js";

function answerOptions(c) {
  const opts = c.answer_type === "scale"
    ? c.scale.steps.map(s => ({ value: String(s.value), label: `${s.value} — ${s.label}` }))
    : c.answer_type === "flag"
      ? [{ value: "yes", label: "Есть нарушение" }, { value: "no", label: "Нарушения нет" }]
      : [{ value: "yes", label: "Да" }, { value: "no", label: "Нет" }];
  if (c.na_allowed) opts.push({ value: "na", label: "Н/П — неприменимо" });
  return opts;
}

class CqaReviewQueue extends HTMLElement {
  async connectedCallback() {
    this.tab = "open";
    this.innerHTML = `
      <div class="cqa-page-head"><div><p class="cqa-eyebrow">ПРОВЕРКА СПОРНЫХ ОЦЕНОК</p><h1 class="cqa-page-title">Апелляции</h1>
        <p class="cqa-subtitle">Проверяющий видит спорную оценку, комментарий и фрагмент диалога, подтверждает или меняет оценку с указанием причины.</p></div>
        <div class="cqa-lang"><button data-tab="open">Открытые</button><button data-tab="closed">Решённые</button></div></div>
      <div id="list"><div class="cqa-empty">Загрузка…</div></div>`;
    this.querySelectorAll("[data-tab]").forEach(b => b.addEventListener("click", () => { this.tab = b.dataset.tab; this.load(); }));
    this.addEventListener("cqa:lang", () => this.render());
    if (api.isMock()) {
      this.querySelector("#list").innerHTML = '<div class="cqa-card cqa-empty">Апелляции работают с backend. Демо-режим их не хранит.</div>';
      return;
    }
    this.checklist = await api.getChecklist();
    await this.load();
  }

  async load() {
    this.querySelectorAll("[data-tab]").forEach(b => b.classList.toggle("active", b.dataset.tab === this.tab));
    try {
      const all = await api.getAppeals();
      this.items = this.tab === "open" ? all.filter(a => a.status === "open") : all.filter(a => a.status !== "open");
      this.render();
    } catch (e) { this.querySelector("#list").innerHTML = `<div class="cqa-empty">${esc(e.message)}</div>`; }
  }

  render() {
    const list = this.querySelector("#list");
    if (!this.items) return;
    if (!this.items.length) {
      list.innerHTML = `<div class="cqa-card cqa-empty">${this.tab === "open"
        ? "Открытых апелляций нет. Подать апелляцию можно в карточке диалога: раскройте критерий → «Оспорить оценку»."
        : "Решённых апелляций пока нет."}</div>`;
      return;
    }
    const lang = currentLang();
    const crit = new Map(this.checklist.criteria.map(c => [c.id, c]));
    list.innerHTML = this.items.map(a => {
      const c = crit.get(a.criterion_id) || { id: a.criterion_id, title: a.criterion_id, answer_type: "binary" };
      const r = a.result || {};
      const ev = new Set((r.evidence || []).map(e => e.msg_index));
      const orig = answerLabel({ answer: a.original.answer }, c);
      return `<article class="cqa-card cqa-appeal-card" data-id="${esc(a.id)}">
        <div class="cqa-row"><div class="cqa-grow">
          <div style="font-weight:700;font-size:15px">${esc(critTitle(c, lang))}</div>
          <div class="cqa-panel-sub">Диалог <button class="cqa-link cqa-id" data-open="${esc(a.conversation_id)}">${esc(a.conversation_id)}</button> · подана ${esc((a.created_at || "").slice(0, 16).replace("T", " "))}</div></div>
          <span class="cqa-badge ${a.status === "open" ? "cqa-badge-info" : a.status === "changed" ? "cqa-badge-warn" : "cqa-badge-success"}">${a.status === "open" ? "Ожидает решения" : a.status === "changed" ? "Оценка изменена" : "Оценка подтверждена"}</span></div>
        <div class="cqa-grid" style="grid-template-columns:repeat(auto-fit,minmax(240px,1fr));margin-top:12px">
          <div><div class="cqa-label">СПОРНАЯ ОЦЕНКА</div>
            <div class="cqa-row"><span class="cqa-answer ${orig.cls}">${orig.text}</span>
              <span class="cqa-muted" style="font-size:12px">${c.answer_type === "scale" ? esc(stepLabel(c, a.original.answer)) : ""} · итог диалога ${fmtScore(a.original.total_score)}</span></div>
            <div class="cqa-label" style="margin-top:12px">ОБОСНОВАНИЕ МОДЕЛИ</div>
            <div style="font-size:12.8px;line-height:1.5">${esc(r.explanations?.[lang] || r.explanation || "")}</div></div>
          <div><div class="cqa-label">КОММЕНТАРИЙ АПЕЛЛЯЦИИ</div>
            <div class="cqa-alert cqa-alert-info" style="margin:0">«${esc(a.comment)}»</div></div>
        </div>
        <div class="cqa-label" style="margin-top:12px">ФРАГМЕНТ ДИАЛОГА</div>
        <div class="cqa-fragment">${(a.fragment || []).map(m => `<div class="cqa-msg ${esc(m.speaker)} ${ev.has(m.msg_index) ? "flash" : ""}">
          <div class="cqa-msg-meta"><span class="idx">#${m.msg_index}</span><span>${ROLE[m.speaker] || esc(m.speaker)}</span></div>${esc(m.text)}</div>`).join("")}</div>
        ${a.status === "open" ? `
          <div class="cqa-row" style="align-items:flex-start;margin-top:6px">
            <div><div class="cqa-label">РЕШЕНИЕ</div>
              <select class="cqa-select" data-action><option value="confirm">Подтвердить оценку</option><option value="change">Изменить оценку</option></select></div>
            <div data-answer-wrap hidden><div class="cqa-label">НОВАЯ ОЦЕНКА</div>
              <select class="cqa-select" data-answer>${answerOptions(c).filter(o => o.value !== String(a.original.answer)).map(o => `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join("")}</select></div>
            <div class="cqa-grow"><div class="cqa-label">ПРИЧИНА (ОБЯЗАТЕЛЬНО)</div>
              <textarea class="cqa-textarea" data-reason style="min-height:40px" placeholder="Например: в реплике #3 оператор назвал имя"></textarea></div>
          </div>
          <div class="cqa-row" style="justify-content:flex-end;margin-top:8px"><button class="cqa-btn cqa-btn-primary" data-decide>Сохранить решение</button></div>`
        : `<div class="cqa-history" style="margin-top:10px">Решение: <b>${a.status === "changed" ? "изменено" : "подтверждено"}</b>
            ${a.status === "changed" ? `· было <b>${orig.text}</b> → стало <b>${esc(answerLabel({ answer: a.decision?.answer }, c).text)}</b>` : ""}
            · причина: ${esc(a.decision?.reason)}<br>
            <span class="cqa-diff">Итог диалога: ${fmtScore(a.original.total_score)} <span class="arrow">→</span> <span>${fmtScore(a.final?.total_score)}</span></span></div>`}
      </article>`;
    }).join("");

    list.querySelectorAll("[data-open]").forEach(b => b.addEventListener("click", () => emit(this, "open-dialog", { conversationId: b.dataset.open })));
    list.querySelectorAll("article").forEach(card => {
      const action = card.querySelector("[data-action]");
      action?.addEventListener("change", () => { card.querySelector("[data-answer-wrap]").hidden = action.value !== "change"; });
      card.querySelector("[data-decide]")?.addEventListener("click", () => this.decide(card));
    });
  }

  async decide(card) {
    const action = card.querySelector("[data-action]").value;
    const reason = card.querySelector("[data-reason]").value.trim();
    if (!reason) { toast("Укажите причину решения", true); return; }
    const body = { action, reason, ...(action === "change" ? { answer: card.querySelector("[data-answer]").value } : {}) };
    try {
      const res = await api.decideAppeal(card.dataset.id, body);
      const before = res.appeal.original.total_score;
      toast(`Решение сохранено. Итог диалога: ${fmtScore(before)} → ${fmtScore(res.evaluation.total_score)}`);
      emit(this, "appeals-changed", {});
      await this.load();
    } catch (e) { toast(e.message, true); }
  }
}
customElements.define("cqa-review-queue", CqaReviewQueue);
