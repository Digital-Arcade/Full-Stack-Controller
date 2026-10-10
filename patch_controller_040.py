#!/usr/bin/env python3
"""
patch_controller_040.py - infra triage, findings, and the remedy queue.

Requires 038 (which requires 037 and 036). Unique anchors, assert before
write, idempotent, refuses rather than guesses.

  python3 patch_controller_040.py worker.js

Adds:
  gsInfraTriage(env)                    - cron pass, detects + judges + files
  GET  /api/controller/findings         - open findings for the console
  POST /api/controller/finding-ack      - acknowledge or resolve one
  host-beat response now carries a remedy, and accepts last_remedy back

THE SAFETY PROPERTY: the model never emits a command. Conditions are detected
in code, code proposes a candidate from a fixed allowlist, and the model may
only APPROVE or VETO it. A misread system can therefore produce a wrong-but-
harmless remedy, never an invented destructive one.
"""
import sys, os

FUNCS = r'''
// ============================================================================
// INFRA TRIAGE
// ============================================================================
// Every remedy a host can be asked to run. The NAME travels; the command
// lives in host-beat.sh on the box and is never sent over the wire. Adding
// an entry here does nothing until the box also knows the name, which is the
// point - the Worker cannot teach a host a new command.
const GS_REMEDIES = {
    clear_failed_unit: 'systemctl reset-failed on the named unit. Clears a stale failed flag; changes nothing that is running.',
    restart_feed_timer: 'systemctl restart feed-relay.timer. Idempotent; worst case the next fetch happens early.',
    rerun_feed: 'Runs /usr/local/bin/relay.sh once. Already safe to run by hand and carries its own guards.'
};

// Conditions are detected here, in code, not by the model. Each returns a
// stable fingerprint so a fault lasting a day is one finding, not 288.
function gsInfraDetect(b) {
    const out = [];
    const age = Number(b.age_s == null ? 0 : b.age_s);

    if (age > 15 * 60) {
        // Deliberately no candidate: a host that cannot be reached cannot be
        // handed a remedy either. This one is always for the human.
        out.push({ kind: 'silent_host', fingerprint: 'silent', severity: 'critical', candidate: null,
                   evidence: { age_s: age, last_beat: b.beat_at } });
        return out;   // nothing else on this beat is current, so do not judge it
    }
    if (Number(b.failed_units || 0) > 0) {
        out.push({ kind: 'failed_unit', fingerprint: 'failed:' + String(b.failed_unit_names || ''),
                   severity: 'warn', candidate: 'clear_failed_unit',
                   evidence: { failed_units: b.failed_units, names: b.failed_unit_names } });
    }
    if (b.feed_timer_ok === false) {
        out.push({ kind: 'feed_timer_down', fingerprint: 'feedtimer', severity: 'critical',
                   candidate: 'restart_feed_timer', evidence: { feed_timer_ok: false } });
    }
    if (b.dns_ok === false) {
        // Structurally handled already by the fallback resolvers and
        // --retry-all-errors. If it is STILL failing, that is a real outage
        // and must not be papered over by an automatic action.
        out.push({ kind: 'dns_failing', fingerprint: 'dns', severity: 'critical', candidate: null,
                   evidence: { dns_ok: false, probe: b.extra && b.extra.dns_probe } });
    }
    const lb = String(b.last_backup_status || '').trim();
    if (lb && lb.toUpperCase() !== 'OK') {
        // No candidate on purpose: re-running a vzdump doubles the I/O and
        // the usual cause is two schedules racing for the same lock, which
        // is a config fix in /etc/pve/jobs.cfg.
        out.push({ kind: 'backup_errors', fingerprint: 'backup:' + lb, severity: 'warn', candidate: null,
                   evidence: { last_backup_status: lb } });
    }
    if (Number(b.disk_used_pct || 0) >= 90) {
        out.push({ kind: 'disk_high', fingerprint: 'disk', severity: 'warn', candidate: null,
                   evidence: { disk_used_pct: b.disk_used_pct } });
    }
    return out;
}

// Asks the model for a verdict and numbered steps, and lets it VETO the
// candidate remedy. It cannot choose a different one: the return is read as
// a boolean against the candidate code already picked.
async function gsInfraJudge(env, host, finding, beat) {
    const fallback = {
        verdict: 'Detected automatically; no model verdict available.',
        steps: 'Open the Infra tab and use Ask AI on this host for a full diagnosis.',
        approve: false
    };
    if (!env.CLAUDE_API_KEY) return fallback;
    try {
        const r = await fetch('https://api.anthropic.com/v1/messages', {
            method: 'POST',
            headers: { 'x-api-key': env.CLAUDE_API_KEY, 'anthropic-version': '2023-06-01', 'content-type': 'application/json' },
            body: JSON.stringify({
                model: gsClaudeModel('claude-opus-5'),
                max_tokens: 1500,
                system: GS_CTL_ASK_SYSTEM + `

You are triaging ONE infra finding, unattended, and writing what the operator will read later. Reply with JSON only, no prose around it:
{"verdict":"one or two sentences on what this is and whether it matters",
 "steps":"numbered steps the operator runs, naming the machine for each, or an empty string if a remedy handles it",
 "approve_remedy":true|false,
 "why":"one sentence on why the remedy is or is not appropriate here"}

A candidate remedy may be offered to you. You may approve it or refuse it. You cannot choose a different one and you cannot write a command - only the name you were given is ever run, and only if you approve it. Refuse whenever the evidence does not clearly match what the remedy does, and say so in "why". If no candidate was offered, approve_remedy must be false.`,
                messages: [{ role: 'user', content: JSON.stringify({
                    host: host,
                    finding: { kind: finding.kind, severity: finding.severity, evidence: finding.evidence },
                    candidate_remedy: finding.candidate ? { name: finding.candidate, does: GS_REMEDIES[finding.candidate] } : null,
                    latest_beat: beat
                }, null, 1) }]
            })
        });
        if (!r.ok) return fallback;
        const d = await r.json();
        const txt = (d.content || []).filter(x => x.type === 'text').map(x => x.text).join('').trim();
        const m = txt.match(/\{[\s\S]*\}/);
        if (!m) return fallback;
        const j = JSON.parse(m[0]);
        return {
            verdict: String(j.verdict || fallback.verdict).slice(0, 2000),
            steps: String(j.steps || '').slice(0, 4000),
            approve: j.approve_remedy === true,
            why: String(j.why || '').slice(0, 600)
        };
    } catch (e) {
        console.warn('[infra] judge:', e && e.message);
        return fallback;
    }
}

// Cron pass. Self-throttled on a KV key so a more frequent trigger is
// harmless - the same property gsRunDueFeeds and the snapshot sweep rely on.
async function gsInfraTriage(env) {
    try {
        const svc = env.SUPABASE_SERVICE_ROLE_KEY || env.SUPABASE_SERVICE_ROLE || env.SUPABASE_SERVICE_KEY;
        if (!svc) return;
        const gate = 'infra-triage-gate';
        if (env.DEPLOYMENTS) {
            if (await env.DEPLOYMENTS.get(gate)) return;
            await env.DEPLOYMENTS.put(gate, '1', { expirationTtl: 540 });
        }
        const H = { 'apikey': svc, 'Authorization': `Bearer ${svc}`, 'Content-Type': 'application/json' };
        const rest = (p) => `${env.SUPABASE_URL}/rest/v1/${p}`;

        const beats = await (await fetch(rest('gs_host_beats?select=*&order=beat_at.desc&limit=200'), { headers: H })).json();
        if (!Array.isArray(beats)) return;
        const latest = {};
        for (const b of beats) if (!latest[b.host]) latest[b.host] = b;

        const open = await (await fetch(rest('gs_infra_findings?select=id,host,fingerprint,remedy,remedy_state&resolved_at=is.null'), { headers: H })).json();
        const openKey = {};
        (Array.isArray(open) ? open : []).forEach(f => { openKey[f.host + '|' + f.fingerprint] = f; });

        for (const host of Object.keys(latest)) {
            const b = latest[host];
            b.age_s = Math.floor((Date.now() - new Date(b.beat_at).getTime()) / 1000);
            const found = gsInfraDetect(b);
            const seen = {};
            for (const f of found) {
                seen[host + '|' + f.fingerprint] = true;
                if (openKey[host + '|' + f.fingerprint]) continue;      // already filed
                const j = await gsInfraJudge(env, host, f, b);
                const remedy = (f.candidate && j.approve && GS_REMEDIES[f.candidate]) ? f.candidate : null;
                await fetch(rest('gs_infra_findings'), {
                    method: 'POST', headers: { ...H, 'Prefer': 'return=minimal' },
                    body: JSON.stringify({
                        host, kind: f.kind, fingerprint: f.fingerprint, severity: f.severity,
                        verdict: j.verdict, steps: j.steps || null,
                        evidence: { ...f.evidence, candidate: f.candidate || null, why: j.why || null },
                        remedy: remedy, remedy_state: remedy ? 'pending' : 'none'
                    })
                });
            }
            // Anything open for this host that no longer shows up has cleared.
            for (const k of Object.keys(openKey)) {
                if (!k.startsWith(host + '|') || seen[k]) continue;
                await fetch(rest(`gs_infra_findings?id=eq.${openKey[k].id}`), {
                    method: 'PATCH', headers: { ...H, 'Prefer': 'return=minimal' },
                    body: JSON.stringify({ resolved_at: new Date().toISOString() })
                });
            }
        }
    } catch (e) { console.warn('[infra] triage:', e && e.message); }
}
'''

