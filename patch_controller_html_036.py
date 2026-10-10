#!/usr/bin/env python3
"""
patch_controller_html_036.py - adds the Feed and Infra tabs to controller.html.

Same discipline as patch_controller.py: unique anchors, assert-before-write,
idempotent, refuses rather than guesses. Nothing existing is removed.

  python3 patch_controller_html_036.py controller.html
"""
import sys, os

RENDERERS = r'''
/* ------------------------------------------------------------------- feed */
// Dealerslink inventory feed. The key subtlety: dealer_feed_runs only records
// a run when the vendor's file CHANGED. The relay fetches every 30 minutes
// and skips identical files, so observed gaps run 9-15 hours and a "last run"
// of several hours is healthy, not a fault. 26h matches STALE_HOURS in
// feed-alert.sh, which is the deadman already watching this on the box.
const FEED_STALE_S = 26 * 3600;

function feedTone(f){
  const st = String(f.run_status || f.last_status || '').toLowerCase();
  if (st && st !== 'ok') return 'rem';
  if (f.age_s == null) return '';
  return f.age_s > FEED_STALE_S ? 'rem' : 'live';
}

function renderFeed(v){
  if (!state.feed.length){
    v.innerHTML = `<div class="empty"><b>No feeds configured</b>A row appears here for every enabled entry in <code>dealer_feeds</code>. Nothing is configured yet, or the platform claim was refused.</div>`;
    return;
  }
  const nameOf = id => (state.fleet.find(f=>f.deployment_id===id)||{}).name || String(id||'').slice(0,8);

  v.innerHTML = state.feed.map(f=>{
    const tone = feedTone(f);
    const errs = Array.isArray(f.errors) ? f.errors : [];
    return `
    <div style="margin-bottom:18px">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
        <i class="dot ${tone}"></i>
        <span style="font-size:13px;font-weight:500">${esc(f.app_name || nameOf(f.app_id))}</span>
        <span class="chip">${esc(f.provider||'?')}</span>
        <span class="chip">${esc(f.mode||'?')}</span>
        ${f.enabled === false ? `<span class="chip rem">disabled</span>` : ''}
        <span style="color:var(--muted);font-size:12px">last import ${ago(f.last_run_at)}</span>
      </div>
      <table><thead><tr>
        <th>Status</th><th>Seen</th><th>Created</th><th>Updated</th><th>Skipped</th><th>Withdrawn</th><th>Source</th>
      </tr></thead><tbody><tr>
        <td><span class="chip ${tone}">${esc(f.run_status || f.last_status || 'never run')}</span></td>
        <td>${f.rows_seen ?? '—'}</td>
        <td>${f.rows_created ?? '—'}</td>
        <td>${f.rows_updated ?? '—'}</td>
        <td>${f.rows_skipped ?? '—'}</td>
        <td>${f.rows_withdrawn ?? '—'}</td>
        <td class="mono">${esc(f.notes || '—')}</td>
      </tr></tbody></table>
      ${errs.length ? `<div class="empty" style="padding:10px 0 0"><b>${errs.length} importer error${errs.length>1?'s':''}</b><span class="mono">${esc(JSON.stringify(errs).slice(0,400))}</span></div>` : ''}
      ${f.age_s != null && f.age_s > FEED_STALE_S
        ? `<div class="empty" style="padding:10px 0 0"><b>Nothing imported in ${Math.floor(f.age_s/3600)} hours</b>The vendor normally regenerates several times a day. Past 26 hours either the vendor stopped publishing or the relay cannot reach them — check <code>tail -20 /var/log/feed-relay.log</code> on the box.</div>`
        : ''}
    </div>`;
  }).join('');

  if (state.feedRuns.length){
    v.innerHTML += `<div class="railhead" style="padding-left:0"><span>Import history</span><span>${state.feedRuns.length} runs</span></div>`
      + `<table><thead><tr><th>When</th><th>Status</th><th>Seen</th><th>Created</th><th>Updated</th><th>Withdrawn</th><th>Source</th></tr></thead><tbody>`
      + state.feedRuns.map(r=>`<tr>
          <td>${ago(r.finished_at)}</td>
          <td><span class="chip ${String(r.status||'').toLowerCase()==='ok'?'live':'rem'}">${esc(r.status||'?')}</span></td>
          <td>${r.rows_seen ?? '—'}</td>
          <td>${r.rows_created ?? '—'}</td>
          <td>${r.rows_updated ?? '—'}</td>
          <td>${r.rows_withdrawn ?? '—'}</td>
          <td class="mono">${esc(r.notes||'—')}</td>
        </tr>`).join('') + `</tbody></table>`;
  }
}

/* ------------------------------------------------------------------ infra */
// Boxes push a beat every five minutes because they sit behind CGNAT and
// cannot be polled. SILENCE IS THE SIGNAL: a host that stops beating still
// shows its last row with a growing age, which is what a network outage
// looks like from here.
const HOST_SILENT_S = 15 * 60;

function renderInfra(v){
  if (!state.hosts.length){
    v.innerHTML = `<div class="empty"><b>No hosts reporting</b>Run <code>install-host-beat.sh</code> on the box. It posts a beat every five minutes; the first one appears here within that window.</div>`;
    return;
  }
  const pct = n => n==null ? '—' : Number(n).toFixed(0)+'%';
  v.innerHTML = state.hosts.map(h=>{
    const silent = h.age_s == null || h.age_s > HOST_SILENT_S;
    const bad = silent || h.failed_units > 0 || h.dns_ok === false || h.feed_timer_ok === false;
    const up = h.uptime_s == null ? '—'
      : h.uptime_s < 3600 ? Math.floor(h.uptime_s/60)+'m'
      : h.uptime_s < 86400 ? Math.floor(h.uptime_s/3600)+'h'
      : Math.floor(h.uptime_s/86400)+'d';
    return `
    <div style="margin-bottom:18px">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
        <i class="dot ${bad?'rem':'live'}"></i>
        <span style="font-size:13px;font-weight:500">${esc(h.host)}</span>
        <span style="color:var(--muted);font-size:12px">beat ${ago(h.beat_at)}</span>
        ${silent ? `<span class="chip rem">not reporting</span>` : ''}
      </div>
      <table><thead><tr>
        <th>Uptime</th><th>Load</th><th>Memory</th><th>Disk</th><th>Failed units</th><th>DNS</th><th>Feed timer</th><th>Last backup</th>
      </tr></thead><tbody><tr>
        <td>${up}</td>
        <td>${h.load1 ?? '—'}</td>
        <td>${pct(h.mem_used_pct)}</td>
        <td>${pct(h.disk_used_pct)}</td>
        <td>${h.failed_units == null ? '—' : (h.failed_units > 0 ? `<span class="chip rem">${h.failed_units}</span>` : '0')}</td>
        <td>${h.dns_ok == null ? '—' : (h.dns_ok ? 'ok' : `<span class="chip rem">failing</span>`)}</td>
        <td>${h.feed_timer_ok == null ? '—' : (h.feed_timer_ok ? 'ok' : `<span class="chip rem">down</span>`)}</td>
        <td class="mono">${esc(h.last_backup_status || '—')}</td>
      </tr></tbody></table>
      ${h.failed_unit_names ? `<div class="empty" style="padding:10px 0 0"><b>Failed units</b><span class="mono">${esc(h.failed_unit_names)}</span></div>` : ''}
      ${silent ? `<div class="empty" style="padding:10px 0 0"><b>No beat for ${h.age_s==null?'—':Math.floor(h.age_s/60)} minutes</b>Beats arrive every five minutes over plain outbound HTTPS. Silence means the box lost its network, lost power, or the timer stopped — it does not mean the box is fine and quiet.</div>` : ''}
    </div>`;
  }).join('');
}

'''

