#!/usr/bin/env bash
# install-host-beat.sh - pushes a health beat from this box to the controller.
#
# WHY PUSH: this host sits behind CGNAT, so nothing outside can poll it. The
# box reports every five minutes and SILENCE IS THE SIGNAL - a host that stops
# beating is a host whose network died, which is exactly the failure that took
# the feed down on 2026-10-03 and that nobody saw until the next morning.
#
# Reuses the token already in /etc/feed-alert.env. No new secret to provision:
# the Worker accepts HOST_BEAT_TOKEN, falling back to FEED_ALERT_TOKEN.
set -uo pipefail

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; DIM=$'\033[2m'; OFF=$'\033[0m'
step(){ printf '\n%s==> %s%s\n' "$DIM" "$1" "$OFF"; }
ok(){   printf '  %s+%s %s\n' "$GRN" "$OFF" "$1"; }
warn(){ printf '  %s!%s %s\n' "$YEL" "$OFF" "$1"; }
die(){  printf '  %sx%s %s\n' "$RED" "$OFF" "$1"; exit 1; }

[[ $EUID -eq 0 ]] || die "Run this as root."
command -v curl >/dev/null || die "curl is not installed."

# ─────────────────────────────────────────────────────────────────────────────
step "1 of 4  Working out where to send beats"

[[ -r /etc/feed-alert.env ]] || die "/etc/feed-alert.env not found. Run install-feed-alerts.sh first - this reuses its token."
# shellcheck disable=SC1091
. /etc/feed-alert.env
[[ -n "${ALERT_URL:-}" ]] || die "ALERT_URL is empty in /etc/feed-alert.env"

# Same host and token, different path. Derived rather than prompted so there
# is no second place for the token to drift out of sync.
BEAT_URL="${ALERT_URL/\/api\/admin\/alert/\/api\/controller\/host-beat}"
[[ "$BEAT_URL" == *"/api/controller/host-beat"* ]] || die "Could not derive the beat URL from ALERT_URL. Expected it to contain /api/admin/alert."
ok "beats will go to ${BEAT_URL%%\?*}"

# ─────────────────────────────────────────────────────────────────────────────
step "2 of 4  Testing it before wiring anything up"

CODE=$(curl -s -o /tmp/.beatprobe -w '%{http_code}' --max-time 20 \
       -X POST "$BEAT_URL" -H 'Content-Type: application/json' \
       --data "{\"host\":\"$(hostname)\",\"extra\":{\"probe\":true}}")
case "$CODE" in
    200) ok "accepted - the controller has its first beat" ;;
    401) die "401 - the token is wrong, or HOST_BEAT_TOKEN is set on the Worker to something else." ;;
    503) die "503 - the Worker has neither HOST_BEAT_TOKEN nor SUPABASE_SERVICE_ROLE_KEY set." ;;
    404) die "404 - the Worker does not have the host-beat route yet. Apply patch_controller_036.py and redeploy." ;;
    *)   warn "unexpected HTTP $CODE: $(head -c 300 /tmp/.beatprobe)"
         read -r -p "      Continue anyway? [y/N] " yn
         [[ "$yn" == [yY] ]] || exit 1 ;;
esac
rm -f /tmp/.beatprobe

cat > /etc/host-beat.env <<ENV
BEAT_URL="$BEAT_URL"
# Host used for the DNS reachability check. Defaults to whatever the feed
# relay fetches from, because that is the lookup that actually matters here.
DNS_PROBE_HOST=""
ENV
chmod 600 /etc/host-beat.env
ok "wrote /etc/host-beat.env"

# ─────────────────────────────────────────────────────────────────────────────
step "3 of 4  The beat script"

cat > /usr/local/bin/host-beat.sh <<'BEAT'
#!/usr/bin/env bash
# Collects a health snapshot and posts it to the controller. Every reading is
# guarded: a probe that cannot be taken reports null rather than failing the
# beat, because a beat that does not arrive is indistinguishable from an
# outage and would raise a false alarm.
set -uo pipefail

[[ -r /etc/host-beat.env ]] && . /etc/host-beat.env
BEAT_URL="${BEAT_URL:-}"
[[ -n "$BEAT_URL" ]] || exit 78

HOST="$(hostname)"

