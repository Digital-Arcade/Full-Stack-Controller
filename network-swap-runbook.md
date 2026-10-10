# Network swap runbook — moving between routers without breaking anything

Everything here runs on the **Proxmox host shell** unless it says otherwise.

The point of this file: you can rearrange the network freely and the Dealerslink
feed keeps working, because the feed is **entirely outbound**. Nothing has to
reach in. The only thing that matters is that Proxmox can reach the internet.

---

## 1. What the feed actually needs

```
relay.sh on Proxmox
  ├── outbound → ftp.dealerslink.com   (fetch the CSV)
  └── outbound → edge.hyperwax.io      (POST it)
```

Four things, and nothing else:

1. Proxmox has working outbound internet
2. **Proxmox can resolve DNS** — see §9; this is the one that has actually bitten
3. `relay.sh` and `feed-relay.timer` are running
4. `/etc/feed-relay.env` still has `FEED_URL` and the FTP credentials

Router brand, IPv6, port forwarding, public IP — none of it is involved.

---

## 2. Current layout — Starlink only, as of 2026-10-03

```
Starlink router            192.168.1.1   ← the only box in the chain
   └── Proxmox nic1 →      192.168.1.224 (static)
         └── VM 100 →      192.168.1.228 (static, Coolify + Supabase)

MoFi    — unplugged, awaiting a SIM. See §5.
ASUS    — removed 2026-10-03. See §4 only if it ever comes back.
```

The ASUS came out on 2026-10-03 after repeated link dropouts traced to it —
one of which took the feed down and produced three unrelated-looking symptoms
at once (§9).

**Why swapping routers does not break anything:** Proxmox asserts its own
address rather than taking a lease.

```
/etc/network/interfaces
  iface vmbr0 inet static
      address 192.168.1.224/24
      gateway 192.168.1.1
```

No DHCP lease to lose. **The ASUS and the Starlink router both use
`192.168.1.1`**, and Starlink's gateway address never changes, so the gateway
line stayed correct through the swap with no edit. That is the single fact
that made this painless.

Confirmed after the swap: gateway MAC changed from `a0:ad:9f:67:83:f0` (ASUS)
to `74:24:9f:93:76:62` (Starlink), 22ms to 1.1.1.1, 0% loss, native IPv6 back
on `2605:59ca:5e90:e008::/64`.

---

## 3. ASUS → Starlink only — DONE 2026-10-03

Kept as the procedure, because the same steps apply to any future router swap.

**What you lose:** the IPv6 inbound path. Those firewall rules lived on the
ASUS, and Starlink's router blocks inbound IPv6 with no setting to change it.
Outbound IPv6 still works. The feed does not care — it is entirely outbound.

1. Quiet the alerts first, so an outage you caused on purpose does not page
   you and file an infra finding:

```
systemctl stop feed-relay.timer host-beat.timer
```

2. Record the current state somewhere off the box:

```
ip -br a ; ip route show ; cat /etc/network/interfaces
```

3. Starlink app → Settings → **Bypass Mode OFF** (or factory reset the dish,
   which also clears bypass). The dish reboots; give it 5–10 minutes.
4. Move the ethernet into the Starlink router's LAN port. Proxmox's cable goes
   into **nic1** — the same physical port as before.
5. **Seat both ends of the cable firmly.** See §6; a half-seated plug is what
   this looked like the first time and it cost two hours.
6. Verify:

```
ip -br a ; ip route show ; ip neigh show 192.168.1.1
```

```
ping -c3 1.1.1.1 ; getent hosts ftp.dealerslink.com
```

The gateway MAC is the proof you are actually on the new router and not still
talking to the old one.

7. Bring the timers back and force a real feed run:

```
systemctl start feed-relay.timer host-beat.timer
```

```
rm -f /srv/feed/pull/.last-sha256 ; /usr/local/bin/relay.sh ; tail -2 /var/log/feed-relay.log
```

Expect a line starting `OK` with the importer's JSON. A `RETRY ... HTTP 500`
line before it is the POST retry loop working, not a fault.

### The one thing to check on Starlink: the DHCP pool

The ASUS pool was deliberately `.50`–`.200`, leaving `.224` and `.228` clear.
Starlink's router gives you very little DHCP control. If it leases `.224` to a
phone or a TV you get an address conflict with Proxmox, and the symptom is the
host randomly dropping off the network — which looks like hardware failure and
isn't.

