#!/usr/bin/env python3
"""
patch_controller_html_046.py - Assist tab: a paperclip, and a real reason
when there is no answer.

Requires 044 (thread + checklist) on the page and patch_controller_046.py on
the Worker. Replaces the whole Assist block between two unique anchors, the
same way 044 did - and only if that block is still exactly what 044 wrote.
If it has been edited since, this stops and writes nothing.

  python3 patch_controller_html_046.py controller.html

PAPERCLIP
  Click it, drag files onto the box, or paste (a screenshot straight from the
  clipboard works). Each file becomes a chip you can remove before asking.

    photo / screenshot   sent as a picture. Anything over 2000 px or 1.2 MB is
                         scaled down in the browser first.
    video / screen rec   Claude takes no video and no sound. The browser
                         steps through the recording and takes still frames -
                         one every ~3 seconds, 16 at most - and sends those,
                         each stamped with its time. The chip says how many
                         and says "no sound".
    PDF                  sent whole, up to 6 MB.
    log / code / text    sent as text, first 100,000 characters.
    Word, Excel, zip, audio and other binaries cannot be read. The chip says
    so and says what to do instead. Nothing is sent for them.

  Limits per question: 24 pictures/files, 9 MB in total. The Worker enforces
  the same numbers again.

  Files stay attached after you ask, so a follow-up can still see them. A
  line under the chips says so. "New conversation" clears them. They live in
  memory only: a page refresh drops them (the thread keeps their names).

NO ANSWER
  When the Worker reports an empty reply it now says why, and the page shows
  that reason with an "Ask again" button instead of filing "No answer
  returned." into the thread as if it were an answer. Same button on a
  network or API error. A counter shows how long it has been thinking.
"""
import sys, os, hashlib

# sha256 of the Assist block exactly as patch_controller_html_044.py wrote it.
EXPECT_044 = '644edafeab17a6ca225651afed4a017f0cec7c68aa71a4a4be0b9950a9a658b4'

CSS_ANCHOR = '''.empty b{color:var(--muted);font-weight:500;display:block;margin-bottom:4px}
'''
CSS = '''
/* assist: attachments */
#asktray{display:flex;flex-wrap:wrap;gap:6px}
#asktray:not(:empty){margin-bottom:8px}
.att{
  display:inline-flex;align-items:center;gap:8px;max-width:100%;
  padding:5px 6px 5px 5px;border-radius:8px;background:var(--panel);border:1px solid var(--line);
}
.att img,.att .atti{width:30px;height:30px;border-radius:5px;flex:none;object-fit:cover;background:var(--panel-2)}
.att .atti{display:flex;align-items:center;justify-content:center;font:500 9px/1 var(--mono);color:var(--muted);font-style:normal;text-transform:uppercase}
.att .attn{display:flex;flex-direction:column;min-width:0;line-height:1.3}
.att .attn b{font-size:12px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:240px}
.att .attn em{font-size:11px;font-style:normal;color:var(--faint)}
.att button{flex:none;width:20px;height:20px;border-radius:50%;color:var(--muted);font-size:14px;line-height:1}
.att button:hover{background:var(--panel-2);color:var(--ink)}
.att.bad{border-color:rgba(229,72,77,.45);align-items:flex-start}
.att.bad .atti{color:var(--crit)}
.att.bad .attn em{color:var(--crit);white-space:normal;max-width:60ch}
.attkeep{flex-basis:100%;font-size:11px;color:var(--faint)}
#askdrop.over textarea{border-color:var(--signal)!important}
#askclip{display:inline-flex;align-items:center;gap:6px}
'''

