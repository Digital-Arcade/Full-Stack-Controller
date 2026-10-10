// Runs the REAL worker.js routes for the feed check (patch 045) against an
// in-memory stand-in for Supabase. Nothing leaves this machine: fetch is
// replaced before the Worker is loaded.
//
//   node t_worker_045.mjs ~/WORKER-hyperwax/worker.js
// Node 18 has WebCrypto but does not expose it as a global to modules (Node 20+
// does). The Worker signs and checks its tokens with crypto.subtle, exactly as
// it does on Cloudflare, so hand it the same thing here.
import { webcrypto as __webcrypto } from 'node:crypto';
if (!globalThis.crypto || !globalThis.crypto.subtle) globalThis.crypto = __webcrypto;
import { readFileSync, writeFileSync, mkdtempSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import { pathToFileURL } from 'url';

const path = process.argv[2] || './worker.js';
const src = readFileSync(path, 'utf8');
if (!src.includes('gsFeedStampCheck')) { console.log('FAIL  this worker.js does not have patch 045 applied'); process.exit(1); }

let f = 0; const ok = (l, c, x = '') => { console.log(`${c ? 'PASS' : 'FAIL'}  ${l}${x ? '  ' + x : ''}`); if (!c) f++; };

// ── stand-in Supabase ───────────────────────────────────────────────────────
const SB = 'https://supabase.test';
const APP = '33a0663b-93b4-458d-8ff6-3f06ec2474bb';
const TOKEN = 'feed-token-for-tests';
const db = {};
const calls = [];
let checkColumns = true;        // false = 045_feed_checks.sql has not been run
const reset = () => {
  db.feeds = [{ id: 'feed-1', app_id: APP, provider: 'dealerslink', seller_ref: 'owner', mode: 'push', enabled: true, format: 'csv',
                secret_token: TOKEN, target_table: '33a0663b_vehicles', target_profile: 'storefront',
                field_map: { ask_price: 'JD Power Clean Trade' }, withdraw_missing: false, last_run_at: null, last_status: null }];
  db.runs = []; db.health = []; db.beats = []; db.findings = []; db.mail = [];
  calls.length = 0; checkColumns = true;
};
const json = (b, status = 200) => new Response(JSON.stringify(b), { status, headers: { 'Content-Type': 'application/json' } });
globalThis.fetch = async (input, init = {}) => {
  const u = new URL(typeof input === 'string' ? input : input.url);
  const method = (init.method || 'GET').toUpperCase();
  const body = init.body ? (() => { try { return JSON.parse(init.body); } catch { return init.body; } })() : null;
  calls.push({ method, host: u.host, path: u.pathname + u.search, body, auth: (init.headers && (init.headers.Authorization || init.headers.authorization)) || '' });
  if (u.host === 'api.resend.com') { db.mail.push(body); return json({ id: 'm' }); }
  if (u.host !== 'supabase.test') return json({}, 200);
  const table = u.pathname.replace('/rest/v1/', '');
  if (table === 'dealer_feeds' && method === 'GET') {
    const tok = (u.searchParams.get('secret_token') || '').replace('eq.', '');
    return json(db.feeds.filter(x => x.secret_token === tok && x.enabled));
  }
  if (table === 'dealer_feeds' && method === 'PATCH') {
    const id = (u.searchParams.get('id') || '').replace('eq.', '');
    if (!checkColumns && Object.keys(body).some(k => k.indexOf('last_check') === 0)) {
      return json({ code: 'PGRST204', message: "Could not find the 'last_check_at' column of 'dealer_feeds' in the schema cache" }, 400);
    }
    const row = db.feeds.find(x => x.id === id); if (row) Object.assign(row, body);
    return new Response(null, { status: 204 });
  }
  if (table === 'dealer_feed_runs' && method === 'POST') { db.runs.push(body); return new Response('', { status: 201 }); }
  if (table === 'gs_feed_health') return json(/gs_platform|eyJ/.test(calls[calls.length - 1].auth) ? db.health : []);
  if (table === 'gs_host_beats' && method === 'GET') return json(db.beats);
  if (table === 'gs_infra_findings' && method === 'GET') return json(db.findings.filter(x => !x.resolved_at));
  if (table === 'gs_infra_findings' && method === 'POST') { db.findings.push({ id: db.findings.length + 1, ...body }); return new Response('', { status: 201 }); }
  if (table === 'gs_infra_findings' && method === 'PATCH') {
    const id = Number((u.searchParams.get('id') || '').replace('eq.', ''));
    const row = db.findings.find(x => x.id === id); if (row) Object.assign(row, body);
    return new Response(null, { status: 204 });
  }
  if (method === 'GET') return json([]);
  return json([], 200);
};

const dir = mkdtempSync(join(tmpdir(), 'gsw-'));
const mod = join(dir, 'worker.mjs');
writeFileSync(mod, src);
const worker = (await import(pathToFileURL(mod).href)).default;

const kv = new Map();
const env = { SUPABASE_URL: SB, SUPABASE_ANON_KEY: 'anon', SUPABASE_SERVICE_ROLE_KEY: 'svc', SUPABASE_JWT_SECRET: 'jwt-secret-for-tests',
              FEED_ALERT_EMAIL: 'ops@example.com', RESEND_API_KEY: 'resend',
              DEPLOYMENTS: { get: async (k) => kv.get(k) || null, put: async (k, v) => { kv.set(k, v); }, delete: async (k) => { kv.delete(k); } } };
const ctx = { waitUntil: (p) => { ctx.jobs.push(Promise.resolve(p).catch(() => {})); }, jobs: [] };
const post = (qs, body, type = 'text/plain', route = '/api/feed/inbound', w = worker) => w.fetch(new Request('https://edge.hyperwax.io' + route + qs, { method: 'POST', headers: { 'Content-Type': type }, body: body == null ? '' : body }), env, ctx);
const quiet = console.warn; console.warn = () => {};
const say = console.log; const hush = async (fn) => { console.log = () => {}; try { return await fn(); } finally { console.log = say; } };

// ── 1. the report route ─────────────────────────────────────────────────────
console.log('\n1. POST /api/feed/check');
const check = (qs, body) => post(qs, body, 'text/plain', '/api/feed/check');
reset();
{
  let r = await check(`?token=${TOKEN}&result=same&bytes=8435`);
  let j = await r.json();
  const row = db.feeds[0];
  ok('"same" is accepted and stored on the feed row', r.status === 200 && j.success === true && row.last_check_result === 'same' && row.last_check_bytes === 8435 && !!row.last_check_at && row.last_check_note === null, JSON.stringify(j));
  ok('it writes no run row and does not move last_run_at (a quiet vendor must still read as quiet)', db.runs.length === 0 && row.last_run_at === null);
  ok('it never reaches the importer (no vehicle table is read or written)', !calls.some(c => /33a0663b_vehicles/.test(c.path)));

  r = await check(`?token=${TOKEN}&result=fetch_failed&bytes=0`, 'curl exit 6');
  ok('"fetch_failed" keeps the relay\'s own note', r.status === 200 && row.last_check_result === 'fetch_failed' && row.last_check_note === 'curl exit 6' && row.last_check_bytes === 0);
  r = await check(`?token=${TOKEN}&result=refused&bytes=57`, 'only 57 bytes (min 200)\nsecond line\u0007');
  ok('"refused" is stored; control characters in the note are flattened', r.status === 200 && row.last_check_result === 'refused' && row.last_check_note === 'only 57 bytes (min 200) second line');
  r = await check(`?token=${TOKEN}&result=same&bytes=notanumber`, 'x'.repeat(5000));
  ok('a bad byte count becomes NULL and a long note is cut to 300', row.last_check_bytes === null && row.last_check_note.length === 300);

  const before = JSON.stringify(row);
  r = await check(`?token=${TOKEN}&result=delete_everything`);
  ok('an unknown result is refused (400) and changes nothing', r.status === 400 && JSON.stringify(row) === before);
  r = await check(`?token=${TOKEN}&result=changed`);
  ok('"changed" cannot be claimed by a caller - only a real import stamps it', r.status === 400 && JSON.stringify(row) === before);
  r = await check(`?token=wrong&result=same`);
  ok('a wrong token gets the same bare 401 as before', r.status === 401 && (await r.text()) === 'unauthorized' && JSON.stringify(row) === before);
  r = await check(`?result=same`);
  ok('no token: 401 "missing token" (what the installer probes for)', r.status === 401 && (await r.text()) === 'missing token');
  r = await worker.fetch(new Request('https://edge.hyperwax.io/api/feed/check?result=same&bytes=11', { method: 'POST', headers: { 'X-Feed-Token': TOKEN }, body: '' }), env, ctx);
  ok('the token is accepted in the X-Feed-Token header, which is how the relay sends it (kept out of the URL)', r.status === 200 && db.feeds[0].last_check_bytes === 11);
  db.feeds[0].enabled = false;
  r = await check(`?token=${TOKEN}&result=same`);
  ok('a disabled feed: 401, indistinguishable from a wrong token', r.status === 401);
}

// ── 2. imports ──────────────────────────────────────────────────────────────
console.log('\n2. A real import');
const CSV = 'VIN,Year,Make,Model,Price,JD Power Clean Trade,Photo URLs\n1GT4UWEYXSF287869,2025,GMC,Sierra 3500,0,71800,http://img.example/1.jpg\n1FTFW1E50NFA00001,2022,Ford,F-150,0,38500,http://img.example/2.jpg\n';
reset();
{
  const r = await post(`?token=${TOKEN}`, CSV, 'text/csv');
  const j = await r.json();
  const row = db.feeds[0];
  ok('imports exactly as before', r.status === 200 && j.success === true && j.seen === 2 && db.runs.length === 1 && db.runs[0].status === 'ok' && !!row.last_run_at, JSON.stringify(j));
  ok('and stamps the check as "changed" with the file size', row.last_check_result === 'changed' && row.last_check_bytes === CSV.length && !!row.last_check_at);
}
reset(); checkColumns = false;
{
  const r = await post(`?token=${TOKEN}`, CSV, 'text/csv');
  const j = await r.json();
  const row = db.feeds[0];
  ok('Worker deployed BEFORE the SQL: the import still succeeds and last_run_at still moves', r.status === 200 && j.success === true && j.seen === 2 && db.runs.length === 1 && !!row.last_run_at && row.last_status === 'ok', JSON.stringify(j));
  const r2 = await check(`?token=${TOKEN}&result=same&bytes=10`);
  const j2 = await r2.json();
  ok('and a report answers 503 with a plain reason instead of pretending', r2.status === 503 && j2.success === false && /045_feed_checks\.sql/.test(j2.error), j2.error);
}

// ── 2b. a Worker WITHOUT the patch ─────────────────────────────────────────
if (process.argv[3]) {
  console.log('\n2b. The same report sent to a Worker that does not have this patch');
  const oldSrc = readFileSync(process.argv[3], 'utf8');
  if (oldSrc.includes('gsFeedStampCheck')) { ok('(setup) second file is an UNPATCHED worker.js', false); }
  else {
    const om = join(dir, 'worker-old.mjs'); writeFileSync(om, oldSrc);
    const old = (await import(pathToFileURL(om).href)).default;
    reset();
    const before = JSON.stringify(db.feeds[0]);
    const r = await post(`?token=${TOKEN}&result=same&bytes=8435`, '', 'text/plain', '/api/feed/check', old);
    const body = await r.text();
    ok('it is not treated as an import: no run row, the feed row untouched, the importer never called', db.runs.length === 0 && JSON.stringify(db.feeds[0]) === before && !calls.some(c => /33a0663b_vehicles|dealer_feed_runs|dealer_feeds/.test(c.path)));
    ok('and its answer is not the "success":true the relay looks for, so the relay logs that the report was not accepted', !/"success"\s*:\s*true/.test(body));
  }
}

// ── 3. findings ─────────────────────────────────────────────────────────────
console.log('\n3. gsFeedDetect - one feed row, one meaning');
const grab = (name) => { const st = src.indexOf('function ' + name + '('); let i = src.indexOf('{', st), d = 0; for (let j = i; j < src.length; j++) { if (src[j] === '{') d++; else if (src[j] === '}') { d--; if (!d) return src.slice(st, j + 1); } } };
const konst = (n) => { const st = src.indexOf('const ' + n + ' ='); return src.slice(st, src.indexOf(';', st) + 1); };
const det = (await import('data:text/javascript;base64,' + Buffer.from(konst('GS_FEED_STALE_S') + '\n' + konst('GS_FEED_CHECK_FRESH_S') + '\n' + grab('gsFeedSpan') + '\n' + grab('gsFeedDetect') + '\nexport { gsFeedDetect, GS_FEED_STALE_S, GS_FEED_CHECK_FRESH_S };').toString('base64')));
const H = 3600, M = 60;
const feed = (o) => ({ feed_id: 'feed-1', app_id: APP, app_name: 'The Desk Trader', provider: 'dealerslink', mode: 'push', enabled: true, last_status: 'ok', run_status: 'ok', ...o });
{
  ok('thresholds: 26h stale (same as the box and the console), 90 min without a report', det.GS_FEED_STALE_S === 26 * H && det.GS_FEED_CHECK_FRESH_S === 90 * M);
  const live = det.gsFeedDetect(feed({ age_s: 33 * H, last_check_at: 'x', check_age_s: 12 * M, last_check_result: 'same', last_check_bytes: 8435 }), false);
  ok('Oct 5 as it happened (33h, checked 12 min ago, same): ONE finding, vendor quiet, warn - not critical', live.length === 1 && live[0].kind === 'feed_vendor_quiet' && live[0].severity === 'warn');
  ok('its words: "has not changed in 33h", "fetched it 12 min ago", "identical (8,435 bytes)", "Nothing is broken on our side."', /has not changed in 33h\./.test(live[0].verdict) && /fetched it 12 min ago and it was identical \(8,435 bytes\)/.test(live[0].verdict) && /Nothing is broken on our side\.$/.test(live[0].verdict), live[0].verdict);
  ok('same file, 25h: no finding (a healthy gap)', det.gsFeedDetect(feed({ age_s: 25 * H, last_check_at: 'x', check_age_s: 5 * M, last_check_result: 'same' }), false).length === 0);
  ok('exactly 26h: not yet', det.gsFeedDetect(feed({ age_s: 26 * H, last_check_at: 'x', check_age_s: 5 * M, last_check_result: 'same' }), false).length === 0);
  ok('just imported: no finding', det.gsFeedDetect(feed({ age_s: 60, last_check_at: 'x', check_age_s: 60, last_check_result: 'changed' }), false).length === 0);
  const dead = det.gsFeedDetect(feed({ age_s: 5 * H, last_check_at: 'x', check_age_s: 2 * H + 10 * M, last_check_result: 'same' }), false);
  ok('no report for 2h10m: critical "feed not checking", even though the last import is only 5h old', dead.length === 1 && dead[0].kind === 'feed_not_checking' && dead[0].severity === 'critical' && /has not reported for 2h 10m/.test(dead[0].verdict) && /on our side, not dealerslink/.test(dead[0].verdict), dead[0] && dead[0].verdict);
  ok('its steps name the machine for each command', /1\. Proxmox shell: systemctl list-timers/.test(dead[0].steps) && /2\. Proxmox shell: tail -20 \/var\/log\/feed-relay\.log/.test(dead[0].steps) && /3\. Proxmox shell: \/usr\/local\/bin\/relay\.sh/.test(dead[0].steps));
  ok('the same silence while a host is already reported down: no second page', det.gsFeedDetect(feed({ age_s: 5 * H, last_check_at: 'x', check_age_s: 2 * H, last_check_result: 'same' }), true).length === 0);
  ok('exactly 90 min without a report: not yet', det.gsFeedDetect(feed({ age_s: 5 * H, last_check_at: 'x', check_age_s: 90 * M, last_check_result: 'same' }), false).length === 0);
  const ff = det.gsFeedDetect(feed({ age_s: 3 * H, last_check_at: 'x', check_age_s: 4 * M, last_check_result: 'fetch_failed', last_check_note: 'curl exit 6' }), false);
  ok('fetch failing: warn, carries the curl exit code, says the box itself is up', ff.length === 1 && ff[0].kind === 'feed_fetch_failing' && ff[0].severity === 'warn' && /\(curl exit 6\)/.test(ff[0].verdict) && /the box and its internet are up/.test(ff[0].verdict));
  const rf = det.gsFeedDetect(feed({ age_s: 3 * H, last_check_at: 'x', check_age_s: 4 * M, last_check_result: 'refused', last_check_note: 'only 57 bytes (min 200)' }), false);
  ok('file refused: warn, with the reason', rf.length === 1 && rf[0].kind === 'feed_file_refused' && /only 57 bytes \(min 200\)/.test(rf[0].verdict));
  ok('a feed that has NEVER reported (relay not updated yet) raises nothing, however old its last import', det.gsFeedDetect(feed({ age_s: 400 * H }), false).length === 0 && det.gsFeedDetect(feed({ age_s: null }), false).length === 0);
  ok('a disabled feed raises nothing', det.gsFeedDetect(feed({ enabled: false, age_s: 90 * H, last_check_at: 'x', check_age_s: 9 * H, last_check_result: 'same' }), false).length === 0);
  const all = [live[0], dead[0], ff[0], rf[0]].map(x => x.fingerprint);
  ok('each kind has its own fingerprint, tied to the feed', new Set(all).size === 4 && all.every(x => /:feed-1$/.test(x)));
}

// ── 4. the triage pass, end to end ──────────────────────────────────────────
console.log('\n4. The cron pass');
const pass = () => hush(async () => { kv.clear(); ctx.jobs = []; await worker.scheduled({}, env, ctx); await Promise.all(ctx.jobs); });
const beat = (o) => ({ host: 'pve', beat_at: new Date(Date.now() - 2 * M * 1000).toISOString(), failed_units: 0, dns_ok: true, feed_timer_ok: true, last_backup_status: 'OK', disk_used_pct: 40, ...o });
reset();
{
  db.beats = [beat({})];
  db.health = [feed({ age_s: 33 * H, last_check_at: 'x', check_age_s: 12 * M, last_check_result: 'same', last_check_bytes: 8435 }),
               { feed_id: 'feed-2', app_id: 'PUT-YOUR-APP-ID-HERE', provider: 'dealerslink', enabled: false, age_s: null }];
  await pass();
  const q = db.findings.filter(x => x.kind === 'feed_vendor_quiet');
  ok('vendor quiet for 33h with checks arriving: one finding, filed under "feed: The Desk Trader"', db.findings.length === 1 && q.length === 1 && q[0].host === 'feed: The Desk Trader' && q[0].severity === 'warn' && q[0].remedy === null && q[0].remedy_state === 'none', JSON.stringify(db.findings.map(x => x.kind)));
  ok('nobody is paged for it', db.mail.length === 0);
  ok('it read the feeds through the platform claim, not the service key', calls.some(c => /gs_feed_health/.test(c.path) && /^Bearer eyJ/.test(c.auth)));
  await pass();
  ok('a second pass files nothing new (one fault, one finding)', db.findings.length === 1);
  db.health[0] = feed({ age_s: 4 * M, last_check_at: 'x', check_age_s: 4 * M, last_check_result: 'changed', last_check_bytes: 8785 });
  await pass();
  ok('the vendor publishes: the finding resolves by itself, still without a page', !!db.findings[0].resolved_at && db.mail.length === 0);
}
reset();
{
  db.beats = [beat({})];
  db.health = [feed({ age_s: 5 * H, last_check_at: 'x', check_age_s: 2 * H + 10 * M, last_check_result: 'same' })];
  await pass();
  ok('relay stops reporting while the host beats normally: critical finding, and it pages', db.findings.length === 1 && db.findings[0].kind === 'feed_not_checking' && db.mail.length === 1 && /^Feed: feed not checking - The Desk Trader$/.test(db.mail[0].subject), JSON.stringify(db.mail.map(m => m.subject)));
  ok('the page carries the verdict and the numbered steps', /has not reported for 2h 10m/.test(db.mail[0].html) && /1\. Proxmox shell: systemctl list-timers/.test(db.mail[0].html));
  await pass();
  ok('it pages once, not every pass', db.mail.length === 1);
  db.health[0] = feed({ age_s: 5 * H + 30 * M, last_check_at: 'x', check_age_s: 3 * M, last_check_result: 'same' });
  await pass();
  ok('reports resume: resolved, with one "Cleared" message', !!db.findings[0].resolved_at && db.mail.length === 2 && /^Cleared: feed not checking - The Desk Trader$/.test(db.mail[1].subject));
}
reset();
{
  db.beats = [beat({ beat_at: new Date(Date.now() - 3 * H * 1000).toISOString() })];
  db.health = [feed({ age_s: 8 * H, last_check_at: 'x', check_age_s: 3 * H, last_check_result: 'same' })];
  await pass();
  ok('the whole box goes dark: the host finding pages, the feed does NOT page a second time for the same outage', db.findings.length === 1 && db.findings[0].kind === 'silent_host' && db.mail.length === 1 && /silent host on pve/.test(db.mail[0].subject), JSON.stringify(db.findings.map(x => x.kind)));
}
reset();
{
  db.beats = [beat({ failed_units: 1, failed_unit_names: 'feed-failed.service' })];
  db.health = [feed({ age_s: 3 * H, last_check_at: 'x', check_age_s: 4 * M, last_check_result: 'fetch_failed', last_check_note: 'curl exit 7' })];
  await pass();
  const kinds = db.findings.map(x => x.kind).sort().join();
  ok('host findings and feed findings sit side by side and do not close each other', kinds === 'failed_unit,feed_fetch_failing', kinds);
  db.health[0] = feed({ age_s: 3 * H, last_check_at: 'x', check_age_s: 2 * M, last_check_result: 'same' });
  await pass();
  const openNow = db.findings.filter(x => !x.resolved_at).map(x => x.kind).join();
  ok('the fetch recovers: only the feed finding closes; the host\'s failed unit stays open', openNow === 'failed_unit', openNow);
  db.beats = [beat({})];
  await pass();
  ok('and the host clearing its own finding still works as before', db.findings.every(x => !!x.resolved_at));
}
reset();
{
  db.beats = [beat({})];
  db.health = [feed({ age_s: 33 * H })];          // SQL not run / relay not updated: no check fields at all
  await pass();
  ok('before the box is updated nothing changes: an old import with no reports raises no feed finding', db.findings.length === 0 && db.mail.length === 0);
}

// ── 5. what the assistant is told ───────────────────────────────────────────
console.log('\n5. The first responder\'s instructions');
{
  const a = src.indexOf('const GS_CTL_ASK_SYSTEM = `'); const sys = src.slice(a, src.indexOf('`;', a));
  ok('it is told how to read the check fields, and that "same" with a fresh check means the vendor is quiet', /last_check_result/.test(sys) && /VENDOR IS QUIET/.test(sys) && /check_age_s under 90 minutes/.test(sys));
  ok('it is told the SAME lines are in /var/log/feed-relay.log and not in journalctl', /\/var\/log\/feed-relay\.log/.test(sys) && /Never send him to journalctl/.test(sys));
  ok('the instructions are still one well-formed template (no stray backtick or ${)', sys.slice(27).indexOf('`') === -1 && sys.indexOf('${') === -1);
}

console.warn = quiet;
console.log(f ? `\n${f} FAILED` : '\nall passed');
process.exit(f ? 1 : 0);
