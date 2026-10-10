#!/usr/bin/env python3
"""
patch_controller_036.py - adds the feed + infra plane to worker.js.

Same discipline as patch_controller.py: unique anchors, assert-before-write,
idempotent, refuses rather than guesses.

  python3 patch_controller_036.py worker.js

Adds, behind requireController:
  GET  /api/controller/feed-health
  GET  /api/controller/feed-runs?feed_id=&limit=
  GET  /api/controller/hosts

Adds, OUTSIDE requireController (Proxmox has no browser session):
  POST /api/controller/host-beat?token=...
"""
import sys, os

# ---------------------------------------------------------------- ingest route
# Sits with setup-state/setup/login, BEFORE the requireController gate, because
# the caller is a systemd timer on a box with no session. Token auth instead:
# HOST_BEAT_TOKEN if set, otherwise the FEED_ALERT_TOKEN the box already holds,
# so this works without provisioning a second secret.
INGEST = r'''
        // Host heartbeat ingest. Proxmox is behind CGNAT so nothing can poll
        // it - the box pushes, and silence is the signal. Deliberately before
        // requireController: the caller is a systemd timer, not a browser.
        //
        // Writes with the service role because gs_host_beats is platform-only
        // and the beat carries no caller identity beyond its token.
        if (leaf === 'host-beat' && request.method === 'POST') {
            try {
                const want = env.HOST_BEAT_TOKEN || env.FEED_ALERT_TOKEN || '';
                if (!want) return gsCtlJson({ error: 'host beats not configured' }, 503);
                const got = url.searchParams.get('token') || request.headers.get('X-Alert-Token') || '';
                // Same silence as the feed and alert routes: a wrong token
                // learns nothing about whether the route exists.
                if (got !== want) return new Response('unauthorized', { status: 401, headers: GS_CTL_CORS });

                const b = await request.json().catch(() => ({}));
                const host = String(b.host || '').trim().slice(0, 120);
                if (!host) return gsCtlJson({ error: 'host is required' }, 400);

                const svc = env.SUPABASE_SERVICE_ROLE_KEY || env.SUPABASE_SERVICE_ROLE || env.SUPABASE_SERVICE_KEY;
                if (!svc) return gsCtlJson({ error: 'service role not configured' }, 503);

                const num = (v) => (v === null || v === undefined || v === '' || isNaN(Number(v))) ? null : Number(v);
                const row = {
                    host: host,
                    beat_at: new Date().toISOString(),
                    uptime_s: num(b.uptime_s),
                    load1: num(b.load1),
                    mem_used_pct: num(b.mem_used_pct),
                    disk_used_pct: num(b.disk_used_pct),
                    failed_units: num(b.failed_units),
                    failed_unit_names: b.failed_unit_names ? String(b.failed_unit_names).slice(0, 500) : null,
                    dns_ok: typeof b.dns_ok === 'boolean' ? b.dns_ok : null,
                    feed_timer_ok: typeof b.feed_timer_ok === 'boolean' ? b.feed_timer_ok : null,
                    last_backup_status: b.last_backup_status ? String(b.last_backup_status).slice(0, 120) : null,
                    extra: (b.extra && typeof b.extra === 'object') ? b.extra : null
                };
                const r = await fetch(`${env.SUPABASE_URL}/rest/v1/gs_host_beats`, {
                    method: 'POST',
                    headers: { 'apikey': svc, 'Authorization': `Bearer ${svc}`, 'Content-Type': 'application/json', 'Prefer': 'return=minimal' },
                    body: JSON.stringify(row)
                });
                if (!r.ok) return gsCtlJson({ error: 'insert failed ' + r.status, detail: (await r.text()).slice(0, 300) }, 502);

                // Keep the table from growing without bound. One beat every
                // five minutes is ~8.6k rows a month per host; 14 days is
                // plenty of history for spotting an outage pattern.
                try {
                    const cut = new Date(Date.now() - 14 * 86400000).toISOString();
                    await fetch(`${env.SUPABASE_URL}/rest/v1/gs_host_beats?beat_at=lt.${encodeURIComponent(cut)}`, {
                        method: 'DELETE',
                        headers: { 'apikey': svc, 'Authorization': `Bearer ${svc}`, 'Prefer': 'return=minimal' }
                    });
                } catch (e) { /* pruning is best-effort, never fail a beat on it */ }

                return gsCtlJson({ ok: true });
            } catch (e) {
                return gsCtlJson({ error: String(e && e.message || e) }, 500);
            }
        }
'''

# ------------------------------------------------------------- read-only leaves
READS = r'''
            // Dealerslink feed. gs_feed_health is one row per configured feed
            // with its newest run folded in; the view excludes secret_token
            // and the FTP credentials by naming its columns.
            //
            // age_s comes from last_run_at, and a row only lands when the
            // vendor's file CHANGED - the relay skips identical files, so
            // gaps of 9-15 hours are normal. The console colours on 26h to
            // match STALE_HOURS in feed-alert.sh.
            if (leaf === 'feed-health' && request.method === 'GET') {
                return await pass('gs_feed_health?select=*&order=last_run_at.desc.nullslast');
            }

            if (leaf === 'feed-runs' && request.method === 'GET') {
                const fid = url.searchParams.get('feed_id') || '';
                const limit = Math.min(parseInt(url.searchParams.get('limit') || '30', 10) || 30, 200);
                let q = 'gs_feed_runs?select=*';
                if (fid) q += `&feed_id=eq.${encodeURIComponent(fid)}`;
                q += `&order=finished_at.desc.nullslast&limit=${limit}`;
                return await pass(q);
            }

            // Latest beat per host. A host that stopped beating still returns
            // its last row with a growing age_s - absence is the signal, so
            // the row must not disappear.
            if (leaf === 'hosts' && request.method === 'GET') {
                return await pass('gs_host_health?select=*&order=host.asc');
            }
'''

INGEST_ANCHOR = "        const ctl = await requireController(env, request);"
READ_ANCHOR   = "            if (leaf === 'fleet' && request.method === 'GET') {"

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'worker.js'
    if not os.path.exists(path):
        sys.exit(f"FAIL: {path} not found")
    src = open(path, encoding='utf-8').read()

    if "leaf === 'feed-health'" in src and "leaf === 'host-beat'" in src:
        print("already patched - nothing to do")
        return

    for name, anchor in (("ingest", INGEST_ANCHOR), ("reads", READ_ANCHOR)):
        n = src.count(anchor)
        if n != 1:
            sys.exit(f"FAIL: {name} anchor found {n} times, expected exactly 1. "
                     f"Nothing written.")

    out = src.replace(INGEST_ANCHOR, INGEST + "\n" + INGEST_ANCHOR, 1)
    out = out.replace(READ_ANCHOR, READS + "\n" + READ_ANCHOR, 1)

    open(path + '.bak', 'w', encoding='utf-8').write(src)
    open(path, 'w', encoding='utf-8').write(out)
    print(f"patched {path} (+{len(out)-len(src)} bytes). backup at {path}.bak")

if __name__ == '__main__':
    main()
