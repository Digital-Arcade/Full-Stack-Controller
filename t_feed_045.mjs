// Executes the Feed tab's decisions out of controller.html, after 045.
//
//   node t_feed_045.mjs [controller.html]
//
// Two halves. First, every case from t_feed.mjs, unchanged: a feed that has
// never checked in (045 not on the box yet) must behave exactly as it did.
// Second, the new cases - built from what actually happened on 2026-10-05,
// when the vendor did not regenerate for 33 hours and the relay logged SAME
// every 30 minutes throughout.
import { readFileSync } from 'fs';
const file = process.argv[2] || './controller.html';
const src = readFileSync(file, 'utf8');
const grab = (n) => { const st = src.indexOf('function '+n+'(');
  if (st < 0) throw new Error(n + ' not found in ' + file + ' - is patch_controller_html_045.py applied?');
  let i = src.indexOf('{', st), d=0;
  for (let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d) return src.slice(st,j+1);} } };
const konst = (n) => { const st = src.indexOf('const '+n+' ='); return src.slice(st, src.indexOf(';', st)+1); };

const mod = await import('data:text/javascript;base64,'+Buffer.from(
  konst('FEED_STALE_S')+'\n'+konst('FEED_CHECK_FRESH_S')+'\n'+konst('HOST_SILENT_S')+'\n'+
  grab('feedCheck')+'\n'+grab('feedTone')+'\n'+grab('feedSpan')+'\n'+grab('feedStory')+
  '\nexport { feedTone, feedCheck, feedStory, feedSpan, FEED_STALE_S, FEED_CHECK_FRESH_S, HOST_SILENT_S };').toString('base64'));

let f=0, n=0; const ok=(l,c,x='')=>{n++; console.log(`${c?'PASS':'FAIL'}  ${l}${x?'  '+x:''}`); if(!c)f++;};
const H = 3600, M = 60;
const T = mod.feedTone, S = mod.feedStory;

console.log('\n-- unchanged: a feed that has never checked in (every case from t_feed.mjs) --');
ok('threshold matches STALE_HOURS=26 in feed-alert.sh', mod.FEED_STALE_S === 26*H, String(mod.FEED_STALE_S));
ok('hosts go silent at 15 min (beats are every 5)',     mod.HOST_SILENT_S === 15*60, String(mod.HOST_SILENT_S));
ok('fresh import is live',            T({run_status:'ok', age_s: 2*H})  === 'live');
ok('9h gap is still healthy',         T({run_status:'ok', age_s: 9*H})  === 'live');
ok('15h gap is still healthy',        T({run_status:'ok', age_s: 15*H}) === 'live');
ok('25h is the last healthy hour',    T({run_status:'ok', age_s: 25*H}) === 'live');
ok('27h is stale',                    T({run_status:'ok', age_s: 27*H}) === 'rem');
ok('failed status beats a fresh age', T({run_status:'error', age_s: 60}) === 'rem');
ok('falls back to last_status',       T({last_status:'error', age_s: 60}) === 'rem');
ok('never-run feed is neutral',       T({}) === '');
ok('exactly 26h is not yet stale',    T({run_status:'ok', age_s: 26*H}) === 'live');
ok('one second past 26h is stale',    T({run_status:'ok', age_s: 26*H+1}) === 'rem');
ok('and it tells no story: no chip, no extra text, so the old 26h block still shows',
   (() => { const s = S({run_status:'ok', age_s: 27*H, provider:'dealerslink'}); return s.check === null && !s.chip && !s.line && !s.head; })());
ok('check columns present but empty (SQL run, box not updated yet) is the same as never',
   T({run_status:'ok', age_s: 27*H, last_check_at:null, last_check_result:null, check_age_s:null}) === 'rem'
   && mod.feedCheck({last_check_at:null, check_age_s:null}) === null);

console.log('\n-- Oct 5 as it happened: 29h since the last import, relay logging SAME 18 minutes ago --');
const oct5 = { run_status:'ok', age_s: 29*H, provider:'dealerslink', enabled:true,
               last_check_at:'2026-10-05T16:19:44Z', last_check_result:'same', last_check_bytes:8435, check_age_s: 18*M };
ok('it is amber, not red',                 T(oct5) === 'warn', T(oct5));
const s5 = S(oct5);
ok('chip says vendor quiet, in amber',     s5.chip === 'vendor quiet' && s5.tone === 'warn');
ok('row reads: checked 18 min ago: unchanged (8,435 bytes)', s5.line === 'checked 18 min ago: unchanged (8,435 bytes)', s5.line);
ok('heading names the vendor and the real gap', s5.head === 'No new file from dealerslink in 29h', s5.head);
ok('body says nothing is broken on our side, and gives no command to run',
   /Nothing is broken on our side and there is nothing to run/.test(s5.body) && s5.cmd === '');

