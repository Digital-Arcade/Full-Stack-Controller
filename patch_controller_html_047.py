#!/usr/bin/env python3
"""
patch_controller_html_047.py - Assist tab: the answer appears as it is written.

Requires patch_controller_html_046.py on the page. Works with a Worker that
has patch_controller_047.py and with one that does not (it falls back to the
whole-answer JSON it gets from an older Worker).

  python3 patch_controller_html_047.py controller.html

WHY
The page asked, then waited in silence for the whole answer. On a long thread
that wait outlasted a timeout further up ("Could not ask - Claude API error
524") and the answer was lost.

WHAT CHANGES
- The page asks with "stream": true and reads the reply line by line.
- The answer is painted into the thread while Claude writes it. The status
  beside the buttons reads "thinking… 12s", then "writing… 31s".
- If the Worker has to start over (empty reply, or the API dropped part way)
  what was shown is cleared and the status says "trying again…".
- If the connection drops before the last line, it says so and offers Ask
  again. Nothing half-written is filed in the thread.
- The [[GSTASKS:…]] marker is hidden while streaming, as it always was after.
Everything else in the Assist tab - thread, checklist, attachments, Ask again -
is untouched.
"""
import sys, os

EDITS = []

# ── 1. the reader ───────────────────────────────────────────────────────────
EDITS.append(("stream reader",
'''function renderAssist(v){
''',
r'''// 047: ask and read the reply as it is written. The Worker answers NDJSON -
// status lines, text as it arrives, then one {type:'result'} line carrying
// what it used to return whole. An older Worker answers plain JSON; that is
// returned as it is, so this page works against either.
async function askStream(payload, onEvent){
  const r = await fetch(store.base.replace(/\/$/,'') + '/api/controller/ask', {
    method: 'POST',
    headers: { 'Authorization': 'Bearer ' + store.token, 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...payload, stream: true })
  });
  if (r.status === 401){ store.token = ''; renderGate('Session ended. Sign in again.'); throw new Error('unauthorized'); }
  if (!r.body || !/ndjson/.test(r.headers.get('content-type') || '')){
    const text = await r.text();
    let data; try { data = JSON.parse(text); } catch(e){ data = text; }
    if (!r.ok) throw new Error((data && data.error) || ('HTTP ' + r.status));
    if (!data || typeof data !== 'object') throw new Error('The Worker sent back something that is not an answer (HTTP ' + r.status + ').');
    return data;
  }
  const reader = r.body.getReader(), dec = new TextDecoder();
  let buf = '', result = null;
  const take = line => {
    if (!line.trim()) return;
    let ev; try { ev = JSON.parse(line); } catch(e){ return; }
    if (ev && ev.type === 'result') result = ev; else if (ev) onEvent(ev);
  };
  for (;;){
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let nl;
    while ((nl = buf.indexOf('\n')) !== -1){ take(buf.slice(0, nl)); buf = buf.slice(nl + 1); }
  }
  take(buf);
  if (!result) throw new Error('The connection dropped before the answer finished.');
  if (result.error) throw new Error(result.error + (result.detail ? ' - ' + String(result.detail).slice(0, 200) : ''));
  return result;
}

function renderAssist(v){
'''))

# ── 2. status line + live painting ──────────────────────────────────────────
EDITS.append(("status and live answer",
r'''    const t0 = Date.now();
    const say = () => { const s = $('#askstat'); if (s) s.textContent = 'thinking… ' + Math.round((Date.now() - t0) / 1000) + 's' + (parts ? ' · with ' + parts + (parts === 1 ? ' attachment' : ' attachments') : ''); };
    say(); const timer = setInterval(say, 1000);
''',
r'''    const t0 = Date.now();
    // 047: what Claude has written so far, painted as it arrives.
    let live = '', startedOver = false;
    const say = () => { const s = $('#askstat'); if (s) s.textContent = (live ? 'writing… ' : (startedOver ? 'trying again… ' : 'thinking… ')) + Math.round((Date.now() - t0) / 1000) + 's' + (parts ? ' · with ' + parts + (parts === 1 ? ' attachment' : ' attachments') : ''); };
    say(); const timer = setInterval(say, 1000);
    const paint = () => {
      const th = $('#askthread'); if (!th) return;
      // The checklist marker is plumbing: hide it, and any half of it that
      // has arrived so far, exactly as the finished answer does.
      let shown = live.replace(/\[\[GSTASKS:[\s\S]*$/, '');
      for (let k = 10; k > 0; k--) if (shown.endsWith('[[GSTASKS:'.slice(0, k))){ shown = shown.slice(0, -k); break; }
      let el = $('#asklive');
      if (!shown.trim()){ if (el) el.remove(); return; }
      const sc = document.querySelector('.body');
      const follow = !!sc && (sc.scrollHeight - sc.scrollTop - sc.clientHeight < 140);
      if (!el){
        th.insertAdjacentHTML('beforeend', `<div id="asklive" style="margin:0 0 18px">
         <div style="font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin-bottom:4px">Assist</div>
         <pre style="white-space:pre-wrap;line-height:1.55;margin:0;font-size:13px"></pre>
       </div>`);
        el = $('#asklive');
      }
      el.querySelector('pre').textContent = shown;
      if (follow) sc.scrollTop = sc.scrollHeight;       // keep up only if you were already at the bottom
    };
    const onEv = ev => {
      if (ev.type === 'text'){ live += ev.delta || ''; paint(); say(); }
      else if (ev.type === 'retry'){ live = ''; startedOver = true; paint(); say(); }
    };
'''))

EDITS.append(("no-answer clears the live text",
r'''    const noAnswer = (head, body) => {
      const th = $('#askthread'); if (!th) return;
''',
r'''    const noAnswer = (head, body) => {
      const lv = $('#asklive'); if (lv) lv.remove();
      const th = $('#askthread'); if (!th) return;
'''))

# ── 3. the call ─────────────────────────────────────────────────────────────
EDITS.append(("ask call (open)",
r'''      const d = await api('ask', { method:'POST', body: JSON.stringify({
        question,
''',
r'''      const d = await askStream({
        question,
'''))

EDITS.append(("ask call (close)",
r'''      }) });
      clearInterval(timer);

      // The Worker says `empty` when Claude wrote nothing.''',
r'''      }, onEv);
      clearInterval(timer);

      // The Worker says `empty` when Claude wrote nothing.'''))


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'controller.html'
    if not os.path.exists(path):
        sys.exit(f"FAIL: {path} not found")
    src = open(path, encoding='utf-8').read()

    if 'async function askStream(' in src:
        print("already patched - nothing to do")
        return
    if 'function askAddFiles(' not in src:
        sys.exit("FAIL: 046 is not applied to this controller.html. Run patch_controller_html_046.py first. Nothing written.")

    out = src
    for name, old, new in EDITS:
        n = out.count(old)
        if n != 1:
            sys.exit(f"FAIL: anchor for '{name}' found {n} times, expected exactly 1. Nothing written.")
        out = out.replace(old, new)

    open(path + '.bak', 'w', encoding='utf-8').write(src)
    open(path, 'w', encoding='utf-8').write(out)
    print(f"patched {path} ({len(out)-len(src):+d} bytes, {len(EDITS)} edits). backup at {path}.bak")


if __name__ == '__main__':
    main()
