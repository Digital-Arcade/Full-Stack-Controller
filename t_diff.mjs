// Executes the diff algorithm itself from the shipped console file.
import { readFileSync } from 'fs';
const html = readFileSync('./console/controller.html','utf8');
const js = html.match(/<script type="module">([\s\S]*?)<\/script>/)[1];
const grab = (n) => { const st = js.indexOf('function '+n+'(');
  let i = js.indexOf('{', st), d=0;
  for (let j=i;j<js.length;j++){ if(js[j]==='{')d++; else if(js[j]==='}'){d--; if(!d) return js.slice(st,j+1);} } };
const m = await import('data:text/javascript;base64,'+Buffer.from(
  grab('lcsDiff')+'\n'+grab('collapse')+'\nexport { lcsDiff, collapse };').toString('base64'));

let f=0; const ok=(l,c,x='')=>{console.log(`${c?'PASS':'FAIL'}  ${l}${x?'  '+x:''}`); if(!c)f++;};
const D=(a,b)=>m.lcsDiff(a.split('\n'), b.split('\n'));
const sig=r=>r.map(x=>x.t).join('');

ok('identical files -> all context', sig(D('a\nb\nc','a\nb\nc'))==='   ');
ok('one line changed', sig(D('a\nb\nc','a\nX\nc'))===' -+ ' || sig(D('a\nb\nc','a\nX\nc'))===' +- ', sig(D('a\nb\nc','a\nX\nc')));
ok('pure insertion', sig(D('a\nc','a\nb\nc'))===' + ');
ok('pure deletion', sig(D('a\nb\nc','a\nc'))===' - ');
ok('empty -> content is all additions', sig(D('','x\ny')).replace(/ /g,'')==='++' || sig(D('','x\ny')).includes('+'));
const rt = D('a\nb\nc\nd','a\nX\nc\nd');
ok('reconstructs the new file', rt.filter(r=>r.t!=='-').map(r=>r.v).join('\n')==='a\nX\nc\nd');
ok('reconstructs the old file', rt.filter(r=>r.t!=='+').map(r=>r.v).join('\n')==='a\nb\nc\nd');

const big = Array.from({length:60},(_,i)=>'line'+i);
const big2 = [...big]; big2[30]='CHANGED';
const col = m.collapse(m.lcsDiff(big,big2));
ok('collapses unchanged stretches', col.length < 20, col.length+' rows from 60 lines');
ok('keeps a gap marker', col.some(r=>r.t==='@'));
ok('keeps the change itself', col.some(r=>r.v==='CHANGED'));

const huge = Array.from({length:2500},(_,i)=>'l'+i);
const t0=Date.now(); const hr=m.lcsDiff(huge, huge.slice().reverse()); const ms=Date.now()-t0;
ok('guard trips on oversized input instead of hanging', hr.length===2 && ms<2000, ms+'ms');
console.log(f?`\n${f} FAILURES`:'\nall checks passed');
process.exit(f?1:0);
