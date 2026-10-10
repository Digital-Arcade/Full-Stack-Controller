#!/usr/bin/env python3
"""
patch_controller_html_045.py - the Feed tab reads the relay's check-ins.

Before this, the tab knew one thing: when the last file IMPORTED. On Oct 5
the vendor did not regenerate for 33 hours, the relay fetched an identical
file every 30 minutes the whole time, and the tab could only say "nothing
imported in 29 hours - either the vendor stopped or the relay cannot reach
them". It could not tell which.

With 045 the relay reports every run, so the tab now says which:

  amber  vendor quiet        import is old, but the relay fetched minutes ago
                             and the file was identical. Nothing to fix.
  red    relay not reporting no check-in for 90 minutes. Our side.
  red    fetch failing       the relay reached us to say the download failed.
  red    file refused        downloaded, failed the size / VIN guard.

A feed that has never checked in (045 not on the box yet) behaves exactly as
it did before: every old case in t_feed.mjs still holds.

Also styles three classes the page was already using but never defined
(.dot.rem, .chip.live, .chip.warn), so a red feed gets a red dot instead of
a grey one.

Requires 036 (the feed tab). Unique anchors, assert before write, idempotent.

  python3 patch_controller_html_045.py controller.html
"""
import sys, os

MARK = 'FEED_CHECK_FRESH_S'

EDITS = []

# ── 1. styles ───────────────────────────────────────────────────────────────
EDITS.append(("dot styles",
'''.dot.crit{background:var(--crit)}
''',
'''.dot.crit{background:var(--crit)}
.dot.rem{background:var(--crit)}
'''))

EDITS.append(("chip styles",
'''.chip.rem{color:var(--crit);border-color:rgba(229,72,77,.3)}
''',
'''.chip.rem{color:var(--crit);border-color:rgba(229,72,77,.3)}
.chip.live{color:var(--ok);border-color:rgba(111,207,151,.3)}
.chip.warn{color:var(--warn);border-color:rgba(224,164,88,.35)}
'''))

# ── 2. the decision ─────────────────────────────────────────────────────────
EDITS.append(("feedTone",
r'''const FEED_STALE_S = 26 * 3600;

function feedTone(f){
  const st = String(f.run_status || f.last_status || '').toLowerCase();
  if (st && st !== 'ok') return 'rem';
  if (f.age_s == null) return '';
  return f.age_s > FEED_STALE_S ? 'rem' : 'live';
}
''',
r'''const FEED_STALE_S = 26 * 3600;
// Since 045 the relay reports EVERY run, not only the ones that import. It
// runs every 30 minutes, so three missed in a row is not jitter. Must match
// GS_FEED_CHECK_FRESH_S in the Worker, or the tab and the alert disagree.
const FEED_CHECK_FRESH_S = 90 * 60;

// What the relay last told us about this feed.
//   null      it has never checked in (045 is not on the box yet), or the
//             feed is disabled. Everything then behaves as it did before.
//   'silent'  it used to check in and has stopped. Our side.
//   'same'    fetched, identical to the last file. The vendor is quiet.
//   'changed' fetched and imported.
//   'fetch_failed' / 'refused'  it reached us to say the fetch went wrong.
function feedCheck(f){
  if (!f || f.enabled === false) return null;
  if (!f.last_check_at || f.check_age_s == null) return null;
  if (Number(f.check_age_s) > FEED_CHECK_FRESH_S) return 'silent';
  const r = String(f.last_check_result || '').toLowerCase();
  return ['same','changed','fetch_failed','refused'].includes(r) ? r : null;
}

function feedTone(f){
  const st = String(f.run_status || f.last_status || '').toLowerCase();
  if (st && st !== 'ok') return 'rem';
  // typeof guard: t_feed.mjs lifts this one function out of the page and runs
  // it alone, and it must keep passing there.
  const c = (typeof feedCheck === 'function') ? feedCheck(f) : null;
  if (c === 'silent' || c === 'fetch_failed' || c === 'refused') return 'rem';
  if (f.age_s == null) return '';
  if (f.age_s <= FEED_STALE_S) return 'live';
  // Old import. If the relay fetched minutes ago and the file was identical,
  // nothing is broken - amber, not red. Anything else is still red.
  return c === 'same' ? 'warn' : 'rem';
}

function feedSpan(s){
  s = Math.max(0, Math.floor(Number(s) || 0));
  if (s < 3600) return Math.max(1, Math.round(s / 60)) + ' min';
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h + 'h' + (h < 6 && m ? ' ' + m + 'm' : '');
}

// The words that go with feedCheck. Plain text only - callers escape it.
//   line   goes after "last import ..." on the feed's header row
//   chip   a short label beside the name, or '' when there is nothing to flag
//   head / body   the explanation under the table, or '' for none
function feedStory(f){
  const c = feedCheck(f);
  const out = { check: c, line: '', chip: '', tone: '', head: '', body: '', cmd: '' };
  if (!c) return out;
  const who   = String(f.provider || 'the vendor');
  const since = feedSpan(f.check_age_s);
  const size  = f.last_check_bytes != null ? ' (' + Number(f.last_check_bytes).toLocaleString('en-US') + ' bytes)' : '';
  const note  = String(f.last_check_note || '').trim();
  const stale = f.age_s != null && f.age_s > FEED_STALE_S;

  if (c === 'silent'){
    out.line = 'relay last reported ' + since + ' ago';
    out.chip = 'relay not reporting'; out.tone = 'rem';
    out.head = 'The relay has not reported for ' + since;
    out.body = 'It reports every 30 minutes whether or not the file changed, so this is on our side, not ' + who + ': the timer, relay.sh itself, or the box\'s route to the edge. If the Infra tab shows the host silent, that is the cause and this is the same outage. On the Proxmox shell:';
    out.cmd  = "systemctl list-timers 'feed-*' --no-pager\ntail -20 /var/log/feed-relay.log";
  } else if (c === 'fetch_failed'){
    out.line = 'checked ' + since + ' ago: could not download' + (note ? ' (' + note + ')' : '');
    out.chip = 'fetch failing'; out.tone = 'rem';
    out.head = 'The relay cannot download the file from ' + who;
    out.body = 'It reached us to say so ' + since + ' ago, so the box and its internet are up. The problem is between the box and the vendor\'s FTP' + (note ? ' (' + note + ')' : '') + '. curl exit 6 is DNS on the box, 7 or 28 is their FTP down or slow, 67 is the login being refused. On the Proxmox shell:';
    out.cmd  = 'tail -20 /var/log/feed-relay.log';
  } else if (c === 'refused'){
    out.line = 'checked ' + since + ' ago: file refused' + (note ? ' (' + note + ')' : '');
    out.chip = 'file refused'; out.tone = 'rem';
    out.head = 'The relay downloaded a file and refused to forward it';
    out.body = (note ? note.charAt(0).toUpperCase() + note.slice(1) + '. ' : '') + 'That guard is deliberate: a truncated file would retire the whole lot. If it repeats, the export on ' + who + '\'s side is broken and there is nothing to fix on ours. On the Proxmox shell:';
    out.cmd  = 'tail -20 /var/log/feed-relay.log';
  } else if (c === 'same'){
    out.line = 'checked ' + since + ' ago: unchanged' + size;
    if (stale){
      out.chip = 'vendor quiet'; out.tone = 'warn';
      out.head = 'No new file from ' + who + ' in ' + feedSpan(f.age_s);
      out.body = 'The relay fetched it ' + since + ' ago and it was identical' + size + ', so the relay, the network and the importer are all working. Nothing is broken on our side and there is nothing to run. The lot updates with the next file they publish.';
    }
  } else if (c === 'changed'){
    out.line = 'checked ' + since + ' ago: new file imported';
  }
  return out;
}
'''))

