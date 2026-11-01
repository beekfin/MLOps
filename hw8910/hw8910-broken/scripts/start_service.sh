#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
unit=mlops-hw8910-serving
if systemctl --user is-active --quiet "$unit.service"; then
  echo 'Сервис уже запущен. После смены accepted.json: systemctl --user restart mlops-hw8910-serving.service'
  exit 0
fi
systemd-run --user --collect --unit="$unit" \
  --property=MemoryMax=3900M --property=MemoryHigh=3900M \
  --property=MemorySwapMax=0 --property=CPUQuota=250% \
  --property=OOMScoreAdjust=600 --property=Nice=8 \
  --working-directory="$project_root" \
  --setenv=OMP_NUM_THREADS=4 --setenv=MKL_NUM_THREADS=4 \
  --setenv=MALLOC_ARENA_MAX=2 --setenv=TOKENIZERS_PARALLELISM=false \
  --setenv=HF_HUB_OFFLINE=1 \
  "$project_root/.venv/bin/python" service.py --workspace .runtime/real \
  --backend transformers --port 8091 --warmup-seconds 1
