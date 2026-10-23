#!/usr/bin/env bash
# Event capture belongs to assistant.service, never to this UI process.
# If Quickshell fails while an event is active, point the owner at its live file.
set -u

[[ "${SERVICE_RESULT:-success}" != "success" ]] || exit 0
command -v assist >/dev/null 2>&1 || exit 0
status=$(assist event status 2>/dev/null) || exit 0
readarray -t fields < <(python3 -c '
import json, sys
try:
    value = json.load(sys.stdin)
except (ValueError, TypeError):
    raise SystemExit(1)
print("1" if value.get("running") else "0")
print(value.get("document", ""))
' <<<"$status") || exit 0
[[ "${fields[0]:-0}" == "1" ]] || exit 0
runtime_dir="${XDG_RUNTIME_DIR:-/tmp}"
stamp="$runtime_dir/elaria-event-console-fallback-$UID"
now=$(date +%s)
last=$(cat "$stamp" 2>/dev/null || printf '0')
if [[ "$last" =~ ^[0-9]+$ ]] && (( now - last < 60 )); then
    exit 0
fi
printf '%s\n' "$now" > "$stamp"
md_path="${fields[1]:-}"
[[ -n "$md_path" ]] || exit 0
txt_path="${md_path%.md}.txt"
message="The console is unavailable. Elaria is still listening; open the live text file."
printf '%s Live document: %s\n' "$message" "$txt_path" >&2
if command -v notify-send >/dev/null 2>&1; then
    notify-send "Elaria · event notebook" "$message"$'\n'"$txt_path" || true
fi
if command -v xdg-open >/dev/null 2>&1 && [[ -f "$txt_path" ]]; then
    xdg-open "$txt_path" >/dev/null 2>&1 &
fi
