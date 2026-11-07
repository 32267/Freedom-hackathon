# frontend/ — правила (Codex-1)

- Только vanilla HTML/CSS/JS, ES modules. Никаких npm, сборщиков, фреймворков, CDN.
- Каждый экран — `frontend/components/cqa-<name>.js`, `customElements.define('cqa-<name>', ...)`.
- Атрибуты: `api-base`, id сущности. Никаких глобальных переменных; связь — `CustomEvent('cqa:...')`, `bubbles: true, composed: true`.
- `fetch` — только в `frontend/api.js`. `?mock=1` → `/fixtures/*.json` (диалоги и оценки) + `/checklists/default.json`.
- Флаг грубой ошибки — заметный бейдж отдельно от балла (он баллы не снимает). Шкала — показывать выбранную ступень и её подпись.
- Тексты на русском. Роли в транскрипте различимы: operator / client / bot / system (bot и system приглушены).
- Реплика: `id="msg-<msg_index>"`; переход к доказательству — `scrollIntoView` + подсветка 2 с.
- Проверка: открыть `index.html?mock=1`, пройти сценарий демо (README §2), без ошибок в консоли.
