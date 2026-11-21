#!/bin/sh
# Literal-pin fallback, kept in a file rather than pasted through chat formatting.
# Trust this file from the selected immutable release, just like its manifest.
# Default: verification only. Optional explicit --install or --check-installed.
expected='c0a558a7116a38ef0b0abd68ca39f6994c93253f3b15f94ce81cc276ee8185fb'
case "${1-}" in
    ''|--install|--check-installed) ;;
    *) printf '%s\n' 'STOP exit=2 reason=unsupported_action'; exit 2 ;;
esac
if test "$#" -gt 1; then
    printf '%s\n' 'STOP exit=2 reason=extra_arguments'
    exit 2
fi
if root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P); then :; else
    printf '%s\n' 'STOP exit=2 reason=release_root_unavailable'
    exit 2
fi
target="$root/console/install_native_launcher.py"
if resolved=$(readlink -f -- "$target"); then target=$resolved; fi
actual=UNREADABLE
if computed=$(sha256sum -- "$target"); then actual=${computed%% *}; fi
printf 'VERIFY path=%s actual=%s expected=%s\n' "$target" "$actual" "$expected"
if test "${#expected}" -ne 64; then
    printf '%s\n' 'STOP exit=2 reason=malformed_expected_literal; not proof of source drift'
    exit 2
fi
case "$expected" in
    *[!0-9a-f]*) printf '%s\n' 'STOP exit=2 reason=malformed_expected_literal; not proof of source drift'; exit 2 ;;
esac
if test "$actual" = UNREADABLE; then
    printf '%s\n' 'STOP exit=2 reason=source_unreadable'
    exit 2
fi
if test "$actual" != "$expected"; then
    manifest_expected=$(awk '$2 == "console/install_native_launcher.py" {print $1}' "$root/console/native-launcher.sha256")
    if test "$actual" = "$manifest_expected"; then
        printf '%s\n' 'STOP exit=2 reason=literal_disagrees_with_matching_manifest; inspect expected literal/release identity, not presumed source drift'
    else
        printf '%s\n' 'STOP exit=2 reason=source_or_expected_pin_disagreement; verify release identity, neither source drift nor clipboard corruption is certified'
    fi
    exit 2
fi
printf '%s\n' 'PASS exit=0: installer literal pin verified; no config edit or reload'
if test "$#" -eq 0; then exit 0; fi
/usr/bin/python3 -IB "$target" "$1"
rc=$?
printf 'installer process exit=%s\n' "$rc"
exit "$rc"
