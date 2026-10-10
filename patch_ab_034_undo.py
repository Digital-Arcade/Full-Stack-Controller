#!/usr/bin/env python3
"""
patch_ab_034_undo.py - Undo in the sandbox chat works again, and the chat stops
saying a console change happened when it did not.

Goes with the AdminBuilder.tsx of the same night (the one that has
GS_ADMIN_APPLY_V2 in it). Patches two files, both or neither:

  python3 patch_ab_034_undo.py ~/Hyperwax
  python3 patch_ab_034_undo.py ~/Hyperwax --reverse      (undo)

    components/AIChatPanel.tsx
    views/AppBuilder.tsx

WHAT HAPPENED (The Desk Trader, Oct 5)
Ghost pressed Undo about ten times on the sandbox AI's admin console changes.
None of them took, and each one was marked "Reverted".

The console's two structural files are guarded: a write to main.tsx with fewer
routes than it has now, or to AdminLayout.tsx with fewer sidebar links, was
refused (so a regenerated file could not quietly lose pages). Undoing a turn
that ADDED a route or a link puts back a file with one fewer - so every such
Undo was refused. The refusal was one line in the browser console; the chat
marked the message "Reverted" regardless.

The same rule refused the AI itself: told to delete the /sell route it had
added, it did, the write was refused, and the chat printed "Admin Console:
updated main.tsx". Three times.

The app side has the same shape: Undo went through the AI shell guard, which
refuses a GenieShell with fewer nav items or page panes, and puts back widgets
and the mobile nav block that the write "lost".

WHAT THIS CHANGES
AIChatPanel.tsx
 1. Undo is sent as a RESTORE (opts.restore). The console bridge and the app
    editor both let a restore put a file back exactly as it was.
 2. Undo reports what happened: which files went back, which could not and
    why, which files were new in that turn (left in place, unused), and when it
    also took out newer changes to the same file. A message is only marked
    "Reverted" when everything was put back.
 3. Undo with no saved earlier version (older messages after a reload) says so
    instead of doing nothing.
 4. A console change the bridge refuses is reported in the chat with the
    reason, instead of "updated". The AI reads that on its next turn.
 5. Console files changed by targeted edits are marked as such, so the bridge
    can tell a deliberate small removal from a regenerated file.
 6. On the Admin tab without full-stack, a turn's earlier versions were never
    kept (so Undo had nothing to restore). They are kept now.
AppBuilder.tsx
 7. handleApplyAICode takes opts.restore: the shell is checked that it compiles
    and nothing else (no AI policies), the "file shrank" refusal is skipped,
    and no modules are auto-wired.

Unique anchors, assert before write, idempotent. No .bak files are left in the
repo (git has the previous version, and --reverse undoes it exactly).
"""
import sys, os, io, hashlib

CHAT = 'components/AIChatPanel.tsx'
APPB = 'views/AppBuilder.tsx'

