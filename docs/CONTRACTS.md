# Контракты (источник правды)

Владелец: Ислам/Claude. Изменения — только PR с `[contract]`.
Версия: v1 — чек-лист сверен с PDF организаторов.

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

Backend при отдаче добавляет **производные** поля (исходные не меняются):
- `transcript[i].msg_index` — индекс;
- `transcript[i].offset_sec` — только у `voice call`: секунды от первой реплики (для перемотки `<audio>`).

### Checklist
Эталон — [`checklists/default.json`](../checklists/default.json) (8 критериев из PDF, см. [CHECKLIST.md](CHECKLIST.md)).
```json
{
  "id": "default",
  "name": "Чек-лист качества чатов (Freedom Broker)",
  "version": 1,
  "rounding": "half_up_2",            // итог до 2 знаков
  "critical_policy": "flag",          // грубая ошибка не влияет на балл, только отметка ("zero_total" — обнулять)
  "notes": ["Общие правила для LLM и UI: «Нет» vs N/A, как ссылаться на реплику..."],
  "sections": [{"id": "start", "name": "Начало и понимание запроса"}],
  "criteria": [
    {
      "id": "needs",                  // стабильный slug, латиница
      "section_id": "start",
      "title": "Выявление потребности",
      "description": "Да — оператор учёл известные детали и уточнил недостающее до ответа.",
      "answer_type": "binary",        // "binary" | "scale" | "flag"
      "scale": null,
      "weight": 15,
      "na_allowed": true,
      "na_rule": "Данных для ответа хватало с самого начала.",
      "lower_if": ["Переспросил то, что клиент уже сообщил"],   // за что снижать — идёт в промпт
      "keep_if": ["Ничего не уточнял, потому что всё было ясно — это N/A"]   // за что НЕ снижать
    },
    {
      "id": "consultation", "answer_type": "scale", "weight": 20,
      "scale": {"min": 0, "max": 20, "steps": [{"value": 20, "label": "Все существенные вопросы закрыты..."}]}
    },                                // ответ — ТОЛЬКО одна из steps[].value
    {
      "id": "gross_errors", "answer_type": "flag", "weight": 0,
      "flag_types": [{"id": "insult", "label": "Оскорбление клиента"}]
    }                                 // flag: "yes" = нарушение найдено; в балл не входит
  ]
}
```
Сохранение меняет `version` (+1); старые оценки ссылаются на свою версию.
Редактор чек-листа должен уметь всё это (на контроле организаторы заменят один критерий):
добавить/удалить/изменить критерий, тип, вес, ступени шкалы с подписями, N/A + условие, секцию.

### Формула итога (`backend/scoring/math.py`, по «Порядку расчёта» PDF)
```
norm_i      = binary: yes→1, no→0 | scale: value / max (верхняя ступень = полный вес)
scored      = критерии с answer_type != "flag" и weight > 0
applicable  = scored с answer != "na"         # N/A только если na_allowed, иначе ошибка
eff_w_i     = weight_i / Σ weight_j (j ∈ applicable) × 100     # максимум остаётся 100
weighted_i  = norm_i × eff_w_i
total       = round_half_up(Σ weighted_i, 2)  # нет applicable → null («итог не рассчитывается»)
section_s   = та же формула внутри секции (0..100); секции только из scored-критериев
critical    = любой flag с answer "yes" → critical_error = true, critical_flags = [...]
```
Пример: identification = N/A, contact = Нет, остальное Да → 1 − 10/80 = **87.5**.

### Несколько ответов (`backend/scoring/ensemble.py`)
LLM_SAMPLES независимых ответов → по каждому критерию: большинство (да/нет/N/A/флаг) или нижняя медиана (шкала);
ничья → ответ первого провайдера (Claude). Объяснение и цитаты берутся из ответа, совпавшего с итоговым.
Провайдеры по уровням из LLM_PROVIDERS: Codex включается, только если Claude не ответил.

### Evaluation
```json
{
  "id": "ev_123",
  "conversation_id": "p1-ru-001",
  "checklist_id": "default",
  "checklist_version": 1,
  "status": "done",                   // queued | running | done | error
  "model": "claude-haiku-5-5",           // через запятую, если ответы от разных моделей
  "providers": ["claude_cli", "claude_cli", "claude_cli"],   // кто дал каждый из ответов
  "samples": 3,                       // сколько ответов сравнивали (LLM_SAMPLES)
  "needs_review": false,              // true — хотя бы по одному критерию ответы разошлись
  "provider_errors": [],              // кто не ответил (например, лимит Claude → ответил Codex)
  "cost_usd": 0.004,
  "tokens": {"input": 3200, "output": 900},
  "cache_key": "sha256(dialog)+checklist_id+version",   // повторная оценка → из кэша
  "total_score": 87.5,                // 0..100 после перераспределения N/A
  "critical_error": false,
  "critical_flags": [],               // id из flag_types, напр. ["bypass"]
  "section_scores": [{"section_id": "start", "score": 100}],
  "results": [
    {
      "criterion_id": "contact",
      "answer": "yes",                // binary: yes|no|na; scale: одна из steps|"na"; flag: yes|no
      "raw_score": 1,
      "max_score": 1,
      "weight": 10,
      "effective_weight": 12.5,       // после перераспределения N/A
      "weighted_score": 12.5,
      "explanation": "Оператор поздоровался в первой реплике...",   // = explanations.ru (для совместимости)
      "explanations": {"ru": "Оператор поздоровался...", "kz": "Оператор сәлемдесті...", "en": "The agent greeted..."},
      "evidence": [{"msg_index": 0, "quote": "Здравствуйте!"}],   // quote обязана быть подстрокой реплики
      "source": "llm",                // "llm" | "rule" (посчитано кодом) | "appeal" (изменено проверяющим)
      "validated": true,              // прошло проверку доказательств
      "problems": [],                 // что не прошло проверку (если validated=false)
      "votes": [{"provider": "claude_cli", "model": "claude-haiku-5-5", "answer": "yes"}],
      "agreement": 1.0,               // доля ответов, совпавших с итоговым
      "needs_review": false,          // ответы моделей разошлись → показать проверяющему
      "flags": [],                    // только для flag: какие нарушения найдены
      "checked_range": null,          // если действие пропущено: где ожидалось {"from": 0, "to": 12}
      "na_reason": null,              // = na_reasons.ru
      "na_reasons": null              // при N/A: {"ru": "...", "kz": "...", "en": "..."}
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
  "criterion_id": "contact",
  "comment": "Оператор представился во 2-й реплике",
  "status": "open",                   // open | confirmed | changed
  "original": {"answer": "no", "weighted_score": 0},
  "decision": null,                   // {"answer": "yes", "reason": "...", "decided_at": "..."}
  "created_at": "..."
}
```
После решения `changed` → backend пересчитывает Evaluation; хранит `original_total` и `final_total`.
При любом решении (confirm или change) результат критерия получает `source: "appeal"` — это проверенная человеком
метка, из неё `llm/export_dataset.py` соберёт обучающий набор для своей модели.

