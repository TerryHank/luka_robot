#!/usr/bin/env bash
set -euo pipefail
base=/home/sunrise/luka_ws/src/system/luka_xiaozhi
sdk=/home/sunrise/luka_data/runtime/oellm/sdk-1.0.0/D-Robotics_LLM_S100_1.0.0_SDK/oellm_runtime
python3 - <<'PY'
from pathlib import Path
import struct
model=Path('/proc/device-tree/model').read_bytes().rstrip(b'\0').decode()
if model != 'D-Robotics RDK S100 V1P1':
    raise SystemExit('This deployment is validated only for RDK S100 V1P1')
node=next(Path('/proc/device-tree/reserved-memory').glob('ion_carveout*'))
reg=(node/'reg').read_bytes()
if len(reg)!=16 or struct.unpack('>QQ',reg)[1] < 2*1024**3:
    raise SystemExit('OELLM requires at least 2 GiB carveout; boot memory profile has not been applied')
PY
export LIBXLM_PATH="$sdk/lib/libxlm.so"
export LD_LIBRARY_PATH="$sdk/lib:${LD_LIBRARY_PATH:-}"
exec python3 -u "$base/oellm_server/openai_server.py" \
  --model-type 7 \
  --hbm-path /home/sunrise/luka_data/ml_models/oellm/Qwen2.5_1.5B_Instruct_1024.hbm \
  --tokenizer-dir "$sdk/config/Qwen2.5_1.5B_Instruct_config" \
  --template-path "$base/oellm_server/raw_chatml.jinja" \
  --bpu-core -1 --host 127.0.0.1 --port "${LUKA_OELLM_PORT:-8092}" \
  --model-id qwen2.5-1.5b-instruct-bpu