EDITS = [
  # 1. state fields
  ("const state = { fleet:[], revisions:[], alerts:[], watchdogs:[], dead:[], traffic:[], pages:[], flags:null,",
   "const state = { fleet:[], revisions:[], alerts:[], watchdogs:[], dead:[], traffic:[], pages:[], flags:null,\n                feed:[], feedRuns:[], hosts:[],"),

  # 2. tab strip
  ("${['changes','traffic','flags','alerts','watchdogs','dead files'].map(t=>",
   "${['changes','feed','infra','traffic','flags','alerts','watchdogs','dead files'].map(t=>"),

  # 3. renderView dispatch
  ("  if (state.tab==='alerts')    return renderAlerts(v);",
   "  if (state.tab==='feed')      return renderFeed(v);\n  if (state.tab==='infra')     return renderInfra(v);\n  if (state.tab==='alerts')    return renderAlerts(v);"),

  # 4. boot fetches - destructure, call list, and assign
  ("    const [fleet, revisions, alerts, watchdogs, dead] = await Promise.all([\n      api('fleet'), api('revisions?limit=60'), api('alerts?open=1'), api('watchdogs'), api('dead-files')\n    ]);\n    Object.assign(state, { fleet, revisions, alerts, watchdogs, dead, error:'' });",
   "    const [fleet, revisions, alerts, watchdogs, dead] = await Promise.all([\n      api('fleet'), api('revisions?limit=60'), api('alerts?open=1'), api('watchdogs'), api('dead-files')\n    ]);\n    Object.assign(state, { fleet, revisions, alerts, watchdogs, dead, error:'' });\n    // Feed and infra load alongside traffic rather than in the blocking set:\n    // an empty gs_feed_health or a host that never beat must never stop the\n    // timeline rendering. Each settles on its own and repaints if visible.\n    Promise.all([api('feed-health'), api('feed-runs?limit=30'), api('hosts')])\n      .then(([feed, feedRuns, hosts]) => { state.feed = feed; state.feedRuns = feedRuns; state.hosts = hosts;\n                                           if (state.tab === 'feed' || state.tab === 'infra') renderView(); })\n      .catch(() => {});"),

  # 5. renderers
  ("function renderDead(v){", RENDERERS + "function renderDead(v){"),
]

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'controller.html'
    if not os.path.exists(path):
        sys.exit(f"FAIL: {path} not found")
    src = open(path, encoding='utf-8').read()

    if "function renderFeed(" in src and "function renderInfra(" in src:
        print("already patched - nothing to do")
        return

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
