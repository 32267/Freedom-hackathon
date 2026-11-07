import { api } from "../api.js";
import { CHANNEL, confirmDialog, emit, esc, fmtScore, scoreClass, toast, trackJob } from "../ui.js";

class CqaDialogList extends HTMLElement {
  async connectedCallback() {
    this.innerHTML = `
      <div class="cqa-page-head"><div><p class="cqa-eyebrow">БАЗА ДИАЛОГОВ</p><h1 class="cqa-page-title">Диалоги</h1>
        <p class="cqa-subtitle">Чаты и звонки клиентов Freedom Broker: загрузка, импорт набора и пакетная оценка.</p></div>
        <div class="cqa-row">
          <label class="cqa-btn" title="JSON одного диалога, списка или ответа API организаторов">⤒ Загрузить JSON<input type="file" accept=".json,application/json" id="file" hidden></label>
          <button class="cqa-btn" id="import">⇣ Импорт набора</button>
        </div></div>
      <div class="cqa-card cqa-panel" style="margin-bottom:14px">
        <div class="cqa-row">
          <strong class="cqa-grow" style="font-size:13.5px">Оценка</strong>
          <span class="cqa-muted" style="font-size:12px">Оценщик</span><select class="cqa-select" id="preset"></select>
          <button class="cqa-btn" id="eval-selected">Оценить выбранные</button>
          <button class="cqa-btn" id="eval-missing">Оценить неоценённые</button>
          <button class="cqa-btn cqa-btn-primary" id="eval-all">Переоценить все</button>
        </div>
        <div class="cqa-panel-sub" style="margin-top:8px">«Неоценённые» — диалоги без оценки по текущей версии чек-листа. После смены критерия используйте её, чтобы применить новый чек-лист.</div>
      </div>
      <div class="cqa-toolbar">
        <input class="cqa-input cqa-search" id="search" placeholder="Поиск по ID или тексту реплик…">
        <select class="cqa-select" id="language"><option value="">Все языки</option><option value="RU">Русский</option><option value="KZ">Қазақша</option><option value="EN">English</option></select>
        <select class="cqa-select" id="channel"><option value="">Все каналы</option><option value="agent chat">Чат</option><option value="voice call">Звонок</option></select>
        <select class="cqa-select" id="status"><option value="">Любой статус</option><option value="done">Оценён</option><option value="not_started">Не оценён</option><option value="review">На проверку</option><option value="critical">Грубая ошибка</option></select>
        <select class="cqa-select" id="group"><option value="">Все наборы</option></select>
      </div>
      <section class="cqa-card"><div class="cqa-table-wrap"><table class="cqa-table">
        <thead><tr><th><input type="checkbox" id="all" aria-label="Выбрать все"></th><th>ДИАЛОГ</th><th>НАБОР</th><th>КАНАЛ</th><th>ЯЗЫК</th><th>РЕПЛИК</th><th>БАЛЛ</th><th>СТАТУС</th><th></th></tr></thead>
        <tbody id="rows"><tr><td colspan="9"><div class="cqa-empty">Загрузка…</div></td></tr></tbody></table></div>
        <div class="cqa-panel-sub" style="padding:12px 16px" id="count"></div></section>`;

    this.querySelectorAll("#search,#language,#channel,#status,#group").forEach(c => c.addEventListener("input", () => this.load()));
    this.querySelector("#all").addEventListener("change", e => this.querySelectorAll(".row-check").forEach(b => { b.checked = e.target.checked; }));
    this.querySelector("#file").addEventListener("change", e => this.upload(e.target.files[0]));
    this.querySelector("#import").addEventListener("click", () => this.importSet());
    this.querySelector("#eval-selected").addEventListener("click", () => this.batch("selected"));
    this.querySelector("#eval-missing").addEventListener("click", () => this.batch("missing"));
    this.querySelector("#eval-all").addEventListener("click", () => this.batch("all"));
    this.onBatchDone = () => this.load();
    document.querySelector("cqa-app")?.addEventListener("cqa:batch-done", this.onBatchDone);

    try {
      const p = await api.getProviders();
      this.querySelector("#preset").innerHTML = p.presets.map(x => `<option value="${esc(x.id)}">${esc(x.label)}</option>`).join("");
      this.presets = p.presets;
    } catch { this.presets = []; }
    await this.load();
  }

  disconnectedCallback() {
    document.querySelector("cqa-app")?.removeEventListener("cqa:batch-done", this.onBatchDone);
  }