# ── AIChatPanel.tsx ─────────────────────────────────────────────────────────
C1_OLD = """interface AIChatPanelProps {
  appId: string;
  files: any[];
  onApplyCode: (files: any[]) => void;
"""
C1_NEW = """// GS_UNDO_V1
// What the admin console did with a set of files (AdminBuilder's editor
// bridge, applyFiles). A console build from before the bridge reported
// anything returns nothing; that is read as "applied", which is what this
// panel always assumed.
export const gsBridgeResult = (res: any, sent: any[]): { applied: string[]; rejected: { name: string; reason: string }[] } => {
  if (res && Array.isArray(res.applied) && Array.isArray(res.rejected)) return { applied: res.applied.map((n: any) => String(n)), rejected: res.rejected.map((r: any) => ({ name: String(r && r.name), reason: String((r && r.reason) || 'refused') })) };
  return { applied: (Array.isArray(sent) ? sent : []).map((f: any) => String(f && f.name)), rejected: [] };
};
const gsShortName = (n: any): string => String(n || '').replace(/^src\\/admin\\//, '').replace(/^src\\//, '');
// The chat lines for a console write: what was changed, and - separately and
// plainly - what was NOT. It used to print "updated" for both.
export const gsAdminWriteLines = (res: { applied: string[]; rejected: { name: string; reason: string }[] }): string[] => {
  const out: string[] = [];
  if (res.applied.length) out.push('Admin Console: updated ' + res.applied.map(gsShortName).join(', ') + ' - press Save Build in the Admin tab to keep it.');
  if (res.rejected.length) out.push('Admin Console: NOT changed - ' + res.rejected.map(r => gsShortName(r.name) + ' (' + r.reason + ')').join('; ') + '. ' + (res.rejected.length === 1 ? 'That file is' : 'Those files are') + ' exactly as ' + (res.rejected.length === 1 ? 'it was' : 'they were') + ', whatever the message above says.');
  return out;
};
// What an Undo of one message has to do. A message keeps the earlier version
// of every file its turn changed (previousCode); an empty earlier version
// means the file did not exist before that turn.
export const gsUndoPlan = (messages: any[], msgIndex: number): { none: boolean; admin: any[]; front: any[]; created: string[]; later: string[]; names: string[] } => {
  const msg = (messages || [])[msgIndex] || {};
  const prev: any[] = Array.isArray(msg.previousCode) ? msg.previousCode.filter((p: any) => p && p.name) : [];
  const isAdmin = (p: any) => String(p.name).includes('src/admin/');
  const real = prev.filter((p: any) => typeof p.content === 'string' && p.content.length > 0);
  const names: string[] = Array.isArray(msg.codeChanges) ? msg.codeChanges.map((c: any) => String(c && c.name)).filter(Boolean) : [];
  // Newer turns that changed the same files and have not been undone: putting
  // a file back to before THIS message takes their changes to it out too.
  const mine: any = {};
  real.forEach((p: any) => { mine[p.name] = true; });
  const later: string[] = [];
  (messages || []).slice(msgIndex + 1).forEach((m: any) => {
    if (!m || m.role !== 'ai' || m.reverted || !Array.isArray(m.codeChanges)) return;
    m.codeChanges.forEach((c: any) => { const n = String(c && c.name); if (mine[n] && later.indexOf(n) === -1) later.push(n); });
  });
  return { none: real.length === 0, admin: real.filter(isAdmin), front: real.filter((p: any) => !isAdmin(p)),
           created: prev.filter((p: any) => !(typeof p.content === 'string' && p.content.length > 0)).map((p: any) => String(p.name)), later: later, names: names };
};
export const gsUndoReport = (done: string[], failed: string[], created: string[], later: string[], anyAdmin: boolean): string => {
  const lines: string[] = [];
  if (done.length) lines.push('Undone: ' + done.map(gsShortName).join(', ') + ' ' + (done.length === 1 ? 'is' : 'are') + ' back to how ' + (done.length === 1 ? 'it was' : 'they were') + ' before that message.' + (anyAdmin ? ' Press Save Build in the Admin tab to keep it.' : ''));
  if (failed.length) lines.push('Could NOT undo: ' + failed.join('; ') + '.');
  if (created.length) lines.push('Left in place: ' + created.map(gsShortName).join(', ') + ' (new in that turn - nothing uses ' + (created.length === 1 ? 'it' : 'them') + ' once the rest is undone).');
  const hit = later.filter(n => done.indexOf(n) !== -1);
  if (hit.length) lines.push('This also took out newer changes to ' + hit.map(gsShortName).join(', ') + ', because Undo puts a file back as it was before this message.');
  return lines.join('\\n');
};
// /GS_UNDO_V1

interface AIChatPanelProps {
  appId: string;
  files: any[];
  onApplyCode: (files: any[], opts?: { restore?: boolean }) => void;
"""

C2_OLD = """      let previousCode: any[] = [];
      const prevPool: any[] = fullStack ? agentFiles : files;
"""
C2_NEW = """      let previousCode: any[] = [];
      // The files this turn was read from are the ones its changes go back to,
      // so they are the ones to keep for Undo. On the Admin tab without
      // full-stack that is the console's files; taking them from the frontend
      // list kept nothing, and Undo had nothing to put back.
      const prevPool: any[] = (fullStack || onAdmin) ? agentFiles : files;
"""

C3_OLD = """      if (fullStack && Array.isArray(data.edits)) {
          data.edits.forEach((ed: any) => {
              if (!ed || !ed.name || previousCode.some((p: any) => p.name === ed.name)) return;
              const oldFile = prevPool.find((f: any) => f.name === ed.name);
"""
C3_NEW = """      if ((fullStack || onAdmin) && Array.isArray(data.edits)) {
          data.edits.forEach((ed: any) => {
              if (!ed || !ed.name || previousCode.some((p: any) => p.name === ed.name)) return;
              const oldFile = prevPool.find((f: any) => f.name === ed.name);
"""

C4_OLD = """          filesToApply.push({ name: name, content: byFile[name], language: (src && src.language) || 'tsx' });
"""
C4_NEW = """          // fromEdit: this content is the file we hold plus exact find/replace
          // edits, not a file the model wrote out. The console bridge allows a
          // targeted edit to take a route or a link out; a whole file may not.
          filesToApply.push({ name: name, content: byFile[name], language: (src && src.language) || 'tsx', fromEdit: true });
"""

