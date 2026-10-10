#!/usr/bin/env bash
# install-net-watchdog.sh - fails the default route over to the backup link
# when the primary stops reaching the internet, and back when it recovers.
#
# WHY NOT CARRIER: the default route lives on vmbr0, a BRIDGE. A bridge keeps
# carrier while any member port is up, and VM 100's firewall veth
# (fwpr100p0) is always up. So nic1 can lose its cable and vmbr0 never
# notices - ignore_routes_with_linkdown has nothing to act on and traffic
# blackholes. Verified on 2026-10-03.
#
# So this probes REACHABILITY instead, which is what actually matters and
# also catches the case carrier never could: router up, uplink dead.
#
# It only ever changes a route METRIC. No interface is touched, no route is
# left missing even mid-run, and every change is reversible by hand.
set -uo pipefail

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; DIM=$'\033[2m'; OFF=$'\033[0m'
step(){ printf '\n%s==> %s%s\n' "$DIM" "$1" "$OFF"; }
ok(){   printf '  %s+%s %s\n' "$GRN" "$OFF" "$1"; }
warn(){ printf '  %s!%s %s\n' "$YEL" "$OFF" "$1"; }
die(){  printf '  %sx%s %s\n' "$RED" "$OFF" "$1"; exit 1; }

[[ $EUID -eq 0 ]] || die "Run this as root."

# ─────────────────────────────────────────────────────────────────────────────
step "1 of 4  Reading the current routing"

PRI_LINE="$(ip route show default | grep -v 'metric' | head -1)"
[[ -n "$PRI_LINE" ]] || die "No metric-less default route found. Expected the primary default via the Starlink router."
PRI_GW="$(awk '{for(i=1;i<=NF;i++) if($i=="via") print $(i+1)}' <<<"$PRI_LINE")"
PRI_DEV="$(awk '{for(i=1;i<=NF;i++) if($i=="dev") print $(i+1)}' <<<"$PRI_LINE")"

BK_LINE="$(ip route show default | grep 'metric 200' | head -1)"
[[ -n "$BK_LINE" ]] || die "No metric-200 default route found. Add the MoFi fallback route first."
BK_GW="$(awk '{for(i=1;i<=NF;i++) if($i=="via") print $(i+1)}' <<<"$BK_LINE")"
BK_DEV="$(awk '{for(i=1;i<=NF;i++) if($i=="dev") print $(i+1)}' <<<"$BK_LINE")"

ok "primary  $PRI_GW via $PRI_DEV"
ok "backup   $BK_GW via $BK_DEV (metric 200)"

# ─────────────────────────────────────────────────────────────────────────────
step "2 of 4  Checking the primary can actually be probed"

if ping -c1 -W3 -I "$PRI_DEV" 1.1.1.1 >/dev/null 2>&1; then
    ok "1.1.1.1 answers when forced out $PRI_DEV"
else
    warn "1.1.1.1 did not answer out $PRI_DEV. Installing anyway, but check this - the watchdog will think the primary is down."
fi

cat > /etc/net-watchdog.env <<ENV
PRI_GW="$PRI_GW"
PRI_DEV="$PRI_DEV"
BK_GW="$BK_GW"
BK_DEV="$BK_DEV"
# Two targets on different networks, so one operator having a bad day does
# not look like your link being down.
TARGETS="1.1.1.1 8.8.8.8"
# Consecutive results before acting. 3 failures is ~3 minutes of real outage;
# 2 successes before coming back avoids flapping on a link that is still sick.
FAILS_TO_DEMOTE=3
OKS_TO_PROMOTE=2
# Metric the primary is pushed to while it is considered down. Must be worse
# than the backup's 200.
DEMOTED_METRIC=500
ENV
chmod 600 /etc/net-watchdog.env
ok "wrote /etc/net-watchdog.env"

# ─────────────────────────────────────────────────────────────────────────────
step "3 of 4  The watchdog"

cat > /usr/local/bin/net-watchdog.sh <<'WD'
#!/usr/bin/env bash
# Probes the PRIMARY link specifically and moves the default route's metric.
# Run from net-watchdog.timer every minute.
set -uo pipefail

[[ -r /etc/net-watchdog.env ]] && . /etc/net-watchdog.env
LOG=/var/log/net-watchdog.log
STATE_DIR=/var/lib/net-watchdog
mkdir -p "$STATE_DIR"
STATE="$STATE_DIR/state"          # up | down
STREAK="$STATE_DIR/streak"

log(){ printf '%s  %s\n' "$(date -Is)" "$1" >> "$LOG"; }
notify(){ [[ -x /usr/local/bin/feed-alert.sh ]] && /usr/local/bin/feed-alert.sh "$1" >/dev/null 2>&1 || true; }

[[ -n "${PRI_GW:-}" && -n "${PRI_DEV:-}" ]] || { log "FATAL config missing"; exit 78; }

