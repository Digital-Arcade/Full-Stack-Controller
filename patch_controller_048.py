#!/usr/bin/env python3
"""
patch_controller_048.py - the watchdog reads disks, backup storage and backup
runs, and says what is wrong in plain words.

Requires 045 (feed triage). Does not need 046/047. No SQL: the new readings
travel in the beat's existing `extra` field, as extra.storage, written by
storage-probe on the box (install-storage-probe.sh).

  python3 patch_controller_048.py worker.js

WHY
For five nights in a row (Oct 1-5) every backup to sysbackup died with
"No space left on device". The watchdog knew one word about backups - the
status of the LAST run - and one number about disks - how full / is. A run
that was OK hid two that failed; nothing looked at the backup disks at all;
nothing checked that an archive had actually landed.

WHAT IT CHECKS NOW (one finding each, text written here, no model call)
  critical - pages once, and again when it clears
    backup_wont_fit       free space on a backup storage is less than the
                          last archive. Proxmox prunes old backups only AFTER
                          a new one lands, so this is a failure tonight.
    backup_stale          a storage that has a job has no archive newer than
                          36 hours (or none at all).
    storage_not_mounted   a storage marked is_mountpoint is not mounted.
    storage_missing       a storage with a job whose folder does not exist.
    fs_errors             the filesystem on a backup disk says it has errors.
    disk_failing          SMART overall result is FAILED.
    disk_bad_sectors      pending or uncorrectable sectors.
    disk_io_errors        the kernel logged I/O errors in the last 24 hours.
  warn - console only
    backup_run_failed     the latest run to a storage failed; carries the
                          error line from the run's own log.
    backup_unlisted       a backup ran that no job in jobs.cfg schedules.
    backup_grew           the newest archive is 50% bigger than the one before.
    storage_full          a backup storage is 90% full.
    storage_dump_missing  the storage has no dump folder.
    disk_reallocated      reallocated sectors (worn, not yet failing).
    storage_probe_stale   the probe itself has not reported for 3 hours.

The old one-word backup_errors finding is dropped for a host that sends the
new readings (it would say the same thing with less). A host that does not
send them behaves exactly as before.

A failed systemd unit now carries its exit code and last log lines into the
finding, so the cause is in front of whoever reads it.
"""
import sys, os

HELPER_ANCHOR = '''// Conditions are detected here, in code, not by the model. Each returns a
'''