C5_OLD = """           if (adminPart.length) fullBridge.applyFiles(adminPart);
           if (frontPart.length && onApplyCode) onApplyCode(frontPart);
           if (adminPart.length) {
             setMessages(prev => [...prev, { role: 'ai', content: 'Admin Console: updated ' + adminPart.map((f: any) => f.name.replace(/^src\\/admin\\//, '')).join(', ') + ' - press Save Build in the Admin tab to keep it.' }]);
           }
         }
         else if (onAdmin) bridge.applyFiles(filesToApply);
         else if (onApplyCode) onApplyCode(filesToApply);
"""
C5_NEW = """           // The bridge says what it wrote and what it refused. Both are
           // shown: "updated" used to be printed for a refused write too.
           const adminRes = adminPart.length ? gsBridgeResult(fullBridge.applyFiles(adminPart), adminPart) : null;
           if (frontPart.length && onApplyCode) onApplyCode(frontPart);
           if (adminRes) {
             const adminLines = gsAdminWriteLines(adminRes);
             if (adminLines.length) setMessages(prev => [...prev, { role: 'ai', content: adminLines.join('\\n') }]);
           }
         }
         else if (onAdmin) {
           const adminRes = gsBridgeResult(bridge.applyFiles(filesToApply), filesToApply);
           if (adminRes.rejected.length) {
             const adminLines = gsAdminWriteLines({ applied: [], rejected: adminRes.rejected });
             setMessages(prev => [...prev, { role: 'ai', content: adminLines.join('\\n') }]);
           }
         }
         else if (onApplyCode) onApplyCode(filesToApply);
"""

C6_OLD = """  const handleRevert = (msgIndex: number) => {
      const msg = messages[msgIndex];
      if (msg.previousCode && onApplyCode) {
          const isAdminPrev = (p: any) => String(p?.name || '').includes('src/admin/');
          const adminPrev = (msg.previousCode as any[]).filter(p => isAdminPrev(p) && p.content);
          const frontPrev = (msg.previousCode as any[]).filter(p => !isAdminPrev(p));
          if (frontPrev.length) onApplyCode(frontPrev);
          if (adminPrev.length && adminBridgeRef?.current?.applyFiles) adminBridgeRef.current.applyFiles(adminPrev);
          setMessages(prev => prev.map((m, idx) => idx === msgIndex ? { ...m, reverted: true } : m));
      }
  };
"""
C6_NEW = """  // GS_UNDO_REVERT_V1
  // Undo puts every file that message's turn changed back to how it was before
  // the turn. It is sent as a RESTORE: the guards that stop the AI removing
  // routes, links, nav items and panes must not stop the owner taking the AI's
  // additions back out. It then says what happened - it used to mark the
  // message "Reverted" whether or not anything had been put back.
  const handleRevert = (msgIndex: number) => {
      const plan = gsUndoPlan(messages, msgIndex);
      const say = (text: string) => setMessages(prev => [...prev, { role: 'ai', content: text }]);
      if (plan.none) {
          say('Undo: nothing was changed. I no longer have the earlier version of ' + (plan.names.length ? plan.names.map(n => n.replace(/^src\\/admin\\//, '').replace(/^src\\//, '')).join(', ') : 'those files')
            + ' for that message' + (plan.created.length ? ' (the files it made were new)' : ' - earlier versions are only kept for the most recent changes once the builder has been reloaded') + '.');
          return;
      }
      const done: string[] = [];
      const failed: string[] = [];
      if (plan.front.length) {
          if (onApplyCode) { onApplyCode(plan.front, { restore: true }); plan.front.forEach((p: any) => done.push(String(p.name))); }
          else plan.front.forEach((p: any) => failed.push(String(p.name).replace(/^src\\//, '') + ' (the app editor is not available)'));
      }
      let anyAdmin = false;
      if (plan.admin.length) {
          const b = adminBridgeRef?.current;
          if (b && typeof b.applyFiles === 'function') {
              const res = gsBridgeResult(b.applyFiles(plan.admin, { restore: true }), plan.admin);
              res.applied.forEach(n => { done.push(n); anyAdmin = true; });
              res.rejected.forEach(r => failed.push(r.name.replace(/^src\\/admin\\//, '') + ' (' + r.reason + ')'));
          } else {
              plan.admin.forEach((p: any) => failed.push(String(p.name).replace(/^src\\/admin\\//, '') + ' (the Admin Console is not open - flip to Admin, then press Undo again)'));
          }
      }
      if (done.length && !failed.length) setMessages(prev => prev.map((m, idx) => idx === msgIndex ? { ...m, reverted: true } : m));
      say(gsUndoReport(done, failed, plan.created, plan.later, anyAdmin));
  };
  // /GS_UNDO_REVERT_V1
"""

CHAT_STEPS = [
    (C1_OLD, C1_NEW, 'chat: result helpers + onApplyCode takes opts'),
    (C2_OLD, C2_NEW, 'chat: earlier versions come from the files the turn read'),
    (C3_OLD, C3_NEW, 'chat: Admin tab turns keep earlier versions too'),
    (C4_OLD, C4_NEW, 'chat: targeted edits are marked'),
    (C5_OLD, C5_NEW, 'chat: a refused console write is reported'),
    (C6_OLD, C6_NEW, 'chat: Undo restores, and says what happened'),
]

