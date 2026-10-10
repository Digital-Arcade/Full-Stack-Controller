#!/usr/bin/env bash
# install-storage-probe.sh - the watchdog starts looking at disks, backup
# storage and backup runs.
#
# WHY: from Oct 1 to Oct 5 every backup to sysbackup died with "No space left
# on device". The beat knew one word about backups (the status of the LAST
# run) and one number about disks (how full / is), so nothing said a thing.
#
# WHAT THIS INSTALLS
#   /usr/local/bin/storage-probe.py   hourly, read-only. Looks at every backup
#                                     storage (mounted? free? newest archive?),
#                                     every disk (SMART, kernel I/O errors) and
#                                     every backup run of the last two days
#                                     (which storage, and why it failed).
#   storage-probe.timer               runs it hourly and 4 minutes after boot.
#   host-beat.sh                      two small additions so each beat carries
#                                     the probe's latest report. Original kept
#                                     as host-beat.sh.bak-048.
#
# The probe never writes to a backup disk, never wakes a sleeping drive and
# never runs du. No new token, no new secret: the report rides in the beat
# that is already going out.
#
# Needs patch_controller_048.py on the Worker for the findings to appear. It
# is safe to install before that: an older Worker stores the report and
# ignores it.
set -uo pipefail

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; DIM=$'\033[2m'; OFF=$'\033[0m'
step(){ printf '\n%s==> %s%s\n' "$DIM" "$1" "$OFF"; }
ok(){   printf '  %s+%s %s\n' "$GRN" "$OFF" "$1"; }
warn(){ printf '  %s!%s %s\n' "$YEL" "$OFF" "$1"; }
die(){  printf '  %sx%s %s\n' "$RED" "$OFF" "$1"; exit 1; }

BEAT="${BEAT:-/usr/local/bin/host-beat.sh}"
PROBE="${PROBE:-/usr/local/bin/storage-probe.py}"
REPORT="${REPORT:-/var/lib/host-beat/storage.json}"
UNITS="${UNITS:-/etc/systemd/system}"

[[ $EUID -eq 0 ]] || die "Run this as root."
command -v python3 >/dev/null || die "python3 is not installed."

# ──────────────────────────────────────────────────────────────────────────
step "1 of 5  Checking what is here"

[[ -f "$BEAT" ]] || die "$BEAT not found. Run install-host-beat.sh first - the report travels in its beat."
ok "found $BEAT"
for t in smartctl tune2fs findmnt lsblk journalctl; do
    if command -v "$t" >/dev/null; then ok "$t is installed"
    else warn "$t is not installed - that reading will be reported as unknown, everything else still works"; fi
done
[[ -r /etc/pve/storage.cfg ]] && ok "this is a Proxmox host (/etc/pve/storage.cfg is readable)" \
    || warn "/etc/pve/storage.cfg is not readable - no backup storages will be reported from this host"

# ──────────────────────────────────────────────────────────────────────────
step "2 of 5  The probe"

cat > "$PROBE" <<'PROBE_PY'
#!/usr/bin/env python3
# storage-probe.py - what the five-minute beat cannot afford to collect.
#
# Runs hourly. Looks at every backup storage, every disk and every backup run
# of the last two days, and writes one small JSON file that host-beat.sh
# carries up to the controller in its next beat.
#
# It only READS. It never writes to a backup disk, never spins up a sleeping
# drive (smartctl -n standby), and never runs du over a tree - sizes come from
# the filesystem and from the archive files themselves.
#
# Every reading is guarded. A probe that cannot be taken is reported as null
# with the reason, and the rest still goes up.
import glob, json, os, re, subprocess, sys, time
from datetime import datetime

STORAGE_CFG = os.environ.get('STORAGE_CFG', '/etc/pve/storage.cfg')
JOBS_CFG    = os.environ.get('JOBS_CFG', '/etc/pve/jobs.cfg')
TASKS_DIR   = os.environ.get('TASKS_DIR', '/var/log/pve/tasks')
OUT         = os.environ.get('OUT', '/var/lib/host-beat/storage.json')
CRON_GLOBS  = os.environ.get('CRON_GLOBS', '/etc/pve/vzdump.cron:/etc/cron.d/*:/etc/crontab:/var/spool/cron/crontabs/*').split(':')
RUN_HOURS   = 50          # how far back backup runs are reported
NOW         = time.time()

