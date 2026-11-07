import { api } from "../api.js";
import { confirmDialog, esc, toast, trackJob } from "../ui.js";

const TYPES = { binary: "Да / Нет", scale: "Шкала", flag: "Флаг нарушения (без баллов)" };
const lines = text => text.split("\n").map(s => s.trim()).filter(Boolean);
const slug = title => {
  const map = { а: "a", б: "b", в: "v", г: "g", д: "d", е: "e", ё: "e", ж: "zh", з: "z", и: "i", й: "y", к: "k", л: "l", м: "m", н: "n", о: "o", п: "p", р: "r", с: "s", т: "t", у: "u", ф: "f", х: "h", ц: "c", ч: "ch", ш: "sh", щ: "sch", ы: "y", э: "e", ю: "yu", я: "ya", ь: "", ъ: "" };
  const s = title.toLowerCase().split("").map(ch => map[ch] ?? ch).join("").replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 32);
  return s || `criterion_${Date.now().toString(36)}`;
};

class CqaChecklistEditor extends HTMLElement {
  async connectedCallback() {
    this.innerHTML = '<div class="cqa-empty">Загружаем чек-лист…</div>';
    try {
      this.saved = await api.getChecklist();
      this.cl = structuredClone(this.saved);
      this.render();
    } catch (e) { this.innerHTML = `<div class="cqa-empty">${esc(e.message)}</div>`; }
  }

  weightSum() {
    return this.cl.criteria.filter(c => c.answer_type !== "flag").reduce((s, c) => s + Number(c.weight || 0), 0);
  }

  render() {
    const cl = this.cl;
    const sum = this.weightSum();
    this.innerHTML = `
      <div class="cqa-page-head"><div><p class="cqa-eyebrow">НАСТРОЙКА ОЦЕНКИ</p><h1 class="cqa-page-title">Чек-лист</h1>
        <p class="cqa-subtitle">${esc(cl.name)} · версия ${cl.version}. Изменения сохраняются новой версией; старые оценки остаются привязаны к своей.</p></div>
        <div class="cqa-row"><button class="cqa-btn" id="add-section">＋ Секция</button><button class="cqa-btn cqa-btn-primary" id="add">＋ Критерий</button></div></div>
      <section class="cqa-card cqa-panel" style="margin-bottom:12px">
        <div class="cqa-grid" style="grid-template-columns:repeat(auto-fit,minmax(220px,1fr))">
          <div class="cqa-field"><label class="cqa-label">Название</label><input class="cqa-input" data-root="name" value="${esc(cl.name)}"></div>
          <div class="cqa-field"><label class="cqa-label">Округление итога</label>
            <select class="cqa-select" data-root="rounding" style="width:100%">${["half_up_0", "half_up_1", "half_up_2"].map(r => `<option value="${r}" ${cl.rounding === r ? "selected" : ""}>${r.slice(-1)} знак(а) после запятой</option>`).join("")}</select></div>
          <div class="cqa-field"><label class="cqa-label">Грубая ошибка</label>
            <select class="cqa-select" data-root="critical_policy" style="width:100%"><option value="flag" ${cl.critical_policy !== "zero_total" ? "selected" : ""}>Только отметка (по чек-листу)</option><option value="zero_total" ${cl.critical_policy === "zero_total" ? "selected" : ""}>Обнулять итог</option></select></div>
          <div class="cqa-field"><label class="cqa-label">Сумма весов (без флагов)</label>
            <div class="cqa-weight-sum ${sum === 100 ? "" : "bad"}" style="font-size:22px">${sum} / 100</div>
            <div class="cqa-panel-sub">${sum === 100 ? "Сходится" : "Итог всё равно нормируется к 100, но по регламенту сумма должна быть 100"}</div></div>
        </div>
        <div class="cqa-field"><label class="cqa-label">Общие правила для оценщика (по строке)</label>
          <textarea class="cqa-textarea" data-root-lines="notes">${esc((cl.notes || []).join("\n"))}</textarea></div>
        <div class="cqa-label">Секции</div>
        <div class="cqa-row">${(cl.sections || []).map((s, i) => `<input class="cqa-input" style="width:auto;flex:1 1 200px" data-section="${i}" value="${esc(s.name)}">`).join("")}</div>
      </section>
      ${cl.criteria.map((c, i) => this.criterionHtml(c, i)).join("")}
      <div class="cqa-sticky-bar">
        <span class="cqa-muted cqa-grow" style="font-size:12.5px">${this.dirty ? "Есть несохранённые изменения" : "Изменений нет"}</span>
        <button class="cqa-btn" id="reset" ${this.dirty ? "" : "disabled"}>Отменить изменения</button>
        <button class="cqa-btn cqa-btn-primary" id="save" ${this.dirty && !api.isMock() ? "" : "disabled"}>Сохранить версию ${cl.version + 1}</button>
      </div>`;
    this.bind();
  }