Check for a conflict from any other machine on the LAN:

```
ping -c2 192.168.1.224      # should answer only when Proxmox is up
arp -a | grep 192.168.1.224 # one MAC, and it should be Proxmox's
```

Proxmox's MAC is `e4:43:4b:a1:5b:65` (nic1 / vmbr0).

If Starlink won't let you narrow the pool, move Proxmox somewhere unlikely to
be leased — but that means editing `/etc/network/interfaces` **and** the
Cloudflare tunnel config that points at the VM, so only do it if you actually
hit a conflict.

---

## 4. Starlink → ASUS — only if the ASUS comes back

The ASUS was removed on 2026-10-03. Kept because it is the only place the IPv6
inbound path is written down, and because the same steps apply to putting any
router back in front of Proxmox.

Reverse. Use when you want the IPv6 inbound path back.

1. **Starlink app → Settings → Bypass Mode ON.** Dish reboots.
2. Starlink → ASUS WAN port. Everything else → ASUS LAN ports.
3. ASUS settings to confirm (they persist, but check after a factory reset):
   - LAN IP `192.168.1.1`, DHCP pool `.50`–`.200`
   - WAN → IPv6 → Connection type **Native**, DHCP-PD **Enable**
   - IPv6 Firewall **enabled**, two inbound rules, both Local IP `::/0`:
     TCP `21`, and TCP `30000:30003`
4. Same verification as §3 step 3 and 4.

**`::/0` on those rules is deliberate.** It makes them survive an IPv6 prefix
change. Narrowing them to one address reintroduces a silent-failure mode.

### Bringing the IPv6 path properly back to life

```
systemctl enable --now feed-dns.timer
systemctl start feed-dns.service
tail -5 /var/log/feed-watchdog.log
```

That re-points `feed.hyperwax.io`'s AAAA at the current address and keeps it
corrected every 5 minutes as the prefix moves.

---

## 5. The MoFi — second path, pending a SIM

**Not wired up.** `nic0` shows `linkdown` and that is correct.

The point of the MoFi is a path that does not share a failure with Starlink.
That only holds if its WAN is its own cellular SIM — plugged into the same
LAN it is just another box in the same chain, which is what it was before and
why it carried nothing. **A Simbase SIM is on order; until it arrives there is
no fallback to configure.**

### When the SIM arrives

1. SIM into the MoFi, confirm it has data on its own.
2. A MoFi LAN port → Proxmox **nic0**. The address is already configured:
   `192.168.10.10/24`, MoFi LAN gateway `192.168.10.1`.
3. Add a second default route with a worse metric. In
   `/etc/network/interfaces`, under the `nic0` stanza:

```
post-up ip route add default via 192.168.10.1 dev nic0 metric 200 || true
```

4. Apply and check:

```
ifdown nic0 ; ifup nic0 ; ip route show
```

Two default routes: `192.168.1.1` with the lower metric, `192.168.10.1` at
200. Traffic takes Starlink; the MoFi sits there costing nothing.

### What this covers, and what it does not

**Covered:** the Starlink router loses power, or its cable is pulled. `nic1`
loses carrier, Linux removes that default route, everything fails over to the
MoFi on its own. DNS follows, because the resolver list in §9 falls through to
1.1.1.1 over whichever path is alive.

**Not covered:** the router stays up but the dish loses its uplink. The route
stays in the table, Linux has no idea the gateway is useless, and traffic
blackholes. **Metric-based failover does not catch this**, and it is worth
knowing rather than discovering.

Closing that gap needs a watchdog: ping something external every minute, raise
the metric on the Starlink route after N consecutive failures, put it back on
recovery. Not built — it is new machinery on a production box and has not been
authorised.

---

## 6. If Proxmox doesn't come back

In order of likelihood, and the first one is from experience:

1. **The cable is not fully seated.** It looks plugged in. It is not. On
   2026-10-03 this presented as every single NIC down and cost two hours.
   Unplug and reseat both ends until they click.

   The giveaway is that **every** interface is down at once, and every route
   says `linkdown`:

