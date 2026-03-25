#!/usr/bin/env bash
set -euo pipefail

echo "==[cleanup] uninstall editable package =="
python -m pip uninstall -y divpipe-engine >/dev/null 2>&1 || true

echo "==[cleanup] remove local egg-info (repo) =="
find . -name "*.egg-info" -prune -exec rm -rf {} \;

echo "==[cleanup] remove editable artefacts (venv site-packages only) =="
if [[ -d ".venv/lib" ]]; then
  find .venv/lib -path "*/site-packages/divpipe_engine-*.dist-info" -prune -exec rm -rf {} \; 2>/dev/null || true
  find .venv/lib -path "*/site-packages/__editable__.divpipe_engine-*.pth" -exec rm -f {} \; 2>/dev/null || true
fi

echo "==[cleanup] remove stale divpipe wrapper (venv bin) =="
rm -f .venv/bin/divpipe 2>/dev/null || true

echo "==[cleanup] reinstall editable (no cache) =="
python -m pip install -e . --no-cache-dir

echo "==[cleanup] verify console_scripts(divpipe) =="
python - <<'PY'
from importlib.metadata import entry_points
eps = [e for e in entry_points(group="console_scripts") if e.name=="divpipe"]
print(eps)
PY