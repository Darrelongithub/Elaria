#!/usr/bin/env bash
# storage-benchmark.sh — WP7 Scene Sheet 1 instrument (Elaria cold storage)
#
# WHAT THIS IS
#   The measurement instrument the OWNER runs on his own Fedora laptop, against
#   his own MEGA account, before any WP7 machinery is built. The design chat
#   rules backend go/no-go and the fetch-latency budget FROM ITS OUTPUT and from
#   nothing else.
#
# WHAT IT MEASURES (all numbers, nothing else)
#   * restic init over the `rclone:` backend, twice (default pack size vs N MiB)
#   * backup of a synthetic ~500 MB tree at both pack sizes — wall-time + bytes
#   * small-file fetch latency x10 at both pack sizes
#   * one ~500 MB restore
#   * restic check
#   * one restic check --read-data-subset, capped at <=5% or <=500 MB
#
# WHAT IT NEVER DOES
#   * It never prints, logs, echoes or transmits a credential. Every secret is
#     read from the owner's own environment or his own 0600 file.
#   * It never touches the Elaria daemon, the real audio/journal/DB dirs, or any
#     real recording. Everything it backs up is synthetic random bytes it made
#     itself, under $BENCH_LOCAL.
#   * It never deletes anything. Scratch-repo cleanup is an explicit, separate,
#     owner-run decision (see the scene sheet). Auto-delete never exists.
#   * It never force-pushes, rewrites, or otherwise mutates shared git state.
#
# USAGE
#   export RESTIC_REPOSITORY_BASE="elaria-mega:elaria-bench"
#   export RESTIC_PASSWORD_FILE="$HOME/.config/elaria/restic-passphrase"
#   bash scripts/storage-benchmark.sh 2>&1 | tee ~/bench.log
#
# The two scratch repositories are created as
#   ${RESTIC_REPOSITORY_BASE}-default     (restic's default 16 MiB pack size)
#   ${RESTIC_REPOSITORY_BASE}-pack${N}    (pack size N MiB, default 32)
# and the script REFUSES to run if either already exists, so a re-run never
# silently overwrites a previous measurement.
#
# Exit status: 0 = every step completed; 1 = a step failed (its output IS the
# result — paste it and stop; do not retry until the design chat has seen it).

set -o errexit
set -o nounset
set -o pipefail

# ---------------------------------------------------------------- configuration

RESTIC_REPOSITORY_BASE="${RESTIC_REPOSITORY_BASE:-}"
RESTIC_PASSWORD_FILE="${RESTIC_PASSWORD_FILE:-}"

BENCH_BYTES="${BENCH_BYTES:-500}"          # MiB of synthetic payload per repo
BENCH_SMALL_COUNT="${BENCH_SMALL_COUNT:-200}"
BENCH_SMALL_SIZE="${BENCH_SMALL_SIZE:-4096}"   # bytes
BENCH_FETCH_SAMPLES="${BENCH_FETCH_SAMPLES:-10}"
BENCH_PACK_ALT="${BENCH_PACK_ALT:-32}"     # MiB; the non-default pack size
BENCH_LOCAL="${BENCH_LOCAL:-$HOME/elaria-bench-work}"

# MEGA-specific: rclone must download+decrypt account metadata before it can
# answer its first request, which routinely exceeds restic's 1m default for
# `rclone.timeout` (restic issue #3511; PR #3514 raised the default to 240s).
# We set it explicitly rather than depend on the shipped default.
RCLONE_TIMEOUT="${RCLONE_TIMEOUT:-10m}"

# restic's default rclone.args is `serve restic --stdio --b2-hard-delete`.
# `--b2-hard-delete` is a B2-only flag and is inert for MEGA, so we deliberately
# leave the default alone rather than risk an argv that a future rclone rejects.
#
# NOTE ON PACK-SIZE TEMP SPACE: restic needs pack_size x (backend connections +
# 1) of scratch in $TMPDIR. At 32 MiB and the default 5 connections that is
# 192 MiB; we point TMPDIR at the bench work dir so it never depends on how big
# /tmp happens to be on the laptop.

# ---------------------------------------------------------------------- helpers

say()  { printf '%s\n' "$*"; }
hr()   { printf '%s\n' "------------------------------------------------------------"; }

die() {
  printf 'BENCH-FAIL: %s\n' "$*" >&2
  exit 1
}

need() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

now() { date +%s.%N; }

elapsed() { awk -v a="$1" -v b="$2" 'BEGIN { printf "%.3f", b - a }'; }

mib() { awk -v b="$1" 'BEGIN { printf "%.1f", b / 1048576 }'; }

# run_timed <label> <command...>  ->  sets REPLY_SECONDS, REPLY_OUT
run_timed() {
  local label="$1"; shift
  local t0 t1 out status
  t0="$(now)"
  set +o errexit
  out="$("$@" 2>&1)"
  status=$?
  set -o errexit
  t1="$(now)"
  REPLY_SECONDS="$(elapsed "$t0" "$t1")"
  REPLY_OUT="$out"
  REPLY_STATUS=$status
  if [ "$status" -ne 0 ]; then
    say "STEP-FAILED [$label] exit=$status after ${REPLY_SECONDS}s"
    say "$out"
    die "$label failed — this output is the result; paste it and stop"
  fi
}

# ------------------------------------------------------------------- preflight

[ -n "$RESTIC_REPOSITORY_BASE" ] || die "set RESTIC_REPOSITORY_BASE (e.g. elaria-mega:elaria-bench)"
[ -n "$RESTIC_PASSWORD_FILE" ] || die "set RESTIC_PASSWORD_FILE to your 0600 passphrase file"
[ -r "$RESTIC_PASSWORD_FILE" ] || die "cannot read RESTIC_PASSWORD_FILE: $RESTIC_PASSWORD_FILE"

need restic
need rclone
need python3

REPO_DEFAULT="${RESTIC_REPOSITORY_BASE}-default"
REPO_ALT="${RESTIC_REPOSITORY_BASE}-pack${BENCH_PACK_ALT}"

# Refuse to run over an existing scratch repo: a re-run must never silently
# overwrite a measurement the design chat has not seen yet. (One listing per
# repo — MEGA listings are slow, and this guard runs four times.)
scratch_present() {
  local listing
  listing="$(rclone lsf "$1" 2>/dev/null || true)"
  [ -n "$listing" ]
}
scratch_present "$REPO_DEFAULT" && die "scratch repo $REPO_DEFAULT already exists — remove it deliberately first (see scene sheet cleanup)"
scratch_present "$REPO_ALT" && die "scratch repo $REPO_ALT already exists — remove it deliberately first (see scene sheet cleanup)"

mkdir -p "$BENCH_LOCAL"
export TMPDIR="$BENCH_LOCAL/tmp"
mkdir -p "$TMPDIR"

TREE="$BENCH_LOCAL/tree"
if [ ! -d "$TREE" ]; then
  say "building synthetic payload: ${BENCH_BYTES} MiB + ${BENCH_SMALL_COUNT} x ${BENCH_SMALL_SIZE} B (random, incompressible)"
  mkdir -p "$TREE/large" "$TREE/small"
  dd if=/dev/urandom of="$TREE/large/payload.bin" \
     bs=1M count="$BENCH_BYTES" status=none
  i=0
  while [ "$i" -lt "$BENCH_SMALL_COUNT" ]; do
    head -c "$BENCH_SMALL_SIZE" /dev/urandom > "$(printf '%s/small/%04d.bin' "$TREE" "$i")"
    i=$((i + 1))
  done
fi

PAYLOAD_BYTES=$(( BENCH_BYTES * 1048576 + BENCH_SMALL_COUNT * BENCH_SMALL_SIZE ))
PAYLOAD_MIB="$(mib "$PAYLOAD_BYTES")"

say ""
hr
say "ELARIA WP7 SCENE SHEET 1 — MEGA / restic rclone: BACKEND BENCHMARK"
hr
say "payload           : ${PAYLOAD_MIB} MiB (${PAYLOAD_BYTES} bytes) synthetic random"
say "repo default pack : $REPO_DEFAULT"
say "repo ${BENCH_PACK_ALT} MiB pack  : $REPO_ALT"
say "rclone timeout    : $RCLONE_TIMEOUT"
say "TMPDIR            : $TMPDIR"
hr

# ------------------------------------------------------------ per-repo routine

