#!/usr/bin/env python3
"""
patch_controller_html_040.py - shows infra findings in the Infra tab.

Requires 039. Unique anchors, assert before write, idempotent.

  python3 patch_controller_html_040.py controller.html
"""
import sys, os

FINDINGS = r'''
// Findings raised by the triage pass. They sit above the hosts because a
// finding is the thing you act on; the host cards are context for it.
//
// remedy_state is the honest bit: 'pending' means queued for the next beat,
// 'sent' means handed over and we are waiting to hear, 'done'/'failed' is
// what actually happened on the box. 'none' means nothing automatic applies
// and the steps are for you.
function renderFindings(v){
  if (!state.findings.length) return '';
  const tone = f => f.severity === 'critical' ? 'rem' : 'chg';
  const rstate = f => {
    if (!f.remedy) return '<span class="chip">manual fix</span>';
    const s = f.remedy_state;
    if (s === 'pending') return `<span class="chip chg">${esc(f.remedy)} queued</span>`;
    if (s === 'sent')    return `<span class="chip chg">${esc(f.remedy)} running</span>`;
    if (s === 'done')    return `<span class="chip live">${esc(f.remedy)} applied</span>`;
    if (s === 'failed')  return `<span class="chip rem">${esc(f.remedy)} failed</span>`;
    return '';
  };
  return `<div class="railhead" style="padding-left:0"><span>Open findings</span><span>${state.findings.length}</span></div>`
    + state.findings.map(f=>`
      <div style="margin-bottom:14px;border-left:2px solid var(--line,#2a2a30);padding-left:12px">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
          <span class="chip ${tone(f)}">${esc(f.severity)}</span>
          <span style="font-size:13px;font-weight:500">${esc(f.kind.replace(/_/g,' '))}</span>
          <span style="color:var(--muted);font-size:12px">${esc(f.host)} · ${ago(f.created_at)}</span>
          ${rstate(f)}
          <button class="btn quiet" data-askfind="${f.id}" style="margin-left:auto;padding:2px 8px;font-size:12px">Ask AI</button>
          <button class="btn quiet" data-resolve="${f.id}" style="padding:2px 8px;font-size:12px">Resolve</button>
        </div>
        ${f.verdict ? `<div style="font-size:13px;line-height:1.5;margin-bottom:4px">${esc(f.verdict)}</div>` : ''}
        ${f.steps ? `<pre style="white-space:pre-wrap;font-size:12px;line-height:1.5;margin:0;color:var(--muted)">${esc(f.steps)}</pre>` : ''}
        ${f.remedy_result ? `<div class="mono" style="font-size:12px;margin-top:4px;color:var(--muted)">${esc(f.remedy_result.output||'')}</div>` : ''}
      </div>`).join('');
}

'''

EDITS = [
  ("                feed:[], feedRuns:[], hosts:[], askFocus:null,",
   "                feed:[], feedRuns:[], hosts:[], findings:[], askFocus:null,"),

  ("    Promise.all([api('feed-health'), api('feed-runs?limit=30'), api('hosts')])\n      .then(([feed, feedRuns, hosts]) => { state.feed = feed; state.feedRuns = feedRuns; state.hosts = hosts;\n                                           if (state.tab === 'feed' || state.tab === 'infra') renderView(); })\n      .catch(() => {});",
   "    Promise.all([api('feed-health'), api('feed-runs?limit=30'), api('hosts'), api('findings')])\n      .then(([feed, feedRuns, hosts, findings]) => { state.feed = feed; state.feedRuns = feedRuns; state.hosts = hosts; state.findings = findings;\n                                           if (state.tab === 'feed' || state.tab === 'infra') renderView(); })\n      .catch(() => {});"),

  ("function renderInfra(v){\n  if (!state.hosts.length){",
   FINDINGS + "function renderInfra(v){\n  if (!state.hosts.length && !state.findings.length){"),

  # findings go above the host cards, and the handler covers both buttons
  ("""  v.onclick = e => {
    const b = e.target.closest('button[data-askhost]'); if(!b) return;
    const host = state.hosts.find(x=>String(x.host)===b.dataset.askhost);
    if (host) askAbout({ kind:'host', ...host }, null, null);
  };
}""",
   """  v.innerHTML = renderFindings(v) + v.innerHTML;

  v.onclick = async e => {
    const af = e.target.closest('button[data-askfind]');
    if (af){
      const f = state.findings.find(x=>String(x.id)===af.dataset.askfind);
      if (f) askAbout({ kind:'infra_finding', ...f }, null, null);
      return;
    }
    const rs = e.target.closest('button[data-resolve]');
    if (rs){
      rs.disabled = true; rs.textContent = 'Resolving…';
      try{
        await api('finding-ack', { method:'POST', body: JSON.stringify({ id: Number(rs.dataset.resolve), resolve: true }) });
        state.findings = await api('findings'); renderView();
      }catch(err){ rs.disabled = false; rs.textContent = 'Retry'; }
      return;
    }
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

    if "function renderFindings(" in src:
        print("already patched - nothing to do")
        return
    if 'data-askhost' not in src:
        sys.exit("FAIL: 039 is not applied to this file. Run patch_controller_html_039.py first.")

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