HELPER = r'''// ── storage, disks and backups (048) ────────────────────────────────────────
// storage-probe on the box looks hourly at every backup storage, every disk
// and every backup run, and the beat carries the result in extra.storage.
// These rules read it. Like the feed rules, each has exactly one meaning, so
// the words are written here rather than asked of the model.
const GS_STORE_STALE_S   = 3 * 3600;      // the probe runs hourly; three missed is not jitter
const GS_BACKUP_MAX_AGE_S = 36 * 3600;    // nightly jobs: a day and a half without an archive
const GS_BACKUP_RUN_WINDOW_S = 26 * 3600; // how far back a failed run still counts

function gsSize(kb) {
    kb = Number(kb) || 0;
    if (kb >= 1073741824) return (kb / 1073741824).toFixed(1) + ' TB';
    if (kb >= 1048576) return Math.round(kb / 1048576) + ' GB';
    if (kb >= 1024) return Math.round(kb / 1024) + ' MB';
    return Math.round(kb) + ' KB';
}

// "4 days" reads better than "109h" once it is past two days.
function gsAge(s) {
    s = Math.max(0, Math.floor(Number(s) || 0));
    return s >= 48 * 3600 ? Math.floor(s / 86400) + ' days' : gsFeedSpan(s);
}

// One beat -> findings about storage, disks and backups. Pure.
function gsStorageDetect(b) {
    const out = [];
    const p = b && b.extra && b.extra.storage;
    if (!p || typeof p !== 'object' || !p.at_ts) return out;
    const beatAge = Number(b.age_s == null ? 0 : b.age_s);
    if (beatAge > 15 * 60) return out;                    // the host is silent: nothing here is current
    const beatTs = Math.floor(new Date(b.beat_at).getTime() / 1000) || 0;
    const nowTs = beatTs + beatAge;
    const probeAge = Math.max(0, nowTs - Number(p.at_ts));
    const add = (kind, fingerprint, severity, verdict, steps, evidence) =>
        out.push({ kind, fingerprint, severity, candidate: null, verdict, steps, evidence });
    const px = 'Proxmox shell: ';

    if (probeAge > GS_STORE_STALE_S) {
        add('storage_probe_stale', 'probe-stale', 'warn',
            'The storage probe last ran ' + gsFeedSpan(probeAge) + ' ago. It runs hourly, so the disk and backup readings below it are old and nothing new is being checked.',
            '1. ' + px + 'systemctl list-timers storage-probe.timer --no-pager\n2. ' + px + '/usr/local/bin/storage-probe.py ; echo "exit: $?"',
            { probe_age_s: probeAge });
    }

    const stores = Array.isArray(p.storages) ? p.storages : [];
    stores.forEach((s) => {
        if (!s || !s.id || !s.path) return;
        const id = String(s.id), path = String(s.path);
        const hasJob = Array.isArray(s.jobs) && s.jobs.length > 0;
        const ev = { storage: id, path, device: s.device || null };

        if (s.exists === false) {
            if (hasJob) add('storage_missing', 'st-missing:' + id, 'critical',
                'Backup storage ' + id + ' points at ' + path + ', and that folder does not exist. A backup job is scheduled to it and cannot run.',
                '1. ' + px + 'ls -ld ' + path + '\n2. ' + px + 'lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINT,MODEL', ev);
            return;
        }
        if (s.is_mountpoint && s.mounted === false) {
            add('storage_not_mounted', 'st-unmounted:' + id, 'critical',
                'Backup storage ' + id + ' (' + path + ') is not mounted. It is marked is_mountpoint, so Proxmox refuses to write to it and backups to it are not happening.',
                '1. ' + px + 'lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINT,MODEL\n2. If the disk is listed without a mount point: ' + px + 'mount ' + path + '\n3. If the disk is not listed at all, it is unplugged, unpowered or dead.', ev);
            return;                                           // every other number would be the parent disk's
        }
        if (s.dump_ok === false && hasJob) {
            add('storage_dump_missing', 'st-nodump:' + id, 'warn',
                'Backup storage ' + id + ' has no dump folder at ' + path + '/dump. Proxmox creates it on the first backup, so this usually means no backup has ever been written here.',
                '1. ' + px + 'ls -la ' + path, ev);
        }
        const state = String(s.fs_state || '').toLowerCase();
        if ((state && state !== 'clean') || Number(s.fs_errors || 0) > 0) {
            add('fs_errors', 'fs:' + id, 'critical',
                'The filesystem on ' + id + ' (' + (s.device || path) + ') reports "' + (s.fs_state || 'errors') + '"' + (Number(s.fs_errors || 0) > 0 ? ', with ' + s.fs_errors + ' recorded errors' : '') + '. Backups written to a damaged filesystem cannot be trusted.',
                '1. ' + px + 'dmesg -T | grep -i -E \'ext4|I/O error\' | tail -30\n2. ' + px + 'smartctl -a ' + (s.device || '/dev/sdX') + ' | head -40\n3. A repair (fsck) needs the disk unmounted. Do not run it while a backup is writing.',
                { ...ev, fs_state: s.fs_state, fs_errors: s.fs_errors });
        }

        const newest = s.newest && s.newest.kb ? s.newest : null;
        const avail = s.avail_kb == null ? null : Number(s.avail_kb);
        const newestAge = newest ? Number(newest.age_s || 0) + probeAge : null;
        let noFit = false;
        if (newest && avail != null && avail < Number(newest.kb) * 1.05) {
            noFit = true;
            const keep = s.keep_last ? 'keep-last=' + s.keep_last : 'the retention setting';
            add('backup_wont_fit', 'st-nofit:' + id, 'critical',
                'The next backup to ' + id + ' will not fit. Free: ' + gsSize(avail) + '. Last archive: ' + gsSize(newest.kb) + '. Proxmox deletes old backups only AFTER a new one has landed, so ' + keep + ' needs room for one more than it keeps. The next run will die with "No space left on device".' +
                (newestAge > GS_BACKUP_MAX_AGE_S ? ' It has already been failing: the newest archive here is ' + gsAge(newestAge) + ' old.' : ''),
                '1. ' + px + 'ls -lh ' + path + '/dump/ | grep -v \'\\.log$\'\n2. Remove the oldest archive: Proxmox GUI > Datacenter > Storage > ' + id + ' > Backups > select the oldest > Remove.\n3. Then make it stay fixed: lower keep-last on ' + id + ', or send one of the jobs that write here to a bigger disk.',
                { ...ev, avail_kb: avail, newest_kb: newest.kb, newest_age_s: newestAge, archives: s.archives, keep_last: s.keep_last || null });
        } else if (Number(s.used_pct || 0) >= 90) {
            add('storage_full', 'st-full:' + id, 'warn',
                'Backup storage ' + id + ' is ' + Math.round(Number(s.used_pct)) + '% full (' + gsSize(avail) + ' free).' + (Number(s.other_kb || 0) > Number(s.archive_kb || 0) ? ' Most of it is not backups: ' + gsSize(s.other_kb) + ' of other data against ' + gsSize(s.archive_kb) + ' of archives.' : ''),
                '1. ' + px + 'ls -lh ' + path + ' ' + path + '/dump | tail -30',
                { ...ev, used_pct: s.used_pct, avail_kb: avail, archive_kb: s.archive_kb, other_kb: s.other_kb });
        }

        // One cause, one page: a storage already reported as "will not fit"
        // is not reported a second time as "no recent backup".
        if (hasJob && !noFit) {
            const age = newestAge;
            if (age == null || age > GS_BACKUP_MAX_AGE_S) {
                add('backup_stale', 'bk-stale:' + id, 'critical',
                    age == null
                        ? 'No backup has ever landed on ' + id + '. A job is scheduled to it (' + s.jobs.join(', ') + '), and ' + path + '/dump holds no archive.'
                        : 'The newest backup on ' + id + ' is ' + gsAge(age) + ' old (' + newest.name + '). A job is scheduled to it nightly, so at least one run has not produced an archive.',
                    '1. Look at the backup runs for this host in the Infra tab: the failed one carries its error.\n2. ' + px + 'ls -lh ' + path + '/dump/ | tail -12',
                    { ...ev, newest: newest ? newest.name : null, age_s: age, jobs: s.jobs });
            }
        }
        if (newest && s.prev_kb && Number(s.prev_kb) > 1048576 && Number(newest.kb) > Number(s.prev_kb) * 1.5) {
            add('backup_grew', 'bk-grew:' + id + ':' + newest.name, 'warn',
                'The newest backup on ' + id + ' is ' + gsSize(newest.kb) + ', up from ' + gsSize(s.prev_kb) + ' the time before. Something large was added inside the VM. Each backup now takes that much more room and time.',
                'Nothing to run now. Check that ' + id + ' still has room for one more than it keeps (free: ' + gsSize(avail) + ').',
                { ...ev, newest_kb: newest.kb, prev_kb: s.prev_kb });
        }
    });

    // Backup runs. Only the LATEST run to each storage is judged: a failure
    // followed by a success has already fixed itself.
    const runs = Array.isArray(p.runs) ? p.runs.filter(r => r && r.start_ts) : [];
    const latest = {};
    runs.forEach((r) => { const k = String(r.storage || '?'); if (!latest[k] || r.start_ts > latest[k].start_ts) latest[k] = r; });
    Object.keys(latest).forEach((k) => {
        const r = latest[k];
        if (r.ok || nowTs - Number(r.start_ts) > GS_BACKUP_RUN_WINDOW_S) return;
        const where = k === '?' ? 'an unidentified storage' : k;
        add('backup_run_failed', 'bk-fail:' + k + ':' + (r.no_space ? 'nospace' : String(r.status || 'failed').toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 30)), 'warn',
            'The last backup to ' + where + ' failed (' + r.start + ', after ' + r.mins + ' min): ' + (r.error || r.status || 'no reason recorded') + '.' +
            (r.no_space ? ' The disk filled before the archive finished. Old backups are only pruned after a new one lands, so it will fail the same way every night until space is freed.' : ''),
            r.no_space
                ? '1. Free space on ' + where + ': Proxmox GUI > Datacenter > Storage > ' + where + ' > Backups > remove the oldest.\n2. Then lower keep-last or move a job, so it does not fill again.'
                : '1. Proxmox GUI > Datacenter > Tasks > open the failed vzdump task from ' + r.start + ' and read the last 20 lines.',
            { storage: r.storage || null, start: r.start, mins: r.mins, status: r.status, error: r.error || null });
    });
    const seenUnlisted = {};
    runs.forEach((r) => {
        if (r.listed !== false || !r.storage || nowTs - Number(r.start_ts) > GS_BACKUP_RUN_WINDOW_S) return;
        const hhmm = String(r.start || '').slice(-5);
        const k = r.storage + ':' + hhmm;
        if (seenUnlisted[k]) return; seenUnlisted[k] = true;
        const cron = Array.isArray(p.cron) && p.cron.length ? ' A vzdump line exists outside jobs.cfg, in ' + p.cron.map(c => c.file).join(', ') + '.' : '';
        add('backup_unlisted', 'bk-unlisted:' + k, 'warn',
            'A backup ran at ' + hhmm + ' to ' + r.storage + ' that no job in /etc/pve/jobs.cfg schedules.' + cron + ' It uses the same disk space as the listed jobs. If you changed a schedule in the last day, ignore this: it clears by itself.',
            '1. ' + px + 'grep -rns vzdump /etc/cron.d /etc/crontab /var/spool/cron/crontabs /etc/pve/vzdump.cron\n2. ' + px + 'cat /etc/pve/jobs.cfg',
            { storage: r.storage, at: hhmm, cron: p.cron || [] });
    });

    // Disks.
    (Array.isArray(p.disks) ? p.disks : []).forEach((d) => {
        if (!d || !d.dev) return;
        const dev = String(d.dev), name = '/dev/' + dev + (d.model ? ' (' + d.model + ')' : '');
        const ev = { dev, model: d.model || null, smart: d.smart, realloc: d.realloc, pending: d.pending, uncorrect: d.uncorrect, media_errors: d.media_errors };
        const smartSteps = '1. ' + px + 'smartctl -a /dev/' + dev + ' | head -60\n2. Anything on this disk that exists nowhere else should be copied off first.';
        if (d.smart === 'FAILED') {
            add('disk_failing', 'smart:' + dev, 'critical', name + ' reports SMART overall health FAILED. The drive itself expects to fail.', smartSteps, ev);
        } else if (Number(d.pending || 0) > 0 || Number(d.uncorrect || 0) > 0) {
            add('disk_bad_sectors', 'sectors:' + dev, 'critical',
                name + ' has ' + Number(d.pending || 0) + ' pending and ' + Number(d.uncorrect || 0) + ' uncorrectable sectors. Those are places it could not read. SMART still says ' + (d.smart || 'unknown') + ', but this is how a failing disk starts.', smartSteps, ev);
        } else if (Number(d.realloc || 0) > 0 || Number(d.media_errors || 0) > 0) {
            add('disk_reallocated', 'realloc:' + dev + ':' + Number(d.realloc || d.media_errors || 0), 'warn',
                name + ' has ' + (Number(d.realloc || 0) > 0 ? d.realloc + ' reallocated sectors' : d.media_errors + ' media errors') + '. It has swapped out bad spots and is still working. Watch whether the number grows.', smartSteps, ev);
        }
    });
    const k = p.kernel;
    if (k && Number(k.io_errors || 0) > 0) {
        const devs = Object.keys(k.by_dev || {}).sort();
        add('disk_io_errors', 'kio:' + (devs.join(',') || 'unknown'), 'critical',
            'The kernel logged ' + k.io_errors + ' disk I/O or filesystem errors in the last ' + (k.hours || 24) + ' hours' + (devs.length ? ', on ' + devs.map(d => '/dev/' + d).join(', ') : '') + '. Latest: ' + (k.sample || '(not captured)'),
            '1. ' + px + 'dmesg -T | grep -i -E \'I/O error|ext4|medium error\' | tail -40' + (devs.length ? '\n2. ' + px + 'smartctl -a /dev/' + devs[0] + ' | head -60' : '') + '\n' + (devs.length ? '3' : '2') + '. For a USB disk, reseat the cable and check its power before blaming the drive.',
            { io_errors: k.io_errors, by_dev: k.by_dev || {}, sample: k.sample || null });
    }
    return out;
}

// Everything known about one host, from one beat. The old rules, then the
// storage rules. Two adjustments when the probe is reporting:
//   - the one-word "backup_errors" is dropped: backup_run_failed says the
//     same thing with the storage and the reason attached;
//   - a failed unit carries its exit code and last log lines.
function gsHostFindings(b) {
    const base = gsInfraDetect(b);
    const p = b && b.extra && b.extra.storage;
    if (!p || typeof p !== 'object' || !p.at_ts) return base;
    const units = Array.isArray(p.failed_units) ? p.failed_units : [];
    const kept = base.filter(f => !(f.kind === 'backup_errors' && Array.isArray(p.runs)));
    kept.forEach((f) => {
        if (f.kind !== 'failed_unit' || !units.length) return;
        const names = String((f.evidence && f.evidence.names) || '').split(',').map(s => s.trim());
        const detail = units.filter(u => names.indexOf(u.name) !== -1);
        if (detail.length) f.evidence = { ...f.evidence, detail };
    });
    return kept.concat(gsStorageDetect(b));
}

'''

