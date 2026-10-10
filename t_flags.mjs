// Executes gsResolveFlags against a stubbed Supabase.
import { readFileSync } from 'fs';
const src = readFileSync('./worker.js','utf8');
const grab = (n) => { const st = src.indexOf('async function '+n+'(');
  let i = src.indexOf('{', st), d=0;
  for (let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d) return src.slice(st,j+1);} } };
const shim = src.slice(src.indexOf('const GS_FLAGS_SHIM'), src.indexOf('`;', src.indexOf('const GS_FLAGS_SHIM'))+2);
const mod = await import('data:text/javascript;base64,'+Buffer.from(
  grab('gsPlatformHeaders')+'\n'+grab('gsResolveFlags')+'\n'+shim+
  '\nexport { gsResolveFlags, GS_FLAGS_SHIM };').toString('base64'));

const env = { SUPABASE_URL:'https://db.test', SUPABASE_ANON_KEY:'anon', SUPABASE_JWT_SECRET:'s3cret' };
let calls=0, mode='ok';
globalThis.fetch = async (u) => {
  calls++;
  if (mode==='fail') return { ok:false, status:500, json:async()=>({}) };
  if (mode==='throw') throw new Error('network down');
  return { ok:true, status:200, json:async()=>([
    {key:'new_checkout',enabled:true,source:'rollout'},
    {key:'legacy_nav',enabled:false,source:'override'}
  ])};
};
let f=0; const ok=(l,c,x='')=>{console.log(`${c?'PASS':'FAIL'}  ${l}${x?'  '+x:''}`); if(!c)f++;};

const a = await mod.gsResolveFlags(env,'app-1');
ok('resolves to a flat key->bool map', JSON.stringify(a)==='{"new_checkout":true,"legacy_nav":false}', JSON.stringify(a));
const before = calls;
await mod.gsResolveFlags(env,'app-1'); await mod.gsResolveFlags(env,'app-1');
ok('cached: repeat calls issue no request', calls===before);
await mod.gsResolveFlags(env,'app-2');
ok('different app does issue a request', calls>before);

ok('no app id -> empty, no request', JSON.stringify(await mod.gsResolveFlags(env,null))==='{}');
mode='fail';
ok('RPC 500 on a NEW app -> empty, does not throw', JSON.stringify(await mod.gsResolveFlags(env,'app-3'))==='{}');
ok('RPC 500 on a CACHED app -> serves last good', JSON.stringify(await mod.gsResolveFlags(env,'app-1'))!=='{}');
mode='throw';
ok('network throw -> empty, does not propagate', JSON.stringify(await mod.gsResolveFlags(env,'app-4'))==='{}');

// the injected shim
const w = {}; globalThis.window = w;
w.__GS_FLAGS = { new_checkout:true, legacy_nav:false };
new Function('window', mod.GS_FLAGS_SHIM)(w);
ok('gsFlag reads an enabled flag', w.gsFlag('new_checkout')===true);
ok('gsFlag reads a disabled flag', w.gsFlag('legacy_nav')===false);
ok('unknown flag falls back to default', w.gsFlag('nope', true)===true && w.gsFlag('nope')===false);
ok('gsFlags returns a copy, not the original', w.gsFlags()!==w.__GS_FLAGS && w.gsFlags().new_checkout===true);
console.log(f?`\n${f} FAILURES`:'\nall checks passed');
process.exit(f?1:0);
