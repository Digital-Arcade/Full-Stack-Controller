#!/usr/bin/env python3
"""
patch_worker_049.py - the sandbox AI can no longer replace a tool tab.

Works on the Worker with or without patch_controller_048 (it touches none of
the same code). Unique anchors, assert before write, idempotent, keeps a .bak.

  python3 patch_worker_049.py worker.js
  python3 patch_worker_049.py worker.js --reverse     (undo)

WHAT HAPPENED (The Desk Trader, Oct 5)
The owner asked the sandbox AI to put two pages "under Tools" and then to move
"the Sell tab" into the new section. Sell is a TOOL TAB: a tab from the tab
settings with the VIN Scanner on it. It has no page file and no route, on
purpose - the platform draws it. The AI was never told any of that. It could
not find "Sell" in the files, so it guessed: a tab inside Wholesale Desk, then
Forms, then a page of its own with a /sell route in main.tsx. That route took
the address of the real tab, and the owner's Sell page was gone.

WHAT THIS CHANGES
1. The AI is TOLD. Every request that carries the admin console's files now
   also carries CONSOLE TABS: the tabs the owner added from the tab settings,
   each with its label, its route, its icon and whether it is a tool or an
   empty tab. Read fresh from admin_shell_settings on each request.
2. New rule 28: what a tool tab is; a tab named by the owner means THAT tab;
   how to link to one (one sidebar link, the tab's own icon, nothing else);
   never edit the platform's GS_ADMIN_MNAV_V1 blocks; how to put pages "under
   Tools" as ONE section instead of adding a second heading.
   New rule 29: "revert" means undo what was changed, nothing new.
3. The platform REFUSES the two edits that did the damage, whatever the AI
   thinks it is doing:
     - a <Route> in src/admin/main.tsx at a tool tab's address
     - a second sidebar section labelled "Tools" that does not hold the tool
       tabs (it would show the heading twice)
   The refusal tells the AI what to do instead, so it corrects in the same
   turn. Removing such a route is always allowed.
4. Admin pages generated from the "backend" key are skipped, with the reason,
   when their address is a tool tab's.

Everything fails open: if the tab list cannot be read, the AI works exactly as
it did before.
"""
import sys, os, hashlib

