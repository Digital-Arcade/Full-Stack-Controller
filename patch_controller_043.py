#!/usr/bin/env python3
"""
patch_controller_043.py - page the operator when triage files a CRITICAL
infra finding, and when one clears.

WHY: findings appear in the Infra tab and nowhere else. A host can go silent
for a day and nothing says so unless somebody opens the console - which was
exactly the case for 21.8 hours on 2026-10-03. The feed has a dead-man; the
hosts did not.

Reuses the same push/email/inbox path the /api/admin/alert route already
uses, so there is one notification mechanism rather than two. Note the Worker
cannot run feed-alert.sh - that lives on the Proxmox box - so it calls those
functions directly.

Only CRITICAL fires. Warnings (a failed unit, backup errors, disk at 90%)
stay in the console where they belong; paging on those trains you to ignore
the pages.

Naturally latched: a notification is sent only when a finding is newly
FILED, and findings dedupe on fingerprint. A fault lasting a week pages once.

  python3 patch_controller_043.py worker.js
"""
import sys, os

NOTIFY = r'''
// Push + email + inbox for an infra finding, via the same helpers the
// /api/admin/alert route uses. Everything is wrapped: a notification that
// cannot be delivered must never break the triage pass that produced it.
async function gsInfraNotify(env, title, message) {
    const appId = env.FEED_ALERT_APP_ID || '';
    const to = env.FEED_ALERT_EMAIL || '';
    const subject = String(title || 'Infrastructure').slice(0, 120);
    const body = String(message || '').slice(0, 4000);

    if (appId) {
        try {
            await pushToAdmins(env, appId, {
                title: subject, body: body.slice(0, 300),
                tag: 'infra-finding', url: '/admin'
            });
        } catch (e) { console.warn('[infra] push:', e && e.message); }
    }
    if (to && env.RESEND_API_KEY) {
        try {
            const brand = await gsEmailBrand(env, appId, null);
            const safe = body.replace(/&/g, '&amp;').replace(/</g, '&lt;')
                             .replace(/>/g, '&gt;').replace(/\n/g, '<br/>');
            await fetch('https://api.resend.com/emails', {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${env.RESEND_API_KEY}`, 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    from: gsEmailFrom(brand), to: [String(to).trim()], subject: subject,
                    html: gsEmailShell({ brand, bodyHtml: safe, note: 'Automated infrastructure alert - no reply needed.' })
                })
            });
        } catch (e) { console.warn('[infra] email:', e && e.message); }
    }
    if (appId) {
        try {
            const threadId = await resolveInboxUserId(env, appId, null);
            await mirrorSmsToInbox(env, {
                app_id: appId, user_id: threadId,
                content: '[' + subject + '] ' + body, sender: 'admin'
            });
        } catch (e) { console.warn('[infra] inbox:', e && e.message); }
    }
}
'''

FUNC_ANCHOR = "// Cron pass. Self-throttled on a KV key so a more frequent trigger is"

SELECT_OLD = "const open = await (await fetch(rest('gs_infra_findings?select=id,host,fingerprint,remedy,remedy_state&resolved_at=is.null'), { headers: H })).json();"
SELECT_NEW = "const open = await (await fetch(rest('gs_infra_findings?select=id,host,fingerprint,severity,kind,remedy,remedy_state&resolved_at=is.null'), { headers: H })).json();"

FILE_OLD = """                        remedy: remedy, remedy_state: remedy ? 'pending' : 'none'
                    })
                });"""
FILE_NEW = """                        remedy: remedy, remedy_state: remedy ? 'pending' : 'none'
                    })
                });
                // Only critical pages. A warning that pages is a warning you
                // learn to ignore. Sent once, on the FILING of a finding -
                // fingerprint dedupe means a week-long fault pages once.
                if (f.severity === 'critical') {
                    await gsInfraNotify(env,
                        'Infra: ' + String(f.kind).replace(/_/g, ' ') + ' on ' + host,
                        (j.verdict || '') +
                        (j.steps ? '\\n\\nWhat to do:\\n' + j.steps : '') +
                        (remedy ? '\\n\\nQueued automatic remedy: ' + remedy : '\\n\\nNo automatic remedy applies - this one needs you.'));
                }"""

RESOLVE_OLD = """                await fetch(rest(`gs_infra_findings?id=eq.${openKey[k].id}`), {
                    method: 'PATCH', headers: { ...H, 'Prefer': 'return=minimal' },
                    body: JSON.stringify({ resolved_at: new Date().toISOString() })
                });"""
RESOLVE_NEW = """                await fetch(rest(`gs_infra_findings?id=eq.${openKey[k].id}`), {
                    method: 'PATCH', headers: { ...H, 'Prefer': 'return=minimal' },
                    body: JSON.stringify({ resolved_at: new Date().toISOString() })
                });
                // Tell them it cleared, but only for the ones that paged.
                // Silence after an alert is indistinguishable from the alert
                // being ignored.
                if (openKey[k].severity === 'critical') {
                    await gsInfraNotify(env,
                        'Cleared: ' + String(openKey[k].kind || 'issue').replace(/_/g, ' ') + ' on ' + host,
                        'The condition is no longer present. Nothing further to do.');
                }"""

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'worker.js'
    if not os.path.exists(path):
        sys.exit(f"FAIL: {path} not found")
    src = open(path, encoding='utf-8').read()

    if 'gsInfraNotify' in src:
        print("already patched - nothing to do")
        return
    if 'gsInfraTriage' not in src:
        sys.exit("FAIL: 040 is not applied to this worker. Run patch_controller_040.py first.")

    hunks = [("notify fn", FUNC_ANCHOR, NOTIFY + "\n" + FUNC_ANCHOR),
             ("select", SELECT_OLD, SELECT_NEW),
             ("file", FILE_OLD, FILE_NEW),
             ("resolve", RESOLVE_OLD, RESOLVE_NEW)]
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