NEW = r'''/* ----------------------------------------------------------------- assist */
// First responder, not a watchdog. It runs only when asked, has no tools, and
// reads a snapshot the Worker assembles server-side - so it can explain and
// recommend, and it cannot touch anything.
//
// The thread and the checklist live in localStorage rather than in `state`,
// so a refresh does not wipe what you were in the middle of. Both are
// explicitly clearable: this is working memory, not a record.
const ASK_THREAD_KEY = 'gsctl.thread';
const ASK_TASKS_KEY  = 'gsctl.tasks';

function askLoad(k, fallback){ try { return JSON.parse(localStorage.getItem(k)) || fallback; } catch(e){ return fallback; } }
function askSave(k, v){ try { localStorage.setItem(k, JSON.stringify(v)); } catch(e){} }

// Stable id derived from the text, so ticking a task survives both a refresh
// and the agent repeating the same step in a later answer.
function taskId(t){ let h = 0; for (let i = 0; i < t.length; i++) h = ((h << 5) - h + t.charCodeAt(i)) | 0; return 't' + Math.abs(h).toString(36); }

// The agent appends [[GSTASKS:[...]]] - the same marker convention the Inbox
// already uses for [[GSOFFER:]] and [[GSPO:]]. Strip it from the prose so the
// reader never sees the plumbing.
function askSplitTasks(text){
  const m = String(text || '').match(/\[\[GSTASKS:(\[[\s\S]*?\])\]\]/);
  if (!m) return { prose: String(text || ''), tasks: [] };
  let tasks = [];
  try { const a = JSON.parse(m[1]); if (Array.isArray(a)) tasks = a.map(x => String(x).trim().slice(0, 300)).filter(Boolean); } catch(e){}
  return { prose: String(text || '').replace(m[0], '').trim(), tasks };
}

/* ---- attachments (046) ---- */
// Claude reads pictures, PDFs and text. It takes no video and no audio, so a
// recording is stepped through here and sent as still frames. These numbers
// mirror the Worker's (GS_CTL_ATT_*); the Worker enforces them again.
const ASK_MAX_PARTS  = 24;          // pictures/files on one question; a video uses one per frame
const ASK_TOTAL_B64  = 12000000;    // ~9 MB for the whole question
const ASK_IMG_B64    = 6600000;     // ~4.9 MB for one picture
const ASK_PDF_B64    = 8000000;     // ~6 MB for one PDF
const ASK_TEXT_CHARS = 100000;
const ASK_IMG_EDGE   = 2000;        // longest side of a picture as sent
const ASK_PASS_BYTES = 1200000;     // a picture this small and within the edge goes untouched
const ASK_FRAME_EDGE = 1280;
const ASK_FRAMES_MAX = 16;
const ASK_FRAME_GAP  = 3;           // seconds between frames, until FRAMES_MAX spreads them wider

// In memory only. A picture is megabytes; localStorage is not the place.
const askTray = [];
let askSeq = 0;

const askExt   = n => { const m = /\.([a-z0-9]+)$/i.exec(String(n || '')); return m ? m[1].toLowerCase() : ''; };
const askClock = s => { s = Math.max(0, Math.round(s)); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); };
const askMB    = b64 => { const b = b64 * 0.75; return b < 104858 ? Math.max(1, Math.round(b / 1024)) + ' KB' : (b / 1048576).toFixed(1) + ' MB'; };

const ASK_TEXT_EXT  = ['txt','log','md','csv','tsv','json','jsonl','js','mjs','cjs','jsx','ts','tsx','py','sh','bash','zsh','sql','html','htm','css','scss','xml','svg','yml','yaml','toml','ini','conf','cfg','env','service','timer','plist','diff','patch','rb','go','rs','php','java','c','h','cpp','swift','kt'];
const ASK_IMAGE_EXT = ['jpg','jpeg','png','gif','webp','heic','heif','bmp','tif','tiff','avif'];
const ASK_VIDEO_EXT = ['mov','mp4','m4v','webm','mkv','avi'];
const ASK_AUDIO_EXT = ['mp3','wav','m4a','aac','ogg','flac','aiff'];
const ASK_OFFICE    = { doc:'Word', docx:'Word', xls:'Excel', xlsx:'Excel', ppt:'PowerPoint', pptx:'PowerPoint', pages:'Pages', numbers:'Numbers', key:'Keynote' };
const ASK_ARCHIVE   = ['zip','gz','tgz','tar','7z','rar','dmg','pkg','iso'];
const ASK_BINARY    = ['exe','bin','app','sqlite','db','woff','woff2','ttf','otf','psd','ai','sketch','fig','wasm','class','o','so','dylib'];

// The extension is checked before the browser's type on purpose: a .ts file
// is reported as video/mp2t, and it is TypeScript.
function askKindOf(name, type){
  const e = askExt(name), t = String(type || '').toLowerCase();
  if (ASK_TEXT_EXT.includes(e)) return 'text';
  if (e === 'pdf' || t === 'application/pdf') return 'pdf';
  if (ASK_IMAGE_EXT.includes(e)) return 'image';
  if (ASK_VIDEO_EXT.includes(e)) return 'video';
  if (ASK_AUDIO_EXT.includes(e)) return 'audio';
  if (ASK_OFFICE[e]) return 'office';
  if (ASK_ARCHIVE.includes(e)) return 'archive';
  if (ASK_BINARY.includes(e)) return 'binary';
  if (t === 'image/svg+xml') return 'text';
  if (t.startsWith('image/')) return 'image';
  if (t.startsWith('video/')) return 'video';
  if (t.startsWith('audio/')) return 'audio';
  return 'text';            // unknown: try it as text; askReadText refuses anything that is not
}

// Why a kind cannot be sent, and what to do instead. '' means it can.
function askWhyNot(kind, name){
  const e = askExt(name);
  if (kind === 'audio')   return 'It cannot hear sound. Pictures, PDFs and text only - type out what was said.';
  if (kind === 'office')  return 'It cannot open ' + ASK_OFFICE[e] + ' files. Export it as a PDF and attach that, or paste the text.';
  if (kind === 'archive') return 'It cannot open a .' + e + ' archive. Attach the files that are inside it.';
  if (kind === 'binary')  return 'It cannot read a .' + e + ' file. Attach a screenshot of what you are looking at instead.';
  return '';
}

function askB64(blob){
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(String(r.result).split(',')[1] || '');
    r.onerror = () => rej(new Error('The browser could not read that file.'));
    r.readAsDataURL(blob);
  });
}

// Draws a picture or the current video frame, scaled so its longest side is
// at most `edge`, onto white (a transparent PNG would otherwise go black as
// a JPEG). Returns a data: URL.
function askDraw(src, w, h, edge, q){
  const s = Math.min(1, edge / Math.max(w, h));
  const c = document.createElement('canvas');
  c.width = Math.max(1, Math.round(w * s)); c.height = Math.max(1, Math.round(h * s));
  const x = c.getContext('2d');
  x.fillStyle = '#fff'; x.fillRect(0, 0, c.width, c.height);
  x.drawImage(src, 0, 0, c.width, c.height);
  return c.toDataURL('image/jpeg', q);
}

async function askReadImage(file){
  const url = URL.createObjectURL(file);
  try{
    const heic = ['heic','heif'].includes(askExt(file.name));
    const img = await new Promise((res, rej) => {
      const i = new Image();
      i.onload = () => res(i);
      i.onerror = () => rej(new Error(heic
        ? 'This browser cannot open HEIC photos (Safari can, Chrome cannot). Open it in Preview and export as JPEG, or screenshot it.'
        : 'This browser could not open that picture. Screenshot it and attach the screenshot.'));
      i.src = url;
    });
    const w = img.naturalWidth, h = img.naturalHeight;
    if (!w || !h) throw new Error('That picture has no size - it may be damaged.');
    const type = String(file.type || '').toLowerCase();
    const fits = Math.max(w, h) <= ASK_IMG_EDGE;
    const thumb = askDraw(img, w, h, 72, 0.6);
    // Small enough already: send the original bytes, untouched.
    if (fits && file.size <= ASK_PASS_BYTES && ['image/png','image/jpeg','image/webp','image/gif'].includes(type)){
      return { parts: [{ kind: 'image', media_type: type, data: await askB64(file) }], thumb, meta: w + '×' + h };
    }
    const s = Math.min(1, ASK_IMG_EDGE / Math.max(w, h));
    const data = askDraw(img, w, h, ASK_IMG_EDGE, 0.9).split(',')[1] || '';
    return { parts: [{ kind: 'image', media_type: 'image/jpeg', data }], thumb,
             meta: w + '×' + h + (s < 1 ? ', sent at ' + Math.round(w * s) + '×' + Math.round(h * s) : '') };
  } finally { URL.revokeObjectURL(url); }
}

// Resolves on the first of `events`, rejects on the element's error event or
// after `ms`. Every listener is removed either way.
function askOnce(el, events, ms, why){
  return new Promise((res, rej) => {
    let t;
    const done = (fn, v) => { clearTimeout(t); events.forEach(e => el.removeEventListener(e, onOk)); el.removeEventListener('error', onErr); fn(v); };
    const onOk  = () => done(res);
    const onErr = () => done(rej, new Error(why));
    events.forEach(e => el.addEventListener(e, onOk));
    el.addEventListener('error', onErr);
    t = setTimeout(() => done(rej, new Error(why)), ms);
  });
}

// A recording becomes still frames. No audio is read - there is nowhere to
// send it. `room` is how many pictures this question still has space for.
async function askReadVideo(file, room, tick){
  const cant = 'This browser cannot play that recording, so no frames could be taken from it. Open the controller in Safari and try again (Safari plays every recording a Mac or iPhone makes), or attach screenshots of the moments that matter.';
  const url = URL.createObjectURL(file);
  const v = document.createElement('video');
  v.muted = true; v.playsInline = true; v.preload = 'auto';
  try{
    v.src = url;
    await askOnce(v, ['loadedmetadata'], 20000, cant);
    if (v.readyState < 2) await askOnce(v, ['loadeddata'], 20000, cant);
    if (!v.videoWidth || !v.videoHeight) throw new Error('That file has sound but no picture, and it cannot hear sound.');

    let dur = v.duration;
    if (!isFinite(dur) || !(dur > 0)){
      // A recording made in the browser carries no length. Seeking far past
      // the end makes the browser read to the end and work it out.
      v.currentTime = 1e7;
      await askOnce(v, ['seeked', 'durationchange'], 20000, cant).catch(() => {});
      await new Promise(r => setTimeout(r, 60));
      dur = isFinite(v.duration) && v.duration > 0 ? v.duration
          : (v.seekable && v.seekable.length ? v.seekable.end(v.seekable.length - 1) : v.currentTime);
    }
    if (!isFinite(dur) || !(dur > 0)) throw new Error(cant);

    let n = dur < ASK_FRAME_GAP * 1.5 ? Math.max(1, Math.ceil(dur / ASK_FRAME_GAP))
                                      : Math.min(ASK_FRAMES_MAX, Math.max(2, Math.round(dur / ASK_FRAME_GAP)));
    n = Math.max(1, Math.min(n, room));
    const parts = []; let thumb = '';
    for (let i = 0; i < n; i++){
      const t = Math.min(Math.max(0, dur - 0.05), (i + 0.5) * dur / n);
      v.currentTime = t;
      await askOnce(v, ['seeked'], 20000, 'The recording stopped responding at ' + askClock(t) + '. Attach screenshots instead.');
      await new Promise(r => setTimeout(r, 40));      // let the frame land before reading it
      parts.push({ kind: 'image', media_type: 'image/jpeg',
                   data: askDraw(v, v.videoWidth, v.videoHeight, ASK_FRAME_EDGE, 0.8).split(',')[1] || '',
                   label: 'frame ' + (i + 1) + ' of ' + n + ', at ' + askClock(t) + ' of ' + askClock(dur) });
      if (!thumb) thumb = askDraw(v, v.videoWidth, v.videoHeight, 72, 0.6);
      if (tick) tick(i + 1, n);
    }
    const gap = dur / n;
    return { parts, thumb,
             meta: n === 1 ? '1 frame of ' + askClock(dur) + ' · no sound'
                           : n + ' frames, one every ' + (gap < 10 ? gap.toFixed(1).replace(/\.0$/, '') : Math.round(gap)) + 's of ' + askClock(dur) + ' · no sound' };
  } finally {
    try { v.removeAttribute('src'); v.load(); } catch(e){}
    URL.revokeObjectURL(url);
  }
}

async function askReadPdf(file){
  const data = await askB64(file);
  // A real PDF says %PDF within its first kilobyte.
  let head = ''; try { head = atob(data.slice(0, 1400)); } catch(e){}
  if (!head.includes('%PDF')) throw new Error('That is named .pdf but is not a PDF inside.');
  return { parts: [{ kind: 'pdf', media_type: 'application/pdf', data }], thumb: '', meta: 'PDF · ' + askMB(data.length) };
}

async function askReadText(file){
  if (file.size > 5 * 1048576) throw new Error('That file is ' + (file.size / 1048576).toFixed(1) + ' MB, too large to send as text. Attach the part that matters (for a log: the last few hundred lines).');
  const t = await file.text();
  if (!t.trim()) throw new Error('That file is empty.');
  // NUL and the "could not decode" mark only turn up in files that are not
  // text. ESC is left out on purpose: coloured logs are full of it.
  const head = t.slice(0, 4000);
  const bad = (head.match(/[\u0000-\u0008�]/g) || []).length;
  if (bad / head.length > 0.01) throw new Error('That does not read as text' + (askExt(file.name) ? ' (.' + askExt(file.name) + ')' : '') + '. Attach a screenshot of it, or export it as a PDF.');
  const keep = ASK_TEXT_CHARS - 200;
  const cut = t.length > keep;
  return { parts: [{ kind: 'text', text: cut ? t.slice(0, keep) + '\n[cut here: the file is ' + t.length + ' characters and only the first ' + keep + ' were sent]' : t }], thumb: '',
           meta: cut ? 'first ' + keep.toLocaleString('en-US') + ' of ' + t.length.toLocaleString('en-US') + ' characters' : t.length.toLocaleString('en-US') + ' characters' };
}

const askPartsUsed = skip => askTray.reduce((n, a) => n + (a === skip || a.error ? 0 : a.parts.length), 0);
const askBytesUsed = skip => askTray.reduce((n, a) => n + (a === skip || a.error ? 0 : (a.size || 0)), 0);

// One at a time, in the order given. A file that cannot be sent stays in the
// tray as a red chip saying why, so nothing is ever dropped silently.
async function askAddFiles(files){
  for (const file of Array.from(files || [])){
    const it = { id: 'a' + (++askSeq), name: file.name || 'pasted image', kind: askKindOf(file.name, file.type),
                 busy: true, parts: [], size: 0, meta: 'reading…', thumb: '', error: '', sent: false };
    askTray.push(it); askTrayRender();
    try{
      const no = askWhyNot(it.kind, it.name);
      if (no) throw new Error(no);
      const room = ASK_MAX_PARTS - askPartsUsed(it);
      if (room < 1) throw new Error('One question holds ' + ASK_MAX_PARTS + ' pictures or files and it is full. Remove something first.');
      const r = it.kind === 'image' ? await askReadImage(file)
              : it.kind === 'video' ? await askReadVideo(file, room, (i, n) => { it.meta = 'taking frame ' + i + ' of ' + n + '…'; askTrayRender(); })
              : it.kind === 'pdf'   ? await askReadPdf(file)
              :                       await askReadText(file);
      const size = r.parts.reduce((s, p) => s + (p.data ? p.data.length : (p.text ? p.text.length : 0)), 0);
      if (it.kind === 'pdf' && size > ASK_PDF_B64) throw new Error('That PDF is ' + askMB(size) + '; the limit is ' + askMB(ASK_PDF_B64) + '. Attach screenshots of the pages that matter.');
      if (r.parts.some(p => p.kind === 'image' && p.data.length > ASK_IMG_B64)) throw new Error('That picture is still over ' + askMB(ASK_IMG_B64) + ' after scaling. Screenshot the part that matters.');
      if (askBytesUsed(it) + size > ASK_TOTAL_B64) throw new Error('That would take this question over ' + askMB(ASK_TOTAL_B64) + ' in total. Remove something first.');
      Object.assign(it, r, { size, busy: false });
    }catch(e){
      Object.assign(it, { error: (e && e.message) || String(e), parts: [], size: 0, meta: '', busy: false });
    }
    askTrayRender();
  }
}

function askTrayRender(){
  const el = $('#asktray'); if (!el) return;
  el.innerHTML = askTray.map(a => `
    <span class="att${a.error ? ' bad' : ''}" data-kind="${esc(a.kind)}">
      ${a.thumb ? `<img src="${a.thumb}" alt="">` : `<i class="atti">${esc(a.error ? '!' : (a.kind === 'pdf' ? 'pdf' : (askExt(a.name) || 'txt')).slice(0, 4))}</i>`}
      <span class="attn"><b title="${esc(a.name)}">${esc(a.name)}</b><em>${esc(a.error || a.meta || '')}</em></span>
      <button data-att="${esc(a.id)}" title="Remove" aria-label="Remove ${esc(a.name)}">×</button>
    </span>`).join('')
    + (askTray.some(a => a.sent && !a.error) ? `<div class="attkeep">Still attached, so a follow-up can see ${askTray.filter(a => a.sent && !a.error).length === 1 ? 'it' : 'them'}. Remove what you no longer need.</div>` : '');
}

// What a file is called in the thread, once the bytes themselves are gone.
const askChipName = a => a.name + (a.kind === 'video' ? ' (' + a.parts.length + (a.parts.length === 1 ? ' frame' : ' frames') + ')' : '');

const ASK_CLIP_SVG = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>';

function askUserHtml(m){
  const files = Array.isArray(m.files) ? m.files : [];
  return `<div style="margin:0 0 10px;padding:8px 12px;border-left:2px solid var(--line,#2a2a30)">
         <div style="font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin-bottom:3px">You</div>
         ${m.content ? `<div style="font-size:13px;line-height:1.5;white-space:pre-wrap">${esc(m.content)}</div>` : ''}
         ${files.length ? `<div style="display:flex;flex-wrap:wrap;gap:5px;margin-top:${m.content ? 6 : 0}px">${files.map(n => `<span class="chip">${esc(n)}</span>`).join('')}</div>` : ''}
       </div>`;
}

function renderAssist(v){
  const thread = askLoad(ASK_THREAD_KEY, []);
  const tasks  = askLoad(ASK_TASKS_KEY, []);
  const open   = tasks.filter(t => !t.done).length;

  const tasksHtml = tasks.length ? `
    <div style="border:1px solid var(--line,#2a2a30);border-radius:10px;padding:12px 14px;margin-bottom:16px">
      <div class="railhead" style="padding:0 0 8px"><span>Steps</span><span>${open} open · ${tasks.length - open} done</span></div>
      ${tasks.map(t => `
        <label style="display:flex;gap:9px;align-items:flex-start;padding:4px 0;cursor:pointer;font-size:13px;line-height:1.45${t.done ? ';opacity:.45' : ''}">
          <input type="checkbox" data-task="${esc(t.id)}" ${t.done ? 'checked' : ''} style="margin-top:3px;flex:none">
          <span style="${t.done ? 'text-decoration:line-through' : ''}">${esc(t.text)}</span>
        </label>`).join('')}
      <div style="display:flex;gap:8px;margin-top:10px">
        <button class="btn quiet" id="taskclear" style="padding:2px 8px;font-size:12px">Clear done</button>
        <button class="btn quiet" id="taskall" style="padding:2px 8px;font-size:12px">Clear all</button>
      </div>
    </div>` : '';

  const threadHtml = thread.length ? thread.map(m => m.role === 'user'
    ? askUserHtml(m)
    : `<div style="margin:0 0 18px">
         <div style="font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin-bottom:4px">Assist</div>
         <pre style="white-space:pre-wrap;line-height:1.55;margin:0;font-size:13px">${esc(m.content)}</pre>
       </div>`).join('') : `
    <div class="empty" style="padding:0 0 14px">
      <b>Ask about the current state</b>
      It reads the feed, the hosts and the open alerts, then tells you what is wrong, what to run, and what would stop it happening again. It cannot change anything. Use the paperclip to show it a screenshot, a photo, a screen recording, a PDF or a log.
    </div>`;

  v.innerHTML = tasksHtml + `<div id="askthread">${threadHtml}</div>
    <div class="field" id="askdrop" style="margin-top:4px">
      <div id="asktray"></div>
      <textarea id="askq" rows="3" placeholder="${thread.length ? 'Follow up - it remembers this conversation…' : 'e.g. the feed emailed me a failure overnight, what happened?'}"
        style="width:100%;background:var(--bg,#0b0b0d);color:inherit;border:1px solid var(--line,#2a2a30);border-radius:8px;padding:10px;font:inherit;resize:vertical"></textarea>
    </div>
    <div style="display:flex;gap:8px;margin:8px 0 16px;flex-wrap:wrap">
      <button class="btn" id="askclip" title="Attach a file, photo, video or screen recording. You can also drag files onto the box, or paste a screenshot." aria-label="Attach files">${ASK_CLIP_SVG}<span>Attach</span></button>
      <input type="file" id="askfile" multiple hidden>
      <button class="btn go" id="askgo">Ask</button>
      <button class="btn" id="askscan">Anything wrong right now?</button>
      ${thread.length ? `<button class="btn quiet" id="askclear">New conversation</button>` : ''}
      <span id="askstat" style="align-self:center;color:var(--muted);font-size:12px"></span>
    </div>`;

  askTrayRender();
  const stat = $('#askstat');
  const lock = on => { ['#askgo', '#askscan'].forEach(s => { const b = $(s); if (b) b.disabled = on; }); };

  // again = true resends the question that is already the last thing in the
  // thread, after an empty reply or an error. It must not be filed twice.
  const run = async (question, again) => {
    const busy = askTray.find(a => a.busy);
    if (busy){ stat.textContent = 'still reading ' + busy.name + '…'; return; }
    const ready = askTray.filter(a => !a.error && a.parts.length);
    const fresh = ready.filter(a => !a.sent);
    const parts = ready.reduce((n, a) => n + a.parts.length, 0);

    lock(true);
    const fail = $('#askfail'); if (fail) fail.remove();
    const t = askLoad(ASK_THREAD_KEY, []);
    if (!again && (question || fresh.length)){
      const msg = { role: 'user', content: question, ...(fresh.length ? { files: fresh.map(askChipName) } : {}) };
      t.push(msg); askSave(ASK_THREAD_KEY, t);
      // Named in the thread from here on, so a later question does not list
      // them as new a second time. They are still sent with every question.
      fresh.forEach(a => { a.sent = true; });
      // Show it now rather than when the answer lands: with attachments the
      // wait is long enough to wonder whether the click registered.
      const th = $('#askthread');
      if (th){ if (t.length === 1) th.innerHTML = ''; th.insertAdjacentHTML('beforeend', askUserHtml(msg)); }
      $('#askq').value = '';
    }

    const t0 = Date.now();
    const say = () => { const s = $('#askstat'); if (s) s.textContent = 'thinking… ' + Math.round((Date.now() - t0) / 1000) + 's' + (parts ? ' · with ' + parts + (parts === 1 ? ' attachment' : ' attachments') : ''); };
    say(); const timer = setInterval(say, 1000);

    // Shown in place of an answer. Nothing is filed in the thread, so a
    // non-answer never becomes part of the conversation the model re-reads.
    const noAnswer = (head, body) => {
      const th = $('#askthread'); if (!th) return;
      th.insertAdjacentHTML('beforeend', `<div class="empty" id="askfail" style="padding:0 0 14px;max-width:70ch"><b>${esc(head)}</b>${esc(body)}<div style="margin-top:8px"><button class="btn" id="askagain">Ask again</button></div></div>`);
      $('#askagain').onclick = () => run(question, true);
      const s = $('#askstat'); if (s) s.textContent = '';
      lock(false);
    };

    try{
      const d = await api('ask', { method:'POST', body: JSON.stringify({
        question,
        // Trimmed before sending as well as in the Worker: no reason to put
        // a long thread on the wire just to have it truncated at the far end.
        history: t.slice(-16),
        focus: state.askFocus ? state.askFocus.row : null,
        revision_id: state.askFocus ? state.askFocus.revision_id : null,
        path: state.askFocus ? state.askFocus.path : null,
        ...(ready.length ? { attachments: ready.flatMap(a => a.parts.map(p => ({ name: a.name, kind: p.kind, media_type: p.media_type, data: p.data, text: p.text, label: p.label }))) } : {})
      }) });
      clearInterval(timer);

      // The Worker says `empty` when Claude wrote nothing. An older Worker
      // says the literal words instead; treat both the same.
      if (d.empty || !d.answer || d.answer === 'No answer returned.'){
        noAnswer('No answer this time', d.empty && d.answer ? d.answer : 'The model replied with no text. Press Ask again. If it keeps happening, the Worker needs patch 046, which also reports why.');
        return;
      }

      for (let i = askTray.length - 1; i >= 0; i--) if (askTray[i].error) askTray.splice(i, 1);

      const split = askSplitTasks(d.answer || '');
      t.push({ role: 'assistant', content: split.prose });
      askSave(ASK_THREAD_KEY, t);

      if (split.tasks.length){
        const cur = askLoad(ASK_TASKS_KEY, []);
        // Dedupe by id: the agent repeating a step it already gave you must
        // not reset a box you have already ticked.
        split.tasks.forEach(txt => {
          const id = taskId(txt);
          if (!cur.some(x => x.id === id)) cur.push({ id, text: txt, done: false });
        });
        askSave(ASK_TASKS_KEY, cur);
      }
      renderAssist(v);
      const u = d.usage || {};
      $('#askstat').textContent = (d.model || '') + (u.input_tokens ? ` · ${u.input_tokens} in / ${u.output_tokens} out` : '')
        + (d.tries > 1 ? ' · answered on the second try' : '');
      // The Worker re-checks every attachment. Anything it dropped is named,
      // so an answer is never read as covering a file it did not see.
      const skipped = d.attachments && Array.isArray(d.attachments.skipped) ? d.attachments.skipped : [];
      if (skipped.length){
        $('#askthread').insertAdjacentHTML('beforeend', `<div class="empty" id="askskipped" style="padding:0 0 14px;max-width:70ch"><b>${skipped.length === 1 ? 'One attachment was not sent' : skipped.length + ' attachments were not sent'}</b>${skipped.map(s => esc(s.name) + ': ' + esc(s.why)).join('<br>')}</div>`);
      } else if (ready.length && !d.attachments){
        $('#askthread').insertAdjacentHTML('beforeend', `<div class="empty" id="askskipped" style="padding:0 0 14px;max-width:70ch"><b>The attachments were not read</b>The Worker answering does not have patch 046 yet, so it ignored them. The answer above is from the question and the live state only.</div>`);
      }
    }catch(e){
      clearInterval(timer);
      noAnswer('Could not ask', e.message);
    }
  };

  $('#askgo').onclick   = () => { const q = $('#askq').value.trim(); if (q || askTray.some(a => !a.error && !a.sent && a.parts.length) || askTray.some(a => a.busy)) run(q); };
  // Empty question on purpose: the route falls back to "look at the state and
  // tell me if anything is wrong", which is the common case at 3am.
  $('#askscan').onclick = () => run('');
  $('#askq').onkeydown  = e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) $('#askgo').click(); };

  // Three ways in, one function: the paperclip, a drop, a paste.
  $('#askclip').onclick = () => $('#askfile').click();
  $('#askfile').onchange = e => { const f = Array.from(e.target.files || []); e.target.value = ''; askAddFiles(f); };
  $('#askq').onpaste = e => {
    const f = Array.from((e.clipboardData && e.clipboardData.files) || []);
    if (f.length){ e.preventDefault(); askAddFiles(f); }     // plain text pastes as text, as before
  };
  const drop = $('#askdrop');
  drop.ondragover  = e => { if (e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files')){ e.preventDefault(); drop.classList.add('over'); } };
  drop.ondragleave = () => drop.classList.remove('over');
  drop.ondrop      = e => { drop.classList.remove('over'); const f = Array.from((e.dataTransfer && e.dataTransfer.files) || []); if (f.length){ e.preventDefault(); askAddFiles(f); } };
  $('#asktray').onclick = e => {
    const b = e.target.closest('button[data-att]'); if (!b) return;
    const i = askTray.findIndex(a => a.id === b.dataset.att);
    if (i >= 0 && !askTray[i].busy){ askTray.splice(i, 1); askTrayRender(); }
  };

  const clr = $('#askclear');
  if (clr) clr.onclick = () => { askSave(ASK_THREAD_KEY, []); askTray.length = 0; renderAssist(v); };

  v.querySelectorAll('input[data-task]').forEach(cb => cb.onchange = () => {
    const cur = askLoad(ASK_TASKS_KEY, []);
    const row = cur.find(x => x.id === cb.dataset.task);
    if (row) { row.done = cb.checked; askSave(ASK_TASKS_KEY, cur); }
    renderAssist(v);
  });
  const tc = $('#taskclear');
  if (tc) tc.onclick = () => { askSave(ASK_TASKS_KEY, askLoad(ASK_TASKS_KEY, []).filter(x => !x.done)); renderAssist(v); };
  const ta = $('#taskall');
  if (ta) ta.onclick = () => { askSave(ASK_TASKS_KEY, []); renderAssist(v); };

  // Arrived from an Ask AI button: show what is being judged and run it
  // straight away.
  if (state.askFocus && !state.askFocusRan){
    state.askFocusRan = true;
    run('');
  }
}

'''