HELPERS = r'''// ── The console's own TABS ─────────────────────────────────────────────────
// Tabs the owner adds from the tab settings live in admin_shell_settings
// (mobile_nav_config), not in the console's files. One with a "tool" on it is
// a platform page (Sell = the VIN Scanner): it has no page file and no route,
// and AdminLayout draws it. The sandbox AI only ever saw the files, so asked
// to "move the Sell tab" it could not find one and built a page and a /sell
// route of its own - which took the address of the real tab (The Desk Trader,
// Oct 5). It is now told the tabs (CONSOLE TABS, rule 28), and the edits that
// did the damage are refused (gsAgentTabGuard).
const GS_TAB_TOOLS = { vin: 'VIN Scanner' };
function gsTabsFromConfig(cfg) {
    const out = [];
    (Array.isArray(cfg) ? cfg : []).forEach((m) => {
        if (!m || m.custom !== true || typeof m.path !== 'string' || !/^\/[A-Za-z0-9_-]{1,60}$/.test(m.path)) return;
        const t = { label: String(m.label || m.id || m.path.slice(1)).slice(0, 60), route: m.path.slice(1) };
        if (typeof m.icon === 'string' && /^[a-z0-9_-]{1,24}$/i.test(m.icon)) t.icon = m.icon;
        if (typeof m.tool === 'string' && m.tool) {
            t.kind = 'tool';
            t.tool = GS_TAB_TOOLS[m.tool] || m.tool.slice(0, 24);
            t.note = 'PLATFORM PAGE. No page file and no route, on purpose. Never add a route or a page at /' + t.route + '. To link to it: one sidebar link with to="/' + t.route + '" (rule 28).';
        } else {
            t.kind = 'blank';
            t.note = 'Empty tab. Building a page at /' + t.route + ' is what it is for.';
        }
        out.push(t);
    });
    return out.slice(0, 30);
}
// null = could not be read (the caller then behaves as if there were none).
async function gsAdminTabs(env, tenantId) {
    try {
        if (!tenantId || !/^[0-9a-f-]{10,40}$/i.test(String(tenantId))) return null;
        const ctrl = new AbortController();
        const timer = setTimeout(() => ctrl.abort(), 4000);
        try {
            const r = await fetch(`${env.SUPABASE_URL}/rest/v1/admin_shell_settings?app_id=eq.${encodeURIComponent(String(tenantId))}&select=mobile_nav_config&limit=1`, {
                headers: { 'apikey': env.SUPABASE_ANON_KEY, 'Authorization': `Bearer ${env.SUPABASE_ANON_KEY}` },
                signal: ctrl.signal
            });
            if (!r.ok) return null;
            const rows = await r.json();
            return gsTabsFromConfig(Array.isArray(rows) && rows[0] ? rows[0].mobile_nav_config : null);
        } finally { clearTimeout(timer); }
    } catch (e) { return null; }
}
// Throws - with what to do instead - when an edit would replace a tool tab or
// give the sidebar a second "Tools" heading. "before" and "after" are the
// whole file. Only an edit that ADDS the problem is refused, so taking a bad
// route back out always works.
function gsAgentTabGuard(p, before, after, tabs) {
    const tools = (Array.isArray(tabs) ? tabs : []).filter((t) => t && t.kind === 'tool' && typeof t.route === 'string' && /^[A-Za-z0-9_-]+$/.test(t.route));
    if (!tools.length) return;
    before = String(before || '');
    after = String(after || '');
    if (p === 'src/admin/main.tsx') {
        for (const t of tools) {
            const re = new RegExp('<Route\\s+path=\\{?["\']\\/?' + t.route + '["\']', 'g');
            if ((after.match(re) || []).length > (before.match(re) || []).length) {
                throw new Error('/' + t.route + ' is the "' + t.label + '" tab - a platform tool tab showing the ' + t.tool + '. It has no route in main.tsx on purpose, and a route here would replace the owner\'s ' + t.label + ' page with yours. Nothing was changed. If the user asked you to move, link or show the ' + t.label + ' tab: add ONE sidebar link with to="/' + t.route + '" in src/admin/AdminLayout.tsx and change nothing else (rule 28c). If they want a different page, build it at a different route.');
            }
        }
        return;
    }
    if (p === 'src/admin/AdminLayout.tsx') {
        // Only the console's own sections count: the platform's Tools list sits
        // between the E markers and is not a NavSection.
        const strip = (s) => s.replace(/\{\/\* GS_ADMIN_MNAV_V1:E \*\/\}[\s\S]*?\{\/\* GS_ADMIN_MNAV_V1:\/E \*\/\}/, '');
        if (after.indexOf('GS_ADMIN_MNAV_V1:E') === -1) return;          // this console has no platform Tools list
        const toolsSecs = (s) => (strip(s).match(/<NavSection\s+id=(['"])[A-Za-z0-9_-]+\1\s+label=(['"])\s*tools\s*\2/gi) || []).length;
        if (toolsSecs(after) <= toolsSecs(before)) return;
        const names = tools.map((t) => t.label).join(', ');
        if (after.indexOf('hwmToolsShown') === -1) {
            throw new Error('The sidebar already shows a "Tools" heading - the platform draws it for the tool tabs (' + names + '). A second section labelled "Tools" would show the heading twice, and this console\'s layout is from before the platform could merge the two. Nothing was changed. Do not add the section under another name either. Tell the user in one line: "Press Sync Core in the Admin tab once, then ask me again - after that I can put these under one Tools section."');
        }
        const own = strip(after);
        const missing = tools.filter((t) => !new RegExp('<Link\\s+(?:[^>]*\\s)?to=["\']\\/' + t.route + '["\']').test(own));
        if (missing.length) {
            throw new Error('The sidebar already shows a "Tools" heading - the platform draws it for the tool tabs (' + names + '). A second section labelled "Tools" beside it would show the heading twice. Nothing was changed. Make it ONE section: send this edit again with a link to each tool tab inside your section too - ' + missing.map((t) => 'to="/' + t.route + '" labelled "' + t.label + '"').join('; ') + ' - written like its neighbours, icon per rule 28c. The platform heading removes itself once your section links to every tool tab, so yours is then the only Tools section.');
        }
    }
}

'''