  criterionHtml(c, i) {
    const sections = this.cl.sections || [];
    return `<section class="cqa-card cqa-editor-crit" data-i="${i}">
      <div class="cqa-row" style="margin-bottom:10px"><strong class="cqa-grow">${i + 1}. ${esc(c.title || "Новый критерий")}</strong>
        <span class="cqa-badge cqa-mono">${esc(c.id)}</span>
        <button class="cqa-btn cqa-btn-sm" data-move="-1" ${i === 0 ? "disabled" : ""}>↑</button>
        <button class="cqa-btn cqa-btn-sm" data-move="1" ${i === this.cl.criteria.length - 1 ? "disabled" : ""}>↓</button>
        <button class="cqa-btn cqa-btn-sm cqa-btn-danger" data-del>Удалить</button></div>
      <div class="cqa-editor-grid">
        <div class="cqa-field"><label class="cqa-label">Название</label><input class="cqa-input" data-f="title" value="${esc(c.title)}"></div>
        <div class="cqa-field"><label class="cqa-label">Секция</label><select class="cqa-select" data-f="section_id" style="width:100%">
          ${sections.map(s => `<option value="${esc(s.id)}" ${s.id === c.section_id ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select></div>
        <div class="cqa-field"><label class="cqa-label">Вес</label><input class="cqa-input" type="number" min="0" max="100" data-f="weight" data-num value="${c.weight}" ${c.answer_type === "flag" ? "disabled" : ""}></div>
        <div class="cqa-field"><label class="cqa-label">Тип ответа</label><select class="cqa-select" data-type style="width:100%">
          ${Object.entries(TYPES).map(([k, v]) => `<option value="${k}" ${c.answer_type === k ? "selected" : ""}>${v}</option>`).join("")}</select></div>
      </div>
      <div class="cqa-field"><label class="cqa-label">Формулировка для оценщика (что считается «Да»)</label>
        <textarea class="cqa-textarea" data-f="description">${esc(c.description)}</textarea></div>
      ${c.answer_type === "scale" ? `<div class="cqa-field"><label class="cqa-label">Ступени шкалы (верхняя = полный вес)</label><div class="cqa-steps">
        ${(c.scale?.steps || []).map((s, j) => `<div class="cqa-step"><input class="cqa-input" type="number" data-step="${j}" data-k="value" value="${s.value}">
          <input class="cqa-input" data-step="${j}" data-k="label" value="${esc(s.label)}"><button class="cqa-btn cqa-btn-sm" data-step-del="${j}">✕</button></div>`).join("")}
        <button class="cqa-btn cqa-btn-sm" data-step-add style="justify-self:start">＋ Ступень</button></div></div>` : ""}
      ${c.answer_type === "flag" ? `<div class="cqa-field"><label class="cqa-label">Виды нарушений (id: название, по строке)</label>
        <textarea class="cqa-textarea" data-flags>${esc((c.flag_types || []).map(f => `${f.id}: ${f.label}`).join("\n"))}</textarea></div>` : ""}
      <div class="cqa-row" style="margin-bottom:10px">
        <label class="cqa-row" style="font-size:13px"><input type="checkbox" data-na ${c.na_allowed ? "checked" : ""} ${c.answer_type === "flag" ? "disabled" : ""}> Допускается Н/П</label>
        ${c.na_allowed ? `<input class="cqa-input cqa-grow" data-f="na_rule" placeholder="Когда ставится Н/П" value="${esc(c.na_rule || "")}">` : ""}</div>
      <div class="cqa-grid" style="grid-template-columns:1fr 1fr">
        <div class="cqa-field"><label class="cqa-label">Снижать, если… (по строке — идёт в промпт)</label><textarea class="cqa-textarea" data-lines="lower_if">${esc((c.lower_if || []).join("\n"))}</textarea></div>
        <div class="cqa-field"><label class="cqa-label">НЕ снижать, если… (по строке)</label><textarea class="cqa-textarea" data-lines="keep_if">${esc((c.keep_if || []).join("\n"))}</textarea></div>
      </div>
    </section>`;
  }

  touch(rerender = false) {
    this.dirty = true;
    if (rerender) this.render();
    else {
      const bar = this.querySelector(".cqa-sticky-bar span");
      if (bar) bar.textContent = "Есть несохранённые изменения";
      this.querySelector("#reset").disabled = false;
      this.querySelector("#save").disabled = api.isMock();
    }
  }

  bind() {
    const cl = this.cl;
    this.querySelector("#add").addEventListener("click", () => this.addCriterion());
    this.querySelector("#add-section").addEventListener("click", () => {
      cl.sections = cl.sections || [];
      cl.sections.push({ id: `section_${cl.sections.length + 1}`, name: "Новая секция" });
      this.touch(true);
    });
    this.querySelector("#reset").addEventListener("click", () => { this.cl = structuredClone(this.saved); this.dirty = false; this.render(); });
    this.querySelector("#save").addEventListener("click", () => this.save());
    this.querySelectorAll("[data-root]").forEach(el => el.addEventListener("change", () => { cl[el.dataset.root] = el.value; this.touch(); }));
    this.querySelectorAll("[data-root-lines]").forEach(el => el.addEventListener("input", () => { cl[el.dataset.rootLines] = lines(el.value); this.touch(); }));
    this.querySelectorAll("[data-section]").forEach(el => el.addEventListener("input", () => { cl.sections[Number(el.dataset.section)].name = el.value; this.touch(); }));

    this.querySelectorAll("[data-i]").forEach(card => {
      const c = cl.criteria[Number(card.dataset.i)];
      card.querySelectorAll("[data-f]").forEach(el => el.addEventListener(el.tagName === "SELECT" ? "change" : "input", () => {
        c[el.dataset.f] = el.dataset.num !== undefined ? Number(el.value) : el.value;
        this.touch(el.dataset.f === "weight" ? false : el.tagName === "SELECT");
        if (el.dataset.f === "weight") this.querySelector(".cqa-weight-sum").textContent = `${this.weightSum()} / 100`;
      }));
      card.querySelectorAll("[data-lines]").forEach(el => el.addEventListener("input", () => { c[el.dataset.lines] = lines(el.value); this.touch(); }));
      card.querySelector("[data-type]").addEventListener("change", e => this.setType(c, e.target.value));
      card.querySelector("[data-na]")?.addEventListener("change", e => { c.na_allowed = e.target.checked; if (!c.na_allowed) c.na_rule = null; this.touch(true); });
      card.querySelector("[data-flags]")?.addEventListener("input", e => {
        c.flag_types = lines(e.target.value).map(l => { const [id, ...rest] = l.split(":"); return { id: slug(id), label: (rest.join(":") || id).trim() }; });
        this.touch();
      });
      card.querySelectorAll("[data-step]").forEach(el => el.addEventListener("input", () => {
        const s = c.scale.steps[Number(el.dataset.step)];
        s[el.dataset.k] = el.dataset.k === "value" ? Number(el.value) : el.value;
        this.fixScale(c);
        this.touch();
      }));
      card.querySelectorAll("[data-step-del]").forEach(b => b.addEventListener("click", () => { c.scale.steps.splice(Number(b.dataset.stepDel), 1); this.fixScale(c); this.touch(true); }));
      card.querySelector("[data-step-add]")?.addEventListener("click", () => { c.scale.steps.push({ value: 0, label: "Описание ступени" }); this.fixScale(c); this.touch(true); });
      card.querySelectorAll("[data-move]").forEach(b => b.addEventListener("click", () => {
        const i = Number(card.dataset.i), j = i + Number(b.dataset.move);
        [cl.criteria[i], cl.criteria[j]] = [cl.criteria[j], cl.criteria[i]];
        this.touch(true);
      }));
      card.querySelector("[data-del]").addEventListener("click", async () => {
        if (!(await confirmDialog(`<h3>Удалить критерий «${esc(c.title)}»?</h3><p class="cqa-muted" style="font-size:13px">После сохранения новой версии он перестанет оцениваться. Старые оценки не изменятся.</p>`))) return;
        cl.criteria.splice(Number(card.dataset.i), 1);
        this.touch(true);
      });
    });
  }

  fixScale(c, sort = false) {
    const values = (c.scale.steps || []).map(s => Number(s.value));
    c.scale.min = values.length ? Math.min(...values) : 0;
    c.scale.max = values.length ? Math.max(...values) : 0;
    if (sort) c.scale.steps.sort((a, b) => b.value - a.value);
  }

  setType(c, type) {
    c.answer_type = type;
    if (type === "scale" && !c.scale?.steps) c.scale = { min: 0, max: 10, steps: [{ value: 10, label: "Полностью" }, { value: 5, label: "Частично" }, { value: 0, label: "Не выполнено" }] };
    if (type !== "scale") c.scale = null;
    if (type === "flag") { c.weight = 0; c.na_allowed = false; c.na_rule = null; c.flag_types = c.flag_types || [{ id: "violation", label: "Нарушение" }]; }
    this.touch(true);
  }

  async addCriterion() {
    const modal = await confirmDialog(`<h3>Новый критерий</h3>
      <div class="cqa-field"><label class="cqa-label">Название</label><input class="cqa-input" id="t" placeholder="Например: Соблюдение скрипта продаж"></div>
      <div class="cqa-field"><label class="cqa-label">Вместо какого критерия (необязательно)</label><select class="cqa-select" id="replace" style="width:100%">
        <option value="">— добавить, ничего не заменяя —</option>${this.cl.criteria.map(c => `<option value="${esc(c.id)}">${esc(c.title)}</option>`).join("")}</select></div>`);
    if (!modal) return;
    const title = modal.querySelector("#t").value.trim() || "Новый критерий";
    const replace = modal.querySelector("#replace").value;
    let id = slug(title);
    while (this.cl.criteria.some(c => c.id === id && c.id !== replace)) id += "_2";
    const old = this.cl.criteria.find(c => c.id === replace);
    const fresh = {
      id, title, section_id: old?.section_id || this.cl.sections?.[0]?.id, description: "Да — …",
      answer_type: "binary", scale: null, weight: old?.weight ?? 10, na_allowed: false, na_rule: null, lower_if: [], keep_if: [],
    };
    if (old) this.cl.criteria.splice(this.cl.criteria.indexOf(old), 1, fresh);
    else this.cl.criteria.push(fresh);
    this.touch(true);
    this.querySelector(`[data-i="${this.cl.criteria.indexOf(fresh)}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  async save() {
    this.cl.criteria.filter(c => c.answer_type === "scale").forEach(c => this.fixScale(c, true));
    try {
      const saved = await api.saveChecklist(this.cl);
      this.saved = saved;
      this.cl = structuredClone(saved);
      this.dirty = false;
      this.render();
      toast(`Сохранена версия ${saved.version}`);
      const go = await confirmDialog(`<h3>Применить чек-лист v${saved.version}?</h3>
        <p class="cqa-muted" style="font-size:13px">Оценить заново все диалоги, у которых нет оценки по новой версии. Можно сделать и позже — кнопкой «Оценить неоценённые» в разделе «Диалоги».</p>`);
      if (go) {
        const job = await api.runBatch({ checklist_id: saved.id, only_missing: true });
        if (job.total) trackJob(job, `Применение чек-листа v${saved.version}`);
      }
    } catch (e) { toast(e.message, true); }
  }
}
customElements.define("cqa-checklist-editor", CqaChecklistEditor);