UPTIME="$(cut -d. -f1 /proc/uptime 2>/dev/null)"; UPTIME="${UPTIME:-null}"
LOAD1="$(cut -d' ' -f1 /proc/loadavg 2>/dev/null)"; LOAD1="${LOAD1:-null}"

MEM="null"
if [[ -r /proc/meminfo ]]; then
    MT=$(awk '/^MemTotal:/{print $2}' /proc/meminfo)
    MA=$(awk '/^MemAvailable:/{print $2}' /proc/meminfo)
    [[ -n "$MT" && -n "$MA" && "$MT" -gt 0 ]] && MEM=$(awk -v t="$MT" -v a="$MA" 'BEGIN{printf "%.1f",(t-a)*100/t}')
fi

DISK="$(df -P / 2>/dev/null | awk 'NR==2{gsub(/%/,"",$5); print $5}')"; DISK="${DISK:-null}"

# systemd units in a failed state. The names matter more than the count when
# something is wrong, so both go up.
FAILED_NAMES="$(systemctl list-units --state=failed --no-legend --plain 2>/dev/null | awk '{print $1}' | paste -sd, - )"
FAILED_N="$(systemctl list-units --state=failed --no-legend --plain 2>/dev/null | grep -c . )"
FAILED_N="${FAILED_N:-0}"

# DNS. Defaults to the host the feed actually fetches from - that is the
# lookup whose failure costs something, not a generic one.
PROBE="${DNS_PROBE_HOST:-}"
if [[ -z "$PROBE" && -r /etc/feed-relay.env ]]; then
    PROBE="$( . /etc/feed-relay.env 2>/dev/null; echo "${FTP_HOST:-}" )"
fi
PROBE="${PROBE:-cloudflare.com}"
if getent hosts "$PROBE" >/dev/null 2>&1; then DNS_OK=true; else DNS_OK=false; fi

if [[ "$(systemctl is-active feed-relay.timer 2>/dev/null)" == "active" ]]; then
    TIMER_OK=true
else
    TIMER_OK=false
fi

# Proxmox writes every task to this index; the final field is its status.
# Absent on a non-Proxmox host, which is fine - it reports null.
BACKUP="$(grep -h 'vzdump' /var/log/pve/tasks/index 2>/dev/null | tail -1 | awk '{print $NF}')"

esc(){ local s="$1"; s="${s//\\/\\\\}"; s="${s//\"/\\\"}"; s="${s//$'\n'/ }"; printf '%s' "$s"; }
jstr(){ [[ -z "${1:-}" ]] && printf 'null' || printf '"%s"' "$(esc "$1")"; }

BODY=$(cat <<JSON
{"host":"$(esc "$HOST")",
 "uptime_s":${UPTIME},
 "load1":${LOAD1},
 "mem_used_pct":${MEM},
 "disk_used_pct":${DISK},
 "failed_units":${FAILED_N},
 "failed_unit_names":$(jstr "$FAILED_NAMES"),
 "dns_ok":${DNS_OK},
 "feed_timer_ok":${TIMER_OK},
 "last_backup_status":$(jstr "$BACKUP"),
 "extra":{"dns_probe":"$(esc "$PROBE")"}}
JSON
)

# Result of whatever we were asked to run last time, carried up with this
# beat. Written as a whole JSON object so the Worker can attribute it to the
# exact finding by id.
LAST="null"
if [[ -s /var/lib/host-beat/last-remedy.json ]]; then
    LAST="$(cat /var/lib/host-beat/last-remedy.json)"
    rm -f /var/lib/host-beat/last-remedy.json
fi
BODY="${BODY%\}}, \"last_remedy\":${LAST}}"

# --retry-all-errors so a DNS blip of the kind that broke the feed on
# 2026-10-03 does not also silence the very beat that would report it.
RESP="$(curl -s --max-time 25 --connect-timeout 10 --retry 2 --retry-delay 3 --retry-all-errors \
        -X POST "$BEAT_URL" -H 'Content-Type: application/json' --data "$BODY" 2>/dev/null)"