## 2. REST API (`/api`)

| Метод | Путь | Описание | Владелец |
|---|---|---|---|
| POST | `/api/datasets/{group_id}/import` | Забрать набор у организаторов, сохранить диалоги | Codex-2 |
| GET | `/api/dialogs?group_id=&language=&channel=` | Список диалогов + последний total_score | Codex-2 |
| GET | `/api/dialogs/{id}` | Диалог целиком | Codex-2 |
| POST | `/api/dialogs/upload` | Загрузка своего транскрипта (JSON формата Dialog) | Codex-2 |
| GET/POST | `/api/checklists` | Список / создать | Codex-2 (хранение) |
| GET/PUT | `/api/checklists/{id}` | Получить / сохранить новую версию | Codex-2 |
| GET | `/api/llm/providers` | Оценщики и пресеты для выбора на сайте → `backend.llm.registry.list_providers()` | Codex-2 |
| POST | `/api/evaluations` | `{conversation_id, checklist_id, providers?, samples?}` → Evaluation | Codex-2 → вызывает `scoring.evaluate()` |
| POST | `/api/evaluations/batch` | `{group_id, checklist_id, providers?, samples?}` → оценить весь набор (контрольный!) | Codex-2 |
| GET | `/api/evaluations/{id}` | Evaluation | Codex-2 |
| POST | `/api/appeals` | `{evaluation_id, criterion_id, comment}` | Codex-2 |
| GET | `/api/appeals?status=open` | Очередь проверяющего | Codex-2 |
| POST | `/api/appeals/{id}/decision` | `{action: "confirm"|"change", answer?, reason}` → пересчёт | Codex-2 → `scoring.recompute()` |

## 3. Python-интерфейс scoring (Ислам → Codex-2)
```python
# backend/scoring/__init__.py
def evaluate(dialog: dict, checklist: dict, providers: str | None = None, samples: int | None = None) -> dict: ...
#   providers/samples — из выбранного на сайте пресета; None → из .env. Вернёт Evaluation (без id)
# backend/llm/registry.py
def list_providers() -> dict: ...   # {"providers": [{id,label,kind,billing,available,reason,configured}],
                                    #  "presets": [{id,label,providers,samples}], "default": {...}}
def recompute(evaluation: dict, checklist: dict) -> dict: ... # пересчёт итогов после апелляции, без LLM
```
Пока не готово — `backend/scoring/mock.py` отдаёт фейковый Evaluation той же формы.

**Языки обоснований:** `explanations` и `na_reasons` всегда на `ru`, `kz`, `en` (одинаковый смысл).
Цитаты в `evidence` — на языке оригинала диалога. UI показывает выбранный язык, по умолчанию `ru`.

Батч (`POST /api/evaluations/batch`) возвращает `{"job_id"}`; прогресс — `GET /api/jobs/{job_id}` →
`{"total": 65, "done": 40, "failed": 1, "status": "running"}`. Параллельность 4–8, ретраи, кэш.

## 4. UI-экраны (Codex-1)
`frontend/` — каждый экран — **Web Component** (vanilla `customElements.define`), чтобы встраивать по одному в Dynamics 365:
- имя тега `cqa-<экран>`, атрибуты: `api-base` (по умолчанию `/api`), id сущности (`conversation-id`, `evaluation-id`);
- общение между компонентами — `CustomEvent` (`cqa:open-dialog`, `cqa:evaluated`, `cqa:appeal-decided`), без глобальных переменных;
- стили — внутри компонента (Shadow DOM или префикс `cqa-`);
- `frontend/api.js` — единственное место с `fetch`; при `?mock=1` отдаёт `fixtures/*.json` (диалоги, оценки) и `checklists/default.json`.

Экраны:
1. `checklist-editor` — критерии, вес, тип, шкала, N/A, секции; сохранить версию.
2. `dialog-list` — фильтры язык/канал, балл, кнопка «Оценить всё».
3. `dialog-card` — транскрипт (якоря `#msg-N`, роли визуально разные), аудиоплеер для звонков,
   таблица результатов, клик по доказательству → скролл + подсветка реплики.
4. `appeal-form` — критерий + комментарий.
5. `review-queue` — спорная оценка, комментарий, фрагмент диалога, решение + причина, исходный/финальный балл.
