#!/usr/bin/env python3
"""
patch_controller_045.py - the Worker learns what the relay saw on EVERY run,
so the controller can tell a quiet vendor from a broken relay.

Requires 043 (infra triage + notify) and 044. Unique anchors, assert before
write, idempotent. Run 045_feed_checks.sql first; the order is safe either way
(see "DEPLOY ORDER" below) but nothing shows until both are in.

  python3 patch_controller_045.py worker.js

WHAT WAS MISSING
dealer_feed_runs only gets a row when the vendor's file CHANGED. From
2026-10-04 03:47 to 10-05 12:49 the relay fetched the file 58 times, found it
identical every time, and said so only in its own log on the box. From here a
quiet vendor and a dead relay were the same thing: "last import 33h ago".

WHAT THIS ADDS
1. POST /api/feed/check?token=...&result=same|fetch_failed|refused[&bytes=N]
   Its own route beside /api/feed/inbound, same feed token, no file. Stores
   the report on the feed row (last_check_at / _result / _bytes / _note). A
   real import stamps 'changed' itself, so every run of relay.sh leaves a
   mark. A Worker without this patch answers 404 to it and records nothing.
2. Feed findings in the triage pass, written in code (no model call):
     feed_vendor_quiet   warn      checks arriving, file unchanged > 26h.
                                   Console only. The box's dead-man already
                                   pages once for this; it now says why.
     feed_fetch_failing  warn      the relay reached us to say it cannot
                                   download the file. The box already alerts
                                   on each failed run (feed-failed.service).
     feed_file_refused   warn      downloaded, but too small / not the
                                   inventory file, so not forwarded.
     feed_not_checking   critical  no report for 90 minutes. This one is
                                   ours and nothing else catches it (a stuck
                                   lock exits 0 and logs one line). Pages -
                                   unless a host is already silent or its
                                   feed timer is already reported down, which
                                   has paged for the same outage.
3. The first responder is told how to read the new fields.

DEPLOY ORDER
SQL -> Worker -> box is the intended order. If the Worker lands before the
SQL, the check columns do not exist yet: the report is refused with a 503 and
a plain message, and imports are NOT affected - the check is written by its
own PATCH, never folded into the one that records last_run_at.
"""
import sys, os

# ── 1. the report: its own route, beside the import route ───────────────────
# A separate path on purpose. As a parameter on /api/feed/inbound, a report
# sent to a Worker WITHOUT this patch (box updated first, or the Worker rolled
# back later) would be read as an import of an empty file and logged as a
# failed run every 30 minutes. On its own path an older Worker simply answers
# 404 and nothing is recorded.
INBOUND_OLD = """    if (url.pathname === '/api/feed/inbound' && (request.method === 'POST' || request.method === 'PUT')) {
"""
INBOUND_NEW = """    // A report, not a file. relay.sh sends one after every run that did NOT
    // import: the file was unchanged, could not be fetched, or was refused.
    // Without it a quiet vendor and a dead relay are indistinguishable from
    // here - both are just "no import". Same token as the import route, so
    // there is nothing new to provision and a report can only ever land on
    // the feed that token owns.
    if (url.pathname === '/api/feed/check' && request.method === 'POST') {
        const J = { ...corsHeaders, 'Content-Type': 'application/json' };
        try {
            const token = url.searchParams.get('token') || request.headers.get('X-Feed-Token') || '';
            if (!token) return new Response('missing token', { status: 401, headers: corsHeaders });
            const svc = env.SUPABASE_SERVICE_ROLE_KEY || env.SUPABASE_SERVICE_ROLE || env.SUPABASE_SERVICE_KEY;
            if (!svc) return new Response('service key not configured', { status: 500, headers: corsHeaders });

            const fr = await fetch(`${env.SUPABASE_URL}/rest/v1/dealer_feeds?secret_token=eq.${encodeURIComponent(token)}&enabled=eq.true&select=id&limit=1`,
                { headers: { 'apikey': svc, 'Authorization': `Bearer ${svc}` } });
            const feeds = await fr.json();
            const feed = Array.isArray(feeds) ? feeds[0] : null;
            // Same silence as the import route: a bad token and a disabled
            // feed look alike, so this cannot be used to test tokens.
            if (!feed) return new Response('unauthorized', { status: 401, headers: corsHeaders });

            const result = String(url.searchParams.get('result') || '').toLowerCase();
            // 'changed' is never accepted from a caller: only a real import
            // stamps it, in the import route below.
            if (!GS_FEED_CHECKS[result] || result === 'changed') {
                return new Response(JSON.stringify({ success: false, error: 'unknown result' }), { status: 400, headers: J });
            }
            const note = (await request.text().catch(() => '')).replace(/[\\u0000-\\u001f]+/g, ' ').trim().slice(0, 300);
            const saved = await gsFeedStampCheck(env, feed, result, url.searchParams.get('bytes'), note);
            if (!saved.ok) return new Response(JSON.stringify({ success: false, error: saved.error }), { status: 503, headers: J });
            return new Response(JSON.stringify({ success: true, result }), { headers: J });
        } catch (e) {
            return new Response(JSON.stringify({ success: false, error: e.message }), { status: 500, headers: J });
        }
    }

    if (url.pathname === '/api/feed/inbound' && (request.method === 'POST' || request.method === 'PUT')) {
"""

