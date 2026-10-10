#!/usr/bin/env python3
"""
patch_controller_037.py - adds the controller's first-responder agent.

Same discipline as patch_controller.py and 036: unique anchor, assert before
write, idempotent, refuses rather than guesses.

  python3 patch_controller_037.py worker.js

Adds, behind requireController:
  POST /api/controller/ask   { question?: string }

READ-ONLY BY CONSTRUCTION. No tools are passed to the model, so it cannot
call anything, change anything, or reach the database on its own. It receives
a snapshot this route gathers server-side and returns prose. Everything it
suggests is for a human to run.
"""
import sys, os

ROUTE = r'''
            // ── first responder ─────────────────────────────────────────────
            // Answers "what does this mean and what do I do" against the live
            // state. Deliberately NOT a watchdog: it runs when asked, never on
            // a schedule, and it is handed no tools, so it can only read the
            // snapshot assembled here and reply in prose.
            //
            // The snapshot is gathered server-side rather than accepted from
            // the browser, so the model cannot be fed a doctored state by
            // anything that reaches the page.
            if (leaf === 'ask' && request.method === 'POST') {
                try {
                    if (!env.CLAUDE_API_KEY) {
                        return gsCtlJson({ error: 'CLAUDE_API_KEY is not set on this Worker.' }, 503);
                    }
                    const body = await request.json().catch(() => ({}));
                    const question = String(body.question || '').trim().slice(0, 4000);

                    // Only the health surfaces. Revision history and file
                    // blobs are deliberately left out: they are large, they
                    // are not what a first responder needs, and they would
                    // put app source into a third-party request.
                    const grab = async (p) => {
                        try {
                            const r = await fetch(rest(p), { headers: h });
                            if (!r.ok) return { error: 'HTTP ' + r.status };
                            return await r.json();
                        } catch (e) { return { error: String(e && e.message) }; }
                    };
                    const [feeds, hosts, alerts, runs] = await Promise.all([
                        grab('gs_feed_health?select=*'),
                        grab('gs_host_health?select=*'),
                        grab('gs_alerts?select=id,deployment_id,severity,message,created_at,acknowledged&acknowledged=is.false&order=id.desc&limit=25'),
                        grab('gs_feed_runs?select=finished_at,status,rows_seen,rows_created,rows_updated,rows_withdrawn,errors,notes&order=finished_at.desc.nullslast&limit=15')
                    ]);

                    const snapshot = JSON.stringify({ now: new Date().toISOString(), feeds, hosts, open_alerts: alerts, recent_feed_runs: runs }, null, 1).slice(0, 60000);

                    const r = await fetch('https://api.anthropic.com/v1/messages', {
                        method: 'POST',
                        headers: { 'x-api-key': env.CLAUDE_API_KEY, 'anthropic-version': '2023-06-01', 'content-type': 'application/json' },
                        body: JSON.stringify({
                            model: gsClaudeModel(body.model || 'claude-opus-5'),
                            max_tokens: 4000,
                            system: GS_CTL_ASK_SYSTEM,
                            messages: [{
                                role: 'user',
                                content: 'Live controller state:\n```json\n' + snapshot + '\n```\n\n' +
                                         (question || 'Nothing specific - look at the state above and tell me whether anything is wrong, and what to do about it.')
                            }]
                        })
                    });
                    if (!r.ok) {
                        return gsCtlJson({ error: 'Claude API error ' + r.status, detail: (await r.text()).slice(0, 400) }, 502);
                    }
                    const d = await r.json();
                    const answer = (d.content || []).filter(b => b.type === 'text').map(b => b.text).join('\n').trim();
                    return gsCtlJson({
                        answer: answer || 'No answer returned.',
                        usage: d.usage || null,
                        model: d.model || null
                    });
                } catch (e) {
                    return gsCtlJson({ error: String(e && e.message || e) }, 500);
                }
            }
'''

