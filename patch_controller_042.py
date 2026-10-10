#!/usr/bin/env python3
"""
patch_controller_042.py - fix the alerts query in the first-responder route.

BUG: patch 037 selected a column that does not exist.

    gs_alerts?select=id,deployment_id,severity,message,...

gs_alerts has `label` and a jsonb `detail`, not `message` - see renderAlerts
in controller.html, which reads a.label and a.detail.sample. PostgREST
answers an unknown column with HTTP 400, so open_alerts in every snapshot
handed to the agent was the string {"error":"HTTP 400"} rather than the
alerts. A monitoring surface returning an error instead of data looks
identical to "no alerts" at a glance, which is the worse failure.

Fixed with select=* rather than a corrected column list: these rows are
small, and the same reasoning gsEmailBrand already uses applies - naming
columns means a schema that differs by age breaks the whole query.

  python3 patch_controller_042.py worker.js
"""
import sys, os

OLD = "grab('gs_alerts?select=id,deployment_id,severity,message,created_at,acknowledged&acknowledged=is.false&order=id.desc&limit=25')"
NEW = "grab('gs_alerts?select=*&acknowledged=is.false&order=id.desc&limit=25')"

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'worker.js'
    if not os.path.exists(path):
        sys.exit(f"FAIL: {path} not found")
    src = open(path, encoding='utf-8').read()

    if NEW in src:
        print("already patched - nothing to do")
        return
    n = src.count(OLD)
    if n != 1:
        sys.exit(f"FAIL: anchor found {n} times, expected exactly 1. Nothing written.")

    out = src.replace(OLD, NEW, 1)
    open(path + '.bak', 'w', encoding='utf-8').write(src)
    open(path, 'w', encoding='utf-8').write(out)
    print(f"patched {path} ({len(out)-len(src):+d} bytes). backup at {path}.bak")

if __name__ == '__main__':
    main()