IMPORTED_OLD = """            await gsLogFeedRun(env, feed, stat, stat.errors.length ? 'partial' : 'ok', 'push');
            return new Response(JSON.stringify({ success: true, ...stat }), { headers: { ...corsHeaders, 'Content-Type': 'application/json' } });
"""
IMPORTED_NEW = """            await gsLogFeedRun(env, feed, stat, stat.errors.length ? 'partial' : 'ok', 'push');
            // An import is a check too: the relay fetched a file and it was new.
            await gsFeedStampCheck(env, feed, 'changed', text.length, null);
            return new Response(JSON.stringify({ success: true, ...stat }), { headers: { ...corsHeaders, 'Content-Type': 'application/json' } });
"""

# ── 2. the helper ───────────────────────────────────────────────────────────
HELPER_ANCHOR = "async function gsLogFeedRun(env, feed, stat, status, note) {"
HELPER = """// What relay.sh can report about one run. 'changed' is never sent by the
// relay: the import route stamps it after a successful import.
const GS_FEED_CHECKS = { changed: 1, same: 1, fetch_failed: 1, refused: 1 };

// Records the newest report on the feed row (migration 045).
// Its own PATCH on purpose. Folding these columns into gsLogFeedRun's update
// would make that update fail outright wherever 045 has not been run, and
// last_run_at would stop moving - breaking the thing this exists to explain.
async function gsFeedStampCheck(env, feed, result, bytes, note) {
    try {
        const svc = env.SUPABASE_SERVICE_ROLE_KEY || env.SUPABASE_SERVICE_ROLE || env.SUPABASE_SERVICE_KEY;
        if (!svc) return { ok: false, error: 'service key not configured' };
        const n = parseInt(bytes, 10);
        const r = await fetch(`${env.SUPABASE_URL}/rest/v1/dealer_feeds?id=eq.${feed.id}`, {
            method: 'PATCH',
            headers: { 'apikey': svc, 'Authorization': `Bearer ${svc}`, 'Content-Type': 'application/json', 'Prefer': 'return=minimal' },
            body: JSON.stringify({
                last_check_at: new Date().toISOString(),
                last_check_result: result,
                last_check_bytes: (isNaN(n) || n < 0) ? null : n,
                last_check_note: note ? String(note).slice(0, 300) : null
            })
        });
        if (r.ok) return { ok: true };
        const detail = (await r.text()).slice(0, 200);
        console.warn('[feed] check not stored:', r.status, detail);
        return { ok: false, error: 'check not stored (HTTP ' + r.status + '). Has 045_feed_checks.sql been run? ' + detail };
    } catch (e) {
        console.warn('[feed] check:', e && e.message);
        return { ok: false, error: String(e && e.message || e) };
    }
}

"""

