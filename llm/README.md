# llm/ — локальная модель-оценщик

Локальный оценщик использует **MLX-VLM** на Apple Silicon. Текущая задача текстовая: модель получает транскрипт и чек-лист без изображений. MLX-VLM предоставляет OpenAI-совместимый Chat Completions API и JSON Schema structured outputs.

## Быстрый запуск на Mac

Из корня репозитория:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U mlx-vlm
bash scripts/start_local_vlm.sh
```

Первый запуск скачает `mlx-community/Qwen3.5-4B-MLX-4bit`. Сервер слушает порт `8080`.

В другом терминале проверь API:

```bash
curl http://localhost:8080/v1/models
```

Настройки в корневом `.env`:

```dotenv
LOCAL_LLM_URL=http://localhost:8080/v1
LOCAL_LLM_MODEL=mlx-community/Qwen3.5-4B-MLX-4bit
LOCAL_LLM_MAX_TOKENS=3072
LOCAL_LLM_TIMEOUT=600
LOCAL_LLM_REPETITION_PENALTY=1.0
LLM_PROVIDERS=local
```

Если порт или модель отличаются, синхронно поменяй `LOCAL_LLM_URL` и `LOCAL_LLM_MODEL`.

## Smoke test

После запуска сервера и настройки `.env`:

```bash
python -m llm.benchmark.smoke \
  --dialogs llm/data/DEV.json \
  --checklist checklists/default.json \
  --model mlx-community/Qwen3.5-4B-MLX-4bit \
  --ids p1-ru-001 p1-kz-001 p1-en-001 \
  --out llm/runs/vlm-smoke.json
```

Это технический smoke test, а не измерение точности: DEV не является gold set. Проверь `completed`, `failed`, `invalid`, latency и валидность evidence в JSON-отчёте.

## Интеграция

`backend/llm/local_provider.py` уже вызывает `/v1/chat/completions` и передаёт `response_format=json_schema`. Поэтому переход с LM на VLM не требует менять scoring API, схему оценки или промпты. Серверная поддержка JSON Schema не заменяет детерминированную проверку evidence и Pydantic-валидацию в приложении.

## Диагностика

Для сохранения сырых запросов/ответов включи локальный capture:

```dotenv
LOCAL_LLM_DEBUG_DIR=llm/runs/debug
```

Файлы могут содержать полный транскрипт. Не отправляй их публично без удаления персональных данных. По умолчанию capture выключен.

## Кандидаты

- Основной: `mlx-community/Qwen3.5-4B-MLX-4bit`.
- Gemma 4 E2B/E4B остаются альтернативами из `llm/benchmark/models.json`; поддержку конкретного checkpoint проверяй на установленной версии MLX-VLM.

Выбирай модель по gold-набору и отдельно по RU/KZ/EN, а не только по скорости или JSON-validity.
