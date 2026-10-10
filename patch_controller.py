#!/usr/bin/env python3
"""
patch_controller.py — adds the controller plane to worker.js.

Surgical. Two insertions at unique anchors, nothing else touched, nothing
removed. Idempotent: running it twice is a no-op. Refuses to write if an
anchor is missing or ambiguous rather than guessing at a location.

  python3 patch_controller.py worker.js

Adds at module scope:
  gsPlatformHeaders(env)     — mints the gs_platform JWT (035's gs_is_platform)
  requireController(env,req) — verifies the controller session token

Adds routes, all gated by requireController except login:
  POST /api/controller/login
  GET  /api/controller/fleet
  GET  /api/controller/revisions?deployment_id=&surface=&limit=
  GET  /api/controller/revision?id=          (file list + hashes)
  GET  /api/controller/file?revision=&path=  (one file body)
  GET  /api/controller/alerts?open=1
  POST /api/controller/alert-ack
  GET  /api/controller/watchdogs
  POST /api/controller/watchdog             (create/update/enable/disable)
  GET  /api/controller/dead-files
"""
import sys, os, hashlib

FUNCS = r'''
// ============================================================================
// CONTROLLER PLANE
// ============================================================================
// Mints the gs_platform claim read by public.gs_is_platform() (migration 035).
// Same signing path as gsAppAuthHeaders - SUPABASE_JWT_SECRET, HS256, one hour
// - but carries gs_platform instead of app_id, so it satisfies the controller
// policies and NOT the per-app gs_scoped_* ones.
//
// This claim bypasses tenant isolation. It is minted here and nowhere else,
// it is never inlined into a rendered page the way the app token is, and the
// only route that can cause it to be minted is gated by requireController.
async function gsPlatformHeaders(env, extra) {
    const base = { 'apikey': env.SUPABASE_ANON_KEY, 'Authorization': `Bearer ${env.SUPABASE_ANON_KEY}`, 'Content-Type': 'application/json', ...(extra || {}) };
    try {
        const secret = env.SUPABASE_JWT_SECRET;
        if (!secret) return base;
        const now = Math.floor(Date.now() / 1000);
        const hit = globalThis.__gsPlatTok;
        if (hit && hit.exp > now + 60) return { ...base, 'Authorization': `Bearer ${hit.t}` };
        const b64urlStr = (str) => btoa(unescape(encodeURIComponent(str))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
        const b64url = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
        const header = b64urlStr(JSON.stringify({ alg: 'HS256', typ: 'JWT' }));
        const payload = b64urlStr(JSON.stringify({ role: 'authenticated', gs_platform: 'true', iss: 'geniestack', iat: now, exp: now + 3600 }));
        const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
        const sig = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(header + '.' + payload));
        const token = header + '.' + payload + '.' + b64url(sig);
        globalThis.__gsPlatTok = { t: token, exp: now + 3600 };
        return { ...base, 'Authorization': `Bearer ${token}` };
    } catch (e) {
        return base;
    }
}

// Controller session gate. Reuses adminVerify (APP_AUTH_JWT_SECRET) and then
// insists on role === 'platform', which only /api/controller/login issues and
// only gsOwnerCredsMatch can reach. A tenant admin token fails this even
// though adminVerify accepts it.
//
// This is the server-side owner check HANDOFF open item 6 asks for. The
// sandbox/live toggle being hidden rather than blocked is the same gap.
async function requireController(env, request) {
    try {
        const auth = request.headers.get('Authorization') || '';
        const tok = auth.startsWith('Bearer ') ? auth.slice(7) : (request.headers.get('X-Controller-Token') || '');
        const payload = await adminVerify(env, tok);
        if (!payload) return null;
        if (payload.role !== 'platform' || payload.scope !== 'controller') return null;
        return payload;
    } catch (e) { return null; }
}

function gsCtlJson(obj, status) {
    return new Response(JSON.stringify(obj), {
        status: status || 200,
        headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }
    });
}

'''

