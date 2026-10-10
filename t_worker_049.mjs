// Runs the REAL worker.js (patch 049) against what the sandbox AI did to The
// Desk Trader's console on 2026-10-05, replayed edit for edit, and checks the
// platform now refuses the two edits that did the damage - and nothing else.
// The tab settings below are the app's real ones, as read from the live
// console that evening. Claude and the database are stood in for; nothing
// leaves this machine.
//
//   node t_worker_049.mjs <patched worker.js>
//
// Node 18 has WebCrypto but does not expose it as a global to modules (Node 20+
// does). The Worker signs its tokens with crypto.subtle, so hand it over.
import { webcrypto as __webcrypto } from 'node:crypto';
if (!globalThis.crypto || !globalThis.crypto.subtle) globalThis.crypto = __webcrypto;
import { readFileSync, writeFileSync, mkdtempSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import { pathToFileURL } from 'url';

const path = process.argv[2] || './worker.js';
const src = readFileSync(path, 'utf8');
if (!src.includes('function gsAgentTabGuard(')) { console.log('FAIL  this worker.js does not have patch 049 applied'); process.exit(1); }
let f = 0, n = 0; const ok = (l, c, x = '') => { n++; console.log(`${c ? 'PASS' : 'FAIL'}  ${l}${(!c && x) ? '  ' + String(typeof x === 'string' ? x : JSON.stringify(x)).slice(0, 700) : ''}`); if (!c) f++; };

// ── The Desk Trader's saved tabs (admin_shell_settings.mobile_nav_config) ───
const APP = '33a0663b-93b4-458d-8ff6-3f06ec2474bb';
const DESK_TABS = [
  { icon: 'dash', id: 'dashboard', label: 'Dashboard', path: '/dashboard' },
  { icon: 'cart', id: 'orders', label: 'Orders', off: true, path: '/orders' },
  { icon: 'zap', id: 'members', label: 'Members', off: true, path: '/members' },
  { icon: 'cal', id: 'buy-bids-desk', label: 'The Desk', path: '/buy-bids-desk' },
  { icon: 'url:https://supabase.hyperwax.io/storage/v1/object/public/app-media/mobile-nav/x/admin-1.png', id: 'vehicles', label: 'Inventory', path: '/vehicles' },
  { custom: true, icon: 'sell', id: 'sell', label: 'Sell', path: '/sell', tool: 'vin' },
  { icon: 'users', id: 'inbox', label: 'Inbox', path: '/inbox' },
];

// ── The console's two structural files, cut down to what matters ────────────
const link = (r, t, icon) => `<Link to="/${r}" className={navClass('${r}')} style={{display:'flex',alignItems:'center'}}><${icon} size={18}/> <span className="font-medium text-sm flex-1" style={{marginLeft:'0.75rem'}}>${t}</span></Link>`;
const wrapped = (r, t, icon) => `{tabWrap('${r}', ${link(r, t, icon)})}`;
const layout = (o = {}) => `import React, { useState } from 'react';
import { Outlet, Link } from 'react-router-dom';
import { LayoutDashboard, Zap, HardDrive, Phone, FileText } from 'lucide-react';
const HwmSellArrow = (p) => <svg {...p}/>;
export const AdminLayout = () => {
  const hwmToolTabs = [];
  ${o.old ? '' : 'const hwmToolsShown = hwmToolTabs.filter((m) => true);'}
  return (
    <div>
          <NavSection id='core' label='Core System'>
${wrapped('dashboard', 'Dashboard', 'LayoutDashboard')}
</NavSection>
${o.noBlock ? '' : `{/* GS_ADMIN_MNAV_V1:E */}
{${o.old ? 'hwmToolTabs' : 'hwmToolsShown'}.length ? (
  <div data-hw-tool-tabs="1">
    <p className="text-[10px] font-bold uppercase">Tools</p>
    {${o.old ? 'hwmToolTabs' : 'hwmToolsShown'}.map((m) => tabWrap(m.id, <Link key={m.id} to={m.path} className={navClass(m.id)}>{m.label}</Link>))}
  </div>
) : null}
{/* GS_ADMIN_MNAV_V1:/E */}`}
<NavSection id='comms' label='Communications'>
${wrapped('sms', 'SMS + Voice', 'Phone')}
${link('buy-bids-desk', 'Wholesale Desk', 'Zap')}
${link('trade-imports', 'Trade Imports', 'HardDrive')}
</NavSection>
<NavSection id='conn' label='Connections'>
${wrapped('forms', 'Forms', 'FileText')}
</NavSection>
      <Outlet/>
    </div>
  );
};
`;
const MAIN = `import React from 'react';
import ReactDOM from 'react-dom/client';
import { HashRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AdminLayout } from './AdminLayout';
import { Dashboard } from './pages/Dashboard';
import { BuyBidsDesk } from './pages/BuyBidsDesk';
import { BlankTab } from './pages/BlankTab';

ReactDOM.createRoot(document.getElementById('root')).render(
  <HashRouter>
    <Routes>
      <Route path="/" element={<AdminLayout />}>
           <Route index element={<Navigate to="/dashboard" replace />} />
           <Route path="dashboard" element={<Dashboard />} />
           <Route path="buy-bids-desk" element={<BuyBidsDesk />} />
           <Route path="*" element={<BlankTab />} />
      </Route>
    </Routes>
  </HashRouter>
);
`;
const SELL_PAGE = `import React from 'react';\nexport const Sell = () => <div>Orders pipeline and open offers</div>;\n`;
// the edits, as the sandbox AI made them
const E_IMPORT = { path: 'src/admin/main.tsx', find: "import { BlankTab } from './pages/BlankTab';", replace: "import { BlankTab } from './pages/BlankTab';\nimport { Sell } from './pages/Sell';" };
const E_ROUTE = { path: 'src/admin/main.tsx', find: '           <Route path="*" element={<BlankTab />} />', replace: '           <Route path="sell" element={<Sell />} />\n           <Route path="*" element={<BlankTab />} />' };
const MOVED = `${link('buy-bids-desk', 'Wholesale Desk', 'Zap')}\n${link('trade-imports', 'Trade Imports', 'HardDrive')}\n`;
const sectionEdit = (label, withSell) => ({ path: 'src/admin/AdminLayout.tsx',
  find: `${MOVED}</NavSection>\n<NavSection id='conn' label='Connections'>`,
  replace: `</NavSection>\n<NavSection id='mytools' label='${label}'>\n${withSell ? wrapped('sell', 'Sell', 'HwmSellArrow') + '\n' : ''}${wrapped('buy-bids-desk', 'Wholesale Desk', 'Zap')}\n${wrapped('trade-imports', 'Trade Imports', 'HardDrive')}\n</NavSection>\n<NavSection id='conn' label='Connections'>` });

// ── load the Worker ─────────────────────────────────────────────────────────
const SB = 'https://supabase.test';
const db = { shell: [{ mobile_nav_config: DESK_TABS }], shellStatus: 200, shellThrows: false, intents: [], deployments: [] };
const seen = { shell: [], claude: [] };
let script = [];        // what "Claude" answers, one entry per call
const json = (b, status = 200) => new Response(JSON.stringify(b), { status, headers: { 'Content-Type': 'application/json' } });
const sse = (blocks, stop) => {
  const ev = [];
  const push = (o) => ev.push('event: ' + o.type + '\ndata: ' + JSON.stringify(o) + '\n\n');
  push({ type: 'message_start', message: { usage: { input_tokens: 100, output_tokens: 0, cache_creation_input_tokens: 0, cache_read_input_tokens: 0 } } });
  blocks.forEach((b, i) => {
    if (b.type === 'text') { push({ type: 'content_block_start', index: i, content_block: { type: 'text', text: '' } }); push({ type: 'content_block_delta', index: i, delta: { type: 'text_delta', text: b.text } }); }
    else { push({ type: 'content_block_start', index: i, content_block: { type: 'tool_use', id: b.id, name: b.name, input: {} } }); push({ type: 'content_block_delta', index: i, delta: { type: 'input_json_delta', partial_json: JSON.stringify(b.input) } }); }
    push({ type: 'content_block_stop', index: i });
  });
  push({ type: 'message_delta', delta: { stop_reason: stop || 'tool_use' }, usage: { output_tokens: 50 } });
  push({ type: 'message_stop' });
  return new Response(new ReadableStream({ start(c) { c.enqueue(new TextEncoder().encode(ev.join(''))); c.close(); } }), { status: 200, headers: { 'content-type': 'text/event-stream' } });
};
globalThis.fetch = async (input, init = {}) => {
  const u = new URL(typeof input === 'string' ? input : input.url);
  const method = (init.method || 'GET').toUpperCase();
  const body = init.body ? (() => { try { return JSON.parse(init.body); } catch { return init.body; } })() : null;
  if (u.host === 'api.anthropic.com') {
    seen.claude.push(JSON.parse(JSON.stringify(body)));
    const step = script.shift();
    if (!step) return sse([{ type: 'tool_use', id: 'tu_end', name: 'finish', input: { response: 'Done.' } }]);
    return sse(step);
  }
  if (u.host !== 'supabase.test') return json({});
  if (u.pathname === '/auth/v1/user') return json({ id: 'user-1', email: 'owner@example.com' });
  const table = u.pathname.replace('/rest/v1/', '');
  if (table === 'admin_shell_settings') {
    seen.shell.push({ url: u.pathname + u.search, headers: init.headers || {} });
    if (db.shellThrows) throw new Error('network down');
    return json(db.shellStatus === 200 ? db.shell : { message: 'no' }, db.shellStatus);
  }
  if (table === 'profiles') return json([{ id: 'user-1', premium_credits: 50, email: 'owner@example.com' }]);
  if (table === 'deployments' && method === 'GET') return json(db.deployments);
  if (table === 'app_backend_intents' && method === 'POST') { db.intents.push(body); return new Response('', { status: 201 }); }
  if (table === 'app_backend_intents') return new Response('', { status: 204 });
  if (table === '') return json({ definitions: {} });
  if (method === 'GET') return json([]);
  return new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } });
};
const dir = mkdtempSync(join(tmpdir(), 'gsw-')); const mod = join(dir, 'worker.mjs');
// Test-only: expose internals from the temp copy. The file on disk is not touched.
writeFileSync(mod, src + '\nexport const __t = { tabs: gsTabsFromConfig, adminTabs: gsAdminTabs, guard: gsAgentTabGuard, ws: gsAgentWorkspace };\n');
const m = await import(pathToFileURL(mod).href);
const worker = m.default, t = m.__t;
const env = { SUPABASE_URL: SB, SUPABASE_ANON_KEY: 'anon-key', CLAUDE_API_KEY: 'k', JWT_SECRET: 'x'.repeat(40) };

