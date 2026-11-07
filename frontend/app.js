import "./components/cqa-dashboard.js";
import "./components/cqa-dialog-list.js";
import "./components/cqa-evaluation.js";
import { api } from "./api.js";

class CqaApp extends HTMLElement {
  connectedCallback() {
    this.innerHTML = `
      <div class="cqa-shell">
        <aside class="cqa-sidebar">
          <div class="cqa-brand"><span class="cqa-brand-mark">✳</span><span class="cqa-brand-name">CQA STUDIO<small>QUALITY ANALYTICS</small></span></div>
          <div class="cqa-nav-label">РАБОЧЕЕ ПРОСТРАНСТВО</div>
          <nav class="cqa-nav">
            <a href="#dashboard" data-route="dashboard"><span class="cqa-nav-icon">▦</span><span class="cqa-nav-text">Обзор</span></a>
            <a href="#conversations" data-route="conversations"><span class="cqa-nav-icon">▤</span><span class="cqa-nav-text">Диалоги</span></a>
            <a href="#evaluation" data-route="evaluation"><span class="cqa-nav-icon">◉</span><span class="cqa-nav-text">Оценка</span></a>
          </nav>
          <div class="cqa-sidebar-foot"><span class="cqa-status-dot"></span><span class="cqa-muted" style="font-size:10px">Интерфейс готов</span><p>LLM подключается отдельно</p></div>
        </aside>
        <main class="cqa-main">
          <header class="cqa-topbar"><div class="cqa-crumb">Рабочее пространство / <strong id="cqa-current-page">Обзор</strong></div><div class="cqa-top-actions"><span class="cqa-mode" id="cqa-mode"></span><span class="cqa-avatar">QA</span></div></header>
          <section class="cqa-content" id="cqa-view"></section>
        </main>
      </div>`;
    this.querySelector("#cqa-mode").textContent = api.isMock() ? "ДЕМО-ДАННЫЕ" : "API";
    this.addEventListener("cqa:open-dialog", event => {
      const id = event.detail?.conversationId;
      if (id) { window.location.hash = `evaluation/${encodeURIComponent(id)}`; }
    });
    this.addEventListener("cqa:run-evaluation", event => {
      const id = event.detail?.conversationId;
      if (id) window.location.hash = `evaluation/${encodeURIComponent(id)}`;
    });
    window.addEventListener("hashchange", () => this.renderRoute());
    this.renderRoute();
  }

  renderRoute() {
    const [route, id] = window.location.hash.replace(/^#/, "").split("/");
    const view = this.querySelector("#cqa-view");
    const active = route || "dashboard";
    const titles = { dashboard: "Обзор", conversations: "Диалоги", evaluation: "Оценка" };
    this.querySelector("#cqa-current-page").textContent = titles[active] || titles.dashboard;
    this.querySelectorAll(".cqa-nav a").forEach(link => link.classList.toggle("active", link.dataset.route === active));
    if (active === "conversations") view.innerHTML = "<cqa-dialog-list></cqa-dialog-list>";
    else if (active === "evaluation") view.innerHTML = `<cqa-evaluation conversation-id="${id ? decodeURIComponent(id) : ""}"></cqa-evaluation>`;
    else view.innerHTML = "<cqa-dashboard></cqa-dashboard>";
  }
}
customElements.define("cqa-app", CqaApp);