ROUTES = r'''    // ---------------------------------------------------------------------
    // CONTROLLER ROUTES
    // ---------------------------------------------------------------------
    if (url.pathname.startsWith('/api/controller/')) {
        const leaf = url.pathname.slice('/api/controller/'.length);

        if (leaf === 'login' && request.method === 'POST') {
            try {
                const { email, password } = await request.json();
                if (!gsOwnerCredsMatch(env, email, password)) {
                    return gsCtlJson({ error: 'Invalid credentials' }, 401);
                }
                const token = await adminSignToken(env, {
                    kind: 'admin', scope: 'controller', role: 'platform',
                    email: String(email).toLowerCase().trim()
                }, 60 * 60 * 12);
                return gsCtlJson({ token, role: 'platform' });
            } catch (e) {
                return gsCtlJson({ error: String(e && e.message || e) }, 400);
            }
        }

        const ctl = await requireController(env, request);
        if (!ctl) return gsCtlJson({ error: 'Unauthorized' }, 401);

        const h = await gsPlatformHeaders(env, {});
        const rest = (p) => `${env.SUPABASE_URL}/rest/v1/${p}`;
        const pass = async (p) => {
            const r = await fetch(rest(p), { headers: h });
            const body = await r.text();
            return new Response(body, {
                status: r.status,
                headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }
            });
        };

        try {
            if (leaf === 'fleet' && request.method === 'GET') {
                return await pass('gs_fleet?select=*&order=last_change.desc.nullslast');
            }

            if (leaf === 'revisions' && request.method === 'GET') {
                const dep = url.searchParams.get('deployment_id') || '';
                const surface = url.searchParams.get('surface') || '';
                const limit = Math.min(parseInt(url.searchParams.get('limit') || '50', 10) || 50, 200);
                let q = 'gs_revisions?select=id,deployment_id,surface,op,tree_hash,file_count,byte_size,paths_added,paths_removed,paths_changed,actor,created_at';
                if (dep) q += `&deployment_id=eq.${encodeURIComponent(dep)}`;
                if (surface) q += `&surface=eq.${encodeURIComponent(surface)}`;
                q += `&order=id.desc&limit=${limit}`;
                return await pass(q);
            }

            if (leaf === 'revision' && request.method === 'GET') {
                const id = url.searchParams.get('id') || '';
                if (!id) return gsCtlJson({ error: 'Missing id' }, 400);
                return await pass(`gs_revisions?id=eq.${encodeURIComponent(id)}&select=*`);
            }

            // One file body from a captured revision. Two hops on purpose: the
            // revision holds path -> hash, the blob store holds hash -> body.
            // Never returns a whole tree - a controller screen that dumps every
            // tenant's source in one response is a liability, not a feature.
            if (leaf === 'file' && request.method === 'GET') {
                const rev = url.searchParams.get('revision') || '';
                const path = url.searchParams.get('path') || '';
                if (!rev || !path) return gsCtlJson({ error: 'Missing revision or path' }, 400);
                const rr = await fetch(rest(`gs_revisions?id=eq.${encodeURIComponent(rev)}&select=file_hashes`), { headers: h });
                const rows = await rr.json();
                const map = Array.isArray(rows) && rows[0] ? rows[0].file_hashes : null;
                if (!map) return gsCtlJson({ error: 'Revision not found' }, 404);
                const hash = map[path];
                if (!hash) return gsCtlJson({ error: 'Path not in revision' }, 404);
                const br = await fetch(rest(`gs_revision_blobs?content_hash=eq.${encodeURIComponent(hash)}&select=content,byte_size`), { headers: h });
                const brows = await br.json();
                const blob = Array.isArray(brows) && brows[0] ? brows[0] : null;
                if (!blob) return gsCtlJson({ error: 'Blob missing' }, 404);
                return gsCtlJson({ path, content_hash: hash, byte_size: blob.byte_size, content: blob.content });
            }

            if (leaf === 'alerts' && request.method === 'GET') {
                const openOnly = url.searchParams.get('open') === '1';
                let q = 'gs_alerts?select=*';
                if (openOnly) q += '&acknowledged=is.false';
                q += '&order=id.desc&limit=200';
                return await pass(q);
            }

            if (leaf === 'alert-ack' && request.method === 'POST') {
                const { id } = await request.json();
                if (!id) return gsCtlJson({ error: 'Missing id' }, 400);
                const r = await fetch(rest(`gs_alerts?id=eq.${encodeURIComponent(id)}`), {
                    method: 'PATCH',
                    headers: { ...h, 'Prefer': 'return=minimal' },
                    body: JSON.stringify({ acknowledged: true, acknowledged_at: new Date().toISOString() })
                });
                return gsCtlJson({ ok: r.ok, status: r.status });
            }

            if (leaf === 'watchdogs' && request.method === 'GET') {
                return await pass('gs_watchdogs?select=*&order=id.asc');
            }

            if (leaf === 'watchdog' && request.method === 'POST') {
                const b = await request.json();
                const row = {
                    name: b.name, enabled: b.enabled !== false,
                    deployment_id: b.deployment_id || null,
                    surface: b.surface || null,
                    match_kind: b.match_kind, pattern: b.pattern || null,
                    threshold_int: b.threshold_int == null ? null : Number(b.threshold_int),
                    severity: b.severity || 'warn'
                };
                if (!row.name || !row.match_kind) return gsCtlJson({ error: 'Missing name or match_kind' }, 400);
                let r;
                if (b.id) {
                    r = await fetch(rest(`gs_watchdogs?id=eq.${encodeURIComponent(b.id)}`), {
                        method: 'PATCH', headers: { ...h, 'Prefer': 'return=representation' },
                        body: JSON.stringify(row)
                    });
                } else {
                    r = await fetch(rest('gs_watchdogs'), {
                        method: 'POST', headers: { ...h, 'Prefer': 'return=representation' },
                        body: JSON.stringify(row)
                    });
                }
                const body = await r.text();
                return new Response(body, { status: r.status, headers: { 'Content-Type': 'application/json' } });
            }

            if (leaf === 'dead-files' && request.method === 'GET') {
                return await pass('gs_dead_files?select=*&order=deployment_id.asc,path.asc');
            }

            return gsCtlJson({ error: 'Unknown controller route' }, 404);
        } catch (e) {
            return gsCtlJson({ error: String(e && e.message || e) }, 500);
        }
    }

'''

