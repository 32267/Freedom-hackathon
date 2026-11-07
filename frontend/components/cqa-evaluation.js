import { api } from "../api.js";
import {
  CHANNEL, FLAG_LABEL, ROLE, answerLabel, critTitle, currentLang, emit, esc, fmtScore, scoreClass, stepLabel, toast,
} from "../ui.js";

const fmtTime = ts => (ts && ts.length >= 19 && ts[10] === "T" ? ts.slice(11, 19) : ts || "");
const fmtSec = s => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

class CqaEvaluation extends HTMLElement {
  async connectedCallback() {
    this.open = null;
    this.innerHTML = '<div class="cqa-empty">Загружаем диалог…</div>';
    this.addEventListener("cqa:lang", () => this.renderResult());
    try {
      let id = this.getAttribute("conversation-id");
      if (!id) id = (await api.getDialogs())[0]?.conversation_id;
      if (!id) { this.innerHTML = '<div class="cqa-empty">Диалогов пока нет — загрузите или импортируйте набор.</div>'; return; }
      const [dialog, evaluation, providers] = await Promise.all([api.getDialog(id), api.getLatestEvaluation(id), api.getProviders()]);
      this.dialog = dialog;
      this.presets = providers.presets || [];
      await this.setEvaluation(evaluation);
      this.renderShell();
      this.renderResult();
    } catch (e) { this.innerHTML = `<div class="cqa-empty">${esc(e.message)}</div>`; }
  }

  async setEvaluation(evaluation) {
    this.evaluation = evaluation;
    this.checklist = await api.getChecklist(evaluation?.checklist_id || "default", evaluation?.checklist_version || null);
    this.appeals = evaluation && !api.isMock() ? await api.getAppeals({ evaluation_id: evaluation.id }) : [];
  }

  renderShell() {
    const d = this.dialog;
    const voice = d.channel === "voice call";
    this.innerHTML = `
      <div class="cqa-page-head"><div><p class="cqa-eyebrow">КАРТОЧКА ДИАЛОГА</p>
        <h1 class="cqa-page-title">${esc(d.conversation_id)}</h1>
        <p class="cqa-subtitle">${voice ? "☎ Голосовой звонок" : "✉ Чат"} · ${esc(d.language)} · набор ${esc(d.dataset_group_id || "—")} · ${d.transcript.length} реплик</p></div>
        <div class="cqa-row"><a class="cqa-btn" href="#conversations">← К списку</a>
          <select class="cqa-select" id="preset">${this.presets.map(p => `<option value="${esc(p.id)}">${esc(p.label)}</option>`).join("")}</select>
          <button class="cqa-btn cqa-btn-primary" id="run" ${api.isMock() ? "disabled title=\"Нужен backend\"" : ""}>▶ ${this.evaluation ? "Оценить заново" : "Оценить"}</button></div></div>
      <div class="cqa-eval-layout">
        <section class="cqa-card cqa-transcript">
          <div class="cqa-transcript-head"><div><strong style="font-size:14px">Транскрипт</strong>
            <div class="cqa-panel-sub">Исходные метки времени · бот и система — контекст, оценивается оператор</div></div>
            <span class="cqa-badge">${esc(d.language)}</span></div>
          ${voice && (d.audio_src || d.audio_url) && !(d.audio_url || "").includes("example.com") ? `
            <div class="cqa-audio"><audio controls preload="metadata" id="audio" src="${esc(d.audio_src || d.audio_url)}"></audio>
            <div class="cqa-panel-sub">Клик по ▶ у реплики или по доказательству — перемотка записи на этот момент</div></div>` : ""}
          <div class="cqa-transcript-body" id="transcript">${d.transcript.map((m, i) => `
            <div class="cqa-msg ${esc(m.speaker)}" id="msg-${i}">
              <div class="cqa-msg-meta"><span class="idx">#${i}</span><span>${ROLE[m.speaker] || esc(m.speaker)}</span><span>${esc(fmtTime(m.timestamp))}</span>
                ${voice && m.offset_sec !== undefined && m.offset_sec !== null ? `<button class="seek" data-seek="${m.offset_sec}">▶ ${fmtSec(m.offset_sec)}</button>` : ""}</div>
              ${esc(m.text)}</div>`).join("")}</div>
        </section>
        <section class="cqa-card" id="result"></section>
      </div>`;
    this.querySelector("#run").addEventListener("click", () => this.run());
    this.querySelectorAll("[data-seek]").forEach(b => b.addEventListener("click", () => this.seek(Number(b.dataset.seek))));
  }

