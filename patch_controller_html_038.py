#!/usr/bin/env python3
"""
patch_controller_html_038.py - an Ask AI button on every alert and watchdog.

Requires 037. Unique anchors, assert before write, idempotent. Nothing
existing is removed; the acknowledge and enable/disable handlers are left
exactly as they were.

  python3 patch_controller_html_038.py controller.html
"""
import sys, os

EDITS = [
  # state slot for the row being asked about
  ("                feed:[], feedRuns:[], hosts:[],",
   "                feed:[], feedRuns:[], hosts:[], askFocus:null,"),

  # ── alerts: button + handler branch ──────────────────────────────────────
  ('        <td><button class="btn quiet" data-ack="${a.id}">Acknowledge</button></td>',
   '        <td><button class="btn quiet" data-askai="${a.id}">Ask AI</button> '
   '<button class="btn quiet" data-ack="${a.id}">Acknowledge</button></td>'),

  ("""  v.onclick = async e => {
    const b = e.target.closest('button[data-ack]'); if(!b) return;""",
   """  v.onclick = async e => {
    // Ask AI first: it only moves the view, so it must not fall through into
    // the acknowledge path and mark something read that nobody has judged.
    const ai = e.target.closest('button[data-askai]');
    if (ai){
      const row = open.find(x=>String(x.id)===ai.dataset.askai);
      if (row) askAbout({ kind:'alert', ...row }, row.revision_id || null, row.detail?.path || null);
      return;
    }
    const b = e.target.closest('button[data-ack]'); if(!b) return;"""),

  # ── watchdogs: button + handler branch ───────────────────────────────────
  ('        <td><button class="btn quiet" data-tog="${w.id}" data-on="${w.enabled}">${w.enabled?\'Disable\':\'Enable\'}</button></td>',
   '        <td><button class="btn quiet" data-askai="${w.id}">Ask AI</button> '
   '<button class="btn quiet" data-tog="${w.id}" data-on="${w.enabled}">${w.enabled?\'Disable\':\'Enable\'}</button></td>'),

  ("""  v.onclick = async e => {
    const b = e.target.closest('button[data-tog]'); if(!b) return;""",
   """  v.onclick = async e => {
    const ai = e.target.closest('button[data-askai]');
    if (ai){
      const w = state.watchdogs.find(x=>String(x.id)===ai.dataset.askai);
      // A watchdog has no revision of its own. Hand it the newest alert this
      // rule raised, if there is one, so the verdict is made against a real
      // file rather than against the pattern string.
      const hit = state.alerts.find(a=>a.watchdog_id===w.id || a.label===w.name);
      if (w) askAbout({ kind:'watchdog', ...w, example_alert: hit || null },
                      hit?.revision_id || null, hit?.detail?.path || null);
      return;
    }
    const b = e.target.closest('button[data-tog]'); if(!b) return;"""),

  # ── send focus with the question ─────────────────────────────────────────
  ("      const d = await api('ask', { method:'POST', body: JSON.stringify({ question }) });",
   "      const d = await api('ask', { method:'POST', body: JSON.stringify({\n"
   "        question,\n"
   "        focus: state.askFocus ? state.askFocus.row : null,\n"
   "        revision_id: state.askFocus ? state.askFocus.revision_id : null,\n"
   "        path: state.askFocus ? state.askFocus.path : null\n"
   "      }) });"),

  # ── auto-run when arriving from an Ask AI button ─────────────────────────
  ("  $('#askq').onkeydown  = e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) run($('#askq').value.trim()); };",
   """  $('#askq').onkeydown  = e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) run($('#askq').value.trim()); };

  // Arrived here from an Ask AI button: show what is being judged and run it
  // straight away. The focus is left in place so a follow-up question in the
  // box stays about the same item, and is cleared when the tab is left.
  if (state.askFocus){
    const f = state.askFocus;
    out.innerHTML = `<div class="empty" style="padding:0 0 12px"><b>Judging this ${esc(f.row?.kind||'item')}</b>`
      + `<span class="mono">${esc(f.row?.label || f.row?.name || '')}${f.path ? ' · '+esc(f.path) : ''}</span></div>`;
    run('');
  }"""),

  # ── the helper, plus clearing focus on any other tab ─────────────────────
  ("function syncTabs(){",
   """// Switches to Assist with a subject attached. It only changes the view -
// nothing is sent until renderAssist runs, and nothing is ever written.
function askAbout(row, revision_id, path){
  state.askFocus = { row, revision_id: revision_id || null, path: path || null };
  state.tab = 'assist';
  renderView(); syncTabs();
}

function syncTabs(){"""),

  ("function renderView(){\n  const v = $('#view'); if(!v) return;",
   """function renderView(){
  const v = $('#view'); if(!v) return;
  // Leaving Assist drops the subject, so a later free-form question is not
  // silently still attached to an alert the operator has moved on from.
  if (state.tab !== 'assist') state.askFocus = null;"""),
]

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'controller.html'
    if not os.path.exists(path):
        sys.exit(f"FAIL: {path} not found")
    src = open(path, encoding='utf-8').read()

    if "function askAbout(" in src:
        print("already patched - nothing to do")
        return
    if "function renderAssist(" not in src:
        sys.exit("FAIL: 037 is not applied to this file. Run patch_controller_html_037.py first.")

    for i, (old, new) in enumerate(EDITS, 1):
        n = src.count(old)
        if n != 1:
            sys.exit(f"FAIL: edit {i} anchor found {n} times, expected exactly 1. "
                     f"Nothing written.\n---\n{old[:220]}\n---")

    out = src
    for old, new in EDITS:
        out = out.replace(old, new, 1)

    open(path + '.bak', 'w', encoding='utf-8').write(src)
    open(path, 'w', encoding='utf-8').write(out)
    print(f"patched {path} (+{len(out)-len(src)} bytes). backup at {path}.bak")

if __name__ == '__main__':
    main()
