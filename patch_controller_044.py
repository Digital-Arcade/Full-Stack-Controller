#!/usr/bin/env python3
"""
patch_controller_044.py - give the first responder conversation memory, and
have it emit a checkable task list.

Requires 038. Unique anchors, assert before write, idempotent.

  python3 patch_controller_044.py worker.js

/api/controller/ask now also accepts:
  history: [{role:'user'|'assistant', content:'...'}]

Still stateless on the server. The console owns the thread and sends it back;
the Worker just forwards it. That keeps the route exactly as replayable and
as debuggable as it was.
"""
import sys, os

TASKS_INSTR = r'''
WHEN YOU GIVE THE OPERATOR THINGS TO DO
End your reply with a machine-readable list so the console can render it as a checklist he ticks off:

[[GSTASKS:["Proxmox: stagger the second vzdump job to 22:00","Supabase: disable the placeholder dealer_feeds row"]]]

One entry per discrete action, in the order they should happen, each naming the machine it runs on where that matters - Proxmox, Mac, Supabase SQL editor. Keep each under 120 characters: the detail belongs in your prose above, not in the checkbox. Do not paste long commands into a task; name the step and let the prose carry the command.

Omit the marker entirely when there is nothing to do. A checklist of one item saying "nothing to do" is worse than no checklist.

If the conversation shows he has already done something, do not re-list it.
- If nothing is wrong, say so in one line and stop.`;'''

HIST = r'''
                    // Conversation history, sent by the console. The server
                    // stays stateless: the client owns the thread, so the
                    // route remains replayable and debuggable exactly as it
                    // was before.
                    //
                    // Capped on both count and length. An unbounded thread
                    // plus a 60k snapshot is how a cheap question quietly
                    // becomes an expensive one.
                    const hist = [];
                    try {
                        const raw = Array.isArray(body.history) ? body.history.slice(-16) : [];
                        for (const m of raw) {
                            const role = (m && m.role === 'assistant') ? 'assistant' : 'user';
                            const content = String((m && m.content) || '').slice(0, 3000);
                            if (content) hist.push({ role, content });
                        }
                        // The API requires the first message to be from the
                        // user; a thread trimmed mid-exchange can start on an
                        // assistant turn.
                        while (hist.length && hist[0].role !== 'user') hist.shift();
                    } catch (e) { /* history is a convenience, never a requirement */ }
'''

MSG_OLD = """                            messages: [{
                                role: 'user',"""
MSG_NEW = """                            messages: [...hist, {
                                role: 'user',"""

SYS_ANCHOR = "- If nothing is wrong, say so in one line and stop.`;"
FOCUS_ANCHOR = """                    const focusCtx = (body.focus && typeof body.focus === 'object')"""

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'worker.js'
    if not os.path.exists(path):
        sys.exit(f"FAIL: {path} not found")
    src = open(path, encoding='utf-8').read()

    if 'GSTASKS' in src and 'const hist = [];' in src:
        print("already patched - nothing to do")
        return
    if 'JUDGING A WATCHDOG MATCH' not in src:
        sys.exit("FAIL: 038 is not applied to this worker. Run patch_controller_038.py first.")

    hunks = [("system", SYS_ANCHOR, TASKS_INSTR),
             ("history", FOCUS_ANCHOR, HIST + "\n" + FOCUS_ANCHOR),
             ("messages", MSG_OLD, MSG_NEW)]
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