# -I <device> uses SO_BINDTODEVICE, which forces the packet out that interface
# REGARDLESS of the routing table. That is the whole trick: it tests the
# primary link even while the primary route is demoted and unused.
probe_primary() {
    local t
    for t in $TARGETS; do
        ping -c1 -W2 -I "$PRI_DEV" "$t" >/dev/null 2>&1 && return 0
    done
    return 1
}

cur="$(cat "$STATE" 2>/dev/null || echo up)"
n="$(cat "$STREAK" 2>/dev/null || echo 0)"
[[ "$n" =~ ^[0-9]+$ ]] || n=0

if probe_primary; then
    if [[ "$cur" == "down" ]]; then
        n=$((n+1)); echo "$n" > "$STREAK"
        log "RECOVERING primary answered ($n/$OKS_TO_PROMOTE)"
        if (( n >= OKS_TO_PROMOTE )); then
            # Add the good route BEFORE removing the demoted one, so there is
            # never a moment with no default route at all.
            ip route add default via "$PRI_GW" dev "$PRI_DEV" onlink 2>/dev/null
            ip route del default via "$PRI_GW" dev "$PRI_DEV" metric "$DEMOTED_METRIC" 2>/dev/null
            # Hand IPv6 back. The RA route was never removed, so it resumes
            # the moment this override is gone - no waiting for the next
            # advertisement.
            ip -6 route del unreachable default metric 100 2>/dev/null
            echo up > "$STATE"; echo 0 > "$STREAK"
            log "PROMOTED  primary restored as the default route"
            notify "Network restored: traffic is back on the primary link ($PRI_DEV via $PRI_GW)."
        fi
    else
        [[ "$n" != "0" ]] && echo 0 > "$STREAK"
    fi
else
    if [[ "$cur" == "up" ]]; then
        n=$((n+1)); echo "$n" > "$STREAK"
        log "FAILING   primary silent ($n/$FAILS_TO_DEMOTE)"
        if (( n >= FAILS_TO_DEMOTE )); then
            ip route add default via "$PRI_GW" dev "$PRI_DEV" metric "$DEMOTED_METRIC" onlink 2>/dev/null
            ip route del default via "$PRI_GW" dev "$PRI_DEV" 2>/dev/null
            # IPv6 has no path to fail over to - the backup link carries no
            # global v6 at all. Deleting the v6 default would not stick either:
            # it is proto ra and the router re-advertises it within seconds.
            #
            # So make v6 fail INSTANTLY instead. An unreachable default at a
            # better metric than the RA route's 1024 returns ENETUNREACH
            # immediately, which is what Happy Eyeballs needs to fall back to
            # IPv4 right away rather than stalling for ten seconds per
            # connection. Only the default is overridden; on-link and
            # link-local traffic is untouched.
            ip -6 route add unreachable default metric 100 2>/dev/null
            echo down > "$STATE"; echo 0 > "$STREAK"
            log "DEMOTED   primary pushed to metric $DEMOTED_METRIC; traffic should now take $BK_DEV"
            notify "Network failover: the primary link stopped answering, traffic moved to the backup ($BK_DEV via $BK_GW). Data on that link is metered."
        fi
    else
        [[ "$n" != "0" ]] && echo 0 > "$STREAK"
    fi
fi

# A short-circuited && as the last statement makes a healthy tick exit
# non-zero, which systemd reports as a failed run even though nothing is
# wrong. Be explicit about success instead.
exit 0
WD
chmod 755 /usr/local/bin/net-watchdog.sh
ok "wrote /usr/local/bin/net-watchdog.sh"

# ─────────────────────────────────────────────────────────────────────────────
step "4 of 4  Every minute, from now on"

cat > /etc/systemd/system/net-watchdog.service <<'UNIT'
[Unit]
Description=Fail the default route over to the backup link when the primary stops answering

[Service]
Type=oneshot
ExecStart=/usr/local/bin/net-watchdog.sh
User=root
UNIT

cat > /etc/systemd/system/net-watchdog.timer <<'UNIT'
[Unit]
Description=Check the primary link every minute

[Timer]
OnBootSec=90s
OnUnitActiveSec=60s
AccuracySec=5s

[Install]
WantedBy=timers.target
UNIT

systemctl daemon-reload
systemctl enable --now net-watchdog.timer >/dev/null 2>&1
systemctl start net-watchdog.service

systemctl is-active --quiet net-watchdog.timer || die "net-watchdog.timer did not start."
ok "net-watchdog.timer is active"

printf '\n%sDone.%s\n' "$GRN" "$OFF"
printf 'Watch it:   tail -f /var/log/net-watchdog.log\n'
printf 'State:      cat /var/lib/net-watchdog/state\n'
printf 'Stop it:    systemctl disable --now net-watchdog.timer\n'
printf 'Undo byhand: ip route add default via %s dev %s onlink ; ip route del default via %s dev %s metric %s\n\n' \
       "$PRI_GW" "$PRI_DEV" "$PRI_GW" "$PRI_DEV" "500"
