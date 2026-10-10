// Runs the REAL worker.js assistant route (patch 047) against a stand-in
// Claude that answers the way the real API does when asked to stream:
// server-sent events, arriving in pieces. Nothing leaves this machine and no
// API key is used.
//
//   node t_worker_047.mjs <patched worker.js> [worker.js WITHOUT 047]
//
// Give the second file (your worker.js.bak) and it also reproduces the fault
// on the old code: a 524 from the API becomes "Claude API error 524".
//
// Node 18 has WebCrypto but does not expose it as a global to modules (Node 20+
// does). The Worker signs and checks its tokens with crypto.subtle, exactly as
// it does on Cloudflare, so hand it the same thing here.
import { webcrypto as __webcrypto } from 'node:crypto';
if (!globalThis.crypto || !globalThis.crypto.subtle) globalThis.crypto = __webcrypto;
import { readFileSync, writeFileSync, mkdtempSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import { pathToFileURL } from 'url';
import crypto from 'crypto';

const path = process.argv[2] || './worker.js';
const src = readFileSync(path, 'utf8');
if (!src.includes('async function gsCtlReadStream(')) { console.log('FAIL  this worker.js does not have patch 047 applied'); process.exit(1); }

let f = 0, n = 0; const ok = (l, c, x = '') => { n++; console.log(`${c ? 'PASS' : 'FAIL'}  ${l}${x ? '  ' + x : ''}`); if (!c) f++; };

// ── a stand-in Claude that streams ──────────────────────────────────────────
const enc = new TextEncoder();
const sse = (type, data) => `event: ${type}\ndata: ${JSON.stringify({ type, ...data })}\n\n`;
// Builds the event list the real API sends for one reply.
const events = ({ thinking = 0, text = [], stop = 'end_turn', out = 600, model = 'claude-opus-5' }) => {
  const ev = [sse('message_start', { message: { id: 'msg', type: 'message', role: 'assistant', model, content: [], stop_reason: null, usage: { input_tokens: 21000, output_tokens: 1 } } }), sse('ping', {})];
  let i = 0;
  if (thinking) {
    ev.push(sse('content_block_start', { index: i, content_block: { type: 'thinking', thinking: '' } }));
    for (let k = 0; k < thinking; k++) ev.push(sse('content_block_delta', { index: i, delta: { type: 'thinking_delta', thinking: 'weighing the evidence ' } }));
    ev.push(sse('content_block_delta', { index: i, delta: { type: 'signature_delta', signature: 'sig' } }), sse('content_block_stop', { index: i })); i++;
  }
  if (text.length) {
    ev.push(sse('content_block_start', { index: i, content_block: { type: 'text', text: '' } }));
    for (const t of text) ev.push(sse('content_block_delta', { index: i, delta: { type: 'text_delta', text: t } }));
    ev.push(sse('content_block_stop', { index: i }));
  }
  ev.push(sse('message_delta', { delta: { stop_reason: stop, stop_sequence: null }, usage: { output_tokens: out } }), sse('message_stop', {}));
  return ev;
};
// Turns events into a body that arrives in awkward pieces: `chop` bytes at a
// time (so events, lines and even characters are split across reads), with an
// optional pause, and optionally ending early or hanging.
const body = (ev, { chop = 0, gapMs = 0, cutAfter = null, hangAfter = null } = {}) => {
  const all = enc.encode((cutAfter == null && hangAfter == null ? ev : ev.slice(0, cutAfter ?? hangAfter)).join(''));
  const size = chop || all.length || 1; let at = 0;
  return new ReadableStream({
    async pull(c) {
      if (gapMs) await new Promise(r => realTimeout(r, gapMs));
      if (at >= all.length) { if (hangAfter != null) return new Promise(() => {}); c.close(); return; }
      c.enqueue(all.slice(at, at + size)); at += size;
    }
  });
};
const streamReply = (spec, how) => ({ kind: 'stream', spec, how });

const SB = 'https://supabase.test';
const json = (b, status = 200) => new Response(JSON.stringify(b), { status, headers: { 'Content-Type': 'application/json' } });
let script = []; const sent = [];
const realTimeout = globalThis.setTimeout, realInterval = globalThis.setInterval;
let shrink = {};                 // { 2000: 1 } = a 2000 ms timer fires after 1 ms, in this test only
globalThis.setTimeout = (fn, ms, ...a) => realTimeout(fn, shrink[ms] ?? ms, ...a);
globalThis.setInterval = (fn, ms, ...a) => realInterval(fn, shrink[ms] ?? ms, ...a);
let cleared = 0; const realClearInterval = globalThis.clearInterval;
globalThis.clearInterval = (id) => { cleared++; return realClearInterval(id); };

globalThis.fetch = async (input, init = {}) => {
  const u = new URL(typeof input === 'string' ? input : input.url);
  if (u.host === 'api.anthropic.com') {
    sent.push(JSON.parse(init.body));
    const next = script.shift() || streamReply({ text: ['default answer'] });
    if (next.kind === 'stream') return new Response(body(events(next.spec).concat(next.spec.then || []), next.how), { status: 200, headers: { 'Content-Type': 'text/event-stream; charset=utf-8' } });
    if (next.kind === 'raw') return new Response(body(next.events, next.how), { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
    if (next.kind === 'throw') throw new TypeError('fetch failed');
    return json(next.body || { type: 'error', error: { type: 'overloaded_error', message: 'Overloaded' } }, next.status);
  }
  if (u.host === 'supabase.test') return json(u.pathname.endsWith('/gs_feed_health') ? [{ feed_id: 'feed-1', app_name: 'The Desk Trader', run_status: 'ok', age_s: 3600 }] : []);
  return json({});
};

const load = async (code, tag) => {
  const dir = mkdtempSync(join(tmpdir(), 'gsw-')); const mod = join(dir, tag + '.mjs');
  const has = (name) => code.includes('function ' + name + '(');
  // Test-only: expose the judge from the temp copy. The file on disk is not touched.
  writeFileSync(mod, code + '\nexport const __t = { judge: ' + (has('gsInfraJudge') ? 'gsInfraJudge' : 'null') + ' };\n');
  const m = await import(pathToFileURL(mod).href);
  return { worker: m.default, t: m.__t };
};
const { worker, t } = await load(src, 'new');
const env = { SUPABASE_URL: SB, SUPABASE_ANON_KEY: 'anon', SUPABASE_SERVICE_ROLE_KEY: 'svc', SUPABASE_JWT_SECRET: 'jwt-secret-for-tests',
              APP_AUTH_JWT_SECRET: 'app-auth-secret-for-tests', CLAUDE_API_KEY: 'not-a-real-key', DEPLOYMENTS: { get: async () => null, put: async () => {}, delete: async () => {} } };
const ctx = { waitUntil: () => {} };
const b64 = (s) => Buffer.from(s).toString('base64');
const head = b64(JSON.stringify({ alg: 'HS256', typ: 'JWT' })), pay = b64(JSON.stringify({ kind: 'admin', role: 'platform', scope: 'controller', exp: Math.floor(Date.now() / 1000) + 600 }));
const TOKEN = head + '.' + pay + '.' + crypto.createHmac('sha256', env.APP_AUTH_JWT_SECRET).update(head + '.' + pay).digest('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');

// Asks the route. With stream:true the NDJSON lines are collected with the
// time each one arrived.
const ask = async (bodyObj, w = worker) => {
  sent.length = 0;
  const t0 = Date.now();
  const r = await w.fetch(new Request('https://edge.hyperwax.io/api/controller/ask', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + TOKEN }, body: JSON.stringify(bodyObj) }), env, ctx);
  const type = r.headers.get('content-type') || '';
  if (!/ndjson/.test(type)) { let j = null; try { j = await r.json(); } catch (e) {} return { status: r.status, type, j, calls: sent.slice() }; }
  const lines = []; const reader = r.body.getReader(); const dec = new TextDecoder(); let buf = '';
  for (;;) { const { done, value } = await reader.read(); if (done) break; buf += dec.decode(value, { stream: true }); let nl;
    while ((nl = buf.indexOf('\n')) !== -1) { lines.push({ at: Date.now() - t0, ...JSON.parse(buf.slice(0, nl)) }); buf = buf.slice(nl + 1); } }
  const result = lines.find(l => l.type === 'result');
  return { status: r.status, type, lines, result, text: lines.filter(l => l.type === 'text').map(l => l.delta).join(''), calls: sent.slice(), headers: r.headers };
};
const quiet = console.warn; console.warn = () => {};
shrink = { 2000: 1 };            // the wait before retrying a busy API

// ── 1. reading the stream ───────────────────────────────────────────────────
console.log('\n1. The Worker reads Claude\'s reply as a stream');
{
  const words = ['FALSE POSITIVE', ' - the ', 'vendor did not regenerate', ' the file.\n\n1. Proxmox shell: ', 'tail -20 /var/log/feed-relay.log', '\n\n[[GSTASKS:["Proxmox: tail the relay log"]]]'];
  script = [streamReply({ thinking: 40, text: words, out: 912 })];
  const r = await ask({ question: 'why did the feed alert fire?' });
  ok('it asks Claude to stream', r.calls.length === 1 && r.calls[0].stream === true && r.calls[0].max_tokens === 16000);
  ok('without "stream" in the request the console still gets one JSON object, as before', /application\/json/.test(r.type) && r.status === 200 && r.j.answer === words.join(''), JSON.stringify(r.j).slice(0, 160));
  ok('stop_reason, model and token counts are read off the stream', r.j.stop_reason === 'end_turn' && r.j.model === 'claude-opus-5' && r.j.usage.input_tokens === 21000 && r.j.usage.output_tokens === 912 && r.j.tries === 1);

  for (const chop of [1, 7, 64, 1000]) {
    script = [streamReply({ thinking: 5, text: ['Größe: 8 785 bytes — “unchanged” ✓ ', 'naïve café 日本語'], out: 50 }, { chop })];
    const c = await ask({ question: 'x' });
    if (c.j.answer !== 'Größe: 8 785 bytes — “unchanged” ✓ naïve café 日本語') { ok('reply arriving ' + chop + ' byte(s) at a time is put back together exactly', false, c.j.answer); break; }
    if (chop === 1000) ok('replies arriving 1, 7, 64 and 1000 bytes at a time are all put back together exactly (accents, quotes and CJK split mid-character)', true);
  }

  script = [{ status: 200, body: { type: 'message', role: 'assistant', model: 'claude-opus-5', content: [{ type: 'text', text: 'whole reply' }], stop_reason: 'end_turn', usage: { input_tokens: 5, output_tokens: 2 } } }];
  const w = await ask({ question: 'x' });
  ok('a reply that comes back whole (not a stream) is still understood', w.j.answer === 'whole reply' && w.j.stop_reason === 'end_turn');
}

// ── 2. to the console, as it is written ─────────────────────────────────────
console.log('\n2. "stream": true - the console gets the answer as it is written');
{
  script = [streamReply({ thinking: 3, text: ['The relay ', 'is healthy. ', 'Nothing to run.'], out: 40 }, { gapMs: 12, chop: 110 })];
  const r = await ask({ question: 'is the feed ok?', stream: true });
  ok('answers 200 as NDJSON, with the controller\'s CORS headers', r.status === 200 && /application\/x-ndjson/.test(r.type) && r.headers.get('access-control-allow-origin') === '*' && r.headers.get('cache-control') === 'no-store');
  ok('the first line goes out at once, before Claude has said anything', r.lines[0].type === 'status' && r.lines[0].at < 60, JSON.stringify(r.lines[0]));
  ok('the words arrive as separate lines, in order, before the result', r.lines.filter(l => l.type === 'text').map(l => l.delta).join('|') === 'The relay |is healthy. |Nothing to run.' && r.lines[r.lines.length - 1].type === 'result');
  const firstText = r.lines.find(l => l.type === 'text'), last = r.lines[r.lines.length - 1];
  ok('the first words reach the console while the rest is still being written', last.at - firstText.at >= 25, `first text at ${firstText.at} ms, result at ${last.at} ms`);
  ok('the last line carries exactly what the route returns without "stream"', r.result.status === 200 && r.result.answer === 'The relay is healthy. Nothing to run.' && r.result.stop_reason === 'end_turn' && r.result.tries === 1 && r.result.usage.output_tokens === 40 && r.result.attachments.used === 0);

  // a long silence from Claude: the console still hears from us
  shrink = { 2000: 1, 10000: 30 };
  const clearedBefore = cleared;
  script = [streamReply({ text: ['done'] }, { gapMs: 110, chop: 400 })];
  const s = await ask({ question: 'x', stream: true });
  const beats = s.lines.filter(l => l.type === 'status' && l.message === 'working').length;
  ok('while Claude is silent a "working" line still goes out on a timer, so the line to the browser is never idle', beats >= 3 && s.result.answer === 'done', beats + ' beats');
  shrink = { 2000: 1 };
  ok('the timer is stopped when the answer is done (nothing left running in the Worker)', cleared > clearedBefore);

  const u = await worker.fetch(new Request('https://edge.hyperwax.io/api/controller/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: 'x', stream: true }) }), env, ctx);
  ok('no session token: plain 401 JSON, no stream, Claude never called', u.status === 401 && /application\/json/.test(u.headers.get('content-type')));
}

// ── 3. things that go wrong part way ────────────────────────────────────────
console.log('\n3. Faults');
{
  script = [streamReply({ thinking: 50, text: [], stop: 'max_tokens', out: 16000 }), streamReply({ text: ['Short answer.'], out: 30 })];
  let r = await ask({ question: 'hard one', stream: true });
  ok('thinking used the whole allowance: tries again at low effort, tells the console, delivers the answer', r.calls.length === 2 && r.calls[1].output_config.effort === 'low' && r.calls[1].stream === true
     && r.lines.some(l => l.type === 'retry' && l.why === 'empty') && r.result.answer === 'Short answer.' && r.result.tries === 2 && r.result.usage.output_tokens === 16030);

  const overloaded = sse('error', { error: { type: 'overloaded_error', message: 'Overloaded' } });
  script = [{ kind: 'raw', events: events({ text: ['Half an ans'] }).slice(0, 4).concat([overloaded]) }, streamReply({ text: ['The whole answer.'] })];
  r = await ask({ question: 'x', stream: true });
  const order = r.lines.filter(l => l.type !== 'status').map(l => l.type === 'text' ? 'text:' + l.delta : l.type).join(' > ');
  ok('Claude overloaded part way: the half answer is withdrawn (retry line) and the second attempt is delivered', order === 'text:Half an ans > retry > text:The whole answer. > result' && r.result.answer === 'The whole answer.' && r.calls.length === 2, order);

  script = [{ kind: 'raw', events: events({ text: ['Half'] }).slice(0, 4).concat([overloaded]) }, { kind: 'raw', events: [overloaded] }];
  r = await ask({ question: 'x', stream: true });
  ok('overloaded twice: stops after two attempts with a plain error, never a half answer passed off as whole', r.calls.length === 2 && r.result.status === 502 && r.result.error === 'Claude stopped part way through the reply (overloaded_error)' && r.result.detail === 'Overloaded' && !r.result.answer, JSON.stringify(r.result));
  script = [{ kind: 'raw', events: [overloaded] }, { kind: 'raw', events: [overloaded] }];
  r = await ask({ question: 'x' });
  ok('the same, to a console that did not ask to stream: HTTP 502 with that error', r.status === 502 && r.j.error === 'Claude stopped part way through the reply (overloaded_error)');

  script = [streamReply({ text: ['Cut sho', 'rt'] }, { cutAfter: 4 }), streamReply({ text: ['Complete.'] })];
  r = await ask({ question: 'x' });
  ok('the connection closes before the reply finishes: tried again, full answer delivered', r.calls.length === 2 && r.j.answer === 'Complete.');
  script = [streamReply({ text: ['a'] }, { cutAfter: 4 }), streamReply({ text: ['a'] }, { cutAfter: 4 })];
  r = await ask({ question: 'x' });
  ok('closes early twice: says the connection dropped', r.status === 502 && r.j.error === 'The connection to Claude dropped part way through the reply');

  shrink = { 2000: 1, 120000: 60 };
  script = [streamReply({ text: ['Starts then'] }, { hangAfter: 4 }), streamReply({ text: ['Recovered.'] })];
  r = await ask({ question: 'x' });
  ok('Claude goes silent mid-reply: given up on after the idle limit and tried again', r.calls.length === 2 && r.j.answer === 'Recovered.');
  script = [streamReply({ text: ['a'] }, { hangAfter: 3 }), streamReply({ text: ['a'] }, { hangAfter: 3 })];
  r = await ask({ question: 'x' });
  ok('silent twice: a plain error instead of hanging forever', r.status === 502 && r.j.error === 'Claude stopped responding part way through the reply' && /sent nothing for 120 seconds/.test(r.j.detail), JSON.stringify(r.j));
  shrink = { 2000: 1 };

  script = [{ kind: 'throw' }, streamReply({ text: ['Back.'] })];
  r = await ask({ question: 'x' });
  ok('the API cannot be reached at all: tried again', r.calls.length === 2 && r.j.answer === 'Back.');

  script = [{ status: 529 }, streamReply({ text: ['ok now'] })];
  r = await ask({ question: 'x' });
  ok('529 before any reply starts: still tried once more', r.j.answer === 'ok now' && r.calls.length === 2);
  script = [{ status: 401, body: { type: 'error', error: { type: 'authentication_error', message: 'invalid x-api-key' } } }];
  r = await ask({ question: 'x', stream: true });
  ok('a wrong API key is not retried; the error arrives as the result line', r.calls.length === 1 && r.result.status === 502 && r.result.error === 'Claude API error 401' && /invalid x-api-key/.test(r.result.detail));
  script = [{ kind: 'raw', events: [sse('error', { error: { type: 'invalid_request_error', message: 'prompt is too long' } })] }];
  r = await ask({ question: 'x' });
  ok('an error retrying cannot fix (invalid request) is not retried', r.calls.length === 1 && r.status === 502 && /invalid_request_error/.test(r.j.error) && r.j.detail === 'prompt is too long');

  script = [streamReply({ text: [], stop: 'refusal', out: 0 })];
  r = await ask({ question: 'x', stream: true });
  ok('a refusal: not retried, reported as a refusal', r.calls.length === 1 && r.result.empty === true && r.result.stop_reason === 'refusal' && /declined this one/.test(r.result.answer));
  script = [streamReply({ text: ['1. First do this\n2. Then'], stop: 'max_tokens' })];
  r = await ask({ question: 'x', stream: true });
  ok('an answer cut off at the length limit is delivered and marked', r.result.truncated === true && /\[Cut off here/.test(r.result.answer) && r.calls.length === 1);
}

// ── 4. attachments and the judge still work over the stream ─────────────────
console.log('\n4. Everything else is unchanged');
{
  const PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';
  script = [streamReply({ text: ['It shows a 401.'] })];
  const r = await ask({ question: 'what is this?', stream: true, attachments: [{ name: 'shot.png', kind: 'image', media_type: 'image/png', data: PNG }, { name: 'deck.pptx', kind: 'binary', data: PNG }] });
  const c = r.calls[0].messages[0].content;
  ok('attachments are sent exactly as in 046, and the result says what was used and what was skipped', Array.isArray(c) && c[2].type === 'image' && c[2].source.data === PNG && r.result.attachments.used === 1 && r.result.attachments.skipped[0].name === 'deck.pptx' && r.result.answer === 'It shows a 401.');
  ok('"stream" from the console is not passed into the question itself', !JSON.stringify(r.calls[0].messages).includes('"stream"'));

  sent.length = 0; script = [streamReply({ thinking: 10, text: ['{"verdict":"Two jobs raced for the lock.","steps":"1. Proxmox shell: cat /etc/pve/jobs.cfg","approve_remedy":false,"why":"none offered"}'] }, { chop: 9 })];
  let v = await t.judge(env, 'pve', { kind: 'backup_failed', severity: 'warn', evidence: {}, candidate: null }, { age_s: 60 });
  ok('the unattended judge reads its verdict off the stream', v.verdict === 'Two jobs raced for the lock.' && v.approve === false && sent[0].stream === true && sent[0].max_tokens === 8000);
  sent.length = 0; script = [{ status: 524, body: { error: 'timeout' } }];
  v = await t.judge(env, 'pve', { kind: 'backup_failed', severity: 'warn', evidence: {}, candidate: null }, { age_s: 60 });
  ok('and still falls back safely when the API fails', /no model verdict available/.test(v.verdict) && v.approve === false);
}

// ── 5. the Worker without 047 ───────────────────────────────────────────────
if (process.argv[3]) {
  console.log('\n5. Compared with the Worker that does not have 047');
  const old = await load(readFileSync(process.argv[3], 'utf8'), 'old');
  script = [{ status: 524, body: 'error code: 524' }];
  const o = await ask({ question: 'next steps for the backups?' }, old.worker);
  ok('the old route asks for the reply whole (no "stream"), so a slow reply is a timeout: "Claude API error 524" - the fault, reproduced', o.status === 502 && o.j.error === 'Claude API error 524' && o.calls[0].stream === undefined, JSON.stringify(o.j).slice(0, 120));
  const bodyObj = { question: 'is the feed ok?', history: [{ role: 'user', content: 'earlier' }, { role: 'assistant', content: 'answer' }] };
  const RealDate = Date; globalThis.Date = class extends RealDate { constructor(...a) { super(...(a.length ? a : [1791205200000])); } static now() { return 1791205200000; } };
  script = [{ status: 200, body: { content: [{ type: 'text', text: 'a' }], stop_reason: 'end_turn' } }]; const a = await ask(bodyObj, old.worker);
  script = [streamReply({ text: ['a'] })]; const b = await ask(bodyObj, worker);
  globalThis.Date = RealDate;
  const A = a.calls[0], B = b.calls[0];
  // 048 adds its own section to the prompt; set it aside so this still compares 047 with what came before it.
  const no048 = (t) => { const i = t.indexOf('DISKS, BACKUP STORAGE AND BACKUP RUNS\n'), j = t.indexOf('HOW TO ANSWER\n'); return i > 0 && j > i ? t.slice(0, i) + t.slice(j) : t; };
  ok('what is sent to Claude is identical to before, plus "stream": true and nothing else', JSON.stringify({ ...B, stream: undefined, system: no048(B.system) }) === JSON.stringify({ ...A, system: no048(A.system) }) && B.stream === true);
}

console.warn = quiet;
console.log(f ? `\n${f} of ${n} FAILED` : `\nall ${n} passed`);
process.exit(f ? 1 : 0);