DETECT_OLD = '''            const found = gsInfraDetect(b);
'''
DETECT_NEW = '''            const found = gsHostFindings(b);
'''

JUDGE_OLD = '''                const j = await gsInfraJudge(env, host, f, b);
'''
JUDGE_NEW = '''                // Storage and backup findings arrive with their words already
                // written (048); only the older kinds are put to the model.
                const j = f.verdict
                    ? { verdict: f.verdict, steps: f.steps || '', approve: false, why: null }
                    : await gsInfraJudge(env, host, f, b);
'''

SYS_OLD = '''HOW TO ANSWER
'''
SYS_NEW = '''DISKS, BACKUP STORAGE AND BACKUP RUNS
- Each host row carries extra.storage, written hourly by storage-probe on the box. Read it before asking the operator to run anything: most of what you would ask for is already there.
  - storages: one per Proxmox backup storage - mounted or not, device, used/free, how many archives, the newest archive (name, size, age), keep_last, and other_kb (space used by things that are NOT backups).
  - runs: every vzdump run of the last two days - start, minutes, status, which storage it wrote to, and for a failure the error line from its own task log. "listed": false means no job in jobs.cfg schedules a run at that time to that storage.
  - jobs and cron: the schedules in /etc/pve/jobs.cfg, and any vzdump line found outside it.
  - disks: SMART result and bad-sector counts per drive. kernel: I/O errors in the last 24 hours. failed_units: exit code and last log lines for each failed unit.
- vzdump backs up a whole VM. It has no idea what is inside it. Two jobs for the same vmid to two storages are two copies of the same image, not "system" and "user data".
- Proxmox prunes old backups only AFTER the new one has landed. A storage therefore needs room for keep_last + 1 archives per job writing to it. "No space left on device" part way through a run is this, and it repeats every night at the same minute until space is freed. It is not a lock and not a bad disk.
- last_backup_status is only the status word of the most recent run. With several runs a night one OK hides the failures. Use extra.storage.runs, never that word alone.
- feed-deadman.service in a failed state with exit code 1 is the dead-man reporting a stale feed, as designed (the script exits 1 after it alerts). It is not a crash. It clears on the next daily run once a file has imported.
- If extra.storage is absent the probe is not installed on that host; say so and name install-storage-probe.sh.

HOW TO ANSWER
'''


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'worker.js'
    if not os.path.exists(path):
        sys.exit(f"FAIL: {path} not found")
    src = open(path, encoding='utf-8').read()

    if 'function gsStorageDetect(' in src:
        print("already patched - nothing to do")
        return
    if 'function gsFeedSpan(' not in src:
        sys.exit("FAIL: 045 is not applied to this worker. Run patch_controller_045.py first. Nothing written.")

    hunks = [("helpers", HELPER_ANCHOR, HELPER + HELPER_ANCHOR),
             ("triage: findings", DETECT_OLD, DETECT_NEW),
             ("triage: judge", JUDGE_OLD, JUDGE_NEW),
             ("system prompt", SYS_OLD, SYS_NEW)]
    for name, old, _ in hunks:
        n = src.count(old)
        if n != 1:
            sys.exit(f"FAIL: {name} anchor found {n} times, expected exactly 1. Nothing written.")

    out = src
    for _, old, new in hunks:
        out = out.replace(old, new, 1)

    open(path + '.bak', 'w', encoding='utf-8').write(src)
    open(path, 'w', encoding='utf-8').write(out)
    print(f"patched {path} ({len(out)-len(src):+d} bytes). backup at {path}.bak")


if __name__ == '__main__':
    main()
