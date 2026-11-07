# AGENTS.md — правила для всех агентов (Claude Code + Codex)

Этот файл читают **все** агенты. Claude Code подхватывает его через `CLAUDE.md`, Codex — напрямую.
Перед любой задачей прочитай: этот файл → `docs/CONTRACTS.md` → свою задачу по ID в `docs/TASKS.md`.
В `frontend/` и `backend/` есть свои `AGENTS.md` с локальными правилами. Тексты PDF: гайд — `docs/GUIDE.md`, чек-лист — `docs/CHECKLIST.md`, о компании — `docs/COMPANY.md` (сами PDF не читай).
Особенности DEV-данных (форматы времени, системные события, маскирование) — `docs/DATA.md`.

## Проект
CQA (Conversation Quality Analytics) — хакатон Freedom Broker, 24 часа.
Оцениваем работу оператора в диалогах (RU / KZ / EN, чаты и звонки) по настраиваемому чек-листу,
показываем баллы + объяснение + реплику-доказательство, поддерживаем апелляцию и пересмотр.

Жёсткие требования жюри (не нарушать):
- UI — чистый **HTML + CSS + JS** (без React/Vue/сборщиков). Каждый экран — самостоятельный компонент,
  который можно встроить как HTML web resource в Dynamics 365.
- Реплики `bot` и `system` — только контекст, оценивается `operator`.
- N/A → вес перераспределяется между применимыми критериями. Грубая ошибка отмечается отдельно.
- Сохранять исходные `timestamp` (чат `MM:SS`, звонок ISO 8601).
- Новый/изменённый критерий применяется **через UI**, без правки кода.
- README с шагами запуска. Для платной модели — название и стоимость одной оценки.

## Стек (зафиксирован, не менять без согласования в TASKS.md)
- Backend: Python 3.11+, FastAPI, SQLite (`data/cqa.db`), pydantic.
- LLM: провайдер через env (`LLM_PROVIDER=openai|anthropic`), код в `backend/llm/`.
- Frontend: `frontend/` — vanilla Web Components (`<cqa-*>`), `fetch` только в `frontend/api.js`, отдаётся тем же FastAPI.
- Данные организаторов идут **только через backend** (CORS).

## Владение кодом — главное правило против конфликтов
Каждый агент правит **только свои папки**. Нужна правка в чужой — оставь заметку в `docs/TASKS.md`
(секция «Запросы») или открой Issue, но не правь сам.

| Владелец | Агент | Папки |
|---|---|---|
| Ислам | Claude Code | `frontend/`, `backend/scoring/` (кроме `prompt.py`), `tools/`, `checklists/`, `fixtures/`, `docs/CONTRACTS.md` |
| Codex-1 | Codex | **LLM:** `backend/llm/`, `backend/scoring/prompt.py`, `llm/` (своя модель, бенчмарк), качество оценки на DEV |
| Codex-2 | Codex | `backend/api.py`, `backend/db.py`, `backend/main.py`, `scripts/`, `README.md` раздел «Запуск» |

Общие файлы (`AGENTS.md`, `README.md` разделы 1–6, `docs/TASKS.md`, `requirements.txt`, `.github/`) — правка только маленькими отдельными коммитами.

## Контракты
`docs/CONTRACTS.md` — единственный источник правды о форматах JSON и эндпоинтах.
- Не меняй форму данных молча. Изменение контракта = отдельный PR с пометкой `[contract]`, всем сообщить.
- Пока чужая часть не готова — работай на моках из `docs/CONTRACTS.md` / `fixtures/`.

## Git-процесс
- `main` всегда запускается. Прямые пуши в `main` — только для `docs/TASKS.md`.
- Ветки: `<owner>/<коротко>` — `islam/scoring-na`, `codex1/transcript-view`, `codex2/appeals-api`.
- Маленькие PR (≤ ~300 строк), часто. Перед PR: `git pull --rebase origin main`, запустить проверки.
- Сообщение коммита: `scope: что сделано` (`scoring: redistribute N/A weight`).
- Не коммитить: `.env`, `data/*.json`, `data/*.db`, аудио.

## Команды
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/fetch_dataset.py DEV        # → data/DEV.json (URL берётся из .env)
uvicorn backend.main:app --reload --port 8000   # UI: http://localhost:8000
pytest -q
# UI без backend: открыть frontend/index.html?mock=1 через любой статический сервер
```

## Как агенту брать задачу
1. Взять **одну** задачу по ID из `docs/TASKS.md`, поставить `[~] (ветка)`.
2. Ветка от свежего `main`. Если задача требует чужого кода, которого ещё нет, — работай на моке, не жди.
3. Не уверен в контракте — не угадывай: допиши вопрос в «Запросы» в TASKS.md и сделай остальное.
4. PR с шаблоном, в заголовке ID: `F3: dialog card evidence links`.

## Definition of Done для задачи
1. Работает локально по командам выше. 2. Соответствует `docs/CONTRACTS.md`.
3. Есть хотя бы один тест (backend) или ручная проверка описана в PR (frontend).
4. Статус обновлён в `docs/TASKS.md`.

## Стиль
- Тексты UI — на русском. Код, имена — на английском.
- Без лишних зависимостей. Без авторизации (не нужна по заданию).
