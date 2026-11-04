#!/usr/bin/env bash
# Event capture belongs to assistant.service, never to this UI process.
# If Quickshell fails while an event is active, point the owner at its live file.
#
# §4.4 (WP0): on a start-limit hit the console unit stops quietly and this
# script emits ONE fallback notification — at most 1 per 10 minutes. Never a
# restart storm, never a notification storm.
set -u

[[ "${SERVICE_RESULT:-success}" != "success" ]] || exit 0
command -v assist >/dev/null 2>&1 || exit 0

# Rate limit: one notification per 600 s, enforced before any work that could
# notify (the stamp is per-user, under the runtime dir).
runtime_dir="${XDG_RUNTIME_DIR:-/tmp}"
stamp="$runtime_dir/elaria-event-console-fallback-$UID"
now=$(date +%s)
last=$(cat "$stamp" 2>/dev/null || printf '0')
if [[ "$last" =~ ^[0-9]+$ ]] && (( now - last < 600 )); then
    exit 0
fi

message=""
txt_path=""
status=$(assist event status 2>/dev/null) || status=""
if [[ -n "$status" ]]; then
    readarray -t fields < <(python3 -c '
import json, sys
try:
    value = json.load(sys.stdin)
except (ValueError, TypeError):
    raise SystemExit(1)
print("1" if value.get("running") else "0")
print(value.get("document", ""))
' <<<"$status" 2>/dev/null) || fields=()
    if [[ "${fields[0]:-0}" == "1" ]]; then
        md_path="${fields[1]:-}"
        if [[ -n "$md_path" ]]; then
            txt_path="${md_path%.md}.txt"
            message="The console is unavailable. Elaria is still listening; open the live text file."
        fi
    fi
fi
if [[ -z "$message" ]]; then
    message="The console is unavailable. Elaria is still answering from the daemon."
fi

printf '%s\n' "$now" > "$stamp"
{
    printf '%s' "$message"
    [[ -n "$txt_path" ]] && printf ' Live document: %s' "$txt_path"
    printf '\n'
} >&2
# NOTIFICATION PRIVACY (owner order 2026-10-26): notifications are signals,
# not carriers. The body is a fixed static sentence only — the live document
# path is journal material (stderr above), never notification content.
if command -v notify-send >/dev/null 2>&1; then
    if [[ -n "$txt_path" ]]; then
        notify-send "Elaria · event notebook" "$message" || true
    else
        notify-send "Elaria · console" "$message" || true
    fi
fi
if command -v xdg-open >/dev/null 2>&1 && [[ -n "$txt_path" && -f "$txt_path" ]]; then
    xdg-open "$txt_path" >/dev/null 2>&1 &
fi
