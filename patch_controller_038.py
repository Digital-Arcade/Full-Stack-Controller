#!/usr/bin/env python3
"""
patch_controller_038.py - gives the first responder a focused subject and the
system knowledge to judge it.

Requires 037. Unique anchors, assert before write, idempotent.

  python3 patch_controller_038.py worker.js

/api/controller/ask now also accepts:
  focus       { ... }   the exact alert or watchdog row being asked about
  revision_id, path     one file to read before answering

STILL READ-ONLY. No tools, no writes. The file fetch reads one blob the alert
already points at, capped, and is never used to write anything back.
"""
import sys, os

# Appended to the system prompt. This is the part that decides whether a
# verdict is right: a watchdog matches TEXT, and matching text is not the same
# as a leak. Without this the model confidently calls safe code critical.
KNOWLEDGE = r'''
JUDGING A WATCHDOG MATCH OR AN ALERT
A watchdog matches text. Matching text is not the same as a problem. Your job is to say which one this is, and you must look at the file content when it is given to you rather than reasoning from the rule name.

Keys, specifically:
- SUPABASE_ANON_KEY belongs in tenant app bundles. It is public by design, RLS is what protects the data, and seeing it in src/ is NORMAL. Do not raise it.
- The SERVICE ROLE key must never appear in a tenant bundle. If a file under src/ contains an actual service-role JWT, that is a genuine critical.
- But the literal string "service_role" appears harmlessly all over this codebase: in RLS policies as auth.role() = 'service_role', in SQL comments, in migration files, and in Worker code that legitimately holds the key. A match on the WORD is not a leak.
- Tell them apart by shape. A real key is a JWT: three base64url segments separated by dots, beginning with eyJ, hundreds of characters long. If what matched is the word in a policy, a comment, a variable name or a string compare, it is a false positive and you should say so plainly.
- env.SUPABASE_SERVICE_ROLE_KEY inside worker.js is correct and expected - that is where the key is supposed to be used. Worker source is not a tenant bundle.
- dealer_feeds and dealer_data_providers hold FTP credentials and secret_token. They are service-role only. Reads of them belong in the Worker, never in an app bundle.
- The Worker deliberately inlines SHORT-LIVED minted tokens into rendered pages: injectAdminPwaHead does it for the admin console and gsInjectStoreAuth for kiosk and merchant pages. Those carry an app_id or gs_platform claim, expire in an hour, and are not a leaked key. gs_token_<APP_TENANT_ID> in localStorage is the identity source of truth and is also expected; _hw_user_ is only a cache of it.

When you are given file content, quote the specific line you are judging so the operator can see what you looked at. If the content was not given to you, say that you are reasoning from metadata alone and name the file you would need to see.

VERDICT FORMAT
Open with one of these words, then the reasoning:
- FALSE POSITIVE - the match is harmless, and why
- REAL - it is what it looks like, with the fix
- CANNOT TELL - what you would need to see, and the exact command or tab that produces it
Then, only if it is REAL: the fix, and anything that would stop it recurring.
Never propose that you make the change yourself. You cannot, and a wrong edit against a system you have misread is worse than the finding.
- If nothing is wrong, say so in one line and stop.`;'''

ROUTE_FETCH = r'''
                    // One file, only when the caller names it. Alerts carry a
                    // revision_id and the matched path, so a verdict can be
                    // made against the real line instead of the rule name.
                    // Capped: a verdict needs the match in context, not a
                    // whole bundle, and this leaves the tenant's source out
                    // of the request unless it is the subject of the question.
                    let fileCtx = '';
                    const revId = String(body.revision_id || '').trim();
                    const fPath = String(body.path || '').trim();
                    if (revId && fPath) {
                        try {
                            const rr = await fetch(rest(`gs_revisions?id=eq.${encodeURIComponent(revId)}&select=file_hashes`), { headers: h });
                            const rws = await rr.json();
                            const map = Array.isArray(rws) && rws[0] ? rws[0].file_hashes : null;
                            const hash = map ? map[fPath] : null;
                            if (hash) {
                                const br = await fetch(rest(`gs_revision_blobs?content_hash=eq.${encodeURIComponent(hash)}&select=content`), { headers: h });
                                const bws = await br.json();
                                const content = Array.isArray(bws) && bws[0] ? String(bws[0].content || '') : '';
                                if (content) fileCtx = '\n\nThe file this fired on (' + fPath + ', truncated to 40k):\n```\n' + content.slice(0, 40000) + '\n```';
                            } else {
                                fileCtx = '\n\n(' + fPath + ' is not present in revision ' + revId + ' - say so rather than guessing at its contents.)';
                            }
                        } catch (e) {
                            fileCtx = '\n\n(Could not read ' + fPath + ': ' + String(e && e.message) + ')';
                        }
                    }

                    const focusCtx = (body.focus && typeof body.focus === 'object')
                        ? '\n\nThe specific item being asked about:\n```json\n' + JSON.stringify(body.focus, null, 1).slice(0, 8000) + '\n```'
                        : '';
'''

ROUTE_CONTENT_OLD = """                                content: 'Live controller state:\\n```json\\n' + snapshot + '\\n```\\n\\n' +
                                         (question || 'Nothing specific - look at the state above and tell me whether anything is wrong, and what to do about it.')"""

ROUTE_CONTENT_NEW = """                                content: 'Live controller state:\\n```json\\n' + snapshot + '\\n```' + focusCtx + fileCtx + '\\n\\n' +
                                         (question || (focusCtx
                                            ? 'Is this a real problem or a false positive? Give me the verdict, the reasoning, and the fix if there is one.'
                                            : 'Nothing specific - look at the state above and tell me whether anything is wrong, and what to do about it.'))"""

SYS_ANCHOR = "- If nothing is wrong, say so in one line and stop.`;"
SNAP_ANCHOR = "                    const snapshot = JSON.stringify({ now: new Date().toISOString(), feeds, hosts, open_alerts: alerts, recent_feed_runs: runs }, null, 1).slice(0, 60000);"

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'worker.js'
    if not os.path.exists(path):
        sys.exit(f"FAIL: {path} not found")
    src = open(path, encoding='utf-8').read()

    if 'JUDGING A WATCHDOG MATCH' in src:
        print("already patched - nothing to do")
        return
    if "leaf === 'ask'" not in src:
        sys.exit("FAIL: 037 is not applied to this worker. Run patch_controller_037.py first.")

    for name, anchor in (("system", SYS_ANCHOR), ("snapshot", SNAP_ANCHOR), ("content", ROUTE_CONTENT_OLD)):
        n = src.count(anchor)
        if n != 1:
            sys.exit(f"FAIL: {name} anchor found {n} times, expected exactly 1. Nothing written.")

    out = src.replace(SYS_ANCHOR, KNOWLEDGE, 1)
    out = out.replace(SNAP_ANCHOR, SNAP_ANCHOR + "\n" + ROUTE_FETCH, 1)
    out = out.replace(ROUTE_CONTENT_OLD, ROUTE_CONTENT_NEW, 1)

    open(path + '.bak', 'w', encoding='utf-8').write(src)
    open(path, 'w', encoding='utf-8').write(out)
    print(f"patched {path} (+{len(out)-len(src)} bytes). backup at {path}.bak")

if __name__ == '__main__':
    main()
