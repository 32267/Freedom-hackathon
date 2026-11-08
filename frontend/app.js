import "./components/cqa-dashboard.js";
import "./components/cqa-dialog-list.js";
import "./components/cqa-evaluation.js";
import "./components/cqa-review-queue.js";
import "./components/cqa-checklist-editor.js";
import "./components/cqa-operators.js";
import { api } from "./api.js";
import { LANGS } from "./ui.js";

const ROUTES = {
  dashboard: { title: "Обзор", icon: "▦", tag: "cqa-dashboard" },
  conversations: { title: "Диалоги", icon: "☰", tag: "cqa-dialog-list" },
  evaluation: { title: "Оценка", icon: "◉", tag: "cqa-evaluation" },
  appeals: { title: "Апелляции", icon: "⚖", tag: "cqa-review-queue" },
  operators: { title: "Операторы", icon: "★", tag: "cqa-operators" },
  checklist: { title: "Чек-лист", icon: "✓", tag: "cqa-checklist-editor" },
};

class CqaApp extends HTMLElement {
  connectedCallback() {
    this.innerHTML = `
      <div class="cqa-shell">
        <aside class="cqa-sidebar">
          <div class="cqa-side-panel">
            <a class="cqa-brand" href="#dashboard" aria-label="Freedom Broker — на главную">
              <img class="cqa-brand-mark" src="./assets/freedom-mark.png" alt="Freedom">
              <img class="cqa-brand-logo" src="./assets/freedom-logo.png" alt="Freedom"></a>
            <nav class="cqa-nav">${Object.entries(ROUTES).map(([key, r]) => `
              <a href="#${key}" data-route="${key}" title="${r.title}"><span class="cqa-nav-icon">${r.icon}</span><span class="cqa-nav-text">${r.title}</span>
                ${key === "appeals" ? '<span class="cqa-nav-count" id="appeal-count" hidden></span>' : ""}</a>`).join("")}
            </nav>
            <button class="cqa-pin" id="pin" title="Закрепить панель">»</button>
          </div>
        </aside>
        <main class="cqa-main">
          <header class="cqa-topbar">
            <div class="cqa-crumb">Контроль качества / <strong id="crumb">Обзор</strong></div>
            <div class="cqa-top-actions">
              <span class="cqa-muted" style="font-size:12px">Язык обоснований</span>
              <div class="cqa-lang" id="lang">${LANGS.map(l => `<button data-lang="${l}">${l.toUpperCase()}</button>`).join("")}</div>
              <span class="cqa-mode ${api.isMock() ? "demo" : ""}">${api.isMock() ? "ДЕМО-ДАННЫЕ" : "LIVE · API"}</span>
            </div>
          </header>
          <section class="cqa-content" id="view"></section>
        </main>
      </div>`;
    this.querySelectorAll("[data-lang]").forEach(b => b.addEventListener("click", () => this.setLang(b.dataset.lang)));
    let pinned = false;
    try { pinned = localStorage.getItem("cqa-sidebar-pinned") === "1"; } catch { /* хранилище недоступно */ }
    this.setPinned(pinned);
    this.querySelector("#pin").addEventListener("click", () => this.setPinned(!this.querySelector(".cqa-shell").classList.contains("pinned")));
    this.setLang(this.getAttribute("lang") || "ru", false);
    this.addEventListener("cqa:open-dialog", e => { window.location.hash = `evaluation/${encodeURIComponent(e.detail.conversationId)}`; });
    this.addEventListener("cqa:appeals-changed", () => this.refreshAppealCount());
    this.addEventListener("cqa:batch-done", () => this.refreshAppealCount());
    window.addEventListener("hashchange", () => this.route());
    this.route();
    this.refreshAppealCount();
  }

  setPinned(pinned) {
    this.querySelector(".cqa-shell").classList.toggle("pinned", pinned);
    const pin = this.querySelector("#pin");
    pin.textContent = pinned ? "«" : "»";
    pin.title = pinned ? "Свернуть панель" : "Закрепить панель";
    try { localStorage.setItem("cqa-sidebar-pinned", pinned ? "1" : "0"); } catch { /* хранилище недоступно */ }
  }

  setLang(lang, notify = true) {
    this.setAttribute("lang", lang);
    this.querySelectorAll("[data-lang]").forEach(b => b.classList.toggle("active", b.dataset.lang === lang));
    if (notify) this.querySelector("#view").firstElementChild?.dispatchEvent(new CustomEvent("cqa:lang", { detail: { lang } }));
  }

  async refreshAppealCount() {
    try {
      const n = (await api.getStats()).open_appeals;
      const badge = this.querySelector("#appeal-count");
      badge.hidden = !n;
      badge.textContent = n;
    } catch { /* сводка необязательна */ }
  }

  route() {
    const [key, id] = window.location.hash.replace(/^#/, "").split("/");
    const name = ROUTES[key] ? key : "dashboard";
    this.querySelector("#crumb").textContent = ROUTES[name].title;
    this.querySelectorAll(".cqa-nav a").forEach(a => a.classList.toggle("active", a.dataset.route === name));
    const view = document.createElement(ROUTES[name].tag);
    if (id) {
      try { view.setAttribute("conversation-id", decodeURIComponent(id)); } catch { view.setAttribute("conversation-id", id); }
    }
    this.querySelector("#view").replaceChildren(view);
    window.scrollTo(0, 0);
  }
}
customElements.define("cqa-app", CqaApp);
