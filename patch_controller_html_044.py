#!/usr/bin/env python3
"""
patch_controller_html_044.py - conversation thread + checkable task list in
the Assist tab.

Requires 038. Replaces the whole renderAssist block between two unique
anchors rather than patching inside it, because the change is structural.

  python3 patch_controller_html_044.py controller.html
"""
import sys, os

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
    ? `<div style="margin:0 0 10px;padding:8px 12px;border-left:2px solid var(--line,#2a2a30)">
         <div style="font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin-bottom:3px">You</div>
         <div style="font-size:13px;line-height:1.5">${esc(m.content)}</div>
       </div>`
    : `<div style="margin:0 0 18px">
         <div style="font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin-bottom:4px">Assist</div>
         <pre style="white-space:pre-wrap;line-height:1.55;margin:0;font-size:13px">${esc(m.content)}</pre>
       </div>`).join('') : `
    <div class="empty" style="padding:0 0 14px">
      <b>Ask about the current state</b>
      It reads the feed, the hosts and the open alerts, then tells you what is wrong, what to run, and what would stop it happening again. It cannot change anything.
    </div>`;

  v.innerHTML = tasksHtml + `<div id="askthread">${threadHtml}</div>
    <div class="field" style="margin-top:4px">
      <textarea id="askq" rows="3" placeholder="${thread.length ? 'Follow up - it remembers this conversation…' : 'e.g. the feed emailed me a failure overnight, what happened?'}"
        style="width:100%;background:var(--bg,#0b0b0d);color:inherit;border:1px solid var(--line,#2a2a30);border-radius:8px;padding:10px;font:inherit;resize:vertical"></textarea>
    </div>
    <div style="display:flex;gap:8px;margin:8px 0 16px;flex-wrap:wrap">
      <button class="btn go" id="askgo">Ask</button>
      <button class="btn" id="askscan">Anything wrong right now?</button>
      ${thread.length ? `<button class="btn quiet" id="askclear">New conversation</button>` : ''}
      <span id="askstat" style="align-self:center;color:var(--muted);font-size:12px"></span>
    </div>`;

  const stat = $('#askstat');

  const run = async (question) => {
    $('#askgo').disabled = true; $('#askscan').disabled = true;
    stat.textContent = 'thinking…';
    const t = askLoad(ASK_THREAD_KEY, []);
    if (question) { t.push({ role: 'user', content: question }); askSave(ASK_THREAD_KEY, t); }
    try{
      const d = await api('ask', { method:'POST', body: JSON.stringify({
        question,
        // Trimmed before sending as well as in the Worker: no reason to put
        // a long thread on the wire just to have it truncated at the far end.
        history: t.slice(-16),
        focus: state.askFocus ? state.askFocus.row : null,
        revision_id: state.askFocus ? state.askFocus.revision_id : null,
        path: state.askFocus ? state.askFocus.path : null
      }) });

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
      $('#askstat').textContent = (d.model || '') + (u.input_tokens ? ` · ${u.input_tokens} in / ${u.output_tokens} out` : '');
    }catch(e){
      $('#askthread').innerHTML += `<div class="empty"><b>Could not ask</b>${esc(e.message)}</div>`;
      stat.textContent = '';
      $('#askgo').disabled = false; $('#askscan').disabled = false;
    }
  };

  $('#askgo').onclick   = () => { const q = $('#askq').value.trim(); if (q) run(q); };
  // Empty question on purpose: the route falls back to "look at the state and
  // tell me if anything is wrong", which is the common case at 3am.
  $('#askscan').onclick = () => run('');
  $('#askq').onkeydown  = e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { const q = $('#askq').value.trim(); if (q) run(q); } };

  const clr = $('#askclear');
  if (clr) clr.onclick = () => { askSave(ASK_THREAD_KEY, []); renderAssist(v); };

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

    if 'ASK_THREAD_KEY' in src:
        print("already patched - nothing to do")
        return
    for name, a in (("start", START), ("end", END)):
        n = src.count(a)
        if n != 1:
            sys.exit(f"FAIL: {name} anchor found {n} times, expected exactly 1. Nothing written.")

    i = src.index(START); j = src.index(END)
    if j < i:
        sys.exit("FAIL: anchors out of order. Nothing written.")

    out = src[:i] + NEW + src[j:]
    open(path + '.bak', 'w', encoding='utf-8').write(src)
    open(path, 'w', encoding='utf-8').write(out)
    print(f"patched {path} ({len(out)-len(src):+d} bytes). backup at {path}.bak")

if __name__ == '__main__':
    main()