// ── 1. the tab list ─────────────────────────────────────────────────────────
console.log('\n1. What the sandbox AI is told about the tabs');
const TABS = t.tabs(DESK_TABS);
{
  ok('The Desk Trader: one tab is passed on - Sell', TABS.length === 1 && TABS[0].label === 'Sell' && TABS[0].route === 'sell', TABS);
  ok('it is marked a tool, and says which one (VIN Scanner)', TABS[0].kind === 'tool' && TABS[0].tool === 'VIN Scanner', TABS[0]);
  ok('it carries the icon key (sell), so the AI can draw the tab\'s own icon', TABS[0].icon === 'sell', TABS[0]);
  ok('its note says: no page file, no route, never add one, link with to="/sell"', /No page file and no route/.test(TABS[0].note) && /Never add a route or a page at \/sell/.test(TABS[0].note) && TABS[0].note.includes('to="/sell"'), TABS[0].note);
  ok('built-in tabs (Dashboard, Inbox, The Desk...) are not listed - they are in the files already', !TABS.some(x => ['dashboard', 'inbox', 'buy-bids-desk', 'vehicles'].includes(x.route)));
  const more = t.tabs(DESK_TABS.concat([{ custom: true, icon: 'star', id: 'notes', label: 'Notes', path: '/notes' }, { custom: true, icon: 'url:https://x/y.png', id: 'lanes', label: 'Lanes', path: '/lanes', tool: 'vin' }]));
  ok('an empty tab is marked "blank": a page may be built there', more.find(x => x.route === 'notes').kind === 'blank' && /what it is for/.test(more.find(x => x.route === 'notes').note), more);
  ok('a tab with an uploaded icon is listed without an icon key (no long URL in the prompt)', more.find(x => x.route === 'lanes').kind === 'tool' && !('icon' in more.find(x => x.route === 'lanes')), more);
  ok('junk in the saved list is ignored, not passed on', t.tabs([null, 5, 'x', { custom: true }, { custom: true, path: 'sell', tool: 'vin' }, { custom: true, path: '/a b', tool: 'vin' }, { custom: true, path: '/../x' }]).length === 0);
  ok('nothing saved -> empty list', t.tabs(null).length === 0 && t.tabs(undefined).length === 0 && t.tabs({}).length === 0);
}