# ── remedy ──────────────────────────────────────────────────────────────────
# The Worker hands back a NAME, never a command. Anything this script does not
# recognise is refused and reported - a Worker cannot teach this box a new
# action, which is the whole point of the design.
#
# python3 rather than sed: jq is not guaranteed on Proxmox, and parsing JSON
# with a regex is how an unexpected character becomes an unexpected command.
mkdir -p /var/lib/host-beat
eval "$(printf '%s' "$RESP" | python3 -c '
import sys, json, re
def sh(v):
    return "\x27" + str(v).replace("\x27", "\x27\\\x27\x27") + "\x27"
try:
    d = json.load(sys.stdin)
    r = d.get("remedy") or {}
except Exception:
    r = {}
print("R_ID=" + sh(r.get("id", "")))
print("R_NAME=" + sh(r.get("name", "")))
print("R_ARG=" + sh(r.get("arg") or ""))
' 2>/dev/null)"
R_ID="${R_ID:-}"; R_NAME="${R_NAME:-}"; R_ARG="${R_ARG:-}"

if [[ -n "$R_ID" && -n "$R_NAME" ]]; then
    R_OK=false
    R_OUT=""
    case "$R_NAME" in
        clear_failed_unit)
            # R_ARG is the only externally supplied value that reaches a
            # command on this box. Each name is validated against the
            # characters systemd actually allows and anything else is dropped,
            # so no separator, flag or path can be smuggled through it.
            cleaned=""
            IFS=',' read -ra _units <<< "$R_ARG"
            for u in "${_units[@]}"; do
                u="$(printf '%s' "$u" | tr -d '[:space:]')"
                if [[ "$u" =~ ^[A-Za-z0-9@._-]+\.(service|timer|mount|socket|target|path)$ ]]; then
                    cleaned="$cleaned $u"
                fi
            done
            if [[ -n "$cleaned" ]]; then
                # shellcheck disable=SC2086
                R_OUT="$(systemctl reset-failed $cleaned 2>&1)" && R_OK=true
                R_OUT="reset-failed$cleaned :: ${R_OUT:-ok}"
            else
                R_OUT="refused: no valid unit name in $(printf '%q' "$R_ARG")"
            fi
            ;;
        restart_feed_timer)
            R_OUT="$(systemctl restart feed-relay.timer 2>&1)" && R_OK=true
            R_OUT="restart feed-relay.timer :: ${R_OUT:-ok}"
            ;;
        rerun_feed)
            R_OUT="$(/usr/local/bin/relay.sh 2>&1 | tail -3)" && R_OK=true
            R_OUT="relay.sh :: ${R_OUT:-ok}"
            ;;
        *)
            R_OUT="refused: this host does not know the remedy $(printf '%q' "$R_NAME")"
            ;;
    esac
    python3 - "$R_ID" "$R_OK" "$R_OUT" <<'PYW' > /var/lib/host-beat/last-remedy.json
import sys, json
print(json.dumps({"id": sys.argv[1], "ok": sys.argv[2] == "true", "output": sys.argv[3][:2000]}))
PYW
fi
BEAT
chmod 755 /usr/local/bin/host-beat.sh
ok "wrote /usr/local/bin/host-beat.sh"

# ─────────────────────────────────────────────────────────────────────────────
step "4 of 4  Every five minutes, from now on"

cat > /etc/systemd/system/host-beat.service <<'UNIT'
[Unit]
Description=Push a health beat to the GenieStack controller

[Service]
Type=oneshot
ExecStart=/usr/local/bin/host-beat.sh
User=root
UNIT

cat > /etc/systemd/system/host-beat.timer <<'UNIT'
[Unit]
Description=Health beat every five minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
AccuracySec=30s
Persistent=true

[Install]
WantedBy=timers.target
UNIT

systemctl daemon-reload
systemctl enable --now host-beat.timer >/dev/null 2>&1
systemctl start host-beat.service

if systemctl is-active --quiet host-beat.timer; then
    ok "host-beat.timer is active"
else
    die "host-beat.timer did not start. Check: systemctl status host-beat.timer"
fi

printf '\n%sDone.%s The Infra tab should show %s within five minutes.\n' "$GRN" "$OFF" "$(hostname)"
printf 'Check a beat by hand:  /usr/local/bin/host-beat.sh ; systemctl status host-beat.service --no-pager\n'
printf 'Stop beating:          systemctl disable --now host-beat.timer\n\n'
