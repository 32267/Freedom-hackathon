# llm/ — локальная модель-оценщик

Текущая задача CQA — текстовая: модель получает транскрипт и чек-лист, без изображений. Backend обращается к одному OpenAI-совместимому **LM endpoint** через `LOCAL_LLM_URL`.

## Два локальных сервера

В текущей конфигурации:

- **VLM :8080** — мультимодальный сервер. Он не является endpoint для текстовой оценки, если вы специально не направили на него `LOCAL_LLM_URL`.
- **LM :8081** — текстовая языковая модель; именно к нему должен обращаться CQA scoring.

В корневом `.env`:

```dotenv
LLM_PROVIDERS=local
LOCAL_LLM_URL=http://localhost:8081/v1
LOCAL_LLM_MODEL=mlx-community/Qwen3.5-4B-MLX-4bit
LOCAL_LLM_MAX_TOKENS=3072
LOCAL_LLM_TIMEOUT=600
LOCAL_LLM_REPETITION_PENALTY=1.0
```

Проверь доступность LM:

```bash
curl http://localhost:8081/v1/models
```

Если модель или порт отличаются, синхронно поменяй `LOCAL_LLM_URL` и `LOCAL_LLM_MODEL`. Не направляй CQA на VLM :8080 случайно: текущий evaluator передаёт текстовые сообщения и JSON Schema через `/chat/completions`.

## Установка MLX-VLM (только если нужен VLM)

Не устанавливай MLX-VLM в основное окружение backend: у MLX-VLM могут быть отдельные зависимости. Используй отдельное виртуальное окружение:

```bash
python3 -m venv .venv-mlx-vlm
source .venv-mlx-vlm/bin/activate
python -m pip install -U pip mlx-vlm
bash scripts/start_local_vlm.sh
```

Скрипт запускает VLM на порту 8080 по умолчанию. Это отдельный сервер от LM на 8081. Для текстовой оценки CQA продолжай использовать `LOCAL_LLM_URL=http://localhost:8081/v1`.

## Smoke test

После запуска LM и настройки `.env`:

```bash
python -m llm.benchmark.smoke \
  --dialogs llm/data/DEV.json \
  --checklist checklists/default.json \
  --model mlx-community/Qwen3.5-4B-MLX-4bit \
  --ids p1-ru-001 p1-kz-001 p1-en-001 \
  --out llm/runs/lm-smoke.json
```

Это технический smoke test, а не измерение точности: DEV не является gold set. Проверь `completed`, `failed`, `invalid`, latency и валидность evidence в JSON-отчёте. Smoke test должен запускаться против того же LM endpoint, который указан в `LOCAL_LLM_URL`.

## Интеграция

`backend/llm/local_provider.py` вызывает `/v1/chat/completions` и передаёт `response_format=json_schema`. Сервер должен поддерживать используемый формат structured outputs. Серверная JSON Schema не заменяет детерминированную проверку evidence и валидацию результата в приложении.

## Диагностика

Для сохранения сырых запросов/ответов включи локальный capture:

```dotenv
LOCAL_LLM_DEBUG_DIR=llm/runs/debug
```

Файлы могут содержать полный транскрипт. Не отправляй их публично без удаления персональных данных. По умолчанию capture выключен.

## Кандидаты

- Основной baseline: `mlx-community/Qwen3.5-4B-MLX-4bit`.
- Gemma 4 E2B/E4B остаются альтернативами в `llm/benchmark/models.json`; поддержку конкретного checkpoint проверяй на установленной версии runtime.

Выбирай модель по human-reviewed gold-набору и отдельно по RU/KZ/EN, а не только по скорости или JSON-validity. Не используй DEV как обучающую или тестовую разметку без независимой проверки человеком.