console.log('\n2. Reading the tabs from the database');
{
  seen.shell = [];
  const r = await t.adminTabs(env, APP);
  ok('read for this app only, one column, with the public key', r && r.length === 1 && seen.shell.length === 1 && seen.shell[0].url.includes('app_id=eq.' + APP) && seen.shell[0].url.includes('select=mobile_nav_config') && seen.shell[0].headers.apikey === 'anon-key', seen.shell);
  db.shell = []; ok('an app with no saved row -> empty list', (await t.adminTabs(env, APP)).length === 0);
  db.shellStatus = 500; ok('the database says no -> "could not read" (null), not an error', (await t.adminTabs(env, APP)) === null);
  db.shellStatus = 200; db.shellThrows = true; ok('the network fails -> null, not an error', (await t.adminTabs(env, APP)) === null);
  db.shellThrows = false; db.shell = [{ mobile_nav_config: DESK_TABS }];
  seen.shell = [];
  ok('a made-up app id is never sent to the database', (await t.adminTabs(env, "x' or 1=1")) === null && (await t.adminTabs(env, '')) === null && seen.shell.length === 0);
}

// ── 3. the edits, through the real tools ────────────────────────────────────
const space = (files, adminTabs, extra = {}) => t.ws({ files: Object.keys(files).map(name => ({ name, content: files[name] })), adminTabs, fullStack: false, ...extra }, 'admin');
const attempt = (ws, tool, inp) => { try { return { ok: true, out: ws.tools[tool](inp) }; } catch (e) { return { ok: false, err: String(e.message) }; } };

