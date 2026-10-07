#!/usr/bin/env bash
# Run a task under one condition with SkillTerminus against the local vLLM server.
#   scripts/run_terminus.sh <task-id> <C0..C5> [extra harbor args]
set -euo pipefail
cd "$(dirname "$0")/.."

TASK=${1:?task id}
COND=${2:?condition C0..C5}
shift 2

VLLM_URL=${VLLM_URL:-http://localhost:8000/v1}
MAX_LEN=${MAX_MODEL_LEN:-32768}
MODEL_INFO="{\"max_input_tokens\": ${MAX_LEN}, \"max_output_tokens\": 4096, \"input_cost_per_token\": 0, \"output_cost_per_token\": 0}"

mapfile -t COND_ARGS < <(uv run python -c "
import sys
from sb.conditions import make_trial, harbor_args
print('\n'.join(harbor_args(make_trial(sys.argv[1], sys.argv[2]))))
" "$TASK" "$COND")

uv run harbor run \
  "${COND_ARGS[@]}" \
  -m hosted_vllm/agent \
  --ak "api_base=${VLLM_URL}" \
  --ak "model_info=${MODEL_INFO}" \
  --ak max_turns=30 \
  --ak suppress_max_turns_warning=true \
  --ak enable_summarize=false \
  --ak temperature=0.7 \
  --job-name "${TASK}__${COND}__$(date +%Y%m%d-%H%M%S)" \
  -o jobs -n 1 \
  "$@"