  seek(sec) {
    const audio = this.querySelector("#audio");
    if (!audio || Number.isNaN(sec)) return;
    audio.currentTime = sec;
    audio.play().catch(() => {});
  }

  goTo(index) {
    const msg = this.querySelector(`#msg-${index}`);
    if (!msg) return;
    msg.scrollIntoView({ behavior: "smooth", block: "center" });
    msg.classList.add("flash");
    setTimeout(() => msg.classList.remove("flash"), 2000);
    const off = this.dialog.transcript[index]?.offset_sec;
    if (off !== undefined && off !== null) this.seek(off);
  }

  highlightRange(range) {
    this.querySelectorAll(".cqa-msg.in-range").forEach(m => m.classList.remove("in-range"));
    if (!range) return;
    for (let i = range.from; i <= range.to; i++) this.querySelector(`#msg-${i}`)?.classList.add("in-range");
  }

  renderResult() {
    const box = this.querySelector("#result");
    if (!box) return;
    const ev = this.evaluation;
    const lang = currentLang();
    if (!ev) {
      box.innerHTML = `<div class="cqa-empty" style="padding:60px 20px"><div style="font-size:34px">◎</div>
        <p><strong>Диалог ещё не оценён</strong></p><p>Выберите оценщика и нажмите «Оценить» — результат появится здесь через 15–40 секунд.</p></div>`;
      return;
    }
    const crit = new Map(this.checklist.criteria.map(c => [c.id, c]));
    const sections = new Map((this.checklist.sections || []).map(s => [s.id, s.name]));
    const total = ev.total_score;
    const invalid = ev.results.filter(r => r.validated === false);
    const appealed = ev.original_total !== undefined && ev.original_total !== null && ev.original_total !== total;
    box.innerHTML = `
      <div class="cqa-score-hero">
        <div class="cqa-ring" style="--p:${total ?? 0};--ring:${total >= 85 ? "var(--fb-green)" : total >= 60 ? "#f0a020" : "var(--red)"}">
          <div class="cqa-ring-inner"><div><b class="${scoreClass(total)}">${fmtScore(total)}</b><small>из 100</small></div></div></div>
        <div>
          <div style="font-weight:700;font-size:15px">Итоговый балл ${appealed ? `<span class="cqa-badge cqa-badge-info">после апелляции: было ${fmtScore(ev.original_total)}</span>` : ""}</div>
          <div class="cqa-panel-sub">Чек-лист v${ev.checklist_version} · ${esc(ev.model || "")} · ответов: ${ev.samples || 1}${ev.cost_usd ? ` · ≈ $${Number(ev.cost_usd).toFixed(4)}` : ""}</div>
          <div class="cqa-sections">${(ev.section_scores || []).map(s => `<span class="cqa-section-chip">${esc(sections.get(s.section_id) || s.section_id)}<b class="${scoreClass(s.score)}">${fmtScore(s.score)}</b></span>`).join("")}</div>
        </div>
      </div>
      ${ev.critical_error ? `<div class="cqa-alert cqa-alert-danger"><strong>⚠ Грубая ошибка:</strong> ${(ev.critical_flags || []).map(f => esc(FLAG_LABEL[f] || f)).join(", ") || "отмечена"}.
        Флаг фиксируется отдельно и не снижает балл по правилам чек-листа.</div>` : ""}
      ${ev.needs_review ? '<div class="cqa-alert cqa-alert-warn">⚑ Оценщики разошлись по отмеченным критериям — проверьте их или подайте апелляцию.</div>' : ""}
      ${invalid.length ? `<div class="cqa-alert cqa-alert-warn">Не все доказательства прошли автоматическую проверку: ${invalid.map(r => esc(critTitle(crit.get(r.criterion_id) || { id: r.criterion_id, title: r.criterion_id }, lang))).join(", ")}.</div>` : ""}
      ${api.isMock() ? '<div class="cqa-alert cqa-alert-info">Демо-режим: оценка взята из тестовых данных, а не от модели.</div>' : ""}
      <div class="cqa-criteria">${ev.results.map(r => this.criterionHtml(r, crit.get(r.criterion_id), lang)).join("")}</div>`;
    box.querySelectorAll("[data-crit]").forEach(b => b.addEventListener("click", () => {
      this.open = this.open === b.dataset.crit ? null : b.dataset.crit;
      this.renderResult();
    }));
    box.querySelectorAll("[data-msg]").forEach(b => b.addEventListener("click", () => this.goTo(Number(b.dataset.msg))));
    box.querySelectorAll("[data-range]").forEach(b => b.addEventListener("click", () => {
      const [from, to] = b.dataset.range.split("-").map(Number);
      this.highlightRange({ from, to });
      this.goTo(from);
    }));
    box.querySelector("[data-appeal]")?.addEventListener("click", () => this.submitAppeal());
    const openRes = ev.results.find(r => r.criterion_id === this.open);
    this.highlightRange(openRes?.checked_range || null);
  }