console.log('\n3. Replay: "move the Sell tab" -> the AI builds its own Sell page and a /sell route');
{
  const ws = space({ 'src/admin/main.tsx': MAIN, 'src/admin/AdminLayout.tsx': layout() }, TABS);
  ok('creating pages/Sell.tsx is not refused by itself (a file is not a route)', attempt(ws, 'create_file', { path: 'src/admin/pages/Sell.tsx', content: SELL_PAGE }).ok);
  ok('adding its import to main.tsx is not refused by itself', attempt(ws, 'edit_file', E_IMPORT).ok);
  const before = ws.vfs.get('src/admin/main.tsx');
  const r = attempt(ws, 'edit_file', E_ROUTE);
  ok('adding <Route path="sell"> is REFUSED', !r.ok, r);
  ok('main.tsx is left exactly as it was', ws.vfs.get('src/admin/main.tsx') === before && !ws.vfs.get('src/admin/main.tsx').includes('path="sell"'));
  ok('the refusal says what /sell is: the "Sell" tab, a platform tool tab showing the VIN Scanner', !r.ok && r.err.includes('/sell is the "Sell" tab') && r.err.includes('platform tool tab showing the VIN Scanner'), r.err);
  ok('and what to do instead: ONE sidebar link with to="/sell", nothing else', !r.ok && r.err.includes('add ONE sidebar link with to="/sell" in src/admin/AdminLayout.tsx and change nothing else'), r.err);
  ok('and that nothing was changed', !r.ok && r.err.includes('Nothing was changed.'), r.err);
  for (const v of ['<Route path=\'sell\' element={<Sell />} />', '<Route path="/sell" element={<Sell />} />', '<Route  path={"sell"} element={<Sell />} />']) {
    const w2 = space({ 'src/admin/main.tsx': MAIN }, TABS);
    ok('same route written another way is refused too: ' + v.slice(0, 26), !attempt(w2, 'edit_file', { ...E_ROUTE, replace: '           ' + v + '\n           <Route path="*" element={<BlankTab />} />' }).ok);
  }
  const w3 = space({ 'src/admin/main.tsx': MAIN }, TABS);
  ok('a route at another address is fine (sell-orders, trade-imports)', attempt(w3, 'edit_file', { ...E_ROUTE, replace: '           <Route path="sell-orders" element={<Sell />} />\n           <Route path="trade-imports" element={<Sell />} />\n           <Route path="*" element={<BlankTab />} />' }).ok);
}

