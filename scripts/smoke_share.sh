#!/usr/bin/env bash
set -euo pipefail

echo "==[0] env =="
python -c "import sys; print(sys.executable)"
python -m pip -V

echo "==[1] clean install (non-editable) =="
python -m pip uninstall -y divpipe-engine >/dev/null 2>&1 || true
python -m pip install . --no-cache-dir

echo "==[2] entrypoint help =="
divpipe -h >/dev/null
divpipe severity -h >/dev/null
divpipe debug-link -h >/dev/null
divpipe ishares -h >/dev/null || true

echo "==[3] regenerate demo fixture run =="
python scripts/gen_synthetic_rows_fixture.py \
  --run-root output/runs/demo_run \
  --write-root-copy \
  --log-level INFO >/dev/null

test -f output/runs/demo_run/stage1_seed/seed_yfinance_dividends_all.csv
test -f output/runs/demo_run/stage1_seed/seed_yfinance_no_dividends_all.csv

echo "==[4] offline stage2 replay (no network, no qa-decisions) =="
RUN_ROOT="${RUN_ROOT:-output/runs/demo_run}"

divpipe severity --run-root "${RUN_ROOT}" >/dev/null

test -f "${RUN_ROOT}/stage2_analysis/econ_severity_summary.csv"
test -f "${RUN_ROOT}/stage2_analysis/qa_queue__econ.csv"
test -f "${RUN_ROOT}/stage2_analysis/qa_queue__rows.csv"

echo "==[5] debug-link invariance smoke =="
divpipe debug-link \
  --in "${RUN_ROOT}/stage1_seed/seed_yfinance_dividends_all.csv" \
  --fail-on-conflict \
  --fail-on-shuffle-diff >/dev/null

echo "==[6] regenerate QA demo fixture run =="
python scripts/gen_synthetic_rows_fixture.py \
  --run-root output/runs/demo_run_qa \
  --write-root-copy \
  --log-level INFO >/dev/null

QA_RUN_ROOT="${QA_RUN_ROOT:-output/runs/demo_run_qa}"
QA_DECISIONS="${QA_DECISIONS:-data/sample/overrides/qa_decisions_demo.csv}"

test -f "${QA_RUN_ROOT}/stage1_seed/seed_yfinance_dividends_all.csv"
test -f "${QA_RUN_ROOT}/stage1_seed/seed_yfinance_no_dividends_all.csv"
test -f "${QA_DECISIONS}"

python - <<'PY'
import pandas as pd
p = "output/runs/demo_run_qa/stage1_seed/seed_yfinance_dividends_all.csv"
df = pd.read_csv(p)
assert "vendor_event_id" in df.columns, "vendor_event_id missing in QA smoke input"
print("OK: vendor_event_id present")
PY

echo "==[7] offline stage2 replay with qa-decisions =="
divpipe severity \
  --run-root "${QA_RUN_ROOT}" \
  --qa-decisions "${QA_DECISIONS}" >/dev/null

test -f "${QA_RUN_ROOT}/stage2_analysis/econ_severity_summary.csv"
test -f "${QA_RUN_ROOT}/stage2_analysis/qa_queue__econ.csv"
test -f "${QA_RUN_ROOT}/stage2_analysis/qa_queue__rows.csv"

echo "==[OK] smoke_share passed =="