// Executes the feed/infra health decisions out of controller.html.
//
// The thing under test is the staleness threshold, because it is the part
// that is quietly wrong by default. dealer_feed_runs only gets a row when the
// vendor's file CHANGED - the relay fetches every 30 minutes and skips
// identical files - so observed gaps between rows run 9-15 hours. A naive
// "red after 6 hours" would alarm every single day on a healthy feed.
import { readFileSync } from 'fs';
const src = readFileSync('./controller.html','utf8');
const grab = (n) => { const st = src.indexOf('function '+n+'(');
  let i = src.indexOf('{', st), d=0;
  for (let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d) return src.slice(st,j+1);} } };
const konst = (n) => { const st = src.indexOf('const '+n+' ='); return src.slice(st, src.indexOf(';', st)+1); };

const mod = await import('data:text/javascript;base64,'+Buffer.from(
  konst('FEED_STALE_S')+'\n'+konst('HOST_SILENT_S')+'\n'+grab('feedTone')+
  '\nexport { feedTone, FEED_STALE_S, HOST_SILENT_S };').toString('base64'));

let f=0; const ok=(l,c,x='')=>{console.log(`${c?'PASS':'FAIL'}  ${l}${x?'  '+x:''}`); if(!c)f++;};
const H = 3600;

ok('threshold matches STALE_HOURS=26 in feed-alert.sh', mod.FEED_STALE_S === 26*H, String(mod.FEED_STALE_S));
ok('hosts go silent at 15 min (beats are every 5)',     mod.HOST_SILENT_S === 15*60, String(mod.HOST_SILENT_S));

// Real gaps measured from dealer_feed_runs on 2026-10-03:
// Oct 1 18:10 -> Oct 2 09:22 = 15h12m, the widest healthy gap observed.
ok('fresh import is live',            mod.feedTone({run_status:'ok', age_s: 2*H})  === 'live');
ok('9h gap is still healthy',         mod.feedTone({run_status:'ok', age_s: 9*H})  === 'live');
ok('15h gap is still healthy',        mod.feedTone({run_status:'ok', age_s: 15*H}) === 'live');
ok('25h is the last healthy hour',    mod.feedTone({run_status:'ok', age_s: 25*H}) === 'live');
ok('27h is stale',                    mod.feedTone({run_status:'ok', age_s: 27*H}) === 'rem');

// A failed status is red whatever the age - a run that failed an hour ago is
// not healthy just because it is recent.
ok('failed status beats a fresh age', mod.feedTone({run_status:'error', age_s: 60}) === 'rem');
ok('falls back to last_status',       mod.feedTone({last_status:'error', age_s: 60}) === 'rem');

// A feed that has never run has no age. It must not render as healthy green,
// and it must not render as red either - there is nothing to be wrong yet.
ok('never-run feed is neutral',       mod.feedTone({}) === '');

// Guard the boundary explicitly: off-by-one here is a daily false alarm.
ok('exactly 26h is not yet stale',    mod.feedTone({run_status:'ok', age_s: 26*H}) === 'live');
ok('one second past 26h is stale',    mod.feedTone({run_status:'ok', age_s: 26*H+1}) === 'rem');

console.log(f ? `\n${f} FAILED` : '\nall passed');
process.exit(f?1:0);
