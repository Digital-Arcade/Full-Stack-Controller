#!/usr/bin/env bash
# install-feed-check.sh - the relay reports EVERY run to the controller, and
# the stale alert says why.
#
# WHY: the importer only hears from relay.sh when the vendor's file CHANGED.
# From 2026-10-04 03:47 to 10-05 12:49 the relay fetched the file 58 times,
# found it identical every time, and said so only in /var/log/feed-relay.log.
# From the controller a quiet vendor and a dead relay looked the same: "last
# import 33h ago". The 09:07 dead-man alert said STALE and could not say which.
#
# WHAT IT CHANGES (two scripts, edited in place, originals kept beside them):
#   /usr/local/bin/relay.sh         after a run that did NOT import - file
#                                   unchanged, could not fetch, or refused -
#                                   it sends one small report to the edge.
#                                   A report can never fail a run.
#   /usr/local/bin/feed-deadman.sh  the stale alert now leads with the cause,
#                                   read from the relay's own last line:
#                                   vendor quiet / relay failing / relay gone
#                                   quiet.
# No timer, unit, env file or credential is touched. Nothing new to configure:
# the report goes to the same host with the same feed token, on its own path.
#
# RUN ORDER: 045_feed_checks.sql, then the Worker (patch_controller_045.py,
# deployed), THEN this. Step 2 below refuses to go further if the Worker does
# not know the route yet, and changes nothing.
#
#   scp install-feed-check.sh root@192.168.1.224:/root/      (from the Mac)
#   bash /root/install-feed-check.sh                         (on Proxmox)
#
# Undo:  cp /usr/local/bin/relay.sh.bak-045 /usr/local/bin/relay.sh
#        cp /usr/local/bin/feed-deadman.sh.bak-045 /usr/local/bin/feed-deadman.sh
set -uo pipefail

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; DIM=$'\033[2m'; OFF=$'\033[0m'
step(){ printf '\n%s==> %s%s\n' "$DIM" "$1" "$OFF"; }
ok(){   printf '  %s+%s %s\n' "$GRN" "$OFF" "$1"; }
warn(){ printf '  %s!%s %s\n' "$YEL" "$OFF" "$1"; }
die(){  printf '  %sx%s %s\n' "$RED" "$OFF" "$1"; exit 1; }

RELAY="${RELAY:-/usr/local/bin/relay.sh}"
DEADMAN="${DEADMAN:-/usr/local/bin/feed-deadman.sh}"
RELAY_ENV="${RELAY_ENV:-/etc/feed-relay.env}"
MARK="GS_FEED_CHECK_V1"

[[ $EUID -eq 0 ]] || die "Run this as root."
command -v curl >/dev/null    || die "curl is not installed."
command -v python3 >/dev/null || die "python3 is not installed (it ships with Proxmox; apt install python3)."

# ─────────────────────────────────────────────────────────────────────────────
step "1 of 5  Finding the relay and where it reports to"

[[ -f "$RELAY" ]]     || die "$RELAY not found. This box does not run the pull relay."
[[ -f "$DEADMAN" ]]   || die "$DEADMAN not found. Run install-feed-alerts.sh first."
[[ -r "$RELAY_ENV" ]] || die "$RELAY_ENV not found or not readable."
# shellcheck disable=SC1090
. "$RELAY_ENV"
[[ -n "${FEED_URL:-}" ]] || die "FEED_URL is empty in $RELAY_ENV"
[[ "$FEED_URL" == *"/api/feed/inbound"* ]] || die "FEED_URL does not contain /api/feed/inbound, so the report address cannot be derived from it."
[[ "$FEED_URL" == *"token="* ]] || die "FEED_URL carries no token= parameter."

# Same host, different path. Derived rather than prompted, so there is no
# second place for the address or the token to drift out of step.
CHECK_URL="${FEED_URL%%\?*}"
CHECK_URL="${CHECK_URL/\/api\/feed\/inbound/\/api\/feed\/check}"
ok "reports will go to $CHECK_URL  (token sent as a header, never printed)"

# ─────────────────────────────────────────────────────────────────────────────
step "2 of 5  Asking the Worker whether it knows that route"

# No token on purpose. A Worker with patch 045 answers 401 "missing token".
# One without it does not have the route and answers something else - and if
# the relay reported to THAT, every report would be thrown away.
PROBE=$(curl -s --max-time 20 -o /tmp/.feedcheckprobe -w '%{http_code}' -X POST "$CHECK_URL" 2>/dev/null) || PROBE="curl-failed"
BODY=$(head -c 200 /tmp/.feedcheckprobe 2>/dev/null); rm -f /tmp/.feedcheckprobe
if [[ "$PROBE" == "401" && "$BODY" == "missing token" ]]; then
    ok "the Worker has the route"
elif [[ "$PROBE" == "curl-failed" ]]; then
    die "Could not reach the edge at all. Check this box's internet, then run this again. Nothing was changed."
else
    die "The Worker does not have /api/feed/check yet (it answered HTTP $PROBE). Apply patch_controller_045.py to worker.js, deploy it, then run this again. Nothing was changed."
fi

