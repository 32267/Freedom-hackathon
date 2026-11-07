# Доска задач

Статусы: `[ ]` todo · `[~]` в работе (указать ветку) · `[x]` в main.
Агент обновляет свою строку сам, отдельным маленьким коммитом.

## Таймлайн (часы от старта)
| Часы | Фаза |
|---|---|
| 0–1 | Все: прочитать AGENTS.md + CONTRACTS.md. Ислам фиксирует чек-лист из PDF → `checklists/default.json` |
| 1–10 | Параллельная работа на моках |
| 10–14 | Интеграция: UI ↔ API ↔ scoring на DEV-наборе |
| 14–20 | Качество оценки (промпты, RU/KZ/EN), полировка UI, апелляции end-to-end |
| 20–22 | Прогон всего DEV, README, репетиция демо (5 мин) |
| 23 | Контрольный набор → `POST /api/evaluations/batch` сразу |
| 24 | Стоп-код. Последний коммит в `main` |

## Ислам / Claude — scoring + LLM
- [ ] `checklists/default.json` из PDF (8 критериев, веса, шкалы, N/A, округление)
- [ ] `backend/scoring/mock.py` — мок Evaluation (нужен Codex-2 в первый час)
- [ ] Математика: веса, шкалы, перераспределение N/A, секции, грубая ошибка, округление + тесты
- [ ] `backend/llm/` — провайдер, один вызов на диалог (все критерии в JSON), учёт стоимости
- [ ] Промпт: evidence как `msg_index`, `checked_range` для пропущенных действий, `na_reason`
- [ ] Ревью PR от Codex-1/2

## Codex-1 — frontend
- [ ] Каркас `frontend/index.html` + роутинг по hash, общий `api.js`, стили
- [ ] `dialog-list`
- [ ] `dialog-card` (транскрипт, якоря, подсветка, аудиоплеер)
- [ ] `checklist-editor`
- [ ] `appeal-form` + `review-queue`

## Codex-2 — API, хранение, данные
- [ ] `backend/main.py`, `requirements.txt`, SQLite-схема, отдача `frontend/` статикой
- [ ] `scripts/fetch_dataset.py` + `POST /api/datasets/{group_id}/import`
- [ ] CRUD чек-листов с версиями
- [ ] Эндпоинты оценок (сначала на `scoring.mock`), batch с прогрессом
- [ ] Апелляции + решение + пересчёт через `scoring.recompute`
- [ ] README: запуск, модель, стоимость одной оценки

## Запросы между владельцами
<!-- "Codex-1 → Codex-2: нужен эндпоинт X" -->
