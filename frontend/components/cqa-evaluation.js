import { api } from "../api.js";

const roleLabels = { operator: "Оператор", client: "Клиент", bot: "Бот", system: "Система" };
const criterionAnswer = result => result.answer === "yes" ? "Да" : result.answer === "no" ? "Нет" : result.answer === "na" ? "Н/П" : result.answer;
class CqaEvaluation extends HTMLElement {
  async connectedCallback() {
    this.language = "ru"; this.selectedCriterion = null; this.evaluation = null;
    this.innerHTML = '<div class="cqa-empty">Загружаем диалог…</div>';
    try {
      const dialogs = await api.getDialogs();
      this.dialog = await api.getDialog(this.getAttribute("conversation-id") || dialogs[0]?.conversation_id);
      this.evaluation = await api.getEvaluation(null, this.dialog.conversation_id);
      this.checklist = await api.getChecklist();
      this.providers = await api.getProviders();
      this.render();
    } catch(error) { this.innerHTML = `<div class="cqa-empty">${error.message}</div>`; }
  }
  render() {
    const dialog = this.dialog, evaluation = this.evaluation;
    const total = evaluation?.total_score;
    this.innerHTML = `
      <div class="cqa-page-head"><div><p class="cqa-eyebrow">ПРОВЕРКА КАЧЕСТВА</p><h1 class="cqa-page-title">Оценка диалога</h1><p class="cqa-subtitle">${dialog.conversation_id} · ${dialog.channel === "voice call" ? "Голосовой звонок" : "Чат"} · ${dialog.language}</p></div><div class="cqa-eval-controls"><select class="cqa-select" id="provider"><option value="compare">Сравнить модели</option><option value="claude_cli">Claude</option><option value="codex_cli">Codex</option><option value="local">Своя модель</option></select><button class="cqa-btn cqa-btn-primary" id="run">▶ Запустить оценку</button></div></div>
      <div class="cqa-eval-head"><div class="cqa-eval-controls"><span class="cqa-badge ${evaluation ? "cqa-badge-success" : "cqa-badge-neutral"}">${evaluation ? "Оценка загружена" : "Ожидает оценки"}</span><span class="cqa-muted" style="font-size:10px">Чек-лист: ${this.checklist.name} · v${this.checklist.version}</span></div><div class="cqa-language" aria-label="Язык объяснений"><button data-lang="ru" class="active">RU</button><button data-lang="kz">KZ</button><button data-lang="en">EN</button></div></div>
      <div class="cqa-eval-grid">
        <section class="cqa-column"><div class="cqa-card cqa-panel"><div class="cqa-panel-head"><div><h2 class="cqa-panel-title">Транскрипт</h2><div class="cqa-panel-sub">${dialog.transcript.length} реплик · исходные отметки времени</div></div><span class="cqa-badge cqa-badge-neutral">${dialog.language}</span></div>
          ${dialog.audio_url ? `<audio controls preload="none" src="${dialog.audio_url}" style="width:100%;margin-bottom:14px"></audio>` : ""}
          <div class="cqa-transcript">${dialog.transcript.map((message,index) => `<article class="cqa-message ${message.speaker}" id="msg-${message.msg_index ?? index}"><div class="cqa-message-meta"><span class="cqa-message-role">${roleLabels[message.speaker] || message.speaker}</span><span>${message.timestamp}</span></div><div class="cqa-message-text">${this.escape(message.text)}</div></article>`).join("")}</div>
        </div></section>
        <section class="cqa-column"><div class="cqa-card cqa-panel"><div class="cqa-panel-head"><div><h2 class="cqa-panel-title">Критерии оценки</h2><div class="cqa-panel-sub">8 критериев · вес перераспределяется для Н/П</div></div></div>
          ${evaluation ? `<div class="cqa-score-summary"><div class="cqa-score-big">${total ?? "—"}<small style="font-size:12px;color:#929bad"> / 100</small></div><div><div style="font-size:11px;font-weight:700">Итоговый балл</div><div class="cqa-score-caption">Источник: ${evaluation.model || "mock"} · ${evaluation.samples || 1} образец(а)</div></div></div>` : '<div class="cqa-validation" style="margin:0 0 10px">Оценка ещё не запускалась. Нажмите «Запустить оценку», чтобы получить демонстрационный результат.</div>'}
          <div id="criteria-list">${this.checklist.criteria.map(criterion => {
            const result = evaluation?.results?.find(item => item.criterion_id === criterion.id);
            const max = criterion.scale?.max || 1;
            const score = result ? (result.answer === "na" ? null : criterion.answer_type === "scale" ? Number(result.answer) : result.answer === "yes" ? 1 : 0) : null;
            const pct = score === null ? 0 : Math.max(0,Math.min(100,score/max*100));
            return `<div class="cqa-criterion"><div class="cqa-criterion-head"><span class="cqa-criterion-name">${criterion.title}</span><span class="cqa-criterion-score">${result ? criterionAnswer(result) + (criterion.answer_type === "scale" ? "/" + max : "") : "—"}</span></div><p class="cqa-criterion-desc">${criterion.description}</p><div class="cqa-progress"><span style="width:${pct}%"></span></div><div class="cqa-criterion-foot"><span class="cqa-muted" style="font-size:9px">Вес: ${criterion.weight}% ${result?.answer === "na" ? "· Н/П" : ""}</span><button class="cqa-text-button" data-criterion="${criterion.id}">Подробнее →</button></div></div>`;
          }).join("")}</div>
          ${evaluation?.critical_error ? '<div class="cqa-validation" style="background:#fff0f1;color:#b52f42">Обнаружена грубая ошибка. Флаг отображается отдельно и не уменьшает балл при текущей политике чек-листа.</div>' : ""}
        </div></section>
        <section class="cqa-column"><div class="cqa-card cqa-panel"><div class="cqa-panel-head"><div><h2 class="cqa-panel-title">Доказательства</h2><div class="cqa-panel-sub">Цитата из исходного транскрипта</div></div></div><div id="evidence-content"><div class="cqa-empty" style="padding:24px 8px">Выберите критерий, чтобы посмотреть объяснение и доказательства.</div></div>
          ${evaluation?.needs_review ? '<div class="cqa-validation">Модели разошлись в оценке одного или нескольких критериев. Требуется проверка человеком.</div>' : ""}
          ${evaluation?.results?.some(r => r.validated === false) ? '<div class="cqa-validation">Некоторые доказательства не прошли автоматическую проверку. Проверьте отмеченные критерии.</div>' : ""}
          <div class="cqa-footer-note">В демо-режиме результат основан на фикстуре и не является выводом подключённой LLM.</div>
        </div></section>
      </div>`;
    this.querySelectorAll("[data-lang]").forEach(button => button.addEventListener("click", () => { this.language = button.dataset.lang; this.querySelectorAll("[data-lang]").forEach(b => b.classList.toggle("active", b === button)); if (this.selectedCriterion) this.showEvidence(this.selectedCriterion); }));
    this.querySelectorAll("[data-criterion]").forEach(button => button.addEventListener("click", () => { this.selectedCriterion = button.dataset.criterion; this.showEvidence(this.selectedCriterion); }));
    this.querySelector("#run").addEventListener("click", () => this.run());
    if (this.evaluation?.results?.length) { this.selectedCriterion = this.evaluation.results[0].criterion_id; this.showEvidence(this.selectedCriterion); }
  }
  showEvidence(id) {
    const criterion = this.checklist.criteria.find(item => item.id === id);
    const result = this.evaluation?.results?.find(item => item.criterion_id === id);
    const panel = this.querySelector("#evidence-content");
    if (!criterion || !panel) return;
    const explanation = result?.explanations?.[this.language] || result?.explanation || "Для этого критерия пока нет объяснения.";
    const naReason = result?.na_reasons?.[this.language] || result?.na_reason;
    panel.innerHTML = `<div style="font-size:11px;font-weight:700;color:#303b51">${criterion.title}</div><div style="font-size:10px;color:#7d8799;line-height:1.6;margin:9px 0">${this.escape(explanation)}</div>${result?.answer === "na" ? `<div class="cqa-validation">Причина Н/П: ${this.escape(naReason || "Не указана")}</div>` : ""}${(result?.evidence || []).map(item => `<button class="cqa-evidence-quote" data-message="${item.msg_index}" style="display:block;width:100%;text-align:left;border:0;cursor:pointer">“${this.escape(item.quote)}”<span style="display:block;color:#898fa0;font-size:9px;margin-top:7px">Перейти к реплике #${item.msg_index} ↗</span></button>`).join("") || '<div class="cqa-evidence-quote">Доказательства не приложены.</div>'}<div style="margin-top:12px"><span class="cqa-badge ${result?.validated === false ? "cqa-badge-warning" : "cqa-badge-success"}">${result ? (result.validated === false ? "Не проверено" : "Валидация пройдена") : "Ожидает оценки"}</span></div>`;
    panel.querySelectorAll("[data-message]").forEach(button => button.addEventListener("click", () => {
      const message = this.querySelector(`#msg-${button.dataset.message}`);
      if (message) { message.scrollIntoView({ behavior:"smooth", block:"center" }); message.classList.add("evidence-highlight"); setTimeout(() => message.classList.remove("evidence-highlight"), 2000); }
    }));
  }
  async run() {
    const button = this.querySelector("#run");
    button.disabled = true; button.textContent = "Оценка…";
    try {
      const provider = this.querySelector("#provider").value;
      this.evaluation = await api.runEvaluation({ conversation_id:this.dialog.conversation_id, checklist_id:this.checklist.id, providers:provider, samples:3 });
      this.render();
      const notice = document.createElement("div"); notice.className = "cqa-toast"; notice.textContent = api.isMock() ? "Демо-оценка загружена" : "Запрос на оценку отправлен"; document.body.append(notice); setTimeout(() => notice.remove(), 2500);
    } catch(error) { button.disabled = false; button.textContent = "▶ Запустить оценку"; alert(error.message); }
  }
  escape(value) { return String(value ?? "").replace(/[&<>"']/g, char => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[char])); }
}
customElements.define("cqa-evaluation", CqaEvaluation);