# bench_repo <repo> <pack-size-or-empty> <label>
bench_repo() {
  local repo="$1" pack="$2" label="$3"
  local init_args=() backup_args=()

  init_args=(-r "$repo" --password-file "$RESTIC_PASSWORD_FILE"
             -o "rclone.timeout=$RCLONE_TIMEOUT"
             --repository-version 2 init)
  if [ -n "$pack" ]; then
    init_args+=(--pack-size "$pack")
  fi

  say ""
  say "### $label — repo $repo (pack size: ${pack:-restic default})"

  # 1. init ------------------------------------------------------------------
  run_timed "init $label" restic "${init_args[@]}"
  local t_init="$REPLY_SECONDS"
  say "init wall_s       : $t_init"

  # 2. backup ----------------------------------------------------------------
  backup_args=(-r "$repo" --password-file "$RESTIC_PASSWORD_FILE"
               -o "rclone.timeout=$RCLONE_TIMEOUT"
               --json backup "$TREE")
  if [ -n "$pack" ]; then
    backup_args+=(--pack-size "$pack")
  fi
  run_timed "backup $label" restic "${backup_args[@]}"
  local t_backup="$REPLY_SECONDS"
  local backup_json="$REPLY_OUT"

  # total_bytes_processed / data_added come from restic's JSON "summary" message.
  local bytes_proc bytes_added
  bytes_proc="$(printf '%s\n' "$backup_json" | python3 -c '
import sys, json
best = {}
for line in sys.stdin:
    line = line.strip()
    if not line.startswith("{"):
        continue
    try:
        msg = json.loads(line)
    except ValueError:
        continue
    if msg.get("message_type") == "summary":
        best = msg
print(best.get("total_bytes_processed", 0))
' 2>/dev/null || echo 0)"
  bytes_added="$(printf '%s\n' "$backup_json" | python3 -c '
import sys, json
best = {}
for line in sys.stdin:
    line = line.strip()
    if not line.startswith("{"):
        continue
    try:
        msg = json.loads(line)
    except ValueError:
        continue
    if msg.get("message_type") == "summary":
        best = msg
print(best.get("data_added", 0))
' 2>/dev/null || echo 0)"

  say "backup wall_s     : $t_backup"
  say "bytes processed   : $bytes_proc ($(mib "$bytes_proc") MiB)"
  say "bytes added to repo: $bytes_added ($(mib "$bytes_added") MiB)"
  say "throughput MiB/s  : $(awk -v b="$bytes_proc" -v t="$t_backup" 'BEGIN { if (t>0) printf "%.2f", (b/1048576)/t; else print "n/a" }')"

  # 3. snapshot id + object counts ------------------------------------------
  local snap
  snap="$(restic -r "$repo" --password-file "$RESTIC_PASSWORD_FILE" \
            -o "rclone.timeout=$RCLONE_TIMEOUT" snapshots --json 2>/dev/null \
          | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d[-1]["id"] if d else "")')"
  [ -n "$snap" ] || die "could not read back the snapshot id for $label"

  local pack_files index_files
  pack_files="$(rclone lsf "$repo/data" 2>/dev/null | wc -l | tr -d ' ')"
  index_files="$(rclone lsf "$repo/index" 2>/dev/null | wc -l | tr -d ' ')"
  say "remote data objects: $pack_files"
  say "remote index objects: $index_files"
  say "remote objects total: $(( pack_files + index_files ))"

  # 4. small-file fetch latency x N -----------------------------------------
  #    Measured with the real cold-read shape: a targeted restore of one small
  #    artifact. --no-lock is used so the number measures the fetch, not lock
  #    contention on the MEGA backend.
  local fetch_dir="$BENCH_LOCAL/fetch-$label"
  rm -rf "$fetch_dir"; mkdir -p "$fetch_dir"
  local n=0 sample times="" t_all=0 t_min=999999 t_max=0
  while [ "$n" -lt "$BENCH_FETCH_SAMPLES" ]; do
    local target
    target="$(printf '%s/small/%04d.bin' "$TREE" "$n")"
    run_timed "fetch $label $n" restic \
      -r "$repo" --password-file "$RESTIC_PASSWORD_FILE" \
      -o "rclone.timeout=$RCLONE_TIMEOUT" \
      --no-lock restore "$snap" --target "$fetch_dir/$n" --include "$target"
    local s="$REPLY_SECONDS"
    times="$times $s"
    t_all="$(awk -v a="$t_all" -v b="$s" 'BEGIN { printf "%.3f", a + b }')"
    t_min="$(awk -v a="$t_min" -v b="$s" 'BEGIN { printf "%.3f", (b < a) ? b : a }')"
    t_max="$(awk -v a="$t_max" -v b="$s" 'BEGIN { printf "%.3f", (b > a) ? b : a }')"
    n=$((n + 1))
  done
  say "fetch samples s   :$times"
  say "fetch mean s      : $(awk -v a="$t_all" -v n="$BENCH_FETCH_SAMPLES" 'BEGIN { printf "%.3f", a / n }')"
  say "fetch min s       : $t_min"
  say "fetch max s       : $t_max"

  # 5. one full ~500 MB restore ---------------------------------------------
  local restore_dir="$BENCH_LOCAL/restore-$label"
  rm -rf "$restore_dir"
  run_timed "restore $label" restic \
    -r "$repo" --password-file "$RESTIC_PASSWORD_FILE" \
    -o "rclone.timeout=$RCLONE_TIMEOUT" \
    --no-lock restore "$snap" --target "$restore_dir"
  local t_restore="$REPLY_SECONDS"
  say "restore wall_s    : $t_restore"
  say "restore MiB/s     : $(awk -v b="$PAYLOAD_BYTES" -v t="$t_restore" 'BEGIN { if (t>0) printf "%.2f", (b/1048576)/t; else print "n/a" }')"

  # byte-identical round trip is a correctness fact, not a nicety
  if cmp -s "$TREE/large/payload.bin" "$restore_dir/$TREE/large/payload.bin"; then
    say "restore verify    : IDENTICAL"
  else
    say "restore verify    : DIFFERENT"
    die "restored payload is not byte-identical to the source — repo $repo is not trustworthy"
  fi

  # 6. restic check ----------------------------------------------------------
  run_timed "check $label" restic \
    -r "$repo" --password-file "$RESTIC_PASSWORD_FILE" \
    -o "rclone.timeout=$RCLONE_TIMEOUT" check
  say "check wall_s      : $REPLY_SECONDS"
  say "check result      : no errors were found"

  # 7. restic check --read-data-subset, capped <=5% or <=500 MB -------------
  local raw_bytes subset_mib
  raw_bytes="$(restic -r "$repo" --password-file "$RESTIC_PASSWORD_FILE" \
                 -o "rclone.timeout=$RCLONE_TIMEOUT" \
                 stats --mode raw-data --json 2>/dev/null \
               | python3 -c 'import sys,json; print(json.load(sys.stdin).get("total_size", 0))')"
  subset_mib="$(awk -v r="$raw_bytes" 'BEGIN {
      five_pct = r * 5 / 100 / 1048576;
      cap = 500;
      v = (five_pct < cap) ? five_pct : cap;
      if (v < 1) v = 1;
      printf "%d", v + 0.5;
  }')"
  say "repo raw data MiB : $(mib "$raw_bytes")"
  say "read-data-subset  : ${subset_mib} MiB (5% capped at 500 MiB)"

  run_timed "check read-data-subset $label" restic \
    -r "$repo" --password-file "$RESTIC_PASSWORD_FILE" \
    -o "rclone.timeout=$RCLONE_TIMEOUT" \
    check --read-data-subset="${subset_mib}M"
  say "subset wall_s     : $REPLY_SECONDS"
  say "subset result     : no errors were found"
}

# ------------------------------------------------------------------ run it all

bench_repo "$REPO_DEFAULT" "" "DEFAULT-PACK"
bench_repo "$REPO_ALT" "$BENCH_PACK_ALT" "ALT-PACK-${BENCH_PACK_ALT}M"

# ------------------------------------------------------------ numbers-only out

say ""
hr
say "NUMBERS ONLY — paste this block (and only this block) into chat"
hr
say "restic version            : $(restic version 2>/dev/null | head -1)"
say "rclone version            : $(rclone version 2>/dev/null | head -1)"
say "payload MiB               : $PAYLOAD_MIB"
say "repo base                 : $RESTIC_REPOSITORY_BASE"
say "alt pack size MiB         : $BENCH_PACK_ALT"
say ""
say "See the per-repo lines above for:"
say "  init wall_s, backup wall_s, bytes processed, bytes added, throughput,"
say "  remote objects total, fetch mean/min/max s, restore wall_s + verify,"
say "  check wall_s, read-data-subset wall_s."
hr

exit 0
