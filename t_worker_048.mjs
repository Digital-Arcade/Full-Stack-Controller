// Runs the REAL worker.js watchdog rules (patch 048) on what the storage probe
// reports. The three probe reports below were produced by the real
// storage-probe.py from a copy of pve built out of what was pasted from the
// box on 2026-10-05 (storage.cfg, jobs.cfg, the task index, the dump listing,
// the failed 02:00 task log). Nothing leaves this machine.
//
//   node t_worker_048.mjs <patched worker.js>
//
// Node 18 has WebCrypto but does not expose it as a global to modules (Node 20+
// does). The Worker signs its tokens with crypto.subtle, so hand it over.
import { webcrypto as __webcrypto } from 'node:crypto';
if (!globalThis.crypto || !globalThis.crypto.subtle) globalThis.crypto = __webcrypto;
import { readFileSync, writeFileSync, mkdtempSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import { pathToFileURL } from 'url';

const path = process.argv[2] || './worker.js';
const src = readFileSync(path, 'utf8');
if (!src.includes('function gsStorageDetect(')) { console.log('FAIL  this worker.js does not have patch 048 applied'); process.exit(1); }
let f = 0, n = 0; const ok = (l, c, x = '') => { n++; console.log(`${c ? 'PASS' : 'FAIL'}  ${l}${(!c && x) ? '  ' + String(x).slice(0, 600) : ''}`); if (!c) f++; };

// pve at 17:00 on Oct 5, after the old archives had been removed by hand.
const TODAY = {"v":1,"at":"2026-10-05T23:00:00Z","at_ts":1791241200,"jobs":[{"id":"backup-d9a4b0f0-b7cb","schedule":"21:00","storage":"sysbackup","vmid":"100","enabled":true},{"id":"backup-3bd271b4-5af1","schedule":"01:00","storage":"userbackup","vmid":"100","enabled":true}],"cron":[],"disks":[{"dev":"sda","model":"SAMSUNG MZ7L3960HCJR-00A07","tran":"sata","size_kb":937692504,"smart":"PASSED","realloc":0,"pending":0,"uncorrect":0,"temp_c":31},{"dev":"sdb","model":"SAMSUNG MZ7LH960HAJR-00005","tran":"sata","size_kb":937692504,"smart":"PASSED","realloc":0,"pending":0,"uncorrect":0,"temp_c":31},{"dev":"sdc","model":"SAMSUNG MZ7L33T8HBLT-00A07","tran":"sata","size_kb":3750738264,"smart":"PASSED","realloc":0,"pending":0,"uncorrect":0,"temp_c":31},{"dev":"sdd","model":"PSSD T7","tran":"usb","size_kb":976762584,"smart":"PASSED","realloc":0,"pending":0,"uncorrect":0,"temp_c":31},{"dev":"sde","model":"WDC WD80EDAZ-11CEWB0","tran":"sata","size_kb":7814026584,"smart":"PASSED","realloc":0,"pending":0,"uncorrect":0,"temp_c":31}],"kernel":{"io_errors":0,"by_dev":{},"sample":null,"hours":24},"failed_units":[{"name":"feed-deadman.service","result":"exit-code","exit":1,"since":"Mon 2026-10-05 09:07:01 MDT","log":["Starting feed-deadman.service - Alert if vehicle inventory deliveries have stopped...","feed-deadman.service: Main process exited, code=exited, status=1/FAILURE","feed-deadman.service: Failed with result 'exit-code'.","Failed to start feed-deadman.service - Alert if vehicle inventory deliveries have stopped."]}],"storages":[{"id":"local","type":"dir","path":"/var/lib/vz","is_mountpoint":false,"jobs":[],"keep_last":null,"exists":true,"mounted":false,"device":"rpool/ROOT/pve-1","fstype":"zfs","total_kb":1520148608,"avail_kb":1520148480,"used_kb":128,"used_pct":0.0,"dump_ok":false,"writable":true,"archives":0,"archive_kb":0,"newest":null,"prev_kb":null,"other_kb":128},{"id":"USB-Restore-Source","type":"dir","path":"/mnt/usb-restore","is_mountpoint":false,"jobs":[],"keep_last":null,"exists":true,"mounted":false,"device":"rpool/ROOT/pve-1","fstype":"zfs","total_kb":1520148608,"avail_kb":1520148480,"used_kb":128,"used_pct":0.0,"dump_ok":false,"writable":true,"archives":0,"archive_kb":0,"newest":null,"prev_kb":null,"other_kb":128},{"id":"sysbackup","type":"dir","path":"/mnt/sysbackup","is_mountpoint":true,"jobs":["backup-d9a4b0f0-b7cb"],"keep_last":3,"exists":true,"mounted":true,"device":"/dev/sdd","fstype":"ext4","total_kb":960303848,"avail_kb":714330296,"used_kb":197119040,"used_pct":21.6,"dump_ok":true,"writable":true,"archives":1,"archive_kb":197132288,"newest":{"name":"vzdump-qemu-100-2026_10_01-02_00_02.vma.zst","kb":197132288,"age_s":394920,"vmid":"100"},"prev_kb":null,"other_kb":0,"fs_state":"clean","fs_errors":0},{"id":"userbackup","type":"dir","path":"/mnt/userbackup","is_mountpoint":true,"jobs":["backup-3bd271b4-5af1"],"keep_last":3,"exists":true,"mounted":true,"device":"/dev/sde","fstype":"ext4","total_kb":7751272876,"avail_kb":7004141788,"used_kb":356413392,"used_pct":4.8,"dump_ok":true,"writable":true,"archives":0,"archive_kb":0,"newest":null,"prev_kb":null,"other_kb":356413392,"fs_state":"clean","fs_errors":0}],"runs":[{"start":"2026-10-05 02:00","start_ts":1791187201,"mins":53.2,"status":"job errors","ok":false,"vmid":"100","storage":"sysbackup","error":"zstd: error 70 : Write error : cannot write block : No space left on device","size":null,"no_space":true},{"start":"2026-10-04 22:00","start_ts":1791172819,"mins":34.6,"status":"OK","ok":true,"vmid":"100","storage":null,"error":null,"size":null},{"start":"2026-10-04 21:00","start_ts":1791169218,"mins":53.4,"status":"job errors","ok":false,"vmid":"100","storage":"sysbackup","error":null,"size":null},{"start":"2026-10-04 02:00","start_ts":1791100802,"mins":51.8,"status":"job errors","ok":false,"vmid":"100","storage":"sysbackup","error":null,"size":null},{"start":"2026-10-03 21:00","start_ts":1791082804,"mins":34.6,"status":"OK","ok":true,"vmid":"100","storage":null,"error":null,"size":null},{"start":"2026-10-03 21:00","start_ts":1791082804,"mins":86.7,"status":"job errors","ok":false,"vmid":"100","storage":"sysbackup","error":null,"size":null}],"took_s":0.0};
// pve at 03:10 on Oct 5, as sysbackup must have been when the runs failed: four archives, 116 GB free.
const BROKEN = {"v":1,"at":"2026-10-05T09:10:00Z","at_ts":1791191400,"jobs":[{"id":"backup-d9a4b0f0-b7cb","schedule":"21:00","storage":"sysbackup","vmid":"100","enabled":true},{"id":"backup-3bd271b4-5af1","schedule":"01:00","storage":"userbackup","vmid":"100","enabled":true}],"cron":[],"disks":[{"dev":"sda","model":"SAMSUNG MZ7L3960HCJR-00A07","tran":"sata","size_kb":937692504,"smart":"PASSED","realloc":0,"pending":0,"uncorrect":0,"temp_c":31},{"dev":"sdb","model":"SAMSUNG MZ7LH960HAJR-00005","tran":"sata","size_kb":937692504,"smart":"PASSED","realloc":0,"pending":0,"uncorrect":0,"temp_c":31},{"dev":"sdc","model":"SAMSUNG MZ7L33T8HBLT-00A07","tran":"sata","size_kb":3750738264,"smart":"PASSED","realloc":0,"pending":0,"uncorrect":0,"temp_c":31},{"dev":"sdd","model":"PSSD T7","tran":"usb","size_kb":976762584,"smart":"PASSED","realloc":0,"pending":0,"uncorrect":0,"temp_c":31},{"dev":"sde","model":"WDC WD80EDAZ-11CEWB0","tran":"sata","size_kb":7814026584,"smart":"PASSED","realloc":0,"pending":0,"uncorrect":0,"temp_c":31}],"kernel":{"io_errors":0,"by_dev":{},"sample":null,"hours":24},"failed_units":[{"name":"feed-deadman.service","result":"exit-code","exit":1,"since":"Mon 2026-10-05 09:07:01 MDT","log":["Starting feed-deadman.service - Alert if vehicle inventory deliveries have stopped...","feed-deadman.service: Main process exited, code=exited, status=1/FAILURE","feed-deadman.service: Failed with result 'exit-code'.","Failed to start feed-deadman.service - Alert if vehicle inventory deliveries have stopped."]}],"storages":[{"id":"local","type":"dir","path":"/var/lib/vz","is_mountpoint":false,"jobs":[],"keep_last":null,"exists":true,"mounted":false,"device":"rpool/ROOT/pve-1","fstype":"zfs","total_kb":1520148608,"avail_kb":1520148480,"used_kb":128,"used_pct":0.0,"dump_ok":false,"writable":true,"archives":0,"archive_kb":0,"newest":null,"prev_kb":null,"other_kb":128},{"id":"USB-Restore-Source","type":"dir","path":"/mnt/usb-restore","is_mountpoint":false,"jobs":[],"keep_last":null,"exists":true,"mounted":false,"device":"rpool/ROOT/pve-1","fstype":"zfs","total_kb":1520148608,"avail_kb":1520148480,"used_kb":128,"used_pct":0.0,"dump_ok":false,"writable":true,"archives":0,"archive_kb":0,"newest":null,"prev_kb":null,"other_kb":128},{"id":"sysbackup","type":"dir","path":"/mnt/sysbackup","is_mountpoint":true,"jobs":["backup-d9a4b0f0-b7cb"],"keep_last":3,"exists":true,"mounted":true,"device":"/dev/sdd","fstype":"ext4","total_kb":960303848,"avail_kb":122000000,"used_kb":790529152,"used_pct":86.6,"dump_ok":true,"writable":true,"archives":4,"archive_kb":788529152,"newest":{"name":"vzdump-qemu-100-2026_10_01-02_00_02.vma.zst","kb":197132288,"age_s":345120,"vmid":"100"},"prev_kb":197132288,"other_kb":2000000,"fs_state":"clean","fs_errors":0},{"id":"userbackup","type":"dir","path":"/mnt/userbackup","is_mountpoint":true,"jobs":["backup-3bd271b4-5af1"],"keep_last":3,"exists":true,"mounted":true,"device":"/dev/sde","fstype":"ext4","total_kb":7751272876,"avail_kb":7004141788,"used_kb":356413392,"used_pct":4.8,"dump_ok":true,"writable":true,"archives":0,"archive_kb":0,"newest":null,"prev_kb":null,"other_kb":356413392,"fs_state":"clean","fs_errors":0}],"runs":[{"start":"2026-10-05 02:00","start_ts":1791187201,"mins":53.2,"status":"job errors","ok":false,"vmid":"100","storage":"sysbackup","error":"zstd: error 70 : Write error : cannot write block : No space left on device","size":null,"no_space":true,"listed":false},{"start":"2026-10-04 22:00","start_ts":1791172819,"mins":34.6,"status":"OK","ok":true,"vmid":"100","storage":null,"error":null,"size":null},{"start":"2026-10-04 21:00","start_ts":1791169218,"mins":53.4,"status":"job errors","ok":false,"vmid":"100","storage":"sysbackup","error":null,"size":null,"listed":true},{"start":"2026-10-04 02:00","start_ts":1791100802,"mins":51.8,"status":"job errors","ok":false,"vmid":"100","storage":"sysbackup","error":null,"size":null},{"start":"2026-10-03 21:00","start_ts":1791082804,"mins":34.6,"status":"OK","ok":true,"vmid":"100","storage":null,"error":null,"size":null},{"start":"2026-10-03 21:00","start_ts":1791082804,"mins":86.7,"status":"job errors","ok":false,"vmid":"100","storage":"sysbackup","error":null,"size":null},{"start":"2026-10-03 02:00","start_ts":1791014402,"mins":55.6,"status":"job errors","ok":false,"vmid":"100","storage":"sysbackup","error":null,"size":null}],"took_s":0.0};
// The same box with a failing drive and kernel I/O errors.
const FAULTS = {"v":1,"at":"2026-10-05T23:00:00Z","at_ts":1791241200,"jobs":[{"id":"backup-d9a4b0f0-b7cb","schedule":"21:00","storage":"sysbackup","vmid":"100","enabled":true},{"id":"backup-3bd271b4-5af1","schedule":"01:00","storage":"userbackup","vmid":"100","enabled":true}],"cron":[],"disks":[{"dev":"sda","model":"SAMSUNG MZ7L3960HCJR-00A07","tran":"sata","size_kb":937692504,"smart":"PASSED","realloc":0,"pending":0,"uncorrect":0,"temp_c":31},{"dev":"sdb","model":"SAMSUNG MZ7LH960HAJR-00005","tran":"sata","size_kb":937692504,"smart":"unknown","note":"smartctl is not installed"},{"dev":"sdc","model":"SAMSUNG MZ7L33T8HBLT-00A07","tran":"sata","size_kb":3750738264,"smart":"asleep"},{"dev":"sdd","model":"PSSD T7","tran":"usb","size_kb":976762584,"smart":"PASSED","realloc":0,"pending":0,"uncorrect":0,"temp_c":31},{"dev":"sde","model":"WDC WD80EDAZ-11CEWB0","tran":"sata","size_kb":7814026584,"smart":"FAILED","realloc":64,"pending":8,"uncorrect":3}],"kernel":{"io_errors":2,"by_dev":{"sde":2},"sample":"2026-10-05T03:11:03-0600 pve kernel: EXT4-fs error (device sde): ext4_find_entry:1658: inode #2: comm ls: reading directory lblock 0","hours":24},"failed_units":[{"name":"feed-deadman.service","result":"exit-code","exit":1,"since":"Mon 2026-10-05 09:07:01 MDT","log":["Starting feed-deadman.service - Alert if vehicle inventory deliveries have stopped...","feed-deadman.service: Main process exited, code=exited, status=1/FAILURE","feed-deadman.service: Failed with result 'exit-code'.","Failed to start feed-deadman.service - Alert if vehicle inventory deliveries have stopped."]}],"storages":[{"id":"local","type":"dir","path":"/var/lib/vz","is_mountpoint":false,"jobs":[],"keep_last":null,"exists":true,"mounted":false,"device":"rpool/ROOT/pve-1","fstype":"zfs","total_kb":1520148608,"avail_kb":1520148480,"used_kb":128,"used_pct":0.0,"dump_ok":false,"writable":true,"archives":0,"archive_kb":0,"newest":null,"prev_kb":null,"other_kb":128},{"id":"USB-Restore-Source","type":"dir","path":"/mnt/usb-restore","is_mountpoint":false,"jobs":[],"keep_last":null,"exists":true,"mounted":false,"device":"rpool/ROOT/pve-1","fstype":"zfs","total_kb":1520148608,"avail_kb":1520148480,"used_kb":128,"used_pct":0.0,"dump_ok":false,"writable":true,"archives":0,"archive_kb":0,"newest":null,"prev_kb":null,"other_kb":128},{"id":"sysbackup","type":"dir","path":"/mnt/sysbackup","is_mountpoint":true,"jobs":["backup-d9a4b0f0-b7cb"],"keep_last":3,"exists":true,"mounted":true,"device":"/dev/sdd","fstype":"ext4","total_kb":960303848,"avail_kb":714330296,"used_kb":197119040,"used_pct":21.6,"dump_ok":true,"writable":true,"archives":1,"archive_kb":197132288,"newest":{"name":"vzdump-qemu-100-2026_10_01-02_00_02.vma.zst","kb":197132288,"age_s":394920,"vmid":"100"},"prev_kb":null,"other_kb":0,"fs_state":"clean","fs_errors":0},{"id":"userbackup","type":"dir","path":"/mnt/userbackup","is_mountpoint":true,"jobs":["backup-3bd271b4-5af1"],"keep_last":3,"exists":true,"mounted":true,"device":"/dev/sde","fstype":"ext4","total_kb":7751272876,"avail_kb":7004141788,"used_kb":356413392,"used_pct":4.8,"dump_ok":true,"writable":true,"archives":0,"archive_kb":0,"newest":null,"prev_kb":null,"other_kb":356413392,"fs_state":"clean","fs_errors":0}],"runs":[{"start":"2026-10-05 02:00","start_ts":1791187201,"mins":53.2,"status":"job errors","ok":false,"vmid":"100","storage":"sysbackup","error":"zstd: error 70 : Write error : cannot write block : No space left on device","size":null,"no_space":true},{"start":"2026-10-04 22:00","start_ts":1791172819,"mins":34.6,"status":"OK","ok":true,"vmid":"100","storage":null,"error":null,"size":null},{"start":"2026-10-04 21:00","start_ts":1791169218,"mins":53.4,"status":"job errors","ok":false,"vmid":"100","storage":"sysbackup","error":null,"size":null},{"start":"2026-10-04 02:00","start_ts":1791100802,"mins":51.8,"status":"job errors","ok":false,"vmid":"100","storage":"sysbackup","error":null,"size":null},{"start":"2026-10-03 21:00","start_ts":1791082804,"mins":34.6,"status":"OK","ok":true,"vmid":"100","storage":null,"error":null,"size":null},{"start":"2026-10-03 21:00","start_ts":1791082804,"mins":86.7,"status":"job errors","ok":false,"vmid":"100","storage":"sysbackup","error":null,"size":null}],"took_s":0.0};

// ── load the Worker ─────────────────────────────────────────────────────────
const SB = 'https://supabase.test';
const db = { beats: [], findings: [], mail: [], health: [] }; const claude = [];
const json = (b, status = 200) => new Response(JSON.stringify(b), { status, headers: { 'Content-Type': 'application/json' } });
globalThis.fetch = async (input, init = {}) => {
  const u = new URL(typeof input === 'string' ? input : input.url);
  const method = (init.method || 'GET').toUpperCase();
  const body = init.body ? (() => { try { return JSON.parse(init.body); } catch { return init.body; } })() : null;
  if (u.host === 'api.resend.com') { db.mail.push(body); return json({ id: 'm' }); }
  if (u.host === 'api.anthropic.com') { claude.push(body); return json({ content: [{ type: 'text', text: '{"verdict":"Model verdict.","steps":"1. Proxmox shell: look","approve_remedy":false,"why":"n/a"}' }], stop_reason: 'end_turn' }); }
  if (u.host !== 'supabase.test') return json({});
  const table = u.pathname.replace('/rest/v1/', '');
  if (table === 'gs_host_beats' && method === 'GET') return json(db.beats);
  if (table === 'gs_host_beats' && method === 'POST') { db.inserted = body; return new Response('', { status: 201 }); }
  if (table === 'gs_feed_health') return json(db.health);
  if (table === 'gs_infra_findings' && method === 'GET') return json(db.findings.filter(x => !x.resolved_at));
  if (table === 'gs_infra_findings' && method === 'POST') { db.findings.push({ id: db.findings.length + 1, ...body }); return new Response('', { status: 201 }); }
  if (table === 'gs_infra_findings' && method === 'PATCH') { const id = Number((u.searchParams.get('id') || '').replace('eq.', '')); const row = db.findings.find(x => x.id === id); if (row) Object.assign(row, body); return new Response(null, { status: 204 }); }
  return json([]);
};
const dir = mkdtempSync(join(tmpdir(), 'gsw-')); const mod = join(dir, 'worker.mjs');
// Test-only: expose three internals from the temp copy. The file on disk is not touched.
writeFileSync(mod, src + '\nexport const __t = { host: gsHostFindings, store: gsStorageDetect, old: gsInfraDetect, sys: GS_CTL_ASK_SYSTEM };\n');
const m = await import(pathToFileURL(mod).href);
const worker = m.default, t = m.__t;

const clone = (o) => JSON.parse(JSON.stringify(o));
// A beat as gs_host_beats holds it, carrying a probe report taken `probeAgoMin` before the beat.
const beat = (probe, o = {}, probeAgoMin = 20) => {
  const beatTs = ((probe && probe.at_ts) || 1791241200) + probeAgoMin * 60;
  return { host: 'pve', beat_at: new Date(beatTs * 1000).toISOString(), age_s: 120, failed_units: 0, failed_unit_names: null, dns_ok: true, feed_timer_ok: true,
           last_backup_status: 'job errors', disk_used_pct: 12, extra: probe ? { dns_probe: 'ftp.dealerslink.com', storage: probe } : { dns_probe: 'ftp.dealerslink.com' }, ...o };
};
const kinds = (list) => list.map(x => x.kind + ':' + x.severity).sort().join(' | ');
const one = (list, kind, storage) => list.find(x => x.kind === kind && (!storage || (x.evidence && x.evidence.storage === storage)));
const H = 3600;

// ── 1. a host without the probe ─────────────────────────────────────────────
console.log('\n1. A host that does not run the probe yet');
{
  const b = beat(null, { failed_units: 1, failed_unit_names: 'feed-deadman.service' });
  ok('exactly the old findings, nothing added, nothing dropped (failed unit + the one-word backup_errors)', JSON.stringify(t.host(b)) === JSON.stringify(t.old(b)) && kinds(t.host(b)) === 'backup_errors:warn | failed_unit:warn', kinds(t.host(b)));
  ok('the storage rules say nothing without a report', t.store(b).length === 0 && t.store(beat({})).length === 0 && t.store({}).length === 0);
}

// ── 2. the night it broke ───────────────────────────────────────────────────
console.log('\n2. 03:10 on Oct 5 - what the watchdog would have said that night');
{
  const fnd = t.host(beat(BROKEN));
  const fit = one(fnd, 'backup_wont_fit', 'sysbackup');
  ok('sysbackup: "will not fit", critical - the finding that would have paged on Oct 1 instead of five silent nights', !!fit && fit.severity === 'critical', kinds(fnd));
  ok('with the real numbers: 116 GB free, 188 GB last archive, keep-last=3', /Free: 116 GB\. Last archive: 188 GB\./.test(fit.verdict) && /keep-last=3 needs room for one more than it keeps/.test(fit.verdict), fit && fit.verdict);
  ok('it says it has already been failing, and for how long', /It has already been failing: the newest archive here is 4 days old\.$/.test(fit.verdict), fit.verdict);
  ok('steps name the machine, list the archives, and send the delete through the GUI (no rm with a wildcard)', /1\. Proxmox shell: ls -lh \/mnt\/sysbackup\/dump\//.test(fit.steps) && /Datacenter > Storage > sysbackup > Backups/.test(fit.steps) && !/\brm\b/.test(fit.steps), fit.steps);
  ok('one cause, one page: sysbackup is not ALSO reported as "no recent backup"', !one(fnd, 'backup_stale', 'sysbackup'));
  const run = one(fnd, 'backup_run_failed');
  ok('the failed 02:00 run is reported with the line from its own log', !!run && run.severity === 'warn' && /The last backup to sysbackup failed \(2026-10-05 02:00, after 53\.2 min\): zstd: error 70 : Write error : cannot write block : No space left on device\./.test(run.verdict), run && run.verdict);
  ok('and explains why it repeats every night', /Old backups are only pruned after a new one lands, so it will fail the same way every night until space is freed/.test(run.verdict));
  const un = one(fnd, 'backup_unlisted');
  ok('the 02:00 run that no job in jobs.cfg schedules is called out (jobs.cfg lists 21:00 and 01:00)', !!un && /A backup ran at 02:00 to sysbackup that no job in \/etc\/pve\/jobs\.cfg schedules/.test(un.verdict) && /grep -rns vzdump \/etc\/cron\.d/.test(un.steps), un && un.verdict);
  ok('the 21:00 run, which jobs.cfg does schedule, is not', fnd.filter(x => x.kind === 'backup_unlisted').length === 1);
  const us = one(fnd, 'backup_stale', 'userbackup');
  ok('userbackup: "no backup has ever landed", critical, naming its job', !!us && us.severity === 'critical' && /No backup has ever landed on userbackup\. A job is scheduled to it \(backup-3bd271b4-5af1\)/.test(us.verdict), us && us.verdict);
  ok('the old one-word backup_errors is gone - backup_run_failed replaces it', !one(fnd, 'backup_errors'));
  ok('all of it, and nothing else', kinds(fnd) === 'backup_run_failed:warn | backup_stale:critical | backup_unlisted:warn | backup_wont_fit:critical', kinds(fnd));
  ok('every storage finding carries its own words and steps, so none is sent to the model', fnd.every(x => x.verdict && x.steps && x.candidate === null));
}

// ── 3. this afternoon ───────────────────────────────────────────────────────
console.log('\n3. 17:00 on Oct 5 - space freed by hand, no successful backup yet');
{
  const fnd = t.host(beat(TODAY, { failed_units: 1, failed_unit_names: 'feed-deadman.service' }));
  ok('sysbackup now has room (682 GB free), so "will not fit" is gone', !one(fnd, 'backup_wont_fit'), kinds(fnd));
  const st = one(fnd, 'backup_stale', 'sysbackup');
  ok('but its newest archive is from Oct 1: "no recent backup", critical, naming the file', !!st && st.severity === 'critical' && /^The newest backup on sysbackup is 4 days old \(vzdump-qemu-100-2026_10_01-02_00_02\.vma\.zst\)\. A job is scheduled to it nightly/.test(st.verdict), st && st.verdict);
  ok('this morning\'s failed run is still on the list until a run succeeds', !!one(fnd, 'backup_run_failed'));
  ok('jobs.cfg was edited today, so nothing is called unlisted yet', !one(fnd, 'backup_unlisted'));
  const fu = one(fnd, 'failed_unit');
  ok('the failed feed-deadman.service finding carries exit code 1 and its last log lines', !!fu && fu.evidence.detail && fu.evidence.detail[0].name === 'feed-deadman.service' && fu.evidence.detail[0].exit === 1 && fu.evidence.detail[0].log.some(l => /status=1\/FAILURE/.test(l)), fu && JSON.stringify(fu.evidence));
  ok('all drives pass SMART and the kernel log is clean: no disk findings', !fnd.some(x => /^disk_|^fs_/.test(x.kind)));
  ok('all of it', kinds(fnd) === 'backup_run_failed:warn | backup_stale:critical | backup_stale:critical | failed_unit:warn', kinds(fnd));
}

// ── 4. tomorrow, fixed ──────────────────────────────────────────────────────
console.log('\n4. After a good night');
{
  const p = clone(TODAY); const at = p.at_ts + 12 * H; p.at_ts = at;
  const good = (st, start, name) => { const s = p.storages.find(x => x.id === st); s.prev_kb = s.newest ? s.newest.kb : null; s.newest = { name, kb: 197000000, age_s: at - start - 1800, vmid: '100' }; s.archives = (s.archives || 0) + 1; s.archive_kb = (s.archive_kb || 0) + 197000000; s.avail_kb -= 197000000; };
  good('sysbackup', TODAY.at_ts + 4 * H, 'vzdump-qemu-100-2026_10_05-21_00_02.vma.zst'); good('userbackup', TODAY.at_ts + 8 * H, 'vzdump-qemu-100-2026_10_06-01_00_02.vma.zst');
  p.runs = [{ start: '2026-10-06 01:00', start_ts: TODAY.at_ts + 8 * H, mins: 34, status: 'OK', ok: true, vmid: '100', storage: 'userbackup', listed: true },
            { start: '2026-10-05 21:00', start_ts: TODAY.at_ts + 4 * H, mins: 78, status: 'OK', ok: true, vmid: '100', storage: 'sysbackup', listed: true }].concat(p.runs);
  p.failed_units = [];
  const fnd = t.host(beat(p, { last_backup_status: 'OK' }));
  ok('both storages have a fresh archive and the last run to each was OK: no findings at all', fnd.length === 0, kinds(fnd));
  ok('a failure followed by a success on the same storage is not reported (only the latest run counts)', !t.store(beat(p)).some(x => x.kind === 'backup_run_failed'));
}

// ── 5. every other rule, one at a time ──────────────────────────────────────
console.log('\n5. The other rules');
{
  const base = () => { const p = clone(TODAY); p.runs = []; p.failed_units = []; p.storages.forEach(s => { if (s.jobs && s.jobs.length) { s.newest = { name: 'vzdump-qemu-100-2026_10_05-21_00_02.vma.zst', kb: 197000000, age_s: 2 * H, vmid: '100' }; s.prev_kb = 197000000; s.archives = 2; s.archive_kb = 394000000; } }); return p; };
  ok('(a healthy report raises nothing)', t.store(beat(base())).length === 0, kinds(t.store(beat(base()))));
  let p = base(); p.storages.find(s => s.id === 'userbackup').mounted = false;
  let fnd = t.store(beat(p));
  ok('backup disk not mounted: critical, says Proxmox refuses to write, gives mount steps - and none of the other numbers for it are judged', kinds(fnd) === 'storage_not_mounted:critical' && /userbackup \(\/mnt\/userbackup\) is not mounted\. It is marked is_mountpoint/.test(fnd[0].verdict) && /mount \/mnt\/userbackup/.test(fnd[0].steps), kinds(fnd));
  p = base(); Object.assign(p.storages.find(s => s.id === 'USB-Restore-Source'), { mounted: false });
  ok('a storage NOT marked is_mountpoint and with no job (USB-Restore-Source) is never judged for being unmounted', t.store(beat(p)).length === 0);
  p = base(); Object.assign(p.storages.find(s => s.id === 'sysbackup'), { exists: false });
  ok('storage folder missing with a job on it: critical', kinds(t.store(beat(p))) === 'storage_missing:critical');
  p = base(); Object.assign(p.storages.find(s => s.id === 'userbackup'), { fs_state: 'not clean with errors', fs_errors: 12 });
  fnd = t.store(beat(p));
  ok('filesystem errors: critical, quotes the state and the count, warns against fsck during a backup', kinds(fnd) === 'fs_errors:critical' && /reports "not clean with errors", with 12 recorded errors/.test(fnd[0].verdict) && /needs the disk unmounted/.test(fnd[0].steps));
  p = base(); Object.assign(p.storages.find(s => s.id === 'userbackup'), { used_pct: 93.4, avail_kb: 512000000, archive_kb: 394000000, other_kb: 6800000000 });
  fnd = t.store(beat(p));
  ok('90% full but the next backup still fits: warn only, and it says most of it is not backups', kinds(fnd) === 'storage_full:warn' && /is 93% full \(488 GB free\)\. Most of it is not backups: 6\.3 TB of other data against 376 GB of archives/.test(fnd[0].verdict), fnd[0] && fnd[0].verdict);
  p = base(); Object.assign(p.storages.find(s => s.id === 'sysbackup'), { prev_kb: 99000000 });
  fnd = t.store(beat(p));
  ok('archive doubled since the last one (what happened on Sep 29): warn "grew", with both sizes', kinds(fnd) === 'backup_grew:warn' && /is 188 GB, up from 94 GB the time before/.test(fnd[0].verdict), fnd[0] && fnd[0].verdict);
  p = base(); p.storages.find(s => s.id === 'sysbackup').newest.age_s = 35 * H;
  ok('newest archive 35h 20m old: not yet stale', t.store(beat(p)).length === 0);
  p.storages.find(s => s.id === 'sysbackup').newest.age_s = 36 * H;
  ok('36h 20m: stale', kinds(t.store(beat(p))) === 'backup_stale:critical');
  p = base(); p.storages.find(s => s.id === 'sysbackup').avail_kb = 197000000 * 1.04;
  ok('free space within 5% of the last archive counts as "will not fit" (archives grow)', kinds(t.store(beat(p))) === 'backup_wont_fit:critical');
  p = base(); p.storages.find(s => s.id === 'sysbackup').dump_ok = false; p.storages.find(s => s.id === 'sysbackup').newest = null;
  ok('no dump folder: warn, alongside "no backup has ever landed"', kinds(t.store(beat(p))) === 'backup_stale:critical | storage_dump_missing:warn');

  fnd = t.store(beat(FAULTS));
  const df = one(fnd, 'disk_failing');
  ok('SMART FAILED on sde: critical, names the drive model', !!df && df.severity === 'critical' && /\/dev\/sde \(WDC WD80EDAZ-11CEWB0\) reports SMART overall health FAILED/.test(df.verdict) && /smartctl -a \/dev\/sde/.test(df.steps), kinds(fnd));
  ok('one finding for that drive, not three (failed covers the bad sectors)', fnd.filter(x => /^disk_(failing|bad|realloc)/.test(x.kind)).length === 1);
  const io = one(fnd, 'disk_io_errors');
  ok('kernel I/O errors: critical, with the count, the device and the latest line', !!io && /logged 2 disk I\/O or filesystem errors in the last 24 hours, on \/dev\/sde\. Latest: .*EXT4-fs error \(device sde\)/.test(io.verdict) && /For a USB disk, reseat the cable/.test(io.steps), io && io.verdict);
  ok('a sleeping drive and one with no smartctl answer raise nothing', !fnd.some(x => x.evidence && (x.evidence.dev === 'sdc' || x.evidence.dev === 'sdb')));
  p = base(); Object.assign(p.disks.find(d => d.dev === 'sde'), { pending: 8, uncorrect: 0 });
  ok('pending sectors while SMART still says PASSED: critical all the same', kinds(t.store(beat(p))) === 'disk_bad_sectors:critical' && /8 pending and 0 uncorrectable sectors/.test(t.store(beat(p))[0].verdict));
  p = base(); Object.assign(p.disks.find(d => d.dev === 'sda'), { realloc: 4 });
  fnd = t.store(beat(p));
  ok('reallocated sectors only: warn, and the count is part of its identity so a rise files a new finding', kinds(fnd) === 'disk_reallocated:warn' && fnd[0].fingerprint === 'realloc:sda:4');

  ok('probe report 2h 50m old: still trusted', !t.store(beat(base(), {}, 170)).some(x => x.kind === 'storage_probe_stale'));
  fnd = t.store(beat(base(), {}, 200));
  ok('3h 20m old: "probe stale" warn, with the timer command', kinds(fnd) === 'storage_probe_stale:warn' && /storage probe last ran 3h 2\dm ago/.test(fnd[0].verdict) && /systemctl list-timers storage-probe\.timer/.test(fnd[0].steps), fnd[0] && fnd[0].verdict);
  ok('a silent host: the storage rules stay quiet (the report is not current, and "silent host" already paged)', t.store(beat(BROKEN, { age_s: 3600 })).length === 0 && kinds(t.host(beat(BROKEN, { age_s: 3600 }))) === 'silent_host:critical');
  ok('garbage where the report should be does not throw', t.store(beat(null, { extra: { storage: 'nope' } })).length === 0 && t.store(beat(null, { extra: { storage: { at_ts: 1, storages: 'x', runs: 5, disks: [null, 7], kernel: 'k' } } })).length >= 0);
  const uniq = (list) => { const fps = list.map(x => x.fingerprint); return new Set(fps).size === fps.length && fps.every(x => /:/.test(x) || x === 'probe-stale'); };
  ok('within one report every finding has its own fingerprint, tied to its storage or drive, so one fault is one finding', uniq(t.host(beat(BROKEN))) && uniq(t.store(beat(FAULTS))) && uniq(t.store(beat(TODAY))));
}

// ── 6. the real cron pass ───────────────────────────────────────────────────
console.log('\n6. The triage pass, end to end');
{
  const kv = new Map();
  const env = { SUPABASE_URL: SB, SUPABASE_ANON_KEY: 'anon', SUPABASE_SERVICE_ROLE_KEY: 'svc', SUPABASE_JWT_SECRET: 'jwt-secret-for-tests', FEED_ALERT_EMAIL: 'ops@example.com', RESEND_API_KEY: 'resend', CLAUDE_API_KEY: 'not-a-real-key',
                DEPLOYMENTS: { get: async (k) => kv.get(k) || null, put: async (k, v) => { kv.set(k, v); }, delete: async (k) => { kv.delete(k); } } };
  const ctx = { waitUntil: (p) => { ctx.jobs.push(Promise.resolve(p).catch(() => {})); }, jobs: [] };
  const say = console.log, warn = console.warn;
  const pass = async () => { console.log = () => {}; console.warn = () => {}; try { kv.clear(); ctx.jobs = []; await worker.scheduled({}, env, ctx); await Promise.all(ctx.jobs); } finally { console.log = say; console.warn = warn; } };
  const live = (probe, o) => { const b = beat(probe, o); b.beat_at = new Date(Date.now() - 120000).toISOString(); delete b.age_s; const p = clone(probe); p.at_ts = Math.floor(Date.now() / 1000) - 1320; b.extra.storage = p; return b; };

  db.beats = [live(BROKEN, { failed_units: 1, failed_unit_names: 'feed-deadman.service' })];
  await pass();
  const filed = db.findings.map(x => x.kind + ':' + x.severity).sort().join(' | ');
  ok('files the five findings for that night under host pve', filed === 'backup_run_failed:warn | backup_stale:critical | backup_unlisted:warn | backup_wont_fit:critical | failed_unit:warn' && db.findings.every(x => x.host === 'pve'), filed);
  const fit = db.findings.find(x => x.kind === 'backup_wont_fit');
  ok('with the words written in code, no remedy queued', /will not fit\. Free: 116 GB/.test(fit.verdict) && /Datacenter > Storage > sysbackup/.test(fit.steps) && fit.remedy === null && fit.remedy_state === 'none');
  ok('the model is asked about the failed unit only - the four storage findings cost nothing', claude.length === 1 && /failed_unit/.test(JSON.stringify(claude[0].messages)), claude.length);
  ok('and what the model is shown for that unit includes its exit code and log lines', /"exit": 1/.test(claude[0].messages[0].content) && /status=1\/FAILURE/.test(claude[0].messages[0].content));
  const subj = db.mail.map(x => x.subject).sort();
  ok('two pages go out, one per critical finding: "will not fit" on sysbackup, "no backup ever" on userbackup', subj.length === 2 && subj[0] === 'Infra: backup stale on pve' && subj[1] === 'Infra: backup wont fit on pve', JSON.stringify(subj));
  const page = db.mail.find(x => /wont fit/.test(x.subject));
  ok('the page carries the numbers and the steps', /Free: 116 GB\. Last archive: 188 GB/.test(page.html) && /What to do:/.test(page.html) && /needs you/.test(page.html));
  await pass();
  ok('a second pass files nothing and pages nobody (one fault, one finding, one page)', db.findings.length === 5 && db.mail.length === 2 && claude.length === 1);

  // space freed, a good backup lands on both
  const p = clone(BROKEN); p.runs = [{ start: 'x 21:00', start_ts: Math.floor(Date.now() / 1000) - 3 * H, mins: 78, status: 'OK', ok: true, storage: 'sysbackup', listed: true }]; p.failed_units = [];
  p.storages.forEach(s => { if (s.jobs && s.jobs.length) { s.newest = { name: 'vzdump-qemu-100-new.vma.zst', kb: 197000000, age_s: 2 * H, vmid: '100' }; s.prev_kb = 197000000; s.avail_kb = 500000000; } });
  db.beats = [live(p, { last_backup_status: 'OK' })];
  await pass();
  ok('once backups land again every finding resolves by itself', db.findings.every(x => !!x.resolved_at), db.findings.filter(x => !x.resolved_at).map(x => x.kind).join(','));
  const cleared = db.mail.slice(2).map(x => x.subject).sort();
  ok('and the two that paged each send one "Cleared"', cleared.length === 2 && cleared[0] === 'Cleared: backup stale on pve' && cleared[1] === 'Cleared: backup wont fit on pve', JSON.stringify(cleared));
}

// ── 6b. the beat route keeps the report ─────────────────────────────────────
console.log('\n6b. The beat route');
{
  const env = { SUPABASE_URL: SB, SUPABASE_ANON_KEY: 'anon', SUPABASE_SERVICE_ROLE_KEY: 'svc', SUPABASE_JWT_SECRET: 'jwt-secret-for-tests', HOST_BEAT_TOKEN: 'beat-token-for-tests', DEPLOYMENTS: { get: async () => null, put: async () => {}, delete: async () => {} } };
  const body = { host: 'pve', uptime_s: 400000, load1: 0.4, mem_used_pct: 61.2, disk_used_pct: 12, failed_units: 0, failed_unit_names: null, dns_ok: true, feed_timer_ok: true, last_backup_status: 'job errors', extra: { dns_probe: 'ftp.dealerslink.com', storage: TODAY }, last_remedy: null };
  const r = await worker.fetch(new Request('https://edge.hyperwax.io/api/controller/host-beat?token=beat-token-for-tests', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }), env, { waitUntil() {} });
  ok('a beat carrying the report is accepted and the report is stored whole, untouched, in extra.storage (no SQL change needed)', r.status === 200 && db.inserted && JSON.stringify(db.inserted.extra.storage) === JSON.stringify(TODAY) && db.inserted.extra.dns_probe === 'ftp.dealerslink.com' && db.inserted.last_backup_status === 'job errors', r.status);
  ok('the beat with the report is ' + JSON.stringify(body).length + ' bytes', JSON.stringify(body).length < 12000);
}

// ── 7. the assistant ────────────────────────────────────────────────────────
console.log('\n7. The assistant is told how to read it');
ok('prompt explains extra.storage, the keep_last + 1 rule, that one OK hides failures, and the dead-man\'s exit code',
   /extra\.storage, written hourly by storage-probe/.test(t.sys) && /room for keep_last \+ 1 archives/.test(t.sys) && /one OK hides the failures/.test(t.sys) && /exit code 1 is the dead-man reporting a stale feed/.test(t.sys));
ok('and the sections around it are intact', t.sys.indexOf('KNOWN FAILURE MODES') < t.sys.indexOf('DISKS, BACKUP STORAGE AND BACKUP RUNS') && t.sys.indexOf('DISKS, BACKUP STORAGE AND BACKUP RUNS') < t.sys.indexOf('HOW TO ANSWER') && t.sys.includes('[[GSTASKS:['));

console.log(f ? `\n${f} of ${n} FAILED` : `\nall ${n} passed`);
process.exit(f ? 1 : 0);