# ── 3. feed findings ────────────────────────────────────────────────────────
TRIAGE_FN_ANCHOR = """// Cron pass. Self-throttled on a KV key so a more frequent trigger is
// harmless - the same property gsRunDueFeeds and the snapshot sweep rely on.
async function gsInfraTriage(env) {"""
TRIAGE_FN = r"""// ============================================================================
// FEED TRIAGE
// ============================================================================
// 26h matches STALE_HOURS on the box and FEED_STALE_S in the console: the
// three must agree or the console and the alert tell different stories.
const GS_FEED_STALE_S = 26 * 3600;
// The relay reports every 30 minutes whether or not the file changed. Three
// missed in a row is not jitter.
const GS_FEED_CHECK_FRESH_S = 90 * 60;

function gsFeedSpan(s) {
    s = Math.max(0, Math.floor(Number(s) || 0));
    if (s < 3600) return Math.max(1, Math.round(s / 60)) + ' min';
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
    return h + 'h' + (h < 6 && m ? ' ' + m + 'm' : '');
}

// One feed row from gs_feed_health -> zero or one finding. Pure, so it can be
// tested without a database. Verdict and steps are written here rather than
// asked of the model: each case has exactly one meaning, and a fixed sentence
// cannot drift.
//
// covered: a host is already silent, or its feed timer is already reported
// down. Either has paged for this same outage, so the feed does not page a
// second time for it.
function gsFeedDetect(f, covered) {
    const out = [];
    if (!f || f.enabled === false) return out;
    // Never reported: 045 is not on the box yet, or this is a pull-mode feed
    // the Worker fetches itself. Nothing to judge - and NOT stale. A feed
    // that has never checked in is not a feed that stopped.
    if (!f.last_check_at || f.check_age_s == null) return out;

    const who = String(f.provider || 'the vendor');
    const res = String(f.last_check_result || '').toLowerCase();
    const checkAge = Number(f.check_age_s);
    const note = String(f.last_check_note || '').trim();
    const ev = { feed_id: f.feed_id, app: f.app_name || f.app_id, provider: f.provider,
                 last_check_result: res, check_age_s: checkAge, age_s: f.age_s, bytes: f.last_check_bytes, note: note || null };
    const log = 'Proxmox shell: tail -20 /var/log/feed-relay.log';

    if (checkAge > GS_FEED_CHECK_FRESH_S) {
        if (covered) return out;
        out.push({ kind: 'feed_not_checking', fingerprint: 'feed-silent:' + f.feed_id, severity: 'critical', evidence: ev,
            verdict: 'The feed relay has not reported for ' + gsFeedSpan(checkAge) + '. It reports every 30 minutes whether or not the file changed, so this is on our side, not ' + who + ': the timer, relay.sh itself, or the box\'s route to the edge.',
            steps: '1. Proxmox shell: systemctl list-timers \'feed-*\' --no-pager\n2. ' + log + '\n3. Proxmox shell: /usr/local/bin/relay.sh ; echo "exit: $?"' });
        return out;
    }
    if (res === 'fetch_failed') {
        out.push({ kind: 'feed_fetch_failing', fingerprint: 'feed-fetch:' + f.feed_id, severity: 'warn', evidence: ev,
            verdict: 'The relay cannot download the file from ' + who + (note ? ' (' + note + ')' : '') + '. It reached us to say so ' + gsFeedSpan(checkAge) + ' ago, so the box and its internet are up. The problem is between the box and the vendor\'s FTP.',
            steps: '1. ' + log + '\n2. Read the curl exit code in that log: 6 is DNS on the box, 7 or 28 is their FTP down or slow, 67 is the login being refused.' });
        return out;
    }
    if (res === 'refused') {
        out.push({ kind: 'feed_file_refused', fingerprint: 'feed-refused:' + f.feed_id, severity: 'warn', evidence: ev,
            verdict: 'The relay downloaded a file from ' + who + ' and refused to forward it' + (note ? ': ' + note : '') + '. That guard is deliberate: a truncated file would retire the whole lot.',
            steps: '1. ' + log + '\n2. If it repeats, the export on the vendor\'s side is broken. There is nothing to fix on ours.' });
        return out;
    }
    if (res === 'same' && f.age_s != null && Number(f.age_s) > GS_FEED_STALE_S) {
        const size = f.last_check_bytes != null ? ' (' + Number(f.last_check_bytes).toLocaleString('en-US') + ' bytes)' : '';
        out.push({ kind: 'feed_vendor_quiet', fingerprint: 'feed-quiet:' + f.feed_id, severity: 'warn', evidence: ev,
            verdict: 'The file from ' + who + ' has not changed in ' + gsFeedSpan(f.age_s) + '. The relay fetched it ' + gsFeedSpan(checkAge) + ' ago and it was identical' + size + ', so the relay, the network and the importer are all working. Nothing is broken on our side.',
            steps: 'Nothing to run. The lot updates with the next file the vendor publishes, and this clears by itself when it does.' });
    }
    return out;
}

// Runs inside the infra triage pass, after the hosts. Feed findings live in
// the same table under a host name of "feed: <app>", so they show in the
// same list, resolve the same way, and need no schema of their own.
async function gsFeedTriage(env, H, rest, latest, openKey) {
    try {
        const ph = await gsPlatformHeaders(env, {});
        const fr = await fetch(rest('gs_feed_health?select=*'), { headers: ph });
        const feeds = await fr.json();
        if (!Array.isArray(feeds)) return;

        let covered = false;
        Object.keys(latest || {}).forEach((h) => {
            const b = latest[h];
            if (Number(b.age_s || 0) > 15 * 60 || b.feed_timer_ok === false) covered = true;
        });

        const seen = {};
        const mine = {};
        for (const f of feeds) {
            if (!f || !f.feed_id) continue;
            const host = ('feed: ' + String(f.app_name || String(f.app_id || '').slice(0, 8) || f.feed_id)).slice(0, 120);
            mine[host] = true;
            for (const d of gsFeedDetect(f, covered)) {
                seen[host + '|' + d.fingerprint] = true;
                if (openKey[host + '|' + d.fingerprint]) continue;      // already filed
                await fetch(rest('gs_infra_findings'), {
                    method: 'POST', headers: { ...H, 'Prefer': 'return=minimal' },
                    body: JSON.stringify({
                        host, kind: d.kind, fingerprint: d.fingerprint, severity: d.severity,
                        verdict: d.verdict, steps: d.steps || null, evidence: d.evidence,
                        remedy: null, remedy_state: 'none'
                    })
                });
                if (d.severity === 'critical') {
                    await gsInfraNotify(env, 'Feed: ' + String(d.kind).replace(/_/g, ' ') + ' - ' + host.slice(6),
                        d.verdict + (d.steps ? '\n\nWhat to do:\n' + d.steps : ''));
                }
            }
        }
        // A feed finding that no longer shows up has cleared. Only rows this
        // pass owns - the host loop above never sees a "feed: " host, and
        // this must never close a real host's finding.
        for (const k of Object.keys(openKey)) {
            const f = openKey[k];
            if (!f || String(f.host || '').indexOf('feed: ') !== 0 || seen[k]) continue;
            // While an outage is covered by a host finding, a feed finding
            // that is already open stays open rather than flapping shut.
            if (covered && f.kind === 'feed_not_checking') continue;
            await fetch(rest(`gs_infra_findings?id=eq.${f.id}`), {
                method: 'PATCH', headers: { ...H, 'Prefer': 'return=minimal' },
                body: JSON.stringify({ resolved_at: new Date().toISOString() })
            });
            if (f.severity === 'critical') {
                await gsInfraNotify(env, 'Cleared: ' + String(f.kind || 'issue').replace(/_/g, ' ') + ' - ' + String(f.host).slice(6),
                    'The relay is reporting again. Nothing further to do.');
            }
        }
    } catch (e) { console.warn('[feed] triage:', e && e.message); }
}

"""