# ─────────────────────────────────────────────────────────────────────────────
step "3 of 5  relay.sh"

# Edits are placed by matching whole lines (ignoring indentation) that must
# each appear exactly once. If this box's script is not the one this was
# written against, it stops and changes nothing.
patch_file() {      # patch_file <which> <src> <dst>
python3 - "$1" "$2" "$3" <<'PY'
import sys
which, src_path, dst_path = sys.argv[1], sys.argv[2], sys.argv[3]
lines = open(src_path, encoding='utf-8').read().split('\n')

def find(text, start=0):
    hits = [i for i, l in enumerate(lines) if i >= start and l.strip() == text.strip()]
    if len(hits) != 1:
        sys.exit("anchor found %d times, expected 1: %s" % (len(hits), text.strip()[:70]))
    return hits[0]

def indent_of(i):
    return lines[i][:len(lines[i]) - len(lines[i].lstrip())]

def after(text, new):
    i = find(text); ind = indent_of(i)
    lines[i + 1:i + 1] = [ind + n if n else n for n in new]

def before(text, new):
    i = find(text)
    lines[i:i] = new

if which == 'relay':
    before('mkdir -p "$WORK_DIR" "$DONE_DIR" "$FAIL_DIR" || exit 73', r'''# ── tell the edge what this run saw (GS_FEED_CHECK_V1) ──────────────────────
# The importer only hears from this script when the file CHANGED. A vendor who
# publishes nothing for a day and a relay that died a day ago therefore looked
# identical from the controller. One small report after every run that did
# NOT import fixes that: unchanged, could not fetch, or refused. A real import
# needs no report - the importer records that one itself.
#
# It can never fail a run. A report that cannot be delivered is noted in the
# log and dropped; the next tick sends a fresh one.
CHECK_URL="${CHECK_URL:-}"
FEED_TOKEN=""
if [[ "$FEED_URL" == *"/api/feed/inbound"* && "$FEED_URL" == *"token="* ]]; then
    if [[ -z "$CHECK_URL" ]]; then
        CHECK_URL="${FEED_URL%%\?*}"
        CHECK_URL="${CHECK_URL/\/api\/feed\/inbound/\/api\/feed\/check}"
    fi
    FEED_TOKEN="${FEED_URL##*token=}"; FEED_TOKEN="${FEED_TOKEN%%&*}"
else
    CHECK_URL=""
fi
report() {      # report <same|fetch_failed|refused> <bytes> [note]
    [[ -n "$CHECK_URL" ]] || return 0
    local out
    # The token goes in a header, not the address, so it stays out of any
    # access log between here and the Worker.
    out=$(curl -s --max-time 15 --connect-timeout 8 -X POST \
               "${CHECK_URL}?result=${1}&bytes=${2:-0}" \
               -H "X-Feed-Token: ${FEED_TOKEN}" -H 'Content-Type: text/plain' \
               --data-binary "${3:-}" 2>/dev/null) \
        || { log "note  could not reach the edge to report '${1}' (curl exit $?)"; return 0; }
    [[ "$out" == *'"success":true'* ]] || log "note  the edge did not accept the '${1}' report: ${out:0:160}"
    return 0
}
'''.split('\n'))
    after('log "FAIL  download from ${FTP_HOST}${FTP_PATH} failed (curl exit $rc)"', ['report fetch_failed 0 "curl exit $rc"'])
    after('log "FAIL  downloaded only ${bytes} bytes (min ${MIN_BYTES}); refusing to forward"', ['report refused "$bytes" "only ${bytes} bytes (min ${MIN_BYTES})"'])
    after('log "FAIL  first line has no VIN column; this is not the inventory file"', ['report refused "$bytes" "first line has no VIN column"'])
    after('log "SAME  file unchanged (${bytes} bytes); nothing to send"', ['report same "$bytes"'])

elif which == 'deadman':
    before('newest=$(find "$DONE_DIR" -maxdepth 1 -type f -printf \'%T@\\n\' 2>/dev/null | sort -n | tail -1)', r'''# ── why is it stale? (GS_FEED_CHECK_V1) ─────────────────────────────────────
# "Nothing imported in 29h" is three very different situations, and the
# relay's own last line says which. Only the relay's result lines count: this
# script's "deadman:" lines, "note" lines and raw curl errors are skipped.
CAUSE=""; CAUSE_SHORT=""
feed_cause() {
    local last when kind mins same_n
    last=$(grep -E '^[^ ]+  (SAME|OK|FAIL|HARD|RETRY|FATAL)' "$LOG_FILE" 2>/dev/null | tail -1)
    if [[ -z "$last" ]]; then
        CAUSE_SHORT="no relay lines in the log"
        CAUSE="THE RELAY HAS WRITTEN NOTHING to $LOG_FILE. It may not be running at all. This is on our side."
        return
    fi
    when="${last%%  *}"
    kind=$(awk '{print $2}' <<<"$last"); kind="${kind%:}"
    mins=$(( ( $(date +%s) - $(date -d "$when" +%s 2>/dev/null || echo 0) ) / 60 ))
    same_n=$(awk '/^[^ ]+  OK /{n=0} /^[^ ]+  SAME /{n++} END{print n+0}' "$LOG_FILE" 2>/dev/null)
    if [[ "$kind" == "SAME" && "$mins" -le 90 ]]; then
        CAUSE_SHORT="vendor file unchanged, relay healthy"
        CAUSE="THE VENDOR IS QUIET. The relay is healthy: it fetched the file ${mins} minutes ago and it was identical to the last one (${same_n} identical checks in a row). There has simply been nothing new to import. Nothing is broken on this side, and this clears by itself when the vendor next changes the file."
    elif [[ "$kind" == "SAME" || "$kind" == "OK" ]]; then
        CAUSE_SHORT="relay has gone quiet"
        CAUSE="THE RELAY HAS GONE QUIET. Its last line is ${mins} minutes old and it should write one every 30. This is on our side - check the timer:  systemctl list-timers 'feed-*' --no-pager
  $last"
    else
        CAUSE_SHORT="relay is failing"
        CAUSE="THE RELAY IS FAILING. This is on our side or between us and the vendor. Its last line:
  $last"
    fi
}
'''.split('\n'))
    i = find('log "STALE - last successful import: ${age_txt}, alerting"')
    ind = indent_of(i)
    lines[i:i + 1] = [ind + 'feed_cause', ind + 'log "STALE - last successful import: ${age_txt}, alerting (${CAUSE_SHORT})"']
    a = find('/usr/local/bin/feed-alert.sh "No vehicle inventory has imported recently on $(hostname).')
    b = find('Force:  rm -f /srv/feed/pull/.last-sha256 && /usr/local/bin/relay.sh"', a)
    if not (0 < b - a <= 12):
        sys.exit("the stale alert block is not the shape expected")
    lines[a:b + 1] = [indent_of(a) + '/usr/local/bin/feed-alert.sh "Nothing new has imported on $(hostname). Last successful import: ${age_txt} (limit ${STALE_HOURS}h).',
                      '',
                      '${CAUSE}',
                      '',
                      'Check:  tail -20 $LOG_FILE',
                      'Force:  rm -f /srv/feed/pull/.last-sha256 && /usr/local/bin/relay.sh"']
else:
    sys.exit("unknown file")

open(dst_path, 'w', encoding='utf-8').write('\n'.join(lines))
PY
}

