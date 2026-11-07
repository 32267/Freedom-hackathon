#!/usr/bin/env bash
set -euo pipefail

MODEL="${LOCAL_LLM_MODEL:-mlx-community/Qwen3.5-4B-MLX-4bit}"
PORT="${LOCAL_LLM_PORT:-8080}"

echo "Starting MLX-VLM with model: ${MODEL}"
echo "OpenAI-compatible API: http://localhost:${PORT}/v1"

exec python -m mlx_vlm.server --model "${MODEL}" --port "${PORT}"
