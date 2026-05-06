#!/usr/bin/env bash
# Launch llama-server (via llama-cpp-python) reading models/active.json.
# Linux + macOS. Windows users: see start-server.ps1.
set -euo pipefail

cd "$(dirname "$0")/.."

MODEL=$(python -c 'import json; print(json.load(open("models/active.json"))["primary_model"])')
THREADS=$(python -c 'import json; hw=json.load(open("hardware.json")); print(hw["cpu"].get("cores_physical") or 4)')
GPU_LAYERS="${LAB_N_GPU_LAYERS:-99}"
PARALLEL="${LAB_PARALLEL:-4}"
CTX="${LAB_N_CTX:-2048}"
PORT="${LAB_SERVER_PORT:-8080}"

echo "==> Starting llama-server"
echo "    model     : $MODEL"
echo "    threads   : $THREADS"
echo "    gpu_layers: $GPU_LAYERS"
echo "    parallel  : $PARALLEL"
echo "    ctx       : $CTX"
echo "    listening : http://0.0.0.0:$PORT"
echo

LLAMA_SERVER_BIN="${LLAMA_SERVER_BIN:-$(command -v llama-server 2>/dev/null || echo /home/son/llama.cpp/build/bin/llama-server)}"

if [ -x "$LLAMA_SERVER_BIN" ]; then
  # llama.cpp native server supports Prometheus /metrics and parallel slots.
  exec "$LLAMA_SERVER_BIN" \
      -m "$MODEL" \
      --host 0.0.0.0 --port "$PORT" \
      -t "$THREADS" \
      -ngl "$GPU_LAYERS" \
      -c "$CTX" \
      --parallel "$PARALLEL" \
      --metrics
else
  echo "WARN: 'llama-server' binary not found. Falling back to python server (no /metrics endpoint)."
  exec python -m llama_cpp.server \
      --model "$MODEL" \
      --host 0.0.0.0 --port "$PORT" \
      --n_threads "$THREADS" \
      --n_gpu_layers "$GPU_LAYERS" \
      --n_ctx "$CTX"
fi