START = '/* ----------------------------------------------------------------- assist */'
END   = 'function renderDead(v){'


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'controller.html'
    if not os.path.exists(path):
        sys.exit(f"FAIL: {path} not found")
    src = open(path, encoding='utf-8').read()

    if 'function askAddFiles(' in src:
        print("already patched - nothing to do")
        return
    if 'ASK_THREAD_KEY' not in src:
        sys.exit("FAIL: 044 is not applied to this controller.html. Run patch_controller_html_044.py first. Nothing written.")
    for name, a in (("start", START), ("end", END), ("css", CSS_ANCHOR)):
        n = src.count(a)
        if n != 1:
            sys.exit(f"FAIL: {name} anchor found {n} times, expected exactly 1. Nothing written.")

    i = src.index(START); j = src.index(END)
    if j < i:
        sys.exit("FAIL: anchors out of order. Nothing written.")
    got = hashlib.sha256(src[i:j].encode('utf-8')).hexdigest()
    if got != EXPECT_044:
        sys.exit("FAIL: the Assist block in this file is not the one patch 044 wrote - it has been edited since.\n"
                 "      Replacing it would throw those edits away, so nothing was written.\n"
                 f"      (found {got[:12]}, expected {EXPECT_044[:12]})")

    out = src[:i] + NEW + src[j:]
    out = out.replace(CSS_ANCHOR, CSS_ANCHOR + CSS, 1)
    open(path + '.bak', 'w', encoding='utf-8').write(src)
    open(path, 'w', encoding='utf-8').write(out)
    print(f"patched {path} ({len(out)-len(src):+d} bytes). backup at {path}.bak")


if __name__ == '__main__':
    main()