FUNC_ANCHOR = "async function gsMintAppToken(env, appId) {"
ROUTE_ANCHOR = "    if (url.pathname === '/api/admin/login' && request.method === 'POST') {"
MARKER = "async function gsPlatformHeaders(env, extra) {"


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'worker.js'
    if not os.path.exists(path):
        sys.exit(f"FAIL: {path} not found")

    src = open(path, encoding='utf-8').read()
    before = hashlib.md5(src.encode()).hexdigest()
    print(f"in  : {path}  md5 {before}  {len(src)} bytes")

    if MARKER in src:
        print("already patched - nothing to do")
        return

    for name, anchor in (("function", FUNC_ANCHOR), ("route", ROUTE_ANCHOR)):
        n = src.count(anchor)
        if n != 1:
            sys.exit(f"FAIL: {name} anchor found {n} times, expected exactly 1. "
                     f"Refusing to guess a location.")

    src = src.replace(FUNC_ANCHOR, FUNCS + FUNC_ANCHOR, 1)
    src = src.replace(ROUTE_ANCHOR, ROUTES + ROUTE_ANCHOR, 1)

    open(path, 'w', encoding='utf-8').write(src)
    after = hashlib.md5(src.encode()).hexdigest()
    print(f"out : {path}  md5 {after}  {len(src)} bytes")
    print("added: gsPlatformHeaders, requireController, gsCtlJson, /api/controller/*")


if __name__ == '__main__':
    main()