console.log('\n4. The console as it stands tonight (the stray route is already in main.tsx)');
{
  const broken = MAIN.replace(E_IMPORT.find, E_IMPORT.replace).replace(E_ROUTE.find, E_ROUTE.replace);
  const ws = space({ 'src/admin/main.tsx': broken, 'src/admin/pages/Sell.tsx': SELL_PAGE }, TABS);
  ok('an unrelated edit to main.tsx still works (the old route is not held against it)', attempt(ws, 'edit_file', { path: 'src/admin/main.tsx', find: '<Route path="dashboard" element={<Dashboard />} />', replace: '<Route path="dashboard" element={<Dashboard />} />\n           <Route path="reports" element={<Dashboard />} />' }).ok);
  ok('TAKING THE ROUTE OUT works', attempt(ws, 'edit_file', { path: 'src/admin/main.tsx', find: '           <Route path="sell" element={<Sell />} />\n', replace: '' }).ok && !ws.vfs.get('src/admin/main.tsx').includes('path="sell"'));
  ok('and so does taking the import out', attempt(ws, 'edit_file', { path: 'src/admin/main.tsx', find: "\nimport { Sell } from './pages/Sell';", replace: '' }).ok);
  ok('putting the route back is refused', !attempt(ws, 'edit_file', E_ROUTE).ok);
}

