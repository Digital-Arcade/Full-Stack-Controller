#!/usr/bin/env python3
"""
patch_controller_html_039.py - Ask AI on feed and infra rows too.

Requires 038. Unique anchors, assert before write, idempotent.

  python3 patch_controller_html_039.py controller.html
"""
import sys, os

EDITS = [
  # ── feed card: button in the header, handler at the end ──────────────────
  ("""        <span style="color:var(--muted);font-size:12px">last import ${ago(f.last_run_at)}</span>
      </div>""",
   """        <span style="color:var(--muted);font-size:12px">last import ${ago(f.last_run_at)}</span>
        <button class="btn quiet" data-askfeed="${esc(f.feed_id)}" style="margin-left:auto;padding:2px 8px;font-size:12px">Ask AI</button>
      </div>"""),

  ("""  if (state.feedRuns.length){
    v.innerHTML += `<div class="railhead" style="padding-left:0"><span>Import history</span>""",
   """  // Bound after the history block below, so it survives the innerHTML +=
  // that appends it - binding earlier would leave the handler on a node that
  // is still there but with its children replaced.
  queueMicrotask(() => {
    v.onclick = e => {
      const b = e.target.closest('button[data-askfeed]'); if(!b) return;
      const f = state.feed.find(x=>String(x.feed_id)===b.dataset.askfeed);
      if (f) askAbout({ kind:'feed', ...f }, null, null);
    };
  });

  if (state.feedRuns.length){
    v.innerHTML += `<div class="railhead" style="padding-left:0"><span>Import history</span>"""),

  # ── infra card: button in the header, handler at the end ─────────────────
  ("""        ${silent ? `<span class="chip rem">not reporting</span>` : ''}
      </div>""",
   """        ${silent ? `<span class="chip rem">not reporting</span>` : ''}
        <button class="btn quiet" data-askhost="${esc(h.host)}" style="margin-left:auto;padding:2px 8px;font-size:12px">Ask AI</button>
      </div>"""),

  ("""      ${silent ? `<div class="empty" style="padding:10px 0 0"><b>No beat for ${h.age_s==null?'—':Math.floor(h.age_s/60)} minutes</b>Beats arrive every five minutes over plain outbound HTTPS. Silence means the box lost its network, lost power, or the timer stopped — it does not mean the box is fine and quiet.</div>` : ''}
    </div>`;
  }).join('');
}""",
   """      ${silent ? `<div class="empty" style="padding:10px 0 0"><b>No beat for ${h.age_s==null?'—':Math.floor(h.age_s/60)} minutes</b>Beats arrive every five minutes over plain outbound HTTPS. Silence means the box lost its network, lost power, or the timer stopped — it does not mean the box is fine and quiet.</div>` : ''}
    </div>`;
  }).join('');

  v.onclick = e => {
    const b = e.target.closest('button[data-askhost]'); if(!b) return;
    const host = state.hosts.find(x=>String(x.host)===b.dataset.askhost);
    if (host) askAbout({ kind:'host', ...host }, null, null);
  };
}"""),
]

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'controller.html'
    if not os.path.exists(path):
        sys.exit(f"FAIL: {path} not found")
    src = open(path, encoding='utf-8').read()

    if 'data-askfeed' in src and 'data-askhost' in src:
        print("already patched - nothing to do")
        return
    if "function askAbout(" not in src:
        sys.exit("FAIL: 038 is not applied to this file. Run patch_controller_html_038.py first.")

    for i, (old, new) in enumerate(EDITS, 1):
        n = src.count(old)
        if n != 1:
            sys.exit(f"FAIL: edit {i} anchor found {n} times, expected exactly 1. "
                     f"Nothing written.\n---\n{old[:200]}\n---")

    out = src
    for old, new in EDITS:
        out = out.replace(old, new, 1)

    open(path + '.bak', 'w', encoding='utf-8').write(src)
    open(path, 'w', encoding='utf-8').write(out)
    print(f"patched {path} (+{len(out)-len(src)} bytes). backup at {path}.bak")

if __name__ == '__main__':
    main()