```
for n in nic0 nic1 nic2 nic3; do echo -n "$n carrier="; cat /sys/class/net/$n/carrier 2>/dev/null || echo "n/a"; done
```

   `0` means the port is up but sees no link — a cable or far-end problem.
   `n/a` means the interface is administratively down, which is normal for
   ports you are not using. If every port reads `0` or `n/a`, stop reading
   configuration files: nothing is electrically connected and no amount of
   software will fix it.

   The decisive test takes thirty seconds: put that same cable into a laptop.
   If the laptop gets a link, the problem is the server's port. If it does
   not, the problem is upstream.

2. **Cable in the wrong physical port.** `vmbr0` is bridged to **nic1**
   specifically. A different jack means no link and the host looks dead.
   nic1's MAC is `e4:43:4b:a1:5b:65`. Note that `nic0`/`nic1` are an Intel
   10-gigabit card (`ixgbe`) — check `ethtool nic1` for `Port:` and the
   supported link modes if a device will not negotiate.
3. **Router isn't on `192.168.1.1`.** The gateway line is hardcoded. Starlink
   never changes its gateway, so this only applies to a different router.
4. **Address conflict** — see §3.
5. **Router still booting.** Starlink takes 5–10 minutes after a bypass change
   or a factory reset.
6. **DNS, not the network.** Pings by IP work, nothing resolves. See §9.

Console access on the physical box always works, whatever the network is
doing. Boot messages about `L1TF CPU bug present and SMT on` and NFSD
`no clients to reclaim` are routine and appear on every boot — they are not
symptoms of anything.

---

## 7. Everything that runs on a schedule

```
systemctl list-timers --all --no-pager
```

Ours are the three `feed-*` units; the rest belong to Proxmox.

| Timer | Interval | Status |
|---|---|---|
| `feed-relay.timer` | 30 min | **required** — this is the feed |
| `feed-deadman.timer` | daily 09:00 | **required** — alerts if deliveries stop |
| `host-beat.timer` | 5 min | **required** — pushes host health to the controller |
| `net-watchdog.timer` | 1 min | **required** — fails the default route over, see §10 |
| `backup-check.timer` | 6 h | proves the backup link still works, see §10 |
| `feed-dns.timer` | 5 min | **disabled 2026-10-01** — updated an AAAA nothing uses |

```
systemctl disable --now feed-dns.timer    # off
systemctl enable --now feed-dns.timer     # back on, if the IPv6 path returns
```

`pure-ftpd` is still installed and listening. Nothing connects to it under
pull mode. Leave it if you want the push path available for another vendor:

```
systemctl stop pure-ftpd && systemctl disable pure-ftpd   # if you want it gone
```

---

## 8. Quick health check, any time

```
systemctl list-timers 'feed-*' 'host-beat*' --no-pager
tail -5 /var/log/feed-relay.log
ip route show
cat /etc/resolv.conf
ip neigh show 192.168.1.1
```

The gateway MAC in that last line is worth knowing by sight. `74:24:9f:93:76:62`
is the Starlink router. Anything else means something changed that you did not
change.

A healthy log alternates `OK` when the vendor regenerates the file and `SAME`
in between. `SAME` is the change detection working, not a failure.

To force a real run regardless:

```
rm -f /srv/feed/pull/.last-sha256
/usr/local/bin/relay.sh ; tail -1 /var/log/feed-relay.log
```

---

## 9. DNS resilience — added 2026-10-03

### What happened

