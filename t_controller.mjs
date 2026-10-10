// t_controller.mjs — executes the patched worker's controller helpers.
// Extracts them and runs them for real against node's WebCrypto, then verifies
// the minted JWT the way Supabase would.
import { readFileSync } from 'fs';
import crypto from 'crypto';

const src = readFileSync('./worker.js', 'utf8');
const grab = (name) => {
  const start = src.indexOf(`async function ${name}(`);
  if (start < 0) throw new Error(`missing ${name}`);
  let i = src.indexOf('{', start), depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === '{') depth++;
    else if (src[j] === '}') { depth--; if (!depth) return src.slice(start, j + 1); }
  }
  throw new Error(`unbalanced ${name}`);
};

const mod = await import('data:text/javascript;base64,' + Buffer.from(
  grab('gsPlatformHeaders') + '\n' + grab('adminSignToken') + '\n' + grab('adminVerify') +
  '\n' + grab('requireController') +
  '\nexport { gsPlatformHeaders, adminSignToken, adminVerify, requireController };'
).toString('base64'));

const env = {
  SUPABASE_ANON_KEY: 'anon-key-xyz',
  SUPABASE_JWT_SECRET: 'super-secret-jwt-value-for-test',
  APP_AUTH_JWT_SECRET: 'app-auth-secret-for-test',
};
let fails = 0;
const ok = (label, cond, extra='') => { console.log(`${cond ? 'PASS' : 'FAIL'}  ${label}${extra?'  '+extra:''}`); if (!cond) fails++; };

// 1. platform header mints a real token, not the anon fallback
const h = await mod.gsPlatformHeaders(env, {});
const tok = h.Authorization.slice(7);
ok('mints a token (not anon fallback)', tok !== env.SUPABASE_ANON_KEY);

// 2. that token verifies under SUPABASE_JWT_SECRET, HS256 — what Supabase does
const [hd, pl, sg] = tok.split('.');
const expect = crypto.createHmac('sha256', env.SUPABASE_JWT_SECRET).update(hd + '.' + pl)
  .digest('base64').replace(/\+/g,'-').replace(/\//g,'_').replace(/=/g,'');
ok('signature verifies under SUPABASE_JWT_SECRET', expect === sg);

// 3. claims are exactly what gs_is_platform() reads
const claims = JSON.parse(Buffer.from(pl, 'base64url').toString());
ok('carries gs_platform="true"', claims.gs_platform === 'true', JSON.stringify(claims));
ok('carries NO app_id (cannot satisfy gs_scoped_*)', claims.app_id === undefined);
ok('expires within the hour', claims.exp - claims.iat === 3600);

// 4. cached on second call
const h2 = await mod.gsPlatformHeaders(env, {});
ok('token cached across calls', h2.Authorization === h.Authorization);

// 5. missing secret degrades to anon rather than throwing
const hNo = await mod.gsPlatformHeaders({ SUPABASE_ANON_KEY: 'anon-key-xyz' }, {});
ok('no JWT secret -> anon fallback, no throw', hNo.Authorization === 'Bearer anon-key-xyz');

// 6. the gate
const req = (t) => ({ headers: { get: (k) => k === 'Authorization' ? 'Bearer ' + t : null } });
const ctlTok = await mod.adminSignToken(env, { kind:'admin', scope:'controller', role:'platform', email:'o@x.com' }, 3600);
ok('controller token accepted', !!(await mod.requireController(env, req(ctlTok))));

const tenantTok = await mod.adminSignToken(env, { kind:'admin', app_id:'550c457e', admin_id:'x', role:'admin' }, 3600);
ok('tenant admin token REJECTED', (await mod.requireController(env, req(tenantTok))) === null);

const ownerRoleTok = await mod.adminSignToken(env, { kind:'admin', app_id:'550c457e', role:'owner' }, 3600);
ok('per-app owner token REJECTED', (await mod.requireController(env, req(ownerRoleTok))) === null);

const forged = await mod.adminSignToken({ APP_AUTH_JWT_SECRET:'wrong-secret' }, { kind:'admin', scope:'controller', role:'platform' }, 3600);
ok('token signed with wrong secret REJECTED', (await mod.requireController(env, req(forged))) === null);

const expired = await mod.adminSignToken(env, { kind:'admin', scope:'controller', role:'platform' }, -10);
ok('expired token REJECTED', (await mod.requireController(env, req(expired))) === null);

ok('garbage token REJECTED', (await mod.requireController(env, req('not.a.token'))) === null);
ok('no token REJECTED', (await mod.requireController(env, { headers:{ get:()=>null } })) === null);

console.log(fails ? `\n${fails} FAILURES` : '\nall checks passed');
process.exit(fails ? 1 : 0);
