#!/usr/bin/env bash
# LOCAL-ONLY validation. No workflow registration, daemon, or automated CI wiring.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
command -v python3 >/dev/null
command -v node >/dev/null  # Never allow build.py's missing-Node fallback here.
command -v npm >/dev/null
npm install --prefix . --no-save --package-lock=false --ignore-scripts --no-audit --no-fund jsdom@30.1.3
python3 build.py
node smoke.js
node session-test.js
python3 - <<'PY'
from pathlib import Path
html = Path('index.html').read_text(encoding='utf-8')
assert 'src="http' not in html and 'href="http' not in html, 'external HTTP reference'
print('PASS: no src="http or href="http references in index.html')
PY