console.log('\n5. Replay: "move Wholesale Desk under Tools" -> a second section called Tools');
{
  let ws = space({ 'src/admin/AdminLayout.tsx': layout() }, TABS);
  const before = ws.vfs.get('src/admin/AdminLayout.tsx');
  let r = attempt(ws, 'edit_file', sectionEdit('Tools', false));
  ok('a second "Tools" section without the Sell tab in it is REFUSED', !r.ok, r);
  ok('the layout is left exactly as it was', ws.vfs.get('src/admin/AdminLayout.tsx') === before);
  ok('the refusal explains: the platform already draws a Tools heading, for Sell', !r.ok && r.err.includes('the platform draws it for the tool tabs (Sell)') && r.err.includes('would show the heading twice'), r.err);
  ok('and how to make it ONE section: put a link to="/sell" labelled "Sell" inside it', !r.ok && r.err.includes('Make it ONE section') && r.err.includes('to="/sell" labelled "Sell"') && r.err.includes('The platform heading removes itself'), r.err);
  r = attempt(ws, 'edit_file', sectionEdit('Tools', true));
  ok('the same section WITH the Sell link is accepted', r.ok, r);
  ok('and is in the file: Sell, Wholesale Desk, Trade Imports under one heading', /<NavSection id='mytools' label='Tools'>\n\{tabWrap\('sell'[^\n]+\n\{tabWrap\('buy-bids-desk'[^\n]+\n\{tabWrap\('trade-imports'/.test(ws.vfs.get('src/admin/AdminLayout.tsx')));
  ws = space({ 'src/admin/AdminLayout.tsx': layout() }, TABS);
  ok('a section with another name ("Dealer Tools") is not refused', attempt(ws, 'edit_file', sectionEdit('Dealer Tools', false)).ok);
  ok('adding the Sell link to it afterwards works', attempt(ws, 'edit_file', { path: 'src/admin/AdminLayout.tsx', find: "<NavSection id='mytools' label='Dealer Tools'>\n", replace: "<NavSection id='mytools' label='Dealer Tools'>\n" + wrapped('sell', 'Sell', 'HwmSellArrow') + '\n' }).ok);
  ws = space({ 'src/admin/AdminLayout.tsx': layout() }, TABS);
  ok('"tools", "TOOLS" and double quotes are the same heading', !attempt(ws, 'edit_file', sectionEdit('tools', false)).ok && !attempt(ws, 'edit_file', sectionEdit('TOOLS', false)).ok && !attempt(ws, 'edit_file', (() => { const e = sectionEdit('Tools', false); e.replace = e.replace.replace("id='mytools' label='Tools'", 'id="mytools" label="Tools"'); return e; })()).ok);
  // a console whose layout has not been synced since before this build
  ws = space({ 'src/admin/AdminLayout.tsx': layout({ old: true }) }, TABS);
  r = attempt(ws, 'edit_file', sectionEdit('Tools', true));
  ok('a console not yet synced: a "Tools" section is refused even with the Sell link (its layout would still show both)', !r.ok && r.err.includes('Press Sync Core in the Admin tab once, then ask me again'), r);
  ok('...and "Dealer Tools" still works there', attempt(ws, 'edit_file', sectionEdit('Dealer Tools', true)).ok);
  ws = space({ 'src/admin/AdminLayout.tsx': layout({ noBlock: true }) }, TABS);
  ok('a console with no platform Tools list at all: a "Tools" section is fine (there is nothing to double)', attempt(ws, 'edit_file', sectionEdit('Tools', false)).ok);
  ws = space({ 'src/admin/AdminLayout.tsx': layout() }, TABS);
  ok('ordinary sidebar edits are untouched: adding a link, renaming a label', attempt(ws, 'edit_file', { path: 'src/admin/AdminLayout.tsx', find: link('trade-imports', 'Trade Imports', 'HardDrive'), replace: link('trade-imports', 'Imports', 'HardDrive') + '\n' + link('reports', 'Reports', 'Zap') }).ok);
}

console.log('\n6. Nothing changes where there is nothing to protect');
{
  for (const [label, tabs] of [['an app with no tool tab', t.tabs(DESK_TABS.filter(x => !x.tool))], ['the tab list could not be read', undefined], ['an empty list', []], ['a garbled list', 'x']]) {
    const ws = space({ 'src/admin/main.tsx': MAIN, 'src/admin/AdminLayout.tsx': layout() }, tabs);
    ok(label + ': a /sell route and a "Tools" section are both allowed, as before', attempt(ws, 'edit_file', E_ROUTE).ok && attempt(ws, 'edit_file', sectionEdit('Tools', false)).ok);
  }
  const blank = t.tabs([{ custom: true, icon: 'star', id: 'notes', label: 'Notes', path: '/notes' }]);
  const ws = space({ 'src/admin/main.tsx': MAIN }, blank);
  ok('an EMPTY tab: building a page and a route at its address is allowed - that is what it is for', attempt(ws, 'edit_file', { ...E_ROUTE, replace: '           <Route path="notes" element={<Dashboard />} />\n           <Route path="*" element={<BlankTab />} />' }).ok);
  const front = t.ws({ files: [{ name: 'src/App.tsx', content: 'export const App = () => <Route path="sell" />;\n' }], adminTabs: TABS, fullStack: false }, 'app');
  ok('the frontend app is not affected (its own /sell route is its own business)', (() => { try { front.tools.edit_file({ path: 'src/App.tsx', find: '<Route path="sell" />', replace: '<><Route path="sell" /><Route path="sell" /></>' }); return true; } catch (e) { return false; } })());
}

// ── 7. the whole route, with Claude stood in for ────────────────────────────
console.log('\n7. A full sandbox AI turn through /api/ai/generate');
const turn = async (files, steps, extra = {}) => {
  script = steps.slice(); seen.claude = []; seen.shell = [];
  const req = new Request('https://edge.hyperwax.io/api/ai/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ appId: APP, model: 'claude-sonnet-5', prompt: 'move my Sell tab into Dealer Tools', rawPrompt: 'move my Sell tab into Dealer Tools', agent: true, userId: 'user-1', accessToken: 'tok',
      surface: 'admin', history: [], files: Object.keys(files).map(name => ({ name, content: files[name] })), ...extra }) });
  const res = await worker.fetch(req, env, { waitUntil() {}, passThroughOnException() {} });
  const lines = (await res.text()).split('\n').filter(Boolean).map(l => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
  return { lines, result: lines.filter(l => l.type === 'result').pop() };
};
{
  const files = { 'src/admin/main.tsx': MAIN, 'src/admin/AdminLayout.tsx': layout(), 'src/admin/pages/BuyBidsDesk.tsx': 'export const BuyBidsDesk = () => null;\n' };
  const good = { path: 'src/admin/AdminLayout.tsx', find: "<NavSection id='conn' label='Connections'>", replace: "<NavSection id='mytools' label='Dealer Tools'>\n" + wrapped('sell', 'Sell', 'HwmSellArrow') + "\n</NavSection>\n<NavSection id='conn' label='Connections'>" };
  const { lines, result } = await turn(files, [
    [{ type: 'tool_use', id: 'tu_1', name: 'create_file', input: { path: 'src/admin/pages/Sell.tsx', content: SELL_PAGE } }, { type: 'tool_use', id: 'tu_2', name: 'edit_file', input: E_ROUTE }],
    [{ type: 'tool_use', id: 'tu_3', name: 'edit_file', input: good }],
    [{ type: 'tool_use', id: 'tu_4', name: 'finish', input: { response: 'Sell is now in Dealer Tools.' } }],
  ]);
  ok('the turn completes', result && result.success === true, result || lines.slice(-3));
  const c0 = seen.claude[0] || {};
  const sys = JSON.stringify(c0.system || '');
  const first = JSON.stringify((c0.messages || [])[0] || '');
  ok('the tab list is read once for the request, for this app', seen.shell.length === 1 && seen.shell[0].url.includes(APP), seen.shell);
  ok('Claude is given CONSOLE TABS with the Sell tab in it', first.includes('CONSOLE TABS') && first.includes('\\\\\\"route\\\\\\":\\\\\\"sell\\\\\\"') || (first.includes('CONSOLE TABS') && /route[^a-z]+sell/.test(first) && /VIN Scanner/.test(first)), first.slice(0, 300));
  ok('the rules it is given include 28 (tool tabs) and 29 (revert)', sys.includes('28. TOOL TABS, AND WHAT') && sys.includes('29. \\"REVERT\\", \\"UNDO\\" AND \\"PUT IT BACK\\" MEAN EXACTLY THAT.'), sys.length);
  ok('rule 28 tells it how to link a tool tab with the tab\'s own icon', sys.includes("hwmIconFor('<icon key>')") && sys.includes('NEVER add a <Route> at a tool tab'), '');
  const toolResults = JSON.stringify((seen.claude[1] || {}).messages || []);
  ok('its /sell route was refused and it was told why, in the same turn', toolResults.includes('tu_2') && toolResults.includes('platform tool tab showing the VIN Scanner') && /is_error[^a-z]+true/.test(toolResults), toolResults.slice(-900));
  const changed = JSON.stringify(result || {});
  ok('what comes back to the builder: the sidebar link edit, and NO change to main.tsx', result && changed.includes("id='mytools' label='Dealer Tools'") && !changed.includes('path=\\"sell\\"') && !/"name":"src\/admin\/main\.tsx"/.test(changed), changed.slice(0, 900));
}
{
  // frontend-only request: no console files, so nothing is read and nothing added
  const { result } = await turn({ 'src/App.tsx': 'export const App = () => null;\n' }, [[{ type: 'tool_use', id: 'tu_1', name: 'finish', input: { response: 'ok' } }]], { surface: 'app' });
  const first = JSON.stringify(((seen.claude[0] || {}).messages || [])[0] || '');
  ok('a frontend-only request: the tab list is not read and not sent', result && result.success === true && seen.shell.length === 0 && !first.includes('CONSOLE TABS'), seen.shell);
}
{
  db.shellStatus = 500;
  const { result } = await turn({ 'src/admin/main.tsx': MAIN, 'src/admin/AdminLayout.tsx': layout() }, [[{ type: 'tool_use', id: 'tu_1', name: 'edit_file', input: E_IMPORT }], [{ type: 'tool_use', id: 'tu_2', name: 'finish', input: { response: 'ok' } }]]);
  db.shellStatus = 200;
  const first = JSON.stringify(((seen.claude[0] || {}).messages || [])[0] || '');
  ok('the tab list cannot be read: the turn still runs, exactly as before the patch', result && result.success === true && !first.includes('CONSOLE TABS'), result);
}

// ── 8. admin pages generated from the "backend" key ─────────────────────────
console.log('\n8. Admin pages the AI asks the platform to generate');
const apply = async (backend) => {
  db.intents = []; seen.shell = [];
  db.deployments = [{ id: APP, user_id: 'user-1', project_files: [], admin_project_files: [], database_tables: [] }];
  const res = await worker.fetch(new Request('https://edge.hyperwax.io/api/fullstack/apply', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ projectId: APP, userId: 'user-1', accessToken: 'tok', backend }) }), env, { waitUntil() {}, passThroughOnException() {} });
  return { status: res.status, body: await res.json() };
};
{
  const pages = { adminPages: [{ entity: 'sell', title: 'Sell', fields: [{ name: 'vin', type: 'text' }] }, { entity: 'sell_orders', title: 'Sell Orders', fields: [{ name: 'vin', type: 'text' }] }] };
  let r = await apply(pages);
  const skip = (r.body.skipped || []).find(x => x.name === 'sell');
  ok('a page that would land on /sell is NOT generated', r.status === 200 && !!skip && !db.intents.some(i => i.spec && i.spec.route === 'sell'), r.body);
  ok('the reason goes back: /sell is the "Sell" tab, which shows the VIN Scanner', !!skip && skip.reason.includes('/sell is the "Sell" tab') && skip.reason.includes('VIN Scanner'), skip);
  ok('the other page in the same request is generated as normal (sell-orders)', db.intents.length === 1 && db.intents[0].spec.route === 'sell-orders' && r.body.admin_pages_queued === 1, db.intents);
  db.shell = [{ mobile_nav_config: DESK_TABS.filter(x => !x.tool) }];
  r = await apply(pages);
  ok('an app with no tool tab: both pages are generated, as before', db.intents.length === 2 && !(r.body.skipped || []).length, r.body);
  db.shellStatus = 500;
  r = await apply(pages);
  ok('the tab list cannot be read: both pages are generated, as before', db.intents.length === 2 && r.status === 200, r.body);
  db.shellStatus = 200; db.shell = [{ mobile_nav_config: DESK_TABS }];
  r = await apply({ records: [] });
  ok('a request with no pages does not read the tab list at all', r.status === 200 && seen.shell.length === 0, seen.shell);
}

console.log(`\n${n - f}/${n} passed`);
process.exit(f ? 1 : 0);