install_patched() {     # install_patched <which> <path>
    local which="$1" path="$2" tmp
    if grep -q "$MARK" "$path"; then
        ok "$path already has it - left as it is"
        return 0
    fi
    tmp=$(mktemp) || die "mktemp failed"
    patch_file "$which" "$path" "$tmp" || { rm -f "$tmp"; die "$path is not the script this was written against (message above). Nothing was changed."; }
    bash -n "$tmp" || { rm -f "$tmp"; die "the edited $path does not parse. Nothing was changed."; }
    cp -p "$path" "${path}.bak-045" || { rm -f "$tmp"; die "could not write ${path}.bak-045"; }
    # Same owner and mode as the original; the content comes from the edit.
    cat "$tmp" > "$path" || { rm -f "$tmp"; die "could not write $path - restore it with: cp ${path}.bak-045 $path"; }
    rm -f "$tmp"
    ok "$path updated  (original kept at ${path}.bak-045)"
    diff -u "${path}.bak-045" "$path" | grep -E '^[+-]' | grep -vE '^(\+\+\+|---)' | sed 's/^/      /' | head -80
}
install_patched relay "$RELAY"

# ─────────────────────────────────────────────────────────────────────────────
step "4 of 5  feed-deadman.sh"
install_patched deadman "$DEADMAN"

# ─────────────────────────────────────────────────────────────────────────────
step "5 of 5  One real run"

LOG_FILE="${LOG_FILE:-/var/log/feed-relay.log}"
LINES_BEFORE=$(wc -l < "$LOG_FILE" 2>/dev/null || echo 0)
"$RELAY"; RC=$?
NEW=$(tail -n +"$((LINES_BEFORE + 1))" "$LOG_FILE" 2>/dev/null)
printf '%s\n' "$NEW" | sed 's/^/      /'
if [[ "$RC" -ne 0 ]]; then
    warn "relay.sh exited $RC. That is the relay's own result (see the lines above), not this installer's."
fi
if grep -q '  note  ' <<<"$NEW"; then
    warn "The report was sent but not accepted - the 'note' line above says why."
    warn "\"check not stored ... 045_feed_checks.sql\" means the SQL has not been run yet: run it, and the next tick is accepted."
elif grep -qE '  (SAME|FAIL) ' <<<"$NEW"; then
    ok "the run above was reported to the controller and accepted"
elif grep -q '  OK ' <<<"$NEW"; then
    ok "that run imported a changed file; the importer records that one itself"
else
    warn "No result line was written by that run. Check: tail -5 $LOG_FILE"
fi

printf '\n%sDone.%s The Feed tab in the controller now shows the last check next to the last import.\n' "$GRN" "$OFF"
printf 'Undo:  cp %s.bak-045 %s ; cp %s.bak-045 %s\n' "$RELAY" "$RELAY" "$DEADMAN" "$DEADMAN"