CRON_ANCHOR = "    ctx.waitUntil(gsRunSnapshotSweep(env));"
CRON_NEW = """    ctx.waitUntil(gsRunSnapshotSweep(env));
    // Infra triage. Self-throttled on a KV gate inside, so a more frequent
    // trigger is harmless - same property as the two sweeps above.
    ctx.waitUntil(gsInfraTriage(env));"""

# host-beat: hand back a remedy, and take last_remedy's result
BEAT_ANCHOR = """                return gsCtlJson({ ok: true });"""
BEAT_NEW = r'''                // Record the result of whatever we handed back last time,
                // before looking for new work. The box reports by remedy id,
                // so a result can never be attributed to the wrong finding.
                try {
                    const lr = b.last_remedy;
                    if (lr && lr.id) {
                        await fetch(`${env.SUPABASE_URL}/rest/v1/gs_infra_findings?id=eq.${encodeURIComponent(String(lr.id))}`, {
                            method: 'PATCH',
                            headers: { 'apikey': svc, 'Authorization': `Bearer ${svc}`, 'Content-Type': 'application/json', 'Prefer': 'return=minimal' },
                            body: JSON.stringify({
                                remedy_state: lr.ok ? 'done' : 'failed',
                                remedy_result: { ok: !!lr.ok, output: String(lr.output || '').slice(0, 2000), at: new Date().toISOString() }
                            })
                        });
                    }
                } catch (e) { /* a lost result must never fail the beat */ }

                // Hand back at most one pending remedy. The NAME travels; the
                // command lives on the box. A host that does not know the name
                // runs nothing, which is the intended failure mode.
                let remedy = null;
                try {
                    const pr = await fetch(`${env.SUPABASE_URL}/rest/v1/gs_infra_findings?host=eq.${encodeURIComponent(host)}&remedy_state=eq.pending&resolved_at=is.null&select=id,remedy,evidence&order=id.asc&limit=1`,
                        { headers: { 'apikey': svc, 'Authorization': `Bearer ${svc}` } });
                    const prs = await pr.json();
                    const row = Array.isArray(prs) && prs[0] ? prs[0] : null;
                    if (row && row.remedy) {
                        remedy = { id: row.id, name: row.remedy, arg: (row.evidence && row.evidence.names) ? String(row.evidence.names) : null };
                        await fetch(`${env.SUPABASE_URL}/rest/v1/gs_infra_findings?id=eq.${row.id}`, {
                            method: 'PATCH',
                            headers: { 'apikey': svc, 'Authorization': `Bearer ${svc}`, 'Content-Type': 'application/json', 'Prefer': 'return=minimal' },
                            body: JSON.stringify({ remedy_state: 'sent' })
                        });
                    }
                } catch (e) { /* no remedy is always a safe answer */ }

                return gsCtlJson({ ok: true, remedy });'''