  criterionHtml(r, c, lang) {
    c = c || { id: r.criterion_id, title: r.criterion_id, answer_type: "binary" };
    const ans = answerLabel(r, c);
    const open = this.open === r.criterion_id;
    const appeal = this.appeals.find(a => a.criterion_id === r.criterion_id && a.status === "open");
    const decided = this.appeals.filter(a => a.criterion_id === r.criterion_id && a.status !== "open");
    const explanation = r.explanations?.[lang] || r.explanation || "";
    const naReason = r.na_reasons?.[lang] || r.na_reason;
    const points = c.answer_type === "flag" ? "без баллов"
      : r.answer === "na" ? "вес → другим" : `${fmtScore(r.weighted_score ?? 0)} / ${fmtScore(r.effective_weight ?? r.weight ?? 0)}`;
    const step = c.answer_type === "scale" && r.answer !== "na" ? stepLabel(c, r.answer) : "";
    return `<div class="cqa-crit ${open ? "open" : ""}">
      <button class="cqa-crit-head" data-crit="${esc(r.criterion_id)}">
        <div><div class="cqa-crit-title">${esc(critTitle(c, lang))}
          ${r.needs_review ? ' <span class="cqa-badge cqa-badge-warn">⚑ расхождение</span>' : ""}
          ${appeal ? ' <span class="cqa-badge cqa-badge-info">апелляция</span>' : ""}
          ${r.source === "appeal" ? ' <span class="cqa-badge cqa-badge-success">решение проверяющего</span>' : ""}</div>
          <div class="cqa-crit-sub">${c.answer_type === "scale" ? `шкала ${c.scale?.min ?? 0}–${c.scale?.max}` : c.answer_type === "flag" ? "флаг" : "да / нет"}${c.na_allowed ? " · допускает Н/П" : ""} · вес ${c.weight}</div></div>
        <span class="cqa-answer ${ans.cls}">${ans.text}</span><span class="cqa-pts">${points}</span>
      </button>
      ${open ? `<div class="cqa-crit-body">
        ${step ? `<h4>СТУПЕНЬ ШКАЛЫ</h4><div><b>${esc(r.answer)}</b> — ${esc(step)}</div>` : ""}
        <h4>ОБОСНОВАНИЕ (${lang.toUpperCase()})</h4><div>${esc(explanation) || '<span class="cqa-faint">нет</span>'}</div>
        ${r.answer === "na" ? `<h4>ПОЧЕМУ Н/П</h4><div>${esc(naReason || "не указано")}</div>` : ""}
        ${(r.flags || []).length ? `<h4>ВИД НАРУШЕНИЯ</h4><div>${r.flags.map(f => `<span class="cqa-badge cqa-badge-danger">${esc(FLAG_LABEL[f] || f)}</span>`).join(" ")}</div>` : ""}
        <h4>ДОКАЗАТЕЛЬСТВА</h4>
        ${(r.evidence || []).map(e => `<button class="cqa-quote" data-msg="${e.msg_index}"><small>Реплика #${e.msg_index} · ${ROLE[this.dialog.transcript[e.msg_index]?.speaker] || ""} · ${esc(fmtTime(this.dialog.transcript[e.msg_index]?.timestamp))} — перейти ↗</small>«${esc(e.quote)}»</button>`).join("")
          || '<div class="cqa-faint">Цитаты не приложены</div>'}
        ${r.checked_range ? `<button class="cqa-quote" style="border-left-color:#f0a020" data-range="${r.checked_range.from}-${r.checked_range.to}">
          <small>Действие пропущено — проверенный участок разговора</small>Реплики #${r.checked_range.from}–#${r.checked_range.to} (подсвечены в транскрипте)</button>` : ""}
        ${(r.votes || []).length > 1 ? `<h4>ГОЛОСА ОЦЕНЩИКОВ · СОГЛАСИЕ ${Math.round((r.agreement ?? 1) * 100)}%</h4><div class="cqa-votes">${r.votes.map(v =>
          `<span class="cqa-badge ${String(v.answer) === String(r.answer) ? "cqa-badge-success" : "cqa-badge-warn"}">${esc(v.provider || v.model)}: ${esc(answerLabel(v, c).text)}</span>`).join("")}</div>` : ""}
        ${decided.map(a => `<div class="cqa-history">Апелляция: «${esc(a.comment)}»<br>
          Решение: <b>${a.status === "changed" ? "изменено" : "подтверждено"}</b> · было <b>${esc(answerLabel({ answer: a.original.answer }, c).text)}</b>
          ${a.status === "changed" ? `→ стало <b>${esc(answerLabel({ answer: a.decision.answer }, c).text)}</b>` : ""} · причина: ${esc(a.decision.reason)}<br>
          Итог диалога: ${fmtScore(a.original.total_score)} → <b>${fmtScore(a.final?.total_score)}</b></div>`).join("")}
        ${appeal ? `<div class="cqa-appeal-box"><b>Апелляция на рассмотрении</b><div class="cqa-panel-sub">«${esc(appeal.comment)}» — решение примет проверяющий в разделе «Апелляции».</div></div>`
          : api.isMock() ? "" : `<div class="cqa-appeal-box"><b style="font-size:13px">Оспорить оценку</b>
            <textarea class="cqa-textarea" id="appeal-text" placeholder="Почему оценка неверна? Например: оператор представился во второй реплике #5" style="margin-top:8px"></textarea>
            <div class="cqa-row" style="margin-top:8px;justify-content:flex-end"><button class="cqa-btn cqa-btn-primary cqa-btn-sm" data-appeal>Подать апелляцию</button></div></div>`}
      </div>` : ""}
    </div>`;
  }