def run(cmd, timeout=20):
    """(exit code, stdout). Never raises: a missing tool is (127, '')."""
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout)
        return p.returncode, p.stdout.decode('utf-8', 'replace')
    except FileNotFoundError:
        return 127, ''
    except Exception:
        return 124, ''

def read(path, limit=None):
    try:
        with open(path, 'r', errors='replace') as f:
            return f.read() if limit is None else f.read(limit)
    except Exception:
        return ''

def cut(s, n=240):
    s = re.sub(r'\s+', ' ', str(s or '')).strip()
    return s[:n]

# ── /etc/pve/*.cfg ──────────────────────────────────────────────────────────
# "type: id" on its own line, then indented "key value" lines.
def pve_cfg(text):
    out, cur = [], None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        m = re.match(r'^(\S+):\s+(\S+)\s*$', line)
        if m and not line[0].isspace():
            cur = {'type': m.group(1), 'id': m.group(2), 'props': {}}
            out.append(cur)
        elif cur is not None and line[0].isspace():
            parts = line.strip().split(None, 1)
            cur['props'][parts[0]] = parts[1].strip() if len(parts) > 1 else '1'
    return out

ARCHIVE = re.compile(r'^vzdump-(qemu|lxc)-(\d+)-(\d{4}_\d\d_\d\d-\d\d_\d\d_\d\d)\.(vma|tar|tgz)(\.(zst|gz|lzo))?$')
DUMPLOG = re.compile(r'^vzdump-(qemu|lxc)-(\d+)-(\d{4}_\d\d_\d\d-\d\d_\d\d_\d\d)\.log$')

def stamp(s):
    try: return time.mktime(time.strptime(s, '%Y_%m_%d-%H_%M_%S'))
    except Exception: return None

def jobs():
    out = []
    for s in pve_cfg(read(JOBS_CFG)):
        if s['type'] != 'vzdump': continue
        p = s['props']
        out.append({'id': s['id'], 'schedule': p.get('schedule'), 'storage': p.get('storage'),
                    'vmid': p.get('vmid') or ('all' if p.get('all') == '1' else None),
                    'enabled': p.get('enabled', '1') != '0'})
    return out

def cron_lines():
    out, seen = [], set()
    for g in CRON_GLOBS:
        for f in sorted(glob.glob(g)):
            real = os.path.realpath(f)
            if real in seen or not os.path.isfile(real): continue
            seen.add(real)
            for line in read(real, 200000).splitlines():
                t = line.strip()
                if t and not t.startswith('#') and 'vzdump' in t:
                    out.append({'file': f, 'line': cut(t, 200)})
    return out[:10]

