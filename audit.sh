#!/usr/bin/env bash
# Elaria audit — one paste, one output file. Read-only: writes nothing to the repo.
set -u
cd "${1:-$PWD}"
OUT=/tmp/elaria-audit.txt
: > "$OUT"
say() { printf '\n===== %s =====\n' "$1" | tee -a "$OUT"; }
run() { printf '\n--- %s ---\n' "$1" >> "$OUT"; shift; "$@" >> "$OUT" 2>&1 || printf '(command failed: %s)\n' "$*" >> "$OUT"; }

say "A. IDENTITY"
{
  echo "branch: $(git rev-parse --abbrev-ref HEAD)"
  echo "head:   $(git rev-parse --short HEAD)"
  echo "origin: $(git rev-parse --short origin/main 2>/dev/null || echo unknown)"
  echo "ahead/behind: $(git rev-list --left-right --count origin/main...HEAD 2>/dev/null || echo '?')"
  echo "dirty files: $(git status --short | wc -l)"
  git status --short | head -20
} >> "$OUT" 2>&1
sed -n '/A. IDENTITY/,$p' "$OUT" | tail -12

COV=""
uv run python -c "import pytest_cov" >/dev/null 2>&1 && COV="--cov=src/assistant --cov-report=term-missing:skip-covered"

say "B. FULL SUITE (this takes ~9 min; be patient)"
uv run pytest -q -rs --durations=25 $COV > /tmp/pytest-full.txt 2>&1
tail -40 /tmp/pytest-full.txt >> "$OUT"
echo "(full log at /tmp/pytest-full.txt)" >> "$OUT"
tail -40 /tmp/pytest-full.txt

say "C. FAILING TESTS, NAMED"
grep -E "^(FAILED|ERROR)" /tmp/pytest-full.txt >> "$OUT" 2>/dev/null || echo "(none)" >> "$OUT"
tail -20 "$OUT"

say "D. SKIPS AND XFAILS"
grep -E "^(SKIPPED|XFAIL)" /tmp/pytest-full.txt >> "$OUT" 2>/dev/null || echo "(none)" >> "$OUT"

say "E. COVERAGE — modules with the least"
grep -E "^src/assistant.*[0-9]+%" /tmp/pytest-full.txt | sort -t'%' -k1 -n | head -30 >> "$OUT" 2>/dev/null

say "F. STATIC SMELLS"
for pat in 'except Exception' 'except:' 'bare pass' 'TODO' 'FIXME' 'HACK' 'noqa' 'type: ignore' 'print(' 'time.sleep'; do
  n=$(grep -rn --include='*.py' -F "$pat" src/ 2>/dev/null | wc -l)
  printf '%-18s %s\n' "$pat" "$n" >> "$OUT"
done
echo "--- bare 'except:' lines ---" >> "$OUT"
grep -rn --include='*.py' -E "except\s*:" src/ 2>/dev/null | head -20 >> "$OUT"

say "G. SIZE — files over 600 lines"
find src -name '*.py' -exec wc -l {} + 2>/dev/null | sort -rn | awk '$1>600 && $2!="total"' | head -20 >> "$OUT"

say "H. SAFETY INVARIANTS"
{
  echo "--- interpreter/allowlist mentions ---"
  grep -rn --include='*.py' -iE "allowlist|allow_list|interpreter" src/assistant/hands/ | head -15
  echo "--- sms.send_sms call sites ---"
  grep -rn --include='*.py' "send_sms" src/ | head -10
  echo "--- fail-closed / refused returns ---"
  grep -rc --include='*.py' "refused" src/assistant/hands/*.py | head -15
  echo "--- muted writers ---"
  grep -rn --include='*.py' '"muted"\]\s*=\|muted=' src/assistant/ | head -20
} >> "$OUT" 2>&1

say "I. REAL DESKTOP vs SIMULATOR"
{
  echo "tests touching SyntheticSpace: $(grep -rl 'SyntheticSpace' tests/ | wc -l) files"
  echo "tests referencing hyprctl/wayland/atspi: $(grep -rliE 'hyprctl|wayland|atspi|layer.shell' tests/ | wc -l) files"
  grep -rliE 'hyprctl|wayland|atspi|layer.shell' tests/ | head -10
} >> "$OUT" 2>&1

say "J. INGESTION ORIGINS — armed vs accepted"
uv run python - <<'PY' >> "$OUT" 2>&1
import json, sys
sys.path.insert(0, 'src')
try:
    from assistant.hands.injection import ORIGINS
    accepted = set(ORIGINS)
except Exception as e:
    accepted, err = set(), e
    print("import failed:", err)
try:
    inv = json.load(open('fixtures/hands/inventory.json'))
    armed = {e['origin'] for e in inv['trap_arm_manifest']}
except Exception as e:
    armed = set(); print("fixture read failed:", e)
print("accepted :", sorted(accepted))
print("armed    :", sorted(armed))
print("UNARMED  :", sorted(accepted - armed))
PY

say "K. LINT"
uv run ruff check . >> "$OUT" 2>&1
tail -3 "$OUT"
uv run mypy --version >/dev/null 2>&1 && run "mypy" uv run mypy src/assistant --ignore-missing-imports

say "DONE"
echo "wrote $OUT ($(wc -l < "$OUT") lines) — paste it here"