  async submitAppeal() {
    const comment = this.querySelector("#appeal-text")?.value.trim();
    if (!comment) { toast("Напишите комментарий к апелляции", true); return; }
    try {
      await api.createAppeal({ evaluation_id: this.evaluation.id, criterion_id: this.open, comment });
      this.appeals = await api.getAppeals({ evaluation_id: this.evaluation.id });
      toast("Апелляция подана — она появилась в очереди проверяющего");
      emit(this, "appeals-changed", {});
      this.renderResult();
    } catch (e) { toast(e.message, true); }
  }

  async run() {
    const button = this.querySelector("#run");
    const p = this.presets.find(x => x.id === this.querySelector("#preset").value) || {};
    button.disabled = true;
    button.textContent = "Оцениваем… 15–40 с";
    try {
      const ev = await api.runEvaluation({ conversation_id: this.dialog.conversation_id, checklist_id: "default",
        providers: p.providers || undefined, samples: p.samples || undefined });
      await this.setEvaluation(ev);
      this.open = null;
      this.renderResult();
      toast(`Оценка готова: ${fmtScore(ev.total_score)} из 100`);
    } catch (e) { toast(e.message, true); }
    button.disabled = false;
    button.textContent = "▶ Оценить заново";
  }
}
customElements.define("cqa-evaluation", CqaEvaluation);
