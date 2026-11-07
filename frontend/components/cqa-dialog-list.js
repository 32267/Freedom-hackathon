import { api } from "../api.js";

class CqaDialogList extends HTMLElement {
  async connectedCallback() {
    this.innerHTML = `<div class="cqa-page-head"><div><p class="cqa-eyebrow">БАЗА ДИАЛОГОВ</p><h1 class="cqa-page-title">Диалоги</h1><p class="cqa-subtitle">Поиск, фильтрация и запуск оценки качества.</p></div><button class="cqa-btn cqa-btn-primary" id="evaluate-visible">Оценить выбранный</button></div>
      <div class="cqa-toolbar"><label class="cqa-search"><input id="search" placeholder="Поиск по ID или тексту диалога…"></label><select class="cqa-select" id="language"><option value="">Все языки</option><option value="RU">Русский</option><option value="KZ">Қазақша</option><option value="EN">English</option></select><select class="cqa-select" id="channel"><option value="">Все каналы</option><option value="agent chat">Чат</option><option value="voice call">Звонок</option></select><select class="cqa-select" id="status"><option value="">Любой статус</option><option value="done">Оценён</option><option value="not_started">Не оценён</option></select></div>
      <section class="cqa-card cqa-table-card"><div class="cqa-table-wrap"><table class="cqa-table"><thead><tr><th><input type="checkbox" id="select-all" aria-label="Выбрать все"></th><th>ДИАЛОГ</th><th>ПЕРВАЯ РЕПЛИКА</th><th>КАНАЛ</th><th>ЯЗЫК</th><th>СООБЩЕНИЯ</th><th>БАЛЛ</th><th>СТАТУС</th><th></th></tr></thead><tbody id="dialog-rows"></tbody></table></div><div class="cqa-panel-sub" style="padding:14px 16px" id="dialog-count"></div></section>`;
    this.rows = this.querySelector("#dialog-rows");
    this.querySelectorAll("#search,#language,#channel,#status").forEach(control => control.addEventListener("input", () => this.load()));
    this.querySelector("#select-all").addEventListener("change", event => this.querySelectorAll(".dialog-check").forEach(box => box.checked = event.target.checked));
    this.querySelector("#evaluate-visible").addEventListener("click", () => {
      const selected = [...this.querySelectorAll(".dialog-check:checked")][0];
      if (!selected) { this.toast("Выберите диалог для оценки"); return; }
      window.location.hash = `evaluation/${encodeURIComponent(selected.value)}`;
    });
    await this.load();
  }
  escape(value) { return String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;"); }
  async load() {
    const filters = { search: this.querySelector("#search").value, language: this.querySelector("#language").value, channel: this.querySelector("#channel").value };
    try {
      let dialogs = await api.getDialogs(filters);
      const status = this.querySelector("#status").value;
      if (status) dialogs = dialogs.filter(d => d.evaluation_status === status);
      this.querySelector("#select-all").checked = false;
      this.rows.innerHTML = dialogs.length ? dialogs.map((d,index) => `<tr><td><input class="dialog-check" type="checkbox" value="${this.escape(d.conversation_id)}" aria-label="Выбрать диалог"></td><td><span class="cqa-id">${this.escape(d.conversation_id)}</span><div class="cqa-muted" style="font-size:9px;margin-top:4px">${this.escape(d.dataset_group_id || "DEV")}</div></td><td>${this.escape(d.transcript[0]?.timestamp || "—")}</td><td>${d.channel === "voice call" ? "☎ Звонок" : "▤ Чат"}</td><td>${this.escape(d.language)}</td><td>${d.transcript.length}</td><td class="cqa-score">${d.total_score ?? "—"}</td><td><span class="cqa-badge ${d.total_score === null ? "cqa-badge-neutral" : "cqa-badge-success"}">${d.total_score === null ? "Не оценён" : "Оценён"}</span>${d.critical_error ? '<span class="cqa-badge cqa-badge-danger">Грубая ошибка</span>' : ""}</td><td><button class="cqa-link" data-open="${this.escape(d.conversation_id)}">Открыть →</button></td></tr>`).join("") : '<tr><td colspan="9"><div class="cqa-empty">Диалоги не найдены. Измените фильтры или поисковый запрос.</div></td></tr>';
      this.querySelector("#dialog-count").textContent = `Показано: ${dialogs.length} диалог(ов)`;
      this.rows.querySelectorAll("[data-open]").forEach(button => button.addEventListener("click", () => window.location.hash = `evaluation/${encodeURIComponent(button.dataset.open)}`));
    } catch (error) { this.rows.innerHTML = `<tr><td colspan="9"><div class="cqa-empty">${error.message}</div></td></tr>`; }
  }
  toast(message) {
    const node = document.createElement("div"); node.className = "cqa-toast"; node.textContent = message; document.body.append(node); setTimeout(() => node.remove(), 2200);
  }
}
customElements.define("cqa-dialog-list", CqaDialogList);
