#!/usr/bin/env python3
"""
patch_controller_html_048.py - the Infra tab shows backup storage, backup runs
and disks for each host.

Requires 036 (the Infra tab). Independent of the Assist patches. Reads what
storage-probe on the box sends in each beat (extra.storage); a host that does
not run the probe looks exactly as it did.

  python3 patch_controller_html_048.py controller.html

Under each host's row:
  Backup storage   one line per storage: mounted or not, free space, newest
                   archive and its age, how many archives against keep-last,
                   how much of the disk is NOT backups, which jobs write here.
                   Red chips: NOT MOUNTED, "next will not fit", "no new backup",
                   "none, ever".
  Backup runs      every run of the last two days: when, where, how long,
                   result, and for a failure the line from its own log.
                   Amber chip on a run no job in jobs.cfg schedules.
  Disks            model, size, SMART result, bad-sector counts, temperature,
                   and kernel I/O errors in the last 24 hours.
All of it is plain text from the box, escaped before it is shown.
"""
import sys, os

FN_ANCHOR = '''function renderInfra(v){
'''

FN = r'''/* ---- infra: storage, backups, disks (048) ---- */
// storage-probe on the box reports hourly; the beat carries it in
// extra.storage. These only DISPLAY it - the judging is done in the Worker
// (gsStorageDetect) and shows up as findings above.
const INFRA_BACKUP_MAX_AGE_S = 36 * 3600;     // must match GS_BACKUP_MAX_AGE_S in the Worker

function infraSize(kb){
  kb = Number(kb) || 0;
  if (kb >= 1073741824) return (kb / 1073741824).toFixed(1) + ' TB';
  if (kb >= 1048576) return Math.round(kb / 1048576) + ' GB';
  if (kb >= 1024) return Math.round(kb / 1024) + ' MB';
  return Math.round(kb) + ' KB';
}
function infraAge(s){
  s = Math.max(0, Math.floor(Number(s) || 0));
  if (s >= 48 * 3600) return Math.floor(s / 86400) + ' days';
  if (s >= 3600) return Math.floor(s / 3600) + 'h ' + Math.floor(s % 3600 / 60) + 'm';
  return Math.max(1, Math.round(s / 60)) + ' min';
}

function infraStorage(h){
  const p = h && h.extra && h.extra.storage;
  if (!p || typeof p !== 'object' || !p.at_ts) return '';
  const beatTs = Math.floor(new Date(h.beat_at).getTime() / 1000) || 0;
  const probeAge = Math.max(0, beatTs + Number(h.age_s || 0) - Number(p.at_ts));
  const head = (a, b) => `<div class="railhead" style="padding:14px 0 6px"><span>${a}</span><span>${b || ''}</span></div>`;
  const chip = (tone, text) => `<span class="chip ${tone}">${esc(text)}</span>`;
  let out = '';

  const stores = (Array.isArray(p.storages) ? p.storages : []).filter(s => s && s.id);
  if (stores.length){
    out += head('Backup storage', 'checked ' + infraAge(probeAge) + ' ago' + (probeAge > 3 * 3600 ? ' - the probe has stopped' : ''))
      + `<table data-infra="storage"><thead><tr><th>Storage</th><th>State</th><th>Free</th><th>Newest backup</th><th>Archives</th><th>Not backups</th><th>Jobs</th></tr></thead><tbody>`
      + stores.map(s => {
          const jobs = Array.isArray(s.jobs) ? s.jobs : [];
          if (!s.path) return `<tr><td>${esc(s.id)}</td><td colspan="6" style="color:var(--muted)">${esc(s.note || 'not readable from this box')}</td></tr>`;
          let st = s.exists === false ? chip('rem', 'folder missing')
                 : s.mounted ? 'mounted'
                 : s.is_mountpoint ? chip('rem', 'NOT MOUNTED') : `<span style="color:var(--muted)">folder, not its own disk</span>`;
          if (s.fs_state && String(s.fs_state).toLowerCase() !== 'clean') st += ' ' + chip('rem', 'filesystem: ' + s.fs_state);
          const usable = s.exists !== false && (s.mounted || !s.is_mountpoint);
          const n = s.newest && s.newest.kb ? s.newest : null;
          const age = n ? Number(n.age_s || 0) + probeAge : null;
          const tight = usable && n && s.avail_kb != null && Number(s.avail_kb) < Number(n.kb) * 1.05;
          const newest = !usable ? '—'
            : n ? `${esc(infraSize(n.kb))}, ${esc(infraAge(age))} old` + (jobs.length && age > INFRA_BACKUP_MAX_AGE_S ? ' ' + chip('rem', 'no new backup') : '')
            : (jobs.length ? chip('rem', 'none, ever') : `<span style="color:var(--muted)">none</span>`);
          return `<tr>
            <td><span style="font-weight:500">${esc(s.id)}</span><div class="mono" style="font-size:11px;color:var(--faint)">${esc(s.path)}${s.device ? ' · ' + esc(s.device) : ''}</div></td>
            <td>${st}</td>
            <td>${usable && s.avail_kb != null ? `${esc(infraSize(s.avail_kb))} <span style="color:var(--faint)">of ${esc(infraSize(s.total_kb))}</span>` + (tight ? ' ' + chip('rem', 'next will not fit') : (Number(s.used_pct || 0) >= 90 ? ' ' + chip('warn', Math.round(s.used_pct) + '% full') : '')) : '—'}</td>
            <td>${newest}${usable && n ? `<div class="mono" style="font-size:11px;color:var(--faint)">${esc(n.name)}</div>` : ''}</td>
            <td>${usable ? esc(String(s.archives ?? 0)) + (s.keep_last ? ` <span style="color:var(--faint)">keep ${esc(String(s.keep_last))}</span>` : '') : '—'}</td>
            <td>${usable && s.other_kb != null && Number(s.other_kb) > 1048576 ? esc(infraSize(s.other_kb)) : '—'}</td>
            <td class="mono">${jobs.length ? jobs.map(j => { const d = (Array.isArray(p.jobs) ? p.jobs : []).find(x => x.id === j); return esc(d && d.schedule ? d.schedule : j); }).join(', ') : '—'}</td>
          </tr>`; }).join('') + `</tbody></table>`;
  }

  const runs = (Array.isArray(p.runs) ? p.runs : []).filter(r => r && r.start);
  if (Array.isArray(p.runs)){
    out += head('Backup runs', 'last two days')
      + (runs.length ? `<table data-infra="runs"><thead><tr><th>When</th><th>Storage</th><th>Minutes</th><th>Result</th><th>Why / size</th></tr></thead><tbody>`
        + runs.map(r => `<tr>
            <td class="mono">${esc(r.start)}</td>
            <td>${r.storage ? esc(r.storage) : `<span style="color:var(--muted)">unknown</span>`}${r.listed === false ? ' ' + chip('warn', 'not in jobs.cfg') : ''}</td>
            <td>${esc(String(r.mins ?? '—'))}</td>
            <td>${chip(r.ok ? 'live' : 'rem', r.status || (r.ok ? 'OK' : 'failed'))}</td>
            <td class="mono" style="white-space:normal">${esc(r.error || r.size || '—')}</td>
          </tr>`).join('') + `</tbody></table>`
        : `<div class="empty" style="padding:0">No backup has run in the last two days.</div>`);
  }

  const disks = (Array.isArray(p.disks) ? p.disks : []).filter(d => d && d.dev);
  if (disks.length){
    const k = p.kernel || {};
    out += head('Disks', k.io_errors == null ? '' : (Number(k.io_errors) > 0 ? '' : 'no kernel I/O errors in 24h'))
      + `<table data-infra="disks"><thead><tr><th>Disk</th><th>Model</th><th>Size</th><th>SMART</th><th>Bad sectors</th><th>Temp</th></tr></thead><tbody>`
      + disks.map(d => {
          const bad = [['reallocated', d.realloc], ['pending', d.pending], ['uncorrectable', d.uncorrect], ['media errors', d.media_errors]].filter(x => Number(x[1] || 0) > 0);
          const smart = d.smart === 'PASSED' ? 'passed' : d.smart === 'FAILED' ? chip('rem', 'FAILED')
                      : `<span style="color:var(--muted)">${esc(d.smart || 'unknown')}${d.note ? ' - ' + esc(d.note) : ''}</span>`;
          return `<tr>
            <td class="mono">/dev/${esc(d.dev)}${d.tran === 'usb' ? ' <span style="color:var(--faint)">usb</span>' : ''}</td>
            <td>${esc(d.model || '—')}</td>
            <td>${esc(infraSize(d.size_kb))}</td>
            <td>${smart}</td>
            <td>${bad.length ? bad.map(x => chip(x[0] === 'reallocated' || x[0] === 'media errors' ? 'warn' : 'rem', x[1] + ' ' + x[0])).join(' ') : (d.smart === 'PASSED' ? '0' : '—')}</td>
            <td>${d.temp_c == null ? '—' : esc(String(d.temp_c)) + '°C'}</td>
          </tr>`; }).join('') + `</tbody></table>`
      + (Number(k.io_errors || 0) > 0 ? `<div class="empty" style="padding:10px 0 0;max-width:none"><b>${esc(String(k.io_errors))} kernel I/O or filesystem errors in the last ${esc(String(k.hours || 24))} hours</b><span class="mono">${esc(k.sample || '')}</span></div>` : '');
  }
  return out;
}

'''