# ── AppBuilder.tsx ──────────────────────────────────────────────────────────
A1_OLD = """  const handleApplyAICode = (updatedFiles: { name: string, content: string, language: string }[]) => {
"""
A1_NEW = """  // opts.restore: an Undo from the chat - files going BACK to an earlier
  // version, not a write by the AI. The AI policies (a shell may not lose nav
  // items, panes, widgets or its mobile nav block; a file may not shrink to a
  // fifth) exist to stop the model dropping things, and they refused exactly
  // what an Undo has to do: take the AI's additions back out. A restore is
  // still checked that the shell compiles. GS_APPLY_RESTORE_V1
  const handleApplyAICode = (updatedFiles: { name: string, content: string, language: string }[], opts?: { restore?: boolean }) => {
    const _restore = !!(opts && opts.restore);
"""

A2_OLD = """              if (typeof _existing === 'string' && _existing.length > 400 && _body.length < _existing.length / 5) {
"""
A2_NEW = """              if (!_restore && typeof _existing === 'string' && _existing.length > 400 && _body.length < _existing.length / 5) {
"""

A3_OLD = """                      ? guardShell(_prevForGuard, mod.content, 'ai-copilot')
"""
A3_NEW = """                      ? guardShell(_prevForGuard, mod.content, _restore ? 'chat-undo' : 'ai-copilot')
"""

A4_OLD = """          const appFile = updatedFiles.find((f: any) => f.name === 'src/App.tsx' || f.name.endsWith('/App.tsx') || f.name === 'App.tsx');
          const hasShell = !!newFiles['src/GenieShell.tsx'];
"""
A4_NEW = """          const appFile = _restore ? undefined : updatedFiles.find((f: any) => f.name === 'src/App.tsx' || f.name.endsWith('/App.tsx') || f.name === 'App.tsx');
          const hasShell = !!newFiles['src/GenieShell.tsx'];
"""

APPB_STEPS = [
    (A1_OLD, A1_NEW, 'app: handleApplyAICode takes opts.restore'),
    (A2_OLD, A2_NEW, 'app: a restore may make a file smaller'),
    (A3_OLD, A3_NEW, 'app: a restore is not an AI shell write'),
    (A4_OLD, A4_NEW, 'app: a restore wires no modules'),
]


def md5(s):
    return hashlib.md5(s.encode('utf-8')).hexdigest()


def run(path, steps, marker, reverse):
    with io.open(path, 'r', encoding='utf-8', newline='') as f:
        s = f.read()
    applied = marker in s
    if applied and not reverse:
        return s, None, 'already applied'
    if reverse and not applied:
        return s, None, 'not applied'
    out = s
    if not reverse:
        for old, new, label in steps:
            n = out.count(old)
            assert n == 1, '%s: anchor found %d times in %s - nothing was written' % (label, n, os.path.basename(path))
        for old, new, label in steps:
            out = out.replace(old, new, 1)
    else:
        for old, new, label in reversed(steps):
            n = out.count(new)
            assert n == 1, '%s: patched text found %d times in %s - nothing was written' % (label, n, os.path.basename(path))
        for old, new, label in reversed(steps):
            out = out.replace(new, old, 1)
    return s, out, 'ok'


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    root = os.path.expanduser(sys.argv[1])
    reverse = '--reverse' in sys.argv[2:]
    chat = os.path.join(root, CHAT)
    appb = os.path.join(root, APPB)
    for p in (chat, appb):
        assert os.path.isfile(p), 'not found: ' + p + '  (give the repo folder, e.g. ~/Hyperwax)'

    # Work both files out first. Nothing is written unless both are good.
    c_before, c_after, c_state = run(chat, CHAT_STEPS, 'GS_UNDO_REVERT_V1', reverse)
    a_before, a_after, a_state = run(appb, APPB_STEPS, 'GS_APPLY_RESTORE_V1', reverse)
    print(CHAT, 'before md5', md5(c_before), '-', c_state)
    print(APPB, 'before md5', md5(a_before), '-', a_state)
    if c_after is None and a_after is None:
        print('nothing to do')
        return

    for path, before, after, steps in ((chat, c_before, c_after, CHAT_STEPS), (appb, a_before, a_after, APPB_STEPS)):
        if after is None:
            continue
        with io.open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(after)
        for old, new, label in steps:
            print(('undone ' if reverse else 'ok ') + label)
    print(CHAT, 'after md5 ', md5(c_after if c_after is not None else c_before))
    print(APPB, 'after md5 ', md5(a_after if a_after is not None else a_before))


if __name__ == '__main__':
    main()