TRIAGE_CALL_OLD = """    } catch (e) { console.warn('[infra] triage:', e && e.message); }
}"""
TRIAGE_CALL_NEW = """        // Feeds, after the hosts: whether a host is silent decides whether a
        // quiet relay is news or the same outage seen twice.
        await gsFeedTriage(env, H, rest, latest, openKey);
    } catch (e) { console.warn('[infra] triage:', e && e.message); }
}"""

# ── 4. what the first responder is told ─────────────────────────────────────
SYS_OLD = """26 hours is the staleness threshold, matching STALE_HOURS in feed-alert.sh.
"""
SYS_NEW = """26 hours is the staleness threshold, matching STALE_HOURS in feed-alert.sh.
- The relay REPORTS EVERY RUN, not only the ones that import. Each feed row carries last_check_at, last_check_result, last_check_bytes, last_check_note and check_age_s. Read them before judging an old "last import": result "same" with a check_age_s under 90 minutes means the relay fetched the file minutes ago and it was identical - the VENDOR IS QUIET and nothing on our side is broken, however old the last import is. Say that plainly; do not send him to the box to confirm what the row already shows. "fetch_failed" means the relay reached us but cannot download from the vendor (the note carries the curl exit code). "refused" means it downloaded a file that was too small or not the inventory file and deliberately did not forward it. A check_age_s over 90 minutes means the relay itself has stopped reporting: that is ours. Null check fields mean that feed has never reported - judge it on age_s alone, as before.
- These reports are in the relay's log file, /var/log/feed-relay.log, as SAME / OK / FAIL lines. They are NOT in journalctl, which only holds systemd's start and finish lines for the unit. Never send him to journalctl for them.
"""


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'worker.js'
    if not os.path.exists(path):
        sys.exit(f"FAIL: {path} not found")
    src = open(path, encoding='utf-8').read()

    if 'gsFeedStampCheck' in src and 'gsFeedTriage' in src:
        print("already patched - nothing to do")
        return
    if 'async function gsInfraNotify(' not in src:
        sys.exit("FAIL: 043 is not applied to this worker. Run patch_controller_043.py first.")
    if 'const hist = [];' not in src:
        sys.exit("FAIL: 044 is not applied to this worker. Run patch_controller_044.py first.")

    hunks = [("report route", INBOUND_OLD, INBOUND_NEW),
             ("import stamps a check", IMPORTED_OLD, IMPORTED_NEW),
             ("helper", HELPER_ANCHOR, HELPER + HELPER_ANCHOR),
             ("feed triage", TRIAGE_FN_ANCHOR, TRIAGE_FN + TRIAGE_FN_ANCHOR),
             ("triage call", TRIAGE_CALL_OLD, TRIAGE_CALL_NEW),
             ("system prompt", SYS_OLD, SYS_NEW)]
    for name, old, _ in hunks:
        n = src.count(old)
        if n != 1:
            sys.exit(f"FAIL: {name} anchor found {n} times, expected exactly 1. Nothing written.")

    out = src
    for _, old, new in hunks:
        out = out.replace(old, new, 1)

    open(path + '.bak', 'w', encoding='utf-8').write(src)
    open(path, 'w', encoding='utf-8').write(out)
    print(f"patched {path} ({len(out)-len(src):+d} bytes). backup at {path}.bak")


if __name__ == '__main__':
    main()