RULES = r'''28. TOOL TABS, AND WHAT "THE SELL TAB" MEANS. A request that carries the admin console's files also carries CONSOLE TABS: the tabs this console's owner added from the tab settings. Each has a label, a route, an icon key and a kind.
   kind "tool" is a PLATFORM PAGE (for example Sell = the VIN Scanner). It has NO page file and NO route in main.tsx, on purpose: the platform draws it at that address. You will not find it by searching the files, and that does not mean it is missing or that you should build it.
   kind "blank" is an empty tab waiting for a page. Building a page at its route is exactly what it is for.
   (a) WHEN THE USER NAMES A TAB THAT IS IN CONSOLE TABS, THEY MEAN THAT TAB. "Sell", "my Sell tab", "the actual Sell tab", "the global Sell tab" all mean the tab labelled Sell at its own route. Never a sub-tab inside another page that happens to share the name, never a form, never a new page of yours. If you are about to point a link at anything other than that tab's route, you have misread the request.
   (b) NEVER add a <Route> at a tool tab's route, never create a page for it, and never send an adminPages entity that would take its address. A route there replaces the owner's tool with your page. The platform refuses it.
   (c) TO LINK TO A TOOL TAB from the sidebar (the user asks to move it, list it, or put it in a section): add ONE link in src/admin/AdminLayout.tsx, written exactly like its neighbours, with to="/<route>" and the tab's label. For its icon use the tab's own: {React.createElement(hwmIconFor('<icon key>'), { size: 18 })} with the icon key from CONSOLE TABS - the same call the platform uses, so it is always the icon the owner chose. Change nothing else: no route, no page, no edit to any other page. The link shows the tool because the address already does.
   (d) THE SIDEBAR "TOOLS" HEADING IS DRAWN BY THE PLATFORM - it is the block between the GS_ADMIN_MNAV_V1:E markers, and it lists the tool tabs. NEVER edit anything between GS_ADMIN_MNAV_V1 markers; Sync Core rewrites those blocks. When the user asks to put pages "under Tools" or "in the Tools section", do NOT add a second heading beside it. Make ONE <NavSection> of your own - a new id, and the label the user used ("Tools" unless they said another) - placed directly after the {/* GS_ADMIN_MNAV_V1:/E */} marker, holding a link to EVERY tool tab first (per (c)) and then the pages the user named, moved from where they were. The platform heading removes itself as soon as your section links to every tool tab, so the sidebar ends up with one Tools section holding everything. Do it in a single edit, so the sidebar is never left with two.
   (e) A sidebar section of your own is kept by Sync Core exactly as you wrote it. Inside it use only what AdminLayout already defines or imports (NavSection, tabWrap, Link, navClass, hwmIconFor, the imported icons).

29. "REVERT", "UNDO" AND "PUT IT BACK" MEAN EXACTLY THAT. Restore what your earlier turns changed - take out the import, route, link or code you added, put back what you removed - and change nothing else. Never answer "revert" by building the thing a different way, and never describe a new change as a revert. The chat history shows what you reported changing: read the current files and undo those changes specifically. If you cannot tell what the earlier state was, say so in one line and tell the user to press Undo on the message that made the change; do not guess. And if you have been told you got the same request wrong twice, stop changing files: say in one line what you understand the request to be and ask the one question that would settle it.

'''

GEN_NEW = r'''        // CONSOLE TABS (rule 28): the tabs the owner added from the tab settings.
        // They are not in the files, so the model is told - fresh on every
        // request that carries the console - and the agent's edits are checked
        // against them (gsAgentTabGuard). Unreadable = none = as before.
        let adminTabs = [];
        if (hasAdminFiles) {
          try { adminTabs = (await gsAdminTabs(env, (backendContext && backendContext.tenant_id) || appId)) || []; } catch (e) { adminTabs = []; }
          if (adminTabs.length) backendSection += `\n\nCONSOLE TABS (tabs this console's owner added from the tab settings - they are NOT in the files. See rule 28):\n${JSON.stringify(adminTabs)}`;
        }

'''

APPLY_PRE = r'''            // An admin page takes the address of its entity. One that would
            // land on a tool tab's address (a "sell" table, with the Sell tab
            // showing the VIN Scanner) would put a second "Sell" in the sidebar
            // on top of the owner's tab. The table is still made; the page is
            // skipped and the reason goes back to the model and the user.
            let gsToolTabs = [];
            if (specPages.length) {
                try { gsToolTabs = ((await gsAdminTabs(env, own.tenantId)) || []).filter(t => t && t.kind === 'tool'); } catch (e) { gsToolTabs = []; }
            }
'''
APPLY_IN = r'''                const gsTabHit = gsToolTabs.find(t => t.route === entity.replace(/_/g, '-'));
                if (gsTabHit) {
                    skipped.push({ name: entity, reason: 'no admin page was generated: /' + gsTabHit.route + ' is the "' + gsTabHit.label + '" tab, which shows the ' + gsTabHit.tool + ' - a page there would sit on top of it. Use a different entity name if this needs its own page' });
                    continue;
                }
'''

