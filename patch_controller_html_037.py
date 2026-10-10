#!/usr/bin/env python3
"""
patch_controller_html_037.py - adds the Assist tab to controller.html.

Requires 036 to be applied first. Unique anchors, assert before write,
idempotent, refuses rather than guesses.

  python3 patch_controller_html_037.py controller.html
"""
import sys, os

RENDERER = r'''
/* ----------------------------------------------------------------- assist */
// First responder, not a watchdog. It runs only when asked, has no tools, and
// reads a snapshot the Worker assembles server-side - so it can explain and
// recommend, and it cannot touch anything.
//
// The answer is rendered as plain text in a <pre>, deliberately: injecting
// model output as HTML into a console that holds platform-wide state is not
// a trade worth making for formatting.
function renderAssist(v){
  v.innerHTML = `
    <div class="empty" style="padding:0 0 14px">
      <b>Ask about the current state</b>
      It reads the feed, the hosts and the open alerts, then tells you what is wrong, what to run, and what would stop it happening again. It cannot change anything.
    </div>
    <div class="field">
      <textarea id="askq" rows="3" placeholder="e.g. the feed emailed me a failure overnight, what happened?"
        style="width:100%;background:var(--bg,#0b0b0d);color:inherit;border:1px solid var(--line,#2a2a30);border-radius:8px;padding:10px;font:inherit;resize:vertical"></textarea>
    </div>
    <div style="display:flex;gap:8px;margin:8px 0 16px">
      <button class="btn go" id="askgo">Ask</button>
      <button class="btn" id="askscan">Anything wrong right now?</button>
      <span id="askstat" style="align-self:center;color:var(--muted);font-size:12px"></span>
    </div>
    <div id="askout"></div>`;

  const out = $('#askout'), stat = $('#askstat');

  const run = async (question) => {
    $('#askgo').disabled = true; $('#askscan').disabled = true;
    stat.textContent = 'thinking…'; out.innerHTML = '';
    try{
      const d = await api('ask', { method:'POST', body: JSON.stringify({ question }) });
      out.innerHTML = `<pre style="white-space:pre-wrap;line-height:1.55;margin:0">${esc(d.answer||'')}</pre>`;
      const u = d.usage || {};
      stat.textContent = (d.model||'') + (u.input_tokens ? ` · ${u.input_tokens} in / ${u.output_tokens} out` : '');
    }catch(e){
      out.innerHTML = `<div class="empty"><b>Could not ask</b>${esc(e.message)}</div>`;
      stat.textContent = '';
    }
    $('#askgo').disabled = false; $('#askscan').disabled = false;
  };

  $('#askgo').onclick   = () => run($('#askq').value.trim());
  // Empty question on purpose: the route falls back to "look at the state and
  // tell me if anything is wrong", which is the common case at 3am.
  $('#askscan').onclick = () => run('');
  $('#askq').onkeydown  = e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) run($('#askq').value.trim()); };
}

'''

EDITS = [
  ("${['changes','feed','infra','traffic','flags','alerts','watchdogs','dead files'].map(t=>",
   "${['changes','feed','infra','assist','traffic','flags','alerts','watchdogs','dead files'].map(t=>"),

  ("  if (state.tab==='infra')     return renderInfra(v);",
   "  if (state.tab==='infra')     return renderInfra(v);\n  if (state.tab==='assist')    return renderAssist(v);"),

  ("function renderDead(v){", RENDERER + "function renderDead(v){"),
]

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'controller.html'
    if not os.path.exists(path):
        sys.exit(f"FAIL: {path} not found")
    src = open(path, encoding='utf-8').read()

    if "function renderAssist(" in src:
        print("already patched - nothing to do")
        return
    if "function renderInfra(" not in src:
        sys.exit("FAIL: 036 is not applied to this file. Run patch_controller_html_036.py first.")

    for i, (old, new) in enumerate(EDITS, 1):
        n = src.count(old)
        if n != 1:
            sys.exit(f"FAIL: edit {i} anchor found {n} times, expected exactly 1. Nothing written.")

    out = src
    for old, new in EDITS:
        out = out.replace(old, new, 1)

    open(path + '.bak', 'w', encoding='utf-8').write(src)
    open(path, 'w', encoding='utf-8').write(out)
    print(f"patched {path} (+{len(out)-len(src)} bytes). backup at {path}.bak")

if __name__ == '__main__':
    main()