The ASUS cut out briefly at 03:54 on 2026-10-03. The box could not resolve
`ftp.dealerslink.com`, the fetch died with **curl exit 6** ("could not resolve
host"), and the run failed. The next run 30 minutes later was fine.

A single resolver blip on the LAN cost a feed cycle and sent a failure email.
Two changes stop that.

### Change 1 — the resolver has somewhere else to go

`/etc/resolv.conf` had exactly one nameserver, the router. One stall, one
failure. It now reads:

```
search hyperworks.local
nameserver 192.168.1.1
nameserver 1.1.1.1
nameserver 8.8.8.8
options timeout:2 attempts:2
```

**Order is deliberate.** The router stays first so internal `.local` names keep
resolving normally; the public servers are only consulted when it does not
answer. `timeout:2` drops glibc's default 5-second wait so failover takes two
seconds instead of ten.

This is **router-agnostic**. Both the ASUS and the Starlink router live on
`192.168.1.1`, so the first entry stays correct through any swap in §3 or §4,
and the public entries cover you if that address stops answering entirely.
Nothing here depends on the MoFi.

`systemd-resolved` is `not-found` on this host and `/etc/resolv.conf` is a
real file, not a symlink into `/run`. Nothing regenerates it. If that ever
changes, this edit will silently revert — check with:

```
systemctl is-enabled systemd-resolved ; ls -l /etc/resolv.conf
```

### Change 2 — the fetch retries

The POST side of `relay.sh` always had a retry loop. The FTP fetch did not, so
one blip became a failure. The fetch is now:

```
curl -sS --max-time 180 --connect-timeout 20 --retry 3 --retry-delay 5 --retry-all-errors $FTP_SSL
```

**`--retry-all-errors` is the operative flag.** Plain `--retry` only retries
HTTP and transfer errors; it does *not* retry a DNS failure. `--retry-all-errors`
does, and it needs curl 7.71 or newer (this host runs 8.14.1).

Three retries five seconds apart means a blip like 03:54 now costs 15 seconds
instead of a cycle plus an email.

Backup of the pre-change script: `/usr/local/bin/relay.sh.bak`.

### Why the failure email said "Your App"

Worth knowing, because it looks like a branding bug and is not one.

Alert emails are sent by the Worker, which looks up the sender name from
`admin_settings` on **your self-hosted Supabase at `supabase.hyperwax.io`** —
on the same network that was failing. That lookup is wrapped:

```js
} catch (e) { console.warn('[Email] brand lookup failed:', e && e.message); }
```

Fetch fails, the row stays empty, and the name falls through to the literal
default `'Your App'`. So the one email sent *during* the outage was the only
unbranded one. `sender_name` in the database was correct the whole time and
`FEED_ALERT_APP_ID` was set correctly on the Worker.

**Diagnostic, any time:**

```
curl -s -X POST "$(. /etc/feed-alert.env; echo "$ALERT_URL")" -H 'Content-Type: application/json' --data '{"title":"Brand probe","text":"probe"}'
```

A healthy reply has all three channels populated:

```json
{"success":true,"push":{"sent":1,"total":1},"email":"sent","inbox":"ok"}
```

`"push":null,"inbox":null` means the Worker resolved no app id — check
`FEED_ALERT_APP_ID`. All three fine but the email still unbranded means the
Worker cannot reach Supabase.

### Alert emails no longer carry stale lines

`feed-alert.sh --failed` used to build its message with
`grep -E 'FAIL|HARD|FATAL' "$LOG_FILE" | tail -3`, which scanned the **whole**
log — so a FATAL from days earlier rode along in every alert and made each
failure look worse than it was. It now sends `tail -6` of the log, which is
always the current run plus a little context.

---

## 10. Failover to the backup link — added 2026-10-03

Starlink is primary. The MoFi on a Verizon SIM is the second path. Both are
outbound-only, so failover is purely a routing decision.

### Carrier is the WRONG signal here, and this cost an evening

The obvious design is `ignore_routes_with_linkdown`: lose carrier, lose the
route, fall through to the backup. **It does not work on this box.**

The default route lives on `vmbr0`, a **bridge**. A bridge reports carrier
while ANY member port is up, and `bridge link show` shows two:

```
nic1                 master vmbr0     ← the physical uplink
fwpr100p0@fwln100i0  master vmbr0     ← VM 100's firewall veth, always up
```

So `nic1` can lose its cable and `vmbr0` never notices. Verified by test:
`ip link set nic1 down`, and `ip route get 1.1.1.1` still chose
`via 192.168.1.1 dev vmbr0` while 100% of packets were lost. The route was
never marked linkdown, so the sysctl had nothing to act on.

Carrier would only signal an outage if VM 100 were also shut down — which is
exactly when you do not need failover.

The sysctl is still set in `/etc/sysctl.d/99-linkdown-failover.conf` and is
harmless, but **it is not what makes failover work.**

### What does work: probing reachability

`/usr/local/bin/net-watchdog.sh`, every minute via `net-watchdog.timer`.

```
ping -c1 -W2 -I vmbr0 1.1.1.1
```

`-I <device>` uses `SO_BINDTODEVICE`, which forces the packet out that
interface **regardless of the routing table**. That is the whole trick: it
keeps testing the Starlink link even while the Starlink route is demoted and
carrying nothing, so recovery can be detected. It also catches the case
carrier never could — router up, dish down.

Three consecutive failures demote, two consecutive successes promote.
Healthy ticks log nothing.

| Action | What changes |
|---|---|
| Demote | primary default moves to metric 500; backup's metric 200 wins |
| Promote | primary default returns to metric 0; demoted route removed |

**Only a metric is ever changed.** No interface is touched, no route is
deleted before its replacement exists, and the undo is printed at the end of
the installer.

### IPv6 needs separate handling

The backup link carries **no global IPv6** — `ip -6 addr show nic0 scope
global` returns nothing. And the v6 default cannot simply be deleted:

```
default via fe80::... dev vmbr0 proto ra metric 1024 expires 197sec
```

It is `proto ra` with `accept_ra = 2`, so the router re-advertises it within
seconds.

So on demote the watchdog adds:

```
ip -6 route add unreachable default metric 100
```

Better metric than the RA route's 1024, so it wins. Connections get
`ENETUNREACH` **immediately**, which is what Happy Eyeballs needs to fall
back to IPv4 right away instead of stalling ten seconds per connection.
Without this, IPv4 fails over cleanly and everything preferring IPv6 — which
is most modern software — keeps trying the dead link.

Only the default is overridden; on-link and link-local v6 are untouched. On
promote the override is removed and the RA route resumes instantly.

### Testing it without losing your session

Proxmox plugs straight into Starlink, so pulling that cable also cuts your
path to the box. Block the probes instead — same effect on the watchdog,
and your LAN session survives because it never uses the default route.

```
systemctl stop net-watchdog.timer
iptables -I OUTPUT -o vmbr0 -p icmp -d 1.1.1.1 -j DROP ; iptables -I OUTPUT -o vmbr0 -p icmp -d 8.8.8.8 -j DROP
/usr/local/bin/net-watchdog.sh ; /usr/local/bin/net-watchdog.sh ; /usr/local/bin/net-watchdog.sh
ip route show ; ip route get 1.1.1.1
curl -4 -s -m 10 -o /dev/null -w "%{http_code} src=%{local_ip}\n" https://edge.hyperwax.io/api/controller/setup-state
```

Want `via 192.168.10.1 dev nic0` and `src=192.168.10.10`. Then undo:

```
iptables -D OUTPUT -o vmbr0 -p icmp -d 1.1.1.1 -j DROP ; iptables -D OUTPUT -o vmbr0 -p icmp -d 8.8.8.8 -j DROP
/usr/local/bin/net-watchdog.sh ; /usr/local/bin/net-watchdog.sh
systemctl start net-watchdog.timer
```

**Use a URL that actually answers.** `https://edge.hyperwax.io/` returns
nothing on a bare GET — an evening was spent chasing MTU and anycast theories
because the test URL was dead, not the path. `/api/controller/setup-state` is
an open GET that returns 200.

### `--interface` binds DNS too

`curl --interface nic0` binds **every** socket to that device, DNS included.
The first resolver in `/etc/resolv.conf` is on the primary LAN and is
unreachable from the backup interface, so a bound request stalls on name
resolution and looks like a dead link. Resolve the name over the normal path
first and pass `--resolve`. This only affects manual testing — during a real
failover nothing is bound and DNS falls through to 1.1.1.1 normally.

### Proving the spare tyre is still inflated

`/usr/local/bin/backup-check.sh`, every six hours via `backup-check.timer`.

A failover path that is never exercised is a guess: a prepaid SIM can be
suspended for inactivity, a carrier can change something, the MoFi can
quietly drop off — and you would find out at the moment you needed it.

It makes a real HTTPS request over the backup interface, not a ping. ICMP
passing proves very little; this setup spent an evening on a host that
answered pings and refused connections. Roughly 2KB per run, four runs a day.

Alerts are **latched** — one message when the backup goes down, one when it
returns, however long it stays broken.

### VM 100 fails over too — solved 2026-10-03

The platform is reachable through a **Cloudflare tunnel**, and the tunnel is
**outbound** from the VM:

```
internet → Cloudflare (A + AAAA anycast) → tunnel → cloudflared in VM 100 → Traefik :443
```

`cloudflared` runs as a **systemd service** in the VM, not a container, which
is why `docker ps` does not show it:

```
/usr/bin/cloudflared --no-autoupdate tunnel run --token eyJ...
```

Because nothing needs to reach in, the VM only needs *some* outbound path. So
Proxmox became its gateway and it inherits the host's failover with no
watchdog of its own.

**Host** — forwarding plus one NAT rule, persisted in `/etc/sysctl.d/99-vm-failover.conf`
and a `post-up` on the `vmbr0` stanza:

```
net.ipv4.ip_forward=1
iptables -t nat -A POSTROUTING -s 192.168.1.228/32 ! -d 192.168.1.0/24 -j MASQUERADE
```

**No `-o` on that rule, deliberately.** It masquerades out of whichever
interface currently holds the default route, so the VM follows the host
automatically with nothing to keep in step. The `post-up` uses `-C` first so
re-running `ifup` cannot stack duplicate rules.

**VM** — `/etc/netplan/99-static.yaml`, default changed from `192.168.1.1` to
`192.168.1.224`. Applied with `netplan try`, which auto-reverts after 120
seconds unless confirmed — use that, not `netplan apply`, when editing the
gateway of the box running the platform.

Its nameservers are already `1.1.1.1, 8.8.8.8` rather than the router, so DNS
works on either path with no change.

### What happens during an outage

The VM's outbound source address changes when the host fails over, so
Cloudflare sees the QUIC sessions move and cloudflared re-registers. Measured:
all four connections back within **31 seconds**, across den01/den03/mci01/mci03.
The brief `failed to accept QUIC stream` errors in the journal during that
window are expected, not a fault.

**Verified end to end, twice — and both runs happened while a vzdump backup
was in flight**, so the failover carried real I/O contention and still
answered in under half a second:

```
public-over-cellular:401 t=0.349921
```

A **401 is success** — it means Cloudflare → tunnel → Traefik → Kong all
worked and Kong refused an unauthenticated request. A broken path returns
`000`. That curl exits via Starlink from the operator side, so it is a
genuine outside-in test, not the box checking itself.

### Two things to remember

**IPv6 on the VM — handled 2026-10-03.** The VM learns its v6 default from
Starlink's RA and the host cannot touch it. If the router stays up with a dead
dish, RAs keep arriving and v6 blackholes indefinitely. Two changes:

1. `cloudflared` pinned to IPv4 edges with a **drop-in**, so the unit's
   ExecStart — which carries the tunnel token — is never edited:

```
/etc/systemd/system/cloudflared.service.d/edge-ipv4.conf
[Service]
Environment=TUNNEL_EDGE_IP_VERSION=4
```

   The flag reads `$TUNNEL_EDGE_IP_VERSION` and defaults to `auto`. Logs
   showed it already choosing v4 edges, so this is insurance against `auto`
   deciding otherwise, not a fix for a live fault.

2. `/etc/gai.conf` on the VM now ends with:

```
precedence ::ffff:0:0/96  100
```

   This covers everything else the VM dials out to — Docker pulls, app calls
   to external APIs — which would otherwise prefer v6 and stall.

**Note the glibc quirk:** setting any `precedence` line makes glibc discard
its entire default precedence table and use only what is written. That is
documented behaviour and this exact line is Debian's own commented example,
but it is a bigger hammer than it looks.

It is permanent, not outage-only. That is deliberate: **only one of the two
uplinks carries IPv6 at all**, so preferring IPv4 means the VM behaves
identically whichever link is live. Fewer behaviours to reason about at 3am.
Rollback is `cp /etc/gai.conf.bak /etc/gai.conf` — read per-lookup, no
restart needed.

**Data.** A Starlink outage now means the platform serves real traffic over a
metered SIM. That is the point, but the failover alert says the link is
metered for a reason: that is the moment to decide whether to let it run or
pull the plug deliberately.

### Not yet proven

None of this has survived a reboot. The persistence is written
(`/etc/network/interfaces`, `/etc/sysctl.d/`, netplan) but untested. Worth a
deliberate reboot at a quiet moment, then:

```
ip route show ; iptables -t nat -L POSTROUTING -n | grep 192.168.1.228 ; sysctl net.ipv4.ip_forward
ssh hyperwax@192.168.1.228 'ip route show'
```
