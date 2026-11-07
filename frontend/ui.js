// Общие помощники интерфейса: экранирование, форматирование, тосты, прогресс пакетной оценки.
import { api } from "./api.js";

export const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));

export const LANGS = ["ru", "kz", "en"];
export const currentLang = () => document.querySelector("cqa-app")?.getAttribute("lang") || "ru";

export const ROLE = { operator: "Оператор", client: "Клиент", bot: "Бот", system: "Система" };
export const CHANNEL = { "voice call": "Звонок", "agent chat": "Чат" };
export const FLAG_LABEL = { insult: "Оскорбление клиента", bypass: "Услуга в обход компании", confidential: "Раскрытие конфиденциальной информации" };

// Названия критериев на трёх языках (для переключателя языка обоснований).
export const CRITERION_I18N = {
  contact: { kz: "Байланыс орнату", en: "Establishing contact" },
  needs: { kz: "Қажеттілікті анықтау", en: "Identifying needs" },
  identification: { kz: "Сәйкестендіру", en: "Identification" },
  consultation: { kz: "Дұрыс әрі толық кеңес", en: "Accurate and complete consultation" },
  empathy: { kz: "Эмпатия және клиентке бағдарлану", en: "Empathy and customer focus" },
  dialog_management: { kz: "Диалогты басқару, жылдамдық және сауаттылық", en: "Dialogue management, speed and clarity" },
  closing: { kz: "Диалогты аяқтау", en: "Closing" },
  gross_errors: { kz: "Өрескел қателер", en: "Critical errors" },
};
export const critTitle = (criterion, lang = currentLang()) =>
  (lang !== "ru" && CRITERION_I18N[criterion.id]?.[lang]) || criterion.title;

export const scoreClass = score => score === null || score === undefined ? "" : score >= 85 ? "score-good" : score >= 60 ? "score-mid" : "score-bad";
export const fmtScore = score => score === null || score === undefined ? "—" : Number(score).toFixed(score % 1 ? 2 : 0);

export function answerLabel(result, criterion) {
  const a = result?.answer;
  if (a === undefined || a === null) return { text: "—", cls: "ans-na" };
  if (a === "na") return { text: "Н/П", cls: "ans-na" };
  if (criterion?.answer_type === "flag") return a === "yes" ? { text: "Есть", cls: "ans-no" } : { text: "Нет", cls: "ans-yes" };
  if (criterion?.answer_type === "scale") {
    const max = criterion.scale?.max ?? 0;
    return { text: `${a}/${max}`, cls: Number(a) >= max ? "ans-yes" : Number(a) === 0 ? "ans-no" : "ans-mid" };
  }
  return a === "yes" ? { text: "Да", cls: "ans-yes" } : { text: "Нет", cls: "ans-no" };
}

export function stepLabel(criterion, value) {
  return criterion?.scale?.steps?.find(s => String(s.value) === String(value))?.label || "";
}

export function toast(message, isError = false) {
  const node = document.createElement("div");
  node.className = `cqa-toast${isError ? " error" : ""}`;
  node.textContent = message;
  document.body.append(node);
  setTimeout(() => node.remove(), isError ? 4500 : 2600);
}

export function emit(from, name, detail) {
  from.dispatchEvent(new CustomEvent(`cqa:${name}`, { detail, bubbles: true, composed: true }));
}

// Окно прогресса пакетной оценки: опрашивает /api/jobs/{id}, по окончании шлёт cqa:batch-done.
export function trackJob(job, title = "Пакетная оценка") {
  const box = document.createElement("div");
  box.className = "cqa-card cqa-job";
  document.body.append(box);
  const render = st => {
    const pct = st.total ? Math.round(((st.done + st.failed) / st.total) * 100) : 100;
    box.innerHTML = `
      <div class="cqa-row"><strong class="cqa-grow">${esc(title)}</strong>
        <span class="cqa-badge ${st.status === "done" ? "cqa-badge-success" : "cqa-badge-info"}">${st.status === "done" ? "Готово" : "Идёт оценка"}</span></div>
      <div class="cqa-bar-track"><div class="cqa-bar-fill" style="width:${pct}%"></div></div>
      <div class="cqa-row cqa-muted" style="font-size:12px"><span class="cqa-grow">Оценено ${st.done} из ${st.total}${st.failed ? ` · ошибок ${st.failed}` : ""}</span><span>${pct}%</span></div>
      ${st.errors?.length ? `<details style="margin-top:6px;font-size:11.5px"><summary>Ошибки</summary>${st.errors.slice(0, 5).map(e => `<div>${esc(e)}</div>`).join("")}</details>` : ""}
      ${st.status === "done" ? '<button class="cqa-btn cqa-btn-sm" style="margin-top:8px" data-close>Закрыть</button>' : ""}`;
    box.querySelector("[data-close]")?.addEventListener("click", () => box.remove());
  };
  render(job);
  if (!job.total) {
    job.status = "done";
    render(job);
    return;
  }
  const timer = setInterval(async () => {
    try {
      const st = await api.getJob(job.job_id);
      render(st);
      if (st.status === "done") {
        clearInterval(timer);
        emit(document.querySelector("cqa-app") || document.body, "batch-done", st);
      }
    } catch (error) {
      clearInterval(timer);
      toast(error.message, true);
    }
  }, 1500);
}

export function confirmDialog(html) {
  return new Promise(resolve => {
    const bg = document.createElement("div");
    bg.className = "cqa-modal-bg";
    bg.innerHTML = `<div class="cqa-card cqa-modal">${html}
      <div class="cqa-row" style="justify-content:flex-end;margin-top:14px">
        <button class="cqa-btn" data-no>Отмена</button><button class="cqa-btn cqa-btn-primary" data-yes>Продолжить</button></div></div>`;
    document.body.append(bg);
    const close = value => { bg.remove(); resolve(value); };
    bg.querySelector("[data-no]").addEventListener("click", () => close(null));
    bg.querySelector("[data-yes]").addEventListener("click", () => close(bg));
  });
}
