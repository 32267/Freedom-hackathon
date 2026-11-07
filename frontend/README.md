# Frontend — CQA Studio

Vanilla HTML/CSS/JavaScript interface built with Web Components. No npm install, build step, framework, or third-party runtime dependency is required.

## Run with the backend (live data)

From the repository root: `uvicorn backend.main:app --port 8000`, then open http://localhost:8000 —
it serves this frontend and the API (`/api/...`) from one origin. Live mode loads the 65 DEV dialogs and their
saved evaluations; **Запустить оценку** calls the configured evaluators (Claude / Codex). Call recordings play
through `/api/dialogs/{id}/audio` (`audio_src`), because the organizers' `audio_url` is an HTML player page.

## Run in demo mode

From the repository root:

```bash
python -m http.server 8080
```

Open [http://localhost:8080/frontend/?mock=1](http://localhost:8080/frontend/?mock=1).

The demo adapter loads the checked-in conversation/evaluation fixtures and checklist. The interface labels this data as demo data; it does not call an LLM.

## Screens

- **Обзор** — KPI cards, score trend, language distribution, recent dialogs.
- **Диалоги** — searchable list with language/channel/status filters and selection.
- **Оценка** — transcript, checklist criteria, evidence navigation, RU/KZ/EN explanations, validation and critical-error indicators.

## Architecture

- `index.html` — application entry.
- `app.js` — shell and hash-based navigation.
- `api.js` — the only module that performs network requests; switches between API and fixture adapters with `?mock=1`.
- `components/cqa-*.js` — independently mountable custom elements.
- `styles.css` — shared responsive light theme.

The API adapter follows the data structures in `docs/CONTRACTS.md`. Live endpoints are not assumed to exist until the backend API work is merged. Evaluation submission in demo mode returns the checked-in mock evaluation and is not a real model inference.

## Manual smoke test

1. Open `/frontend/?mock=1`; confirm the demo indicator is visible.
2. On **Обзор**, open a dialog from the recent list and use **Все диалоги**.
3. On **Диалоги**, search by `fixture-chat-ru`; filter RU and chat; clear filters.
4. Select a row and open its evaluation.
5. On **Оценка**, switch explanation language RU/KZ/EN.
6. Open a criterion with evidence; click its quote and confirm the transcript scrolls to and highlights the referenced message.
7. Click **Запустить оценку**; confirm the demo result is shown and remains labelled as mock data.
8. Resize to mobile width and confirm the navigation collapses and columns stack.

## Known scope boundaries

This frontend slice implements the core overview, dialog browsing, and evaluation review experience. Batch evaluation/progress, checklist editing, appeals/review queue, audio seeking, provider preset availability, and production API integration remain separate tasks.