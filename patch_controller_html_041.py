#!/usr/bin/env python3
"""
patch_controller_html_041.py - one failing panel must not blank the others.

Fixes a defect introduced in 040: feed, infra and findings were fetched in a
single Promise.all, so ANY one of them failing - a view not yet created, a
permission refused, a transient 500 - rejected the whole batch and left all
three tabs empty with no error shown anywhere.

Each call now settles on its own and falls back to an empty list.

  python3 patch_controller_html_041.py controller.html
"""
import sys, os

OLD = """    Promise.all([api('feed-health'), api('feed-runs?limit=30'), api('hosts'), api('findings')])
      .then(([feed, feedRuns, hosts, findings]) => { state.feed = feed; state.feedRuns = feedRuns; state.hosts = hosts; state.findings = findings;
                                           if (state.tab === 'feed' || state.tab === 'infra') renderView(); })
      .catch(() => {});"""

NEW = """    // Each panel settles on its own. Promise.all rejects the whole batch on
    // a single failure, which is how a view that did not exist yet silently
    // emptied the feed and infra tabs rather than just its own.
    //
    // An empty list is the honest fallback: these tabs already render a
    // "nothing here" state, and a missing panel must never take out a
    // working one.
    const soft = (p) => api(p).then(r => Array.isArray(r) ? r : []).catch(e => { console.warn('[controller]', p, e.message); return []; });
    Promise.all([soft('feed-health'), soft('feed-runs?limit=30'), soft('hosts'), soft('findings')])
      .then(([feed, feedRuns, hosts, findings]) => { state.feed = feed; state.feedRuns = feedRuns; state.hosts = hosts; state.findings = findings;
                                           if (state.tab === 'feed' || state.tab === 'infra') renderView(); });"""

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'controller.html'
    if not os.path.exists(path):
        sys.exit(f"FAIL: {path} not found")
    src = open(path, encoding='utf-8').read()

    if 'const soft = (p) =>' in src:
        print("already patched - nothing to do")
        return
    n = src.count(OLD)
    if n != 1:
        sys.exit(f"FAIL: anchor found {n} times, expected exactly 1. Nothing written.")

    out = src.replace(OLD, NEW, 1)
    open(path + '.bak', 'w', encoding='utf-8').write(src)
    open(path, 'w', encoding='utf-8').write(out)
    print(f"patched {path} (+{len(out)-len(src)} bytes). backup at {path}.bak")

if __name__ == '__main__':
    main()