SYSTEM = r'''
// System prompt for the controller's first responder. This is the system
// knowledge the model does not otherwise have, written from what actually
// broke rather than from how the stack is supposed to work.
const GS_CTL_ASK_SYSTEM = `You are the first responder for GenieStack / HyperWax, a self-hosted multi-tenant app platform. The operator is its sole engineer. He is highly technical and wants diagnosis first, then the fix, then what would prevent a recurrence. No preamble, no reassurance, plain English, numbered steps for anything he has to run.

ARCHITECTURE
- Cloudflare Worker at edge.hyperwax.io is the API for every app. Supabase is SELF-HOSTED at supabase.hyperwax.io on the operator's own Proxmox box, not Supabase cloud.
- The box sits behind CGNAT on a residential link. Nothing can reach in. Every integration is outbound-only, and anything that looks like it needs inbound access is the wrong answer.
- A Proxmox host called pve runs the VM that carries Supabase and Coolify. Its LAN router is 192.168.1.1.

THE DEALERSLINK FEED
- relay.sh on pve runs every 30 minutes under feed-relay.timer. It fetches a CSV over FTP from ftp.dealerslink.com and POSTs it to the Worker's importer.
- It compares a sha256 and SKIPS the POST when the file is unchanged, logging "SAME". So dealer_feed_runs only gets a row when the vendor's file actually CHANGED. Observed gaps between rows are 9-15 hours. A "last import" several hours old is HEALTHY. 26 hours is the staleness threshold, matching STALE_HOURS in feed-alert.sh.
- The importer will not touch a vehicle whose status is sold, pending, hold, deposit or withdrawn. That is how a deal in progress is protected from being overwritten or auto-withdrawn. Returning a car to Available is deliberately a human action - the feed must never reopen a closed deal.

KNOWN FAILURE MODES, SEEN IN PRODUCTION
- "curl exit 6" means COULD NOT RESOLVE HOST. It is DNS on the box, not the vendor and not credentials - the request never left. /etc/resolv.conf now lists the router first with 1.1.1.1 and 8.8.8.8 behind it, and the fetch retries with --retry-all-errors, which is the only flag that retries a DNS failure.
- An alert email arriving as "Your App" instead of the configured sender name means the Worker could not read admin_settings while sending. The brand lookup is wrapped in a try/catch and falls through to that literal default. Because Supabase is self-hosted on the same network, a local outage breaks the lookup - so the one email sent DURING an outage is the one that arrives unbranded. It is not a branding bug.
- Hosts push a beat every 5 minutes because they cannot be polled. SILENCE IS THE SIGNAL: a host with a growing age_s lost its network, lost power, or had its timer stop. It does not mean the host is fine and quiet. Past 15 minutes treat it as down.
- The ASUS router dropping its link has been the root cause of several unrelated-looking failures at once - a feed failure, an unbranded email, and backup job errors in the same window are one network event, not three faults.
- Two Proxmox backup jobs scheduled at the same minute race for the VM lock and one reports "job errors". Check /etc/pve/jobs.cfg for duplicate schedules before suspecting storage.

HOW TO ANSWER
- Say what the evidence shows before saying what to do. If the state does not support a conclusion, say what you would need to see and which command produces it.
- Distinguish clearly between "this is broken" and "this is normal and looks alarming". A feed that last imported 14 hours ago is the second kind.
- Never suggest renting a VPS, a managed service or any third-party host. Everything runs on the operator's own hardware by deliberate choice.
- You cannot run anything. Every command you give is for the operator to run, and you should say which machine it runs on: the Proxmox shell, his Mac, or the Supabase SQL editor.
- If nothing is wrong, say so in one line and stop.`;
'''

ROUTE_ANCHOR = "            if (leaf === 'feed-health' && request.method === 'GET') {"
FUNC_ANCHOR  = "async function gsPlatformHeaders(env, extra) {"

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'worker.js'
    if not os.path.exists(path):
        sys.exit(f"FAIL: {path} not found")
    src = open(path, encoding='utf-8').read()

    if "leaf === 'ask'" in src and 'GS_CTL_ASK_SYSTEM' in src:
        print("already patched - nothing to do")
        return
    if "leaf === 'feed-health'" not in src:
        sys.exit("FAIL: 036 is not applied to this worker. Run patch_controller_036.py first.")

    for name, anchor in (("route", ROUTE_ANCHOR), ("system", FUNC_ANCHOR)):
        n = src.count(anchor)
        if n != 1:
            sys.exit(f"FAIL: {name} anchor found {n} times, expected exactly 1. Nothing written.")

    out = src.replace(FUNC_ANCHOR, SYSTEM + "\n" + FUNC_ANCHOR, 1)
    out = out.replace(ROUTE_ANCHOR, ROUTE + "\n" + ROUTE_ANCHOR, 1)

    open(path + '.bak', 'w', encoding='utf-8').write(src)
    open(path, 'w', encoding='utf-8').write(out)
    print(f"patched {path} (+{len(out)-len(src)} bytes). backup at {path}.bak")

if __name__ == '__main__':
    main()