A_HELP = 'function gsAgentLineOf(text, idx) {'
A_EDIT = "            if (!next.trim()) throw new Error('That edit would leave ' + p + ' empty. Nothing was changed.');\n"
A_GEN = '        const combinedPrompt = `Project Files:'
A_CALL = '              schemaLookup: gsMakeSchemaLookup(env, appId, backendContext),\n'
A_LOOP = '            for (const p of specPages) {\n'
A_ENT = "                const entity = bareEntity(p && p.entity);\n                if (!IDENT.test(entity)) continue;\n"
A_RULE = '25. REPORT WHAT HAPPENED, NOT WHAT YOU SENT.'

# (anchor, replacement, label)
STEPS = [
    (A_HELP, HELPERS + A_HELP, 'tab list + edit guard'),
    (A_EDIT, A_EDIT + "            gsAgentTabGuard(p, cur, next, o.adminTabs);\n", 'edit_file checks the guard'),
    (A_GEN, GEN_NEW + A_GEN, 'CONSOLE TABS in every admin request'),
    (A_CALL, A_CALL + '              adminTabs,\n', 'agent receives the tab list'),
    (A_LOOP, APPLY_PRE + A_LOOP, 'backend pages: read tool tabs'),
    (A_ENT, A_ENT + APPLY_IN, 'backend pages: skip a page on a tool tab'),
    (A_RULE, RULES + A_RULE, 'rules 28 and 29'),
]


def md5(s):
    return hashlib.md5(s.encode('utf-8')).hexdigest()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    path = sys.argv[1]
    reverse = '--reverse' in sys.argv[2:]
    with open(path, 'r', encoding='utf-8') as f:
        s = f.read()
    print('before md5', md5(s))

    applied = 'function gsAgentTabGuard(p, before, after, tabs) {' in s
    if applied and not reverse:
        print('already applied - nothing to do')
        return
    if reverse and not applied:
        print('not applied - nothing to undo')
        return

    # the prompt lives in a template literal: nothing in the rules may end it
    assert '`' not in RULES and '${' not in RULES, 'rules text would break the prompt string'

    out = s
    if not reverse:
        assert out.count('async function gsAgentRun(o) {') == 1, 'this worker has no sandbox agent - wrong file?'
        assert out.count("const hasAdminFiles = fileNames.some(n => n.includes('src/admin/'));") == 1, 'hasAdminFiles not found'
        assert out.count("        let backendSection = '';") == 1, 'backendSection not found'
        for old, new, label in STEPS:
            n = out.count(old)
            assert n == 1, '%s: anchor found %d times - nothing was written' % (label, n)
        for old, new, label in STEPS:
            out = out.replace(old, new, 1)
            print('ok', label)
    else:
        for old, new, label in reversed(STEPS):
            n = out.count(new)
            assert n == 1, '%s: patched text found %d times - nothing was written' % (label, n)
        for old, new, label in reversed(STEPS):
            out = out.replace(new, old, 1)
            print('undone', label)

    # self-check
    if not reverse:
        for needle in ['function gsTabsFromConfig(cfg) {', 'async function gsAdminTabs(env, tenantId) {',
                       'gsAgentTabGuard(p, cur, next, o.adminTabs);', 'CONSOLE TABS (tabs this console', '              adminTabs,\n',
                       'const gsTabHit = gsToolTabs.find(', '28. TOOL TABS, AND WHAT "THE SELL TAB" MEANS.', '29. "REVERT", "UNDO" AND "PUT IT BACK" MEAN EXACTLY THAT.']:
            assert out.count(needle) == 1, 'self-check failed: ' + needle[:40]
    else:
        assert 'gsAgentTabGuard' not in out and 'gsAdminTabs' not in out and 'CONSOLE TABS' not in out, 'undo left something behind'

    with open(path + '.bak', 'w', encoding='utf-8') as f:
        f.write(s)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(out)
    print('after md5 ', md5(out))
    print('backup    ', os.path.basename(path) + '.bak')


if __name__ == '__main__':
    main()