  async load() {
    const filters = { search: this.querySelector("#search").value, language: this.querySelector("#language").value,
      channel: this.querySelector("#channel").value, group_id: this.querySelector("#group").value };
    const rows = this.querySelector("#rows");
    try {
      let dialogs = await api.getDialogs(filters);
      if (!filters.group_id && !this.groupsFilled) {
        const groups = [...new Set(dialogs.map(d => d.dataset_group_id).filter(Boolean))];
        this.querySelector("#group").innerHTML = '<option value="">Все наборы</option>'
          + groups.map(g => `<option>${esc(g)}</option>`).join("");
        this.groupsFilled = true;
      }
      const status = this.querySelector("#status").value;
      if (status === "review") dialogs = dialogs.filter(d => d.needs_review);
      else if (status === "critical") dialogs = dialogs.filter(d => d.critical_error);
      else if (status) dialogs = dialogs.filter(d => d.evaluation_status === status);
      this.querySelector("#all").checked = false;
      rows.innerHTML = dialogs.length ? dialogs.map(d => `<tr>
          <td><input class="row-check" type="checkbox" value="${esc(d.conversation_id)}" aria-label="Выбрать"></td>
          <td><button class="cqa-link cqa-id" data-open="${esc(d.conversation_id)}">${esc(d.conversation_id)}</button></td>
          <td class="cqa-muted">${esc(d.dataset_group_id || "—")}</td>
          <td>${d.channel === "voice call" ? "☎ Звонок" : "✉ Чат"}</td><td>${esc(d.language)}</td><td>${d.turns ?? d.transcript.length}</td>
          <td class="cqa-score ${scoreClass(d.total_score)}">${fmtScore(d.total_score)}</td>
          <td>${d.evaluation_status === "done" ? '<span class="cqa-badge cqa-badge-success">Оценён</span>' : '<span class="cqa-badge">Не оценён</span>'}
            ${d.critical_error ? '<span class="cqa-badge cqa-badge-danger">Грубая ошибка</span>' : ""}
            ${d.needs_review ? '<span class="cqa-badge cqa-badge-warn">На проверку</span>' : ""}</td>
          <td><button class="cqa-link" data-open="${esc(d.conversation_id)}">Открыть →</button></td></tr>`).join("")
        : '<tr><td colspan="9"><div class="cqa-empty">Диалоги не найдены — измените фильтры.</div></td></tr>';
      this.querySelector("#count").textContent = `Показано: ${dialogs.length}`;
      this.visible = dialogs;
      rows.querySelectorAll("[data-open]").forEach(b => b.addEventListener("click", () => emit(this, "open-dialog", { conversationId: b.dataset.open })));
    } catch (e) { rows.innerHTML = `<tr><td colspan="9"><div class="cqa-empty">${esc(e.message)}</div></td></tr>`; }
  }

  preset() {
    const p = (this.presets || []).find(x => x.id === this.querySelector("#preset").value) || {};
    return { providers: p.providers || undefined, samples: p.samples || undefined };
  }

  async batch(mode) {
    const p = this.preset();
    let body;
    if (mode === "selected") {
      const ids = [...this.querySelectorAll(".row-check:checked")].map(b => b.value);
      if (!ids.length) { toast("Отметьте диалоги галочками"); return; }
      body = { conversation_ids: ids, only_missing: false };
    } else {
      const group = this.querySelector("#group").value;
      body = { ...(group ? { group_id: group } : {}), only_missing: mode === "missing" };
      if (mode === "all" && !(await confirmDialog(`<h3>Переоценить все диалоги${group ? ` набора ${esc(group)}` : ""}?</h3>
        <p class="cqa-muted" style="font-size:13px">Каждый диалог отправится оценщику заново. Это займёт время и расход модели.</p>`))) return;
    }
    try {
      const job = await api.runBatch({ ...body, checklist_id: "default", ...p });
      if (!job.total) { toast("Нечего оценивать — всё уже оценено по текущему чек-листу"); return; }
      trackJob(job, `Оценка: ${job.total} диалог(ов)`);
    } catch (e) { toast(e.message, true); }
  }

  async upload(file) {
    if (!file) return;
    try {
      const data = JSON.parse(await file.text());
      const res = await api.uploadDialogs(data);
      toast(`Загружено диалогов: ${res.imported}`);
      this.groupsFilled = false;
      await this.load();
    } catch (e) { toast(e instanceof SyntaxError ? "Файл не является JSON" : e.message, true); }
    this.querySelector("#file").value = "";
  }

  async importSet() {
    const modal = await confirmDialog(`<h3>Импорт набора организаторов</h3>
      <p class="cqa-muted" style="font-size:13px">Укажите group_id: DEV или значение для контрольного набора.</p>
      <input class="cqa-input" id="gid" value="DEV" autocomplete="off">
      <label class="cqa-row" style="margin-top:10px;font-size:13px"><input type="checkbox" id="then-eval" checked> Сразу оценить импортированные диалоги</label>`);
    if (!modal) return;
    const gid = modal.querySelector("#gid").value.trim();
    const thenEval = modal.querySelector("#then-eval").checked;
    if (!gid) return;
    try {
      const res = await api.importDataset(gid);
      toast(`Импортировано ${res.imported} диалог(ов) из ${res.group_id}`);
      this.groupsFilled = false;
      await this.load();
      if (thenEval) {
        const job = await api.runBatch({ group_id: gid, checklist_id: "default", only_missing: true, ...this.preset() });
        if (job.total) trackJob(job, `Оценка набора ${gid}`);
      }
    } catch (e) { toast(e.message, true); }
  }
}
customElements.define("cqa-dialog-list", CqaDialogList);
