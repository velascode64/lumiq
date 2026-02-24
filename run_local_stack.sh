#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_URL="${LUMIQ_CORE_API_URL:-http://127.0.0.1:8000}"
API_HOST="${LUMIQ_CORE_API_HOST:-0.0.0.0}"
API_PORT="${LUMIQ_CORE_API_PORT:-8000}"

CORE_PID=""
BOT_PID=""

cleanup() {
  set +e
  if [[ -n "${BOT_PID}" ]] && kill -0 "${BOT_PID}" 2>/dev/null; then
    kill "${BOT_PID}" 2>/dev/null || true
  fi
  if [[ -n "${CORE_PID}" ]] && kill -0 "${CORE_PID}" 2>/dev/null; then
    kill "${CORE_PID}" 2>/dev/null || true
  fi
  wait 2>/dev/null || true
}

trap cleanup EXIT INT TERM

echo "[stack] starting core api on ${API_HOST}:${API_PORT}"
conda run --no-capture-output -n lumiq \
  python "${ROOT_DIR}/core/run_api.py" --host "${API_HOST}" --port "${API_PORT}" &
CORE_PID=$!

echo "[stack] waiting for core api to boot..."
for _ in $(seq 1 30); do
  if curl -fsS "${API_URL}/health" >/dev/null 2>&1; then
    echo "[stack] core api is healthy"
    break
  fi
  sleep 1
done

if ! curl -fsS "${API_URL}/health" >/dev/null 2>&1; then
  echo "[stack] core api did not become healthy at ${API_URL}/health"
  exit 1
fi

echo "[stack] starting telegram frontend (api=${API_URL})"
conda run --no-capture-output -n lumiq \
  python "${ROOT_DIR}/telegram_bot/run_bot.py" --api-base-url "${API_URL}" &
BOT_PID=$!

wait "${BOT_PID}"