CSS_ANCHOR = '''.chip.rem{color:var(--crit);border-color:rgba(229,72,77,.3)}
'''
CSS = '''[data-infra] .chip{white-space:nowrap;display:inline-block}
[data-infra] td.mono:first-child{white-space:nowrap}
'''

ROW_OLD = r'''      ${silent ? `<div class="empty" style="padding:10px 0 0"><b>No beat for ${h.age_s==null?'—':Math.floor(h.age_s/60)} minutes</b>Beats arrive every five minutes over plain outbound HTTPS. Silence means the box lost its network, lost power, or the timer stopped — it does not mean the box is fine and quiet.</div>` : ''}
'''
ROW_NEW = ROW_OLD + r'''      ${infraStorage(h)}
'''


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'controller.html'
    if not os.path.exists(path):
        sys.exit(f"FAIL: {path} not found")
    src = open(path, encoding='utf-8').read()

    if 'function infraStorage(' in src:
        print("already patched - nothing to do")
        return
    hunks = [("helper", FN_ANCHOR, FN + FN_ANCHOR), ("host block", ROW_OLD, ROW_NEW), ("styles", CSS_ANCHOR, CSS_ANCHOR + CSS)]
    for name, old, _ in hunks:
        n = src.count(old)
        if n != 1:
            sys.exit(f"FAIL: anchor for '{name}' found {n} times, expected exactly 1. Nothing written.")
    out = src
    for _, old, new in hunks:
        out = out.replace(old, new, 1)

    open(path + '.bak', 'w', encoding='utf-8').write(src)
    open(path, 'w', encoding='utf-8').write(out)
    print(f"patched {path} ({len(out)-len(src):+d} bytes). backup at {path}.bak")


if __name__ == '__main__':
    main()
