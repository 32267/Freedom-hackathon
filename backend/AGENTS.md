# backend/ — правила

- Python 3.11+, FastAPI, pydantic v2, sqlite3 из stdlib (без ORM). Зависимости — только через `requirements.txt`.
- `backend/scoring/` и `backend/llm/` — зона Ислама. Codex-2 вызывает только `scoring.evaluate()` и `scoring.recompute()`.
- Разработка API/UI без затрат: `SCORING_MODE=mock` в `.env` → фейковые оценки той же формы. `SCORING_MODE=llm` — настоящая модель.
- `scoring.evaluate()` синхронный и может идти 10–60 с: в эндпоинтах вызывать в фоне/потоке, ошибки — `backend.llm.LLMError`.
- Секреты только из `.env` (`python-dotenv`). Никогда не логировать `CQA_API_URL` целиком (в нём подпись).
- Каждый эндпоинт — тест в `tests/` через `fastapi.testclient`.
- Ошибки API: `{"error": "текст"}` + корректный HTTP-код.
