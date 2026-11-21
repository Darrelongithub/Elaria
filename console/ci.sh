#!/usr/bin/env bash
# Local-only; requires an existing interpreter with requirements-bridge.txt installed.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
command -v "${PYTHON:-python3}" >/dev/null
command -v node >/dev/null
node --check bridge-client.js
node wire-test.js
node wire-client-test.js
case "${1:-}" in
  '') ;;
  --legacy-fixtures)
    # Run on the immutable legacy K fixture, not on the release payload. No installs or writes.
    test -f index.html
    node smoke.js
    node wire-client-test.js --legacy-shell
    node audio-owner-test.js
    ;;
  *) echo 'usage: ci.sh [--legacy-fixtures]' >&2; exit 2 ;;
esac