console.log('\n-- the same check-in when the import is recent: nothing to flag --');
const fine = { ...oct5, age_s: 9*H };
ok('9h since import + SAME 18 min ago is plain green', T(fine) === 'live');
ok('no chip and no explanation, just the check-in on the row',
   (() => { const s = S(fine); return !s.chip && !s.head && s.line === 'checked 18 min ago: unchanged (8,435 bytes)'; })());
ok('a fresh import reads "new file imported"',
   S({ run_status:'ok', age_s: 5*M, last_check_at:'x', last_check_result:'changed', check_age_s: 5*M, enabled:true }).line === 'checked 5 min ago: new file imported');

console.log('\n-- the relay stops reporting --');
const silent = { ...oct5, age_s: 9*H, check_age_s: 3*H };
ok('red even though the last import is only 9h old', T(silent) === 'rem');
const ss = S(silent);
ok('chip: relay not reporting',            ss.chip === 'relay not reporting' && ss.tone === 'rem');
ok('says it is our side, not the vendor',  /on our side, not dealerslink/.test(ss.body));
ok('gives the two commands, and tail not journalctl',
   ss.cmd.includes("systemctl list-timers 'feed-*' --no-pager") && ss.cmd.includes('tail -20 /var/log/feed-relay.log') && !/journalctl/.test(ss.body + ss.cmd));
ok('exactly 90 minutes is not yet silent', T({ ...oct5, age_s: 9*H, check_age_s: 90*M }) === 'live');
ok('one second past 90 minutes is',        T({ ...oct5, age_s: 9*H, check_age_s: 90*M + 1 }) === 'rem');
ok('threshold matches the Worker (90 min)', mod.FEED_CHECK_FRESH_S === 90*M);
ok('stale import AND silent relay: red, and the story is the relay (the cause), not the vendor',
   T({ ...oct5, check_age_s: 5*H }) === 'rem' && S({ ...oct5, check_age_s: 5*H }).chip === 'relay not reporting');

console.log('\n-- the relay reports a failed fetch --');
const ff = { ...oct5, age_s: 3*H, last_check_result:'fetch_failed', last_check_note:'curl exit 6', last_check_bytes:0, check_age_s: 4*M };
ok('red, with the import only 3h old',     T(ff) === 'rem');
ok('row carries the curl exit code',       S(ff).line === 'checked 4 min ago: could not download (curl exit 6)', S(ff).line);
ok('says the box is up and the problem is toward the vendor', /box and its internet are up/.test(S(ff).body) && /curl exit 6 is DNS on the box/.test(S(ff).body));
const rf = { ...oct5, age_s: 3*H, last_check_result:'refused', last_check_note:'only 13 bytes (min 200)', last_check_bytes:13, check_age_s: 4*M };
ok('a refused file is red and gives the reason', T(rf) === 'rem' && S(rf).line === 'checked 4 min ago: file refused (only 13 bytes (min 200))' && /^Only 13 bytes \(min 200\)\. That guard is deliberate/.test(S(rf).body));

console.log('\n-- edges --');
ok('a failed import status still wins over a healthy check-in', T({ ...oct5, age_s: 60, run_status:'error' }) === 'rem');
ok('a disabled feed is not judged on check-ins (it is not supposed to run)',
   mod.feedCheck({ ...silent, enabled:false }) === null && !S({ ...silent, enabled:false }).chip);
ok('an unknown result word is ignored rather than guessed at',
   mod.feedCheck({ ...oct5, last_check_result:'banana' }) === null && T({ ...oct5, last_check_result:'banana' }) === 'rem');
ok('check-in but never imported: neutral, not green', T({ last_check_at:'x', last_check_result:'same', check_age_s: 60, enabled:true }) === '');
ok('spans read naturally', mod.feedSpan(40) === '1 min' && mod.feedSpan(18*M) === '18 min' && mod.feedSpan(2*H+5*M) === '2h 5m' && mod.feedSpan(29*H+40*M) === '29h');
ok('vendor text cannot inject markup: the story is plain text and the page escapes it',
   /\$\{esc\(story\.head\)\}/.test(src) && /\$\{esc\(story\.body\)\}/.test(src) && /esc\(story\.line\)/.test(src) && /esc\(story\.chip\)/.test(src) && /esc\(story\.cmd\)/.test(src));
ok('the three classes the page uses are now styled', /\.dot\.rem\{/.test(src) && /\.chip\.live\{/.test(src) && /\.chip\.warn\{/.test(src));

console.log(f ? `\n${f} of ${n} FAILED` : `\nall ${n} passed`);
process.exit(f?1:0);
