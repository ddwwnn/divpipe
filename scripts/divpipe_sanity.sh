#!/usr/bin/env bash
set -euo pipefail

echo "==[0] Working directory / environment =="
pwd
echo "VIRTUAL_ENV=${VIRTUAL_ENV:-<unset>}"
python -c "import sys; print('python =', sys.executable)"
python -m pip --version
python -m pip -V
echo

echo "==[1] Verify pyproject.toml console script entry (divpipe) =="
python - <<'PY'
import pathlib, re, sys
p = pathlib.Path("pyproject.toml")
if not p.exists():
    print("ERROR: pyproject.toml not found"); sys.exit(1)
t = p.read_text(encoding="utf-8", errors="replace")

def expect(val: str):
    ok = (val.strip() == "engine.divpipe.cli:main")
    print("divpipe =", val)
    print("OK" if ok else "ERROR: expected engine.divpipe.cli:main")
    sys.exit(0 if ok else 2)

m = re.search(r'(?s)\[project\.scripts\].*?\n\s*divpipe\s*=\s*"([^"]+)"', t)
if m: expect(m.group(1))

m = re.search(r'(?s)\[tool\.poetry\.scripts\].*?\n\s*divpipe\s*=\s*"([^"]+)"', t)
if m: expect(m.group(1))

print("ERROR: could not find a divpipe entry under [project.scripts] or [tool.poetry.scripts]")
sys.exit(3)
PY
echo

echo "==[2] Scan tracked files only for any remaining 'from/import src' (will break packaging) =="

python - <<'PY'
import subprocess
import sys
import re
from pathlib import Path

pattern = re.compile(r'(^|\s)(from|import)\s+src(\.|$)')
tracked = subprocess.run(
    ["git", "ls-files"],
    check=True,
    capture_output=True,
    text=True,
).stdout.splitlines()

bad = []

for rel in tracked:
    p = Path(rel)
    if not p.is_file():
        continue
    if p.suffix not in {".py", ".pyi"}:
        continue

    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        print(f"WARN: could not read {rel}: {e}")
        continue

    for i, line in enumerate(text.splitlines(), start=1):
        if pattern.search(line):
            bad.append((rel, i, line))

if bad:
    for rel, i, line in bad:
        print(f"{rel}:{i}:{line}")
    print("ERROR: found src.* imports in tracked files")
    sys.exit(10)

print("OK: no src.* imports found in tracked files")
PY
echo

echo "==[3] Reinstall editable package (clean) =="
python -m pip uninstall -y divpipe-engine >/dev/null 2>&1 || true
python -m pip install -e . --no-cache-dir
echo

echo "==[4] Verify installed console_scripts entry point (must be exactly one) =="
python - <<'PY'
from importlib.metadata import entry_points
eps = [e for e in entry_points(group="console_scripts") if e.name=="divpipe"]
print(eps)
if len(eps) == 0:
    raise SystemExit("ERROR: divpipe is not present in console_scripts")
if len(eps) != 1:
    raise SystemExit(f"ERROR: expected exactly 1 divpipe entry point, found {len(eps)}")
val = eps[0].value.strip()
print("OK: divpipe console_script =", val)
if val != "engine.divpipe.cli:main":
    raise SystemExit("ERROR: divpipe entry point is not engine.divpipe.cli:main")
PY
echo

echo "==[5] Confirm divpipe executable points at the virtual environment and imports engine.* =="
which divpipe
DIVPIPE="$(which divpipe)"
echo "--- head -n 20 ${DIVPIPE} ---"
head -n 20 "$DIVPIPE"
echo

python - "$DIVPIPE" <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1])
t = p.read_text(encoding="utf-8", errors="replace")
if "from engine.divpipe.cli import main" not in t:
    raise SystemExit("ERROR: divpipe wrapper does not import engine.divpipe.cli:main")
print("OK: divpipe wrapper imports engine.divpipe.cli:main")
PY
echo

echo "==[6] Confirm import path resolves correctly =="
python - <<'PY'
import importlib
m = importlib.import_module("engine.divpipe.cli")
print("OK: imported engine.divpipe.cli ->", m.__file__)
PY
echo

echo "==[7] Verify CLI help / subcommands are exposed =="
divpipe -h
echo
divpipe ingest -h || true
echo
divpipe severity -h || true
echo
divpipe debug-link -h || true
echo

echo "==[8] (Optional) If the iShares subcommand exists, show its help =="
divpipe ishares -h >/dev/null 2>&1 && divpipe ishares -h || echo "(skip) divpipe ishares subcommand not present"
echo

echo "==[9] (Optional) Smoke run: short ingest window =="
BGN="${BGN:-20250101}"
END="${END:-20250131}"
RUN_INGEST_SMOKE="${RUN_INGEST_SMOKE:-0}"

if [[ "${RUN_INGEST_SMOKE}" != "1" ]]; then
  echo "(skip) set RUN_INGEST_SMOKE=1 to enable live ingest smoke"
elif test -f data/holdings_EEM.csv && test -f data/holdings_EFA.csv; then
  echo "Running: divpipe ingest --bgn ${BGN} --end ${END}"
  divpipe ingest \
    --holdings data/holdings_EEM.csv data/holdings_EFA.csv \
    --bgn "${BGN}" \
    --end "${END}"
else
  echo "(skip) holdings files not found; skipping ingest"
fi
echo

echo "==[10] (Optional) debug-link smoke =="
DEBUG_LINK_IN="${DEBUG_LINK_IN:-output/runs/demo_run/stage1_seed/seed_yfinance_dividends_all.csv}"

if test -f "${DEBUG_LINK_IN}"; then
  echo "Running: divpipe debug-link --in ${DEBUG_LINK_IN}"
  divpipe debug-link \
    --in "${DEBUG_LINK_IN}" \
    --fail-on-conflict \
    --fail-on-shuffle-diff
else
  echo "(skip) debug-link input not found; skipping debug-link smoke"
fi
echo

echo "==[DONE] If all checks pass, the package is ready to share =="