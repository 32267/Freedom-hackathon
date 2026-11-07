#!/usr/bin/env bash
# Публичная ссылка на локальный сервер через Cloudflare Tunnel (быстрый туннель, аккаунт не нужен).
#   scripts/tunnel.sh            → поднимет сервер (если не запущен) и выдаст https://<...>.trycloudflare.com
# Посетители по ссылке вводят логин/пароль из CQA_BASIC_AUTH в .env. Локально пароль не спрашивается.
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${PORT:-8000}"

command -v cloudflared >/dev/null || { echo "Нужен cloudflared: brew install cloudflared"; exit 1; }

if ! grep -q '^CQA_BASIC_AUTH=.' .env 2>/dev/null; then
  pass="$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 16)"
  echo "CQA_BASIC_AUTH=freedom:${pass}" >> .env
  echo "Создан пароль для публичной ссылки — смотрите CQA_BASIC_AUTH в .env (логин: freedom)."
fi

if ! curl -fs "http://localhost:${PORT}/api/health" >/dev/null; then
  echo "Запускаю сервер на :${PORT}…"
  .venv/bin/uvicorn backend.main:app --port "${PORT}" > data/uvicorn.log 2>&1 &
  for _ in $(seq 1 20); do curl -fs "http://localhost:${PORT}/api/health" >/dev/null && break; sleep 1; done
fi

echo "Открываю туннель Cloudflare… ссылка появится ниже (строка с trycloudflare.com). Ctrl+C — закрыть."
exec cloudflared tunnel --no-autoupdate --url "http://localhost:${PORT}"