READS = r'''
            if (leaf === 'findings' && request.method === 'GET') {
                return await pass('gs_infra_open?select=*&order=created_at.desc&limit=100');
            }

            if (leaf === 'finding-ack' && request.method === 'POST') {
                try {
                    const b = await request.json();
                    const id = parseInt(b.id, 10);
                    if (!id) return gsCtlJson({ error: 'id is required' }, 400);
                    // resolve closes it for good; ack just marks it read and
                    // lets triage keep tracking whether it actually cleared.
                    const patch = b.resolve ? { resolved_at: new Date().toISOString(), acknowledged: true }
                                            : { acknowledged: true };
                    const r = await fetch(rest(`gs_infra_findings?id=eq.${id}`), {
                        method: 'PATCH', headers: { ...h, 'Prefer': 'return=minimal' },
                        body: JSON.stringify(patch)
                    });
                    return gsCtlJson({ ok: r.ok });
                } catch (e) { return gsCtlJson({ error: String(e && e.message) }, 500); }
            }
'''

FUNC_ANCHOR = "async function gsPlatformHeaders(env, extra) {"
READ_ANCHOR = "            if (leaf === 'feed-health' && request.method === 'GET') {"

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'worker.js'
    if not os.path.exists(path):
        sys.exit(f"FAIL: {path} not found")
    src = open(path, encoding='utf-8').read()

    if 'gsInfraTriage' in src:
        print("already patched - nothing to do")
        return
    if 'JUDGING A WATCHDOG MATCH' not in src:
        sys.exit("FAIL: 038 is not applied to this worker. Run patch_controller_038.py first.")

    for name, anchor in (("funcs", FUNC_ANCHOR), ("cron", CRON_ANCHOR),
                         ("beat", BEAT_ANCHOR), ("reads", READ_ANCHOR)):
        n = src.count(anchor)
        if n != 1:
            sys.exit(f"FAIL: {name} anchor found {n} times, expected exactly 1. Nothing written.")

    out = src.replace(FUNC_ANCHOR, FUNCS + "\n" + FUNC_ANCHOR, 1)
    out = out.replace(CRON_ANCHOR, CRON_NEW, 1)
    out = out.replace(BEAT_ANCHOR, BEAT_NEW, 1)
    out = out.replace(READ_ANCHOR, READS + "\n" + READ_ANCHOR, 1)

    open(path + '.bak', 'w', encoding='utf-8').write(src)
    open(path, 'w', encoding='utf-8').write(out)
    print(f"patched {path} (+{len(out)-len(src)} bytes). backup at {path}.bak")

if __name__ == '__main__':
    main()
