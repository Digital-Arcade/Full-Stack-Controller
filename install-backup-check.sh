#!/usr/bin/env bash
# install-backup-check.sh - proves the backup link still works, and keeps the
# SIM from going dormant.
#
# WHY: a failover path that is never exercised is a guess. A prepaid SIM can
# be suspended for inactivity, a carrier can change something, the MoFi can
# quietly drop off - and you would find out at the exact moment you needed it.
# This sends a few KB over the backup link on a schedule and tells you when
# that stops working, which is the only way the fallback stays trustworthy.
#
# Deliberately separate from net-watchdog: that decides which route to use
# RIGHT NOW. This answers "is the spare tyre still inflated".
set -uo pipefail

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; DIM=$'\033[2m'; OFF=$'\033[0m'
step(){ printf '\n%s==> %s%s\n' "$DIM" "$1" "$OFF"; }
ok(){   printf '  %s+%s %s\n' "$GRN" "$OFF" "$1"; }
warn(){ printf '  %s!%s %s\n' "$YEL" "$OFF" "$1"; }
die(){  printf '  %sx%s %s\n' "$RED" "$OFF" "$1"; exit 1; }

[[ $EUID -eq 0 ]] || die "Run this as root."
[[ -r /etc/net-watchdog.env ]] || die "/etc/net-watchdog.env not found. Run install-net-watchdog.sh first - this reuses its backup-link settings."
. /etc/net-watchdog.env
[[ -n "${BK_DEV:-}" ]] || die "BK_DEV is empty in /etc/net-watchdog.env"

# ─────────────────────────────────────────────────────────────────────────────
step "1 of 3  Testing the backup link right now"

# A real HTTPS request to a route known to answer, not a ping. ICMP passing
# proves almost nothing - this very setup spent an evening on a host that
# answered pings and refused connections.
PROBE_URL="${PROBE_URL:-https://edge.hyperwax.io/api/controller/setup-state}"
CODE=$(curl -4 -s -m 20 --interface "$BK_DEV" -o /dev/null -w '%{http_code}' "$PROBE_URL" 2>/dev/null || echo 000)
if [[ "$CODE" == "200" ]]; then
    ok "backup link reached the edge over $BK_DEV (HTTP $CODE)"
else
    warn "backup link returned $CODE. Installing anyway - the first scheduled run will alert you."
fi

cat > /etc/backup-check.env <<ENV
BK_DEV="$BK_DEV"
# A route that returns 200 to an unauthenticated GET and sends a tiny body.
# Keep it small: this runs on a metered link.
PROBE_URL="$PROBE_URL"
# Consecutive failures before saying the backup is down. Two spaced six hours
# apart means a single blip does not cry wolf.
FAILS_TO_ALERT=2
ENV
chmod 600 /etc/backup-check.env
ok "wrote /etc/backup-check.env"

# ─────────────────────────────────────────────────────────────────────────────
step "2 of 3  The check"

cat > /usr/local/bin/backup-check.sh <<'BC'
#!/usr/bin/env bash
# Exercises the backup link and reports when it stops working.
set -uo pipefail

[[ -r /etc/backup-check.env ]] && . /etc/backup-check.env
LOG=/var/log/backup-check.log
DIR=/var/lib/backup-check
mkdir -p "$DIR"
STREAK="$DIR/fails"
LATCH="$DIR/alerted"        # present while we have already said it is down

log(){ printf '%s  %s\n' "$(date -Is)" "$1" >> "$LOG"; }
notify(){ [[ -x /usr/local/bin/feed-alert.sh ]] && /usr/local/bin/feed-alert.sh "$1" >/dev/null 2>&1 || true; }

[[ -n "${BK_DEV:-}" ]] || { log "FATAL config missing"; exit 78; }

# --interface binds every socket to the device, DNS included. The first
# resolver is on the primary LAN and is unreachable from here, so resolve the
# name first over the normal path and hand curl the address. Without this the
# check times out on DNS and looks like a dead link when it is not.
host="${PROBE_URL#https://}"; host="${host%%/*}"
addr="$(getent ahostsv4 "$host" | awk '{print $1; exit}')"

if [[ -n "$addr" ]]; then
    code=$(curl -4 -s -m 20 --interface "$BK_DEV" --resolve "${host}:443:${addr}" \
                -o /dev/null -w '%{http_code}' "$PROBE_URL" 2>/dev/null || echo 000)
else
    code=$(curl -4 -s -m 20 --interface "$BK_DEV" -o /dev/null -w '%{http_code}' "$PROBE_URL" 2>/dev/null || echo 000)
fi

n="$(cat "$STREAK" 2>/dev/null || echo 0)"; [[ "$n" =~ ^[0-9]+$ ]] || n=0

if [[ "$code" == "200" ]]; then
    log "OK    backup link answered over $BK_DEV"
    echo 0 > "$STREAK"
    if [[ -f "$LATCH" ]]; then
        rm -f "$LATCH"
        notify "Backup link is working again: $BK_DEV reached the edge. The fallback is trustworthy once more."
    fi
else
    n=$((n+1)); echo "$n" > "$STREAK"
    log "FAIL  backup link returned $code over $BK_DEV ($n/$FAILS_TO_ALERT)"
    if (( n >= FAILS_TO_ALERT )) && [[ ! -f "$LATCH" ]]; then
        touch "$LATCH"
        notify "Backup link is DOWN: $BK_DEV could not reach the edge ($code). Your failover will not work until this is fixed - check the SIM's data and the MoFi."
    fi
fi
exit 0
BC
chmod 755 /usr/local/bin/backup-check.sh
ok "wrote /usr/local/bin/backup-check.sh"

# ─────────────────────────────────────────────────────────────────────────────
step "3 of 3  Four times a day"

cat > /etc/systemd/system/backup-check.service <<'UNIT'
[Unit]
Description=Prove the backup link still works and keep the SIM active

[Service]
Type=oneshot
ExecStart=/usr/local/bin/backup-check.sh
User=root
UNIT

cat > /etc/systemd/system/backup-check.timer <<'UNIT'
[Unit]
Description=Exercise the backup link every six hours

[Timer]
OnBootSec=5min
OnUnitActiveSec=6h
AccuracySec=5min
Persistent=true

[Install]
WantedBy=timers.target
UNIT

systemctl daemon-reload
systemctl enable --now backup-check.timer >/dev/null 2>&1
systemctl start backup-check.service
systemctl is-active --quiet backup-check.timer || die "backup-check.timer did not start."
ok "backup-check.timer is active"

printf '\n%sDone.%s  Roughly 2KB per run, four runs a day.\n' "$GRN" "$OFF"
printf 'Watch it:  tail -f /var/log/backup-check.log\n'
printf 'Run now:   /usr/local/bin/backup-check.sh ; tail -1 /var/log/backup-check.log\n'
printf 'Stop it:   systemctl disable --now backup-check.timer\n\n'