def storages(job_list):
    out = []
    for s in pve_cfg(read(STORAGE_CFG)):
        p = s['props']
        if 'backup' not in [c.strip() for c in p.get('content', '').split(',')]: continue
        if s['type'] == 'pbs':
            out.append({'id': s['id'], 'type': 'pbs', 'note': 'Proxmox Backup Server storage - not readable from this box'}); continue
        path = p.get('path') or ('/mnt/pve/' + s['id'] if s['type'] in ('nfs', 'cifs', 'cephfs', 'glusterfs') else None)
        if not path: continue
        d = {'id': s['id'], 'type': s['type'], 'path': path,
             'is_mountpoint': p.get('is_mountpoint') in ('yes', '1', path),
             'jobs': [j['id'] for j in job_list if j['enabled'] and j['storage'] == s['id']],
             'keep_last': None, 'exists': os.path.isdir(path), 'mounted': False}
        m = re.search(r'keep-last=(\d+)', p.get('prune-backups', ''))
        if m: d['keep_last'] = int(m.group(1))
        if not d['exists']:
            out.append(d); continue
        d['mounted'] = os.path.ismount(path)
        rc, o = run(['findmnt', '-n', '-o', 'SOURCE,FSTYPE', '-T', path])
        f = o.split()
        d['device'] = f[0] if len(f) > 0 else None
        d['fstype'] = f[1] if len(f) > 1 else None
        try:
            v = os.statvfs(path)
            d['total_kb'] = v.f_blocks * v.f_frsize // 1024
            d['avail_kb'] = v.f_bavail * v.f_frsize // 1024
            d['used_kb']  = (v.f_blocks - v.f_bfree) * v.f_frsize // 1024
            d['used_pct'] = round(d['used_kb'] * 100.0 / max(1, d['used_kb'] + d['avail_kb']), 1)
        except Exception:
            pass
        dump = os.path.join(path, 'dump')
        d['dump_ok'] = os.path.isdir(dump)
        d['writable'] = os.access(dump if d['dump_ok'] else path, os.W_OK)
        arch, logs = [], []
        if d['dump_ok']:
            try:
                for e in os.scandir(dump):
                    m = ARCHIVE.match(e.name)
                    if m:
                        st = e.stat(); arch.append((st.st_mtime, e.name, st.st_size // 1024, m.group(2)))
                    elif DUMPLOG.match(e.name):
                        logs.append((stamp(DUMPLOG.match(e.name).group(3)), e.name))
            except Exception:
                pass
        arch.sort(reverse=True)
        d['archives'] = len(arch)
        d['archive_kb'] = sum(a[2] for a in arch)
        d['newest'] = {'name': arch[0][1], 'kb': arch[0][2], 'age_s': int(NOW - arch[0][0]), 'vmid': arch[0][3]} if arch else None
        d['prev_kb'] = arch[1][2] if len(arch) > 1 else None
        if 'used_kb' in d: d['other_kb'] = max(0, d['used_kb'] - d['archive_kb'])
        d['_logs'] = logs
        # ext2/3/4 keep their own verdict on themselves in the superblock.
        if d.get('device', '') and str(d['device']).startswith('/dev/') and str(d.get('fstype') or '').startswith('ext') and d['mounted']:
            rc, o = run(['tune2fs', '-l', d['device']], 15)
            m = re.search(r'^Filesystem state:\s*(.+)$', o, re.M)
            d['fs_state'] = cut(m.group(1), 60) if m else None
            m = re.search(r'^FS Error count:\s*(\d+)', o, re.M)
            d['fs_errors'] = int(m.group(1)) if m else 0
        out.append(d)
    return out

def disks():
    out = []
    rc, o = run(['lsblk', '-dn', '-b', '-P', '-o', 'NAME,SIZE,TYPE,TRAN,MODEL'])
    for line in o.splitlines():
        f = dict(re.findall(r'(\w+)="([^"]*)"', line))
        name = f.get('NAME', '')
        if f.get('TYPE') != 'disk' or re.match(r'^(zd|loop|ram|zram|nbd|dm-|sr|md)', name) or not int(f.get('SIZE') or 0): continue
        d = {'dev': name, 'model': cut(f.get('MODEL'), 60) or None, 'tran': f.get('TRAN') or None,
             'size_kb': int(f.get('SIZE') or 0) // 1024, 'smart': 'unknown'}
        j = None
        for extra in ([], ['-d', 'sat']):
            # -n standby: a drive that is asleep is left asleep.
            rc, o2 = run(['smartctl', '-n', 'standby', '-H', '-A', '-j'] + extra + ['/dev/' + name], 25)
            try: j = json.loads(o2)
            except Exception: j = None
            if j and ('smart_status' in j or 'ata_smart_attributes' in j or 'nvme_smart_health_information_log' in j): break
            if rc == 127: break
        if rc == 127:
            d['note'] = 'smartctl is not installed'
        elif j is None:
            d['note'] = 'smartctl gave no answer'
        else:
            msgs = ' '.join(m.get('string', '') for m in (j.get('smartctl', {}).get('messages') or []))
            if 'smart_status' in j:
                d['smart'] = 'PASSED' if j['smart_status'].get('passed') else 'FAILED'
            elif re.search(r'STANDBY|SLEEP', msgs, re.I):
                d['smart'] = 'asleep'
            else:
                d['note'] = cut(msgs, 160) or 'the drive did not report SMART status'
            for a in (j.get('ata_smart_attributes', {}) or {}).get('table', []) or []:
                raw = (a.get('raw') or {}).get('value')
                if a.get('id') == 5:   d['realloc'] = raw
                if a.get('id') == 197: d['pending'] = raw
                if a.get('id') == 198: d['uncorrect'] = raw
            nv = j.get('nvme_smart_health_information_log')
            if nv:
                d['media_errors'] = nv.get('media_errors'); d['wear_pct'] = nv.get('percentage_used')
                if nv.get('critical_warning'): d['smart'] = 'FAILED'
            t = (j.get('temperature') or {}).get('current')
            if t is not None: d['temp_c'] = t
        out.append(d)
    return out

KERR = re.compile(r'(I/O error|EXT4-fs error|EXT4-fs \([^)]*\): error|critical medium error|Medium Error|blk_update_request|Buffer I/O error|failed command|XFS \([^)]*\): .*(error|corrupt))', re.I)
KDEV = re.compile(r'\b(sd[a-z]+|nvme\d+n\d+)\b')

def kernel():
    rc, o = run(['journalctl', '-k', '-q', '--since', '24 hours ago', '--no-pager', '-o', 'short-iso'], 30)
    if rc not in (0, 1):
        return {'io_errors': None, 'note': 'could not read the kernel log'}
    by, n, sample = {}, 0, None
    for line in o.splitlines():
        if not KERR.search(line): continue
        n += 1; sample = line
        m = KDEV.search(line)
        if m: by[m.group(1)] = by.get(m.group(1), 0) + 1
    return {'io_errors': n, 'by_dev': by, 'sample': cut(sample, 260) if sample else None, 'hours': 24}

def failed_units():
    out = []
    rc, o = run(['systemctl', 'list-units', '--state=failed', '--no-legend', '--plain'])
    for line in o.splitlines()[:8]:
        name = (line.split() or [''])[0]
        if not re.match(r'^[A-Za-z0-9@._:-]+$', name): continue
        rc, s = run(['systemctl', 'show', '-p', 'Result,ExecMainStatus,InactiveEnterTimestamp', name])
        kv = dict(l.split('=', 1) for l in s.splitlines() if '=' in l)
        rc, lg = run(['journalctl', '-u', name, '-n', '4', '--no-pager', '-o', 'cat'])
        ex = kv.get('ExecMainStatus', '')
        out.append({'name': name, 'result': kv.get('Result') or None, 'exit': int(ex) if ex.isdigit() else None,
                    'since': kv.get('InactiveEnterTimestamp') or None, 'log': [cut(l, 200) for l in lg.splitlines() if l.strip()][-4:]})
    return out

def runs(stores, job_list):
    out = []
    lines = []
    for f in ('index.1', 'index'):
        lines += read(os.path.join(TASKS_DIR, f), 2000000).splitlines()
    simple = all(re.match(r'^\d\d?:\d\d$', j['schedule'] or '') for j in job_list if j['enabled']) and any(j['enabled'] for j in job_list)
    # A run that began before jobs.cfg was last edited ran under a schedule
    # that may no longer be written there. It cannot be judged against today's.
    try: cfg_changed = os.path.getmtime(JOBS_CFG)
    except Exception: cfg_changed = NOW
    for line in lines:
        m = re.match(r'^(UPID:[^:]*:[0-9A-Fa-f]+:[0-9A-Fa-f]+:([0-9A-Fa-f]+):vzdump:([^:]*):[^:]*:)\s+([0-9A-Fa-f]+)\s+(.*)$', line.strip())
        if not m: continue
        upid, start, vmid, end, status = m.group(1), int(m.group(2), 16), m.group(3), int(m.group(4), 16), m.group(5).strip()
        if start < NOW - RUN_HOURS * 3600: continue
        r = {'start': datetime.fromtimestamp(start).strftime('%Y-%m-%d %H:%M'), 'start_ts': start, 'mins': round((end - start) / 60.0, 1),
             'status': cut(status, 60), 'ok': status.strip().upper() == 'OK', 'vmid': vmid or None, 'storage': None, 'error': None, 'size': None}
        # The run's own log says where it wrote and why it stopped.
        log = ''
        for p in glob.glob(os.path.join(TASKS_DIR, '*', upid)):
            try:
                sz = os.path.getsize(p)
                with open(p, 'r', errors='replace') as f:
                    log = f.read(12000)
                    if sz > 60000: f.seek(sz - 48000); log += '\n' + f.read()
                    else: log += f.read()
            except Exception:
                pass
            break
        if log:
            m2 = re.search(r'starting new backup job:.*?--storage[ =](\S+)', log)
            if m2: r['storage'] = m2.group(1).strip('\'"')
            if not r['storage']:
                m2 = re.search(r"creating vzdump archive '([^']+)'", log)
                if m2:
                    for s in stores:
                        if s.get('path') and m2.group(1).startswith(s['path'].rstrip('/') + '/'): r['storage'] = s['id']
            if not r['ok']:
                m2 = re.search(r'^.*No space left on device.*$', log, re.M)
                if m2: r['error'] = cut(m2.group(0)); r['no_space'] = True
                else:
                    errs = re.findall(r'^(?:ERROR|TASK ERROR):\s*(.+)$', log, re.M)
                    if errs: r['error'] = cut(errs[0])
            m2 = re.search(r'archive file size:\s*(\S+)', log)
            if m2: r['size'] = m2.group(1)
        if not r['storage']:
            # No task log (they are rotated). The log vzdump leaves beside the
            # archive is named for the moment the backup itself began: at the
            # task's start, or later if it first had to wait for a lock - but
            # never in the task's last half minute (that is another run
            # starting as this one ends).
            for s in stores:
                for ts, name in s.get('_logs', []):
                    if ts and (abs(ts - start) <= 90 or start <= ts <= end - 30) and (not vmid or ('-' + vmid + '-') in name): r['storage'] = s['id']
        # Is there a job in jobs.cfg that explains this run? Only answerable
        # when every enabled job has a plain HH:MM schedule.
        if simple and r['storage'] and start > cfg_changed:
            mins = datetime.fromtimestamp(start).hour * 60 + datetime.fromtimestamp(start).minute
            hit = False
            for j in job_list:
                if not j['enabled'] or j['storage'] != r['storage']: continue
                h, mm = (j['schedule'] or '0:0').split(':')
                if 0 <= mins - (int(h) * 60 + int(mm)) <= 3: hit = True
            r['listed'] = hit
        out.append(r)
    out.sort(key=lambda r: r['start_ts'], reverse=True)
    return out[:14]

def main():
    t0 = time.time()
    doc = {'v': 1, 'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(NOW)), 'at_ts': int(NOW)}
    parts = [('jobs', jobs), ('cron', cron_lines), ('disks', disks), ('kernel', kernel), ('failed_units', failed_units)]
    for key, fn in parts:
        try: doc[key] = fn()
        except Exception as e: doc[key] = None; doc.setdefault('errors', []).append(key + ': ' + cut(e, 120))
    try: doc['storages'] = storages(doc.get('jobs') or [])
    except Exception as e: doc['storages'] = None; doc.setdefault('errors', []).append('storages: ' + cut(e, 120))
    try: doc['runs'] = runs(doc.get('storages') or [], doc.get('jobs') or [])
    except Exception as e: doc['runs'] = None; doc.setdefault('errors', []).append('runs: ' + cut(e, 120))
    for s in doc.get('storages') or []: s.pop('_logs', None)
    doc['took_s'] = round(time.time() - t0, 1)
    text = json.dumps(doc, separators=(',', ':'))
    if OUT == '-':
        print(text); return
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + '.tmp'
    with open(tmp, 'w') as f: f.write(text)
    os.replace(tmp, OUT)        # whole file or the old one - the beat never reads half

if __name__ == '__main__':
    main()
PROBE_PY
chmod 755 "$PROBE"
python3 -m py_compile "$PROBE" 2>/dev/null || die "the probe did not compile under this python3 ($(python3 -V 2>&1)). Nothing else was changed."
rm -rf "$(dirname "$PROBE")/__pycache__" 2>/dev/null
ok "wrote $PROBE"

# ──────────────────────────────────────────────────────────────────────────
step "3 of 5  One real run"

mkdir -p "$(dirname "$REPORT")"
OUT="$REPORT" "$PROBE" || die "the probe exited with an error. Nothing else was changed. Run it by hand to see why:  $PROBE"
[[ -s "$REPORT" ]] || die "the probe wrote no report at $REPORT. Nothing else was changed."
ok "report written to $REPORT ($(wc -c < "$REPORT") bytes)"

# What it found, in words - this is what the controller will be judging.
python3 - "$REPORT" <<'SHOW'
import json, sys
d = json.load(open(sys.argv[1]))
def size(kb):
    kb = kb or 0
    return '%.1f TB' % (kb / 1073741824.0) if kb >= 1073741824 else '%d GB' % round(kb / 1048576.0) if kb >= 1048576 else '%d MB' % round(kb / 1024.0)
def age(s):
    return '%dd %dh' % (s // 86400, s % 86400 // 3600) if s >= 86400 else '%dh %dm' % (s // 3600, s % 3600 // 60)
print('\n      Backup storage')
for s in d.get('storages') or []:
    if 'path' not in s: print('        %-20s %s' % (s['id'], s.get('note', ''))); continue
    if not s.get('exists'): print('        %-20s %s  FOLDER MISSING' % (s['id'], s['path'])); continue
    n = s.get('newest')
    print('        %-20s %-9s %s free of %s   %s   jobs: %s' % (
        s['id'], 'mounted' if s.get('mounted') else ('NOT MOUNTED' if s.get('is_mountpoint') else 'folder'),
        size(s.get('avail_kb')), size(s.get('total_kb')),
        ('%d archive%s, newest %s (%s old)' % (s.get('archives', 0), '' if s.get('archives') == 1 else 's', size(n['kb']), age(n['age_s'])) if n else 'no archives'),
        ', '.join(s.get('jobs') or []) or 'none'))
print('\n      Backup runs, newest first')
for r in (d.get('runs') or [])[:8]:
    print('        %s  %-12s %6.1f min  %-11s %s' % (r['start'], r.get('storage') or '(unknown)', r['mins'], r['status'], r.get('error') or r.get('size') or ''))
if not d.get('runs'): print('        none in the last two days')
print('\n      Disks')
for x in d.get('disks') or []:
    bad = ', '.join('%s %s' % (k, x[k]) for k in ('realloc', 'pending', 'uncorrect', 'media_errors') if x.get(k))
    print('        /dev/%-8s %-28s %8s  SMART %-8s %s%s' % (x['dev'], (x.get('model') or '')[:28], size(x.get('size_kb')), x.get('smart'), bad, ('  (' + x['note'] + ')') if x.get('note') else ''))
k = d.get('kernel') or {}
print('\n      Kernel I/O errors, last 24h: %s%s' % (k.get('io_errors'), ('  latest: ' + k['sample']) if k.get('sample') else ''))
for u in d.get('failed_units') or []:
    print('      Failed unit: %s (exit %s)' % (u['name'], u.get('exit')))
if d.get('cron'): print('      vzdump lines outside jobs.cfg: ' + '; '.join(c['file'] for c in d['cron']))
if d.get('errors'): print('      Could not read: ' + '; '.join(d['errors']))
print()
SHOW

# ──────────────────────────────────────────────────────────────────────────
step "4 of 5  host-beat.sh carries the report"

if grep -q 'GS_STORAGE_PROBE_V1' "$BEAT"; then
    ok "$BEAT already carries it - not touched"
else
    TMP="$(mktemp)"
    python3 - "$BEAT" "$TMP" <<'BEATPATCH' || { rm -f "$TMP"; die "host-beat.sh is not the version this expects, so it was left exactly as it is. Paste the output of:  cat $BEAT"; }
import sys
src = open(sys.argv[1]).read()
lines = src.split('\n')
def find(text):
    hits = [i for i, l in enumerate(lines) if l.strip() == text]
    if len(hits) != 1:
        sys.stderr.write("      looked for exactly one line reading:  %s   (found %d)\n" % (text, len(hits))); sys.exit(1)
    return hits[0]
a = find('BODY=$(cat <<JSON')
b = find('"extra":{"dns_probe":"$(esc "$PROBE")"}}')
block = r"""# ── storage, disks and backups (GS_STORAGE_PROBE_V1) ────────────────────────
# storage-probe.py writes this report hourly. It is read back through a JSON
# parser before it goes into the beat, so a damaged file becomes null instead
# of a beat the Worker cannot parse - a beat that does not arrive is
# indistinguishable from an outage.
STORAGE="null"
if [[ -s /var/lib/host-beat/storage.json ]]; then
    STORAGE="$(python3 -c 'import sys,json; print(json.dumps(json.load(open(sys.argv[1])),separators=(",",":")))' /var/lib/host-beat/storage.json 2>/dev/null)"
    [[ -n "$STORAGE" ]] || STORAGE="null"
fi
""".split('\n')
lines[b] = lines[b].replace('"extra":{"dns_probe":"$(esc "$PROBE")"}}', '"extra":{"dns_probe":"$(esc "$PROBE")","storage":${STORAGE}}}')
lines[a:a] = block
open(sys.argv[2], 'w').write('\n'.join(lines))
BEATPATCH
    bash -n "$TMP" || { rm -f "$TMP"; die "the edited host-beat.sh does not parse. Nothing was changed."; }
    cp -p "$BEAT" "$BEAT.bak-048"
    cat "$TMP" > "$BEAT"; rm -f "$TMP"
    ok "$BEAT updated  (original kept at $BEAT.bak-048)"
    diff "$BEAT.bak-048" "$BEAT" | grep '^[<>]' | sed 's/^/      /'
fi

# ──────────────────────────────────────────────────────────────────────────
step "5 of 5  Hourly, from now on - and one beat right away"

cat > "$UNITS/storage-probe.service" <<'UNIT'
[Unit]
Description=Read disks, backup storage and backup runs for the GenieStack controller

[Service]
Type=oneshot
ExecStart=/usr/local/bin/storage-probe.py
User=root
Nice=10
IOSchedulingClass=idle
UNIT

cat > "$UNITS/storage-probe.timer" <<'UNIT'
[Unit]
Description=Storage and backup probe, hourly

[Timer]
OnBootSec=4min
OnUnitActiveSec=1h
AccuracySec=1min
Persistent=true

[Install]
WantedBy=timers.target
UNIT

systemctl daemon-reload
systemctl enable --now storage-probe.timer >/dev/null 2>&1
if systemctl is-active --quiet storage-probe.timer; then ok "storage-probe.timer is active"
else die "storage-probe.timer did not start. Check: systemctl status storage-probe.timer"; fi

if "$BEAT"; then ok "sent a beat carrying the report"
else warn "host-beat.sh exited with $? - the report will go with the next scheduled beat"; fi

printf '\n%sDone.%s The Infra tab shows storage, backups and disks for %s after the next refresh.\n' "$GRN" "$OFF" "$(hostname)"
printf 'Run the probe by hand:  /usr/local/bin/storage-probe.py ; python3 -m json.tool /var/lib/host-beat/storage.json | head -60\n'
printf 'Undo:                   systemctl disable --now storage-probe.timer ; cp %s.bak-048 %s\n\n' "$BEAT" "$BEAT"
