# Контракты (источник правды)

Владелец: Ислам/Claude. Изменения — только PR с `[contract]`.
Версия: v0.1 — ⚠️ поля чек-листа уточнить по PDF с 8 критериями (шкалы, правила N/A, округление).

## 1. Модели данных

### Dialog (как отдаёт API организаторов, храним без изменений)
```json
{
  "conversation_id": "p1-ru-001",
  "channel": "agent chat",            // "agent chat" | "voice call"
  "language": "RU",                   // "RU" | "KZ" | "EN"
  "transcript": [
    {"timestamp": "00:02", "speaker": "operator", "text": "Здравствуйте!"}
  ],                                  // speaker: client | operator | bot | system
  "audio_url": null,                  // строка у звонков
  "dataset_group_id": "DEV"           // добавляем мы
}
```
Ссылка на реплику = индекс в `transcript` (`msg_index`, с 0). Якорь в UI: `#msg-<index>`.

### Checklist
```json
{
  "id": "default-v1",
  "name": "Базовый чек-лист",
  "version": 1,
  "rounding": "half_up_1",            // правило округления из PDF
  "sections": [{"id": "greeting", "name": "Приветствие"}],
  "criteria": [
    {
      "id": "c1",
      "section_id": "greeting",
      "title": "Оператор поздоровался и представился",
      "description": "Подробная формулировка для LLM",
      "answer_type": "binary",        // "binary" | "scale"
      "scale": null,                  // для scale: {"min": 0, "max": 5}
      "weight": 10,
      "na_allowed": true,
      "na_rule": "Если диалог начат ботом и оператор подключился позже...",
      "is_critical": false            // грубая ошибка → флаг в итоге
    }
  ]
}
```
Сохранение меняет `version` (+1); старые оценки ссылаются на свою версию.

### Evaluation
```json
{
  "id": "ev_123",
  "conversation_id": "p1-ru-001",
  "checklist_id": "default-v1",
  "checklist_version": 1,
  "status": "done",                   // queued | running | done | error
  "model": "gpt-4.1-mini",
  "cost_usd": 0.004,
  "total_score": 87.5,                // 0..100 после перераспределения N/A
  "critical_error": false,
  "section_scores": [{"section_id": "greeting", "score": 100}],
  "results": [
    {
      "criterion_id": "c1",
      "answer": "yes",                // binary: yes|no|na; scale: число|"na"
      "raw_score": 1,
      "max_score": 1,
      "weight": 10,
      "effective_weight": 12.5,       // после перераспределения N/A
      "weighted_score": 12.5,
      "explanation": "Оператор поздоровался в первой реплике...",
      "evidence": [{"msg_index": 0, "quote": "Здравствуйте!"}],
      "checked_range": null,          // если действие пропущено: {"from": 0, "to": 12}
      "na_reason": null
    }
  ],
  "created_at": "2026-11-07T10:00:00Z"
}
```

### Appeal
```json
{
  "id": "ap_1",
  "evaluation_id": "ev_123",
  "criterion_id": "c1",
  "comment": "Оператор представился во 2-й реплике",
  "status": "open",                   // open | confirmed | changed
  "original": {"answer": "no", "weighted_score": 0},
  "decision": null,                   // {"answer": "yes", "reason": "...", "decided_at": "..."}
  "created_at": "..."
}
```
После решения `changed` → backend пересчитывает Evaluation; хранит `original_total` и `final_total`.

## 2. REST API (`/api`)

| Метод | Путь | Описание | Владелец |
|---|---|---|---|
| POST | `/api/datasets/{group_id}/import` | Забрать набор у организаторов, сохранить диалоги | Codex-2 |
| GET | `/api/dialogs?group_id=&language=&channel=` | Список диалогов + последний total_score | Codex-2 |
| GET | `/api/dialogs/{id}` | Диалог целиком | Codex-2 |
| POST | `/api/dialogs/upload` | Загрузка своего транскрипта (JSON формата Dialog) | Codex-2 |
| GET/POST | `/api/checklists` | Список / создать | Codex-2 (хранение) |
| GET/PUT | `/api/checklists/{id}` | Получить / сохранить новую версию | Codex-2 |
| POST | `/api/evaluations` | `{conversation_id, checklist_id}` → Evaluation | Codex-2 → вызывает `scoring.evaluate()` |
| POST | `/api/evaluations/batch` | `{group_id, checklist_id}` → оценить весь набор (контрольный!) | Codex-2 |
| GET | `/api/evaluations/{id}` | Evaluation | Codex-2 |
| POST | `/api/appeals` | `{evaluation_id, criterion_id, comment}` | Codex-2 |
| GET | `/api/appeals?status=open` | Очередь проверяющего | Codex-2 |
| POST | `/api/appeals/{id}/decision` | `{action: "confirm"|"change", answer?, reason}` → пересчёт | Codex-2 → `scoring.recompute()` |

## 3. Python-интерфейс scoring (Ислам → Codex-2)
```python
# backend/scoring/__init__.py
def evaluate(dialog: dict, checklist: dict) -> dict: ...      # вернёт Evaluation (без id)
def recompute(evaluation: dict, checklist: dict) -> dict: ... # пересчёт итогов после апелляции, без LLM
```
Пока не готово — `backend/scoring/mock.py` отдаёт фейковый Evaluation той же формы.

## 4. UI-экраны (Codex-1)
`frontend/` — каждый экран отдельный модуль, монтируется в `<div id="...">`:
1. `checklist-editor` — критерии, вес, тип, шкала, N/A, секции; сохранить версию.
2. `dialog-list` — фильтры язык/канал, балл, кнопка «Оценить всё».
3. `dialog-card` — транскрипт (якоря `#msg-N`, роли визуально разные), аудиоплеер для звонков,
   таблица результатов, клик по доказательству → скролл + подсветка реплики.
4. `appeal-form` — критерий + комментарий.
5. `review-queue` — спорная оценка, комментарий, фрагмент диалога, решение + причина, исходный/финальный балл.