# ── 3. the header row ───────────────────────────────────────────────────────
EDITS.append(("feed row: story",
r'''    const tone = feedTone(f);
    const errs = Array.isArray(f.errors) ? f.errors : [];
''',
r'''    const tone = feedTone(f);
    const story = feedStory(f);
    const errs = Array.isArray(f.errors) ? f.errors : [];
'''))

EDITS.append(("feed row: last import line",
r'''        <span style="color:var(--muted);font-size:12px">last import ${ago(f.last_run_at)}</span>
''',
r'''        ${story.chip ? `<span class="chip ${story.tone}">${esc(story.chip)}</span>` : ''}
        <span style="color:var(--muted);font-size:12px">last import ${ago(f.last_run_at)}${story.line ? ' · ' + esc(story.line) : ''}</span>
'''))

# ── 4. the explanation under the table ──────────────────────────────────────
EDITS.append(("feed row: explanation",
r'''      ${f.age_s != null && f.age_s > FEED_STALE_S
        ? `<div class="empty" style="padding:10px 0 0"><b>Nothing imported in ${Math.floor(f.age_s/3600)} hours</b>The vendor normally regenerates several times a day. Past 26 hours either the vendor stopped publishing or the relay cannot reach them — check <code>tail -20 /var/log/feed-relay.log</code> on the box.</div>`
        : ''}
''',
r'''      ${story.head
        ? `<div class="empty" style="padding:10px 0 0;max-width:70ch"><b>${esc(story.head)}</b>${esc(story.body)}${story.cmd ? `<pre class="mono" style="margin:8px 0 0;white-space:pre-wrap;color:var(--muted)">${esc(story.cmd)}</pre>` : ''}</div>`
        : (f.age_s != null && f.age_s > FEED_STALE_S
          ? `<div class="empty" style="padding:10px 0 0"><b>Nothing imported in ${Math.floor(f.age_s/3600)} hours</b>The vendor normally regenerates several times a day. Past 26 hours either the vendor stopped publishing or the relay cannot reach them — check <code>tail -20 /var/log/feed-relay.log</code> on the box.</div>`
          : '')}
'''))


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'controller.html'
    if not os.path.exists(path):
        sys.exit(f"FAIL: {path} not found")
    src = open(path, encoding='utf-8').read()

    if MARK in src:
        print("already patched - nothing to do")
        return
    if 'function renderFeed(v){' not in src:
        sys.exit("FAIL: this controller.html has no Feed tab. Apply patch_controller_html_036.py first. Nothing written.")

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
