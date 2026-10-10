#!/usr/bin/env python3
"""
patch_controller_047.py - the Assist tab stops timing out ("Claude API error 524").

Requires 046. Unique anchors, assert before write, idempotent.

  python3 patch_controller_047.py worker.js

WHAT HAPPENED
046 gave Claude 16000 tokens of room instead of 4000, which stopped the empty
answers. But the route still asked for the reply WHOLE: not one byte came back
until Claude had finished thinking and writing. On a long thread that now
takes longer than the connection in front of the API will sit silent, so it
answered 524 (a timeout) and the reply was lost. Same cause as before, one
layer out: the wait got longer, and something else gave up first.

WHAT THIS CHANGES
1. The Worker reads Claude's reply as a stream. Bytes start at once and keep
   coming, so there is no silent wait to time out. Used by the ask route and
   by the unattended triage judge.
2. If the stream breaks part way (overloaded, connection dropped, nothing for
   two minutes) it is tried once more. If that fails too, the error says which
   of those it was.
3. POST /api/controller/ask with "stream": true answers as NDJSON, the same
   shape the builder chat already uses:
     {"type":"status","message":"thinking"}     at once, then every 10 seconds
     {"type":"text","delta":"..."}              words as they are written
     {"type":"retry","why":"empty"|"busy"}      discard what was shown, trying again
     {"type":"result","status":200, ...}        last line: exactly what the
                                                route returns without "stream"
   Without "stream" the route answers one JSON object as before, so a console
   page that has not had patch_controller_html_047.py still works - and no
   longer times out at the API, though it shows nothing until the end.
"""
import sys, os

FN_OLD = r'''async function gsCtlClaude(env, payload, waitMs) {
    const once = async (p) => {
        const send = () => fetch('https://api.anthropic.com/v1/messages', {
            method: 'POST',
            headers: { 'x-api-key': env.CLAUDE_API_KEY, 'anthropic-version': '2023-06-01', 'content-type': 'application/json' },
            body: JSON.stringify(p)
        });
        let r = await send();
        if (!r.ok && GS_CTL_RETRY_STATUS.indexOf(r.status) !== -1) {
            await new Promise((res) => setTimeout(res, waitMs == null ? 2000 : waitMs));
            r = await send();
        }
        if (!r.ok) return { ok: false, status: r.status, detail: (await r.text()).slice(0, 400) };
        return { ok: true, d: await r.json() };
    };

    const a = await once(payload);
    if (!a.ok) return a;
    let rep = gsCtlReplyOf(a.d);
    let usage = a.d.usage || null;
    let model = a.d.model || null;
    const first = rep.stop;
    let tries = 1;

    // A refusal is a decision, not a shortage of room: asking the identical
    // thing again at lower effort does not change it.
    if (!rep.text && rep.stop !== 'refusal') {
        tries = 2;
        const b = await once({ ...payload, output_config: { ...(payload.output_config || {}), effort: 'low' } });
        if (b.ok) {
            rep = gsCtlReplyOf(b.d);
            usage = gsCtlUsageAdd(usage, b.d.usage || null);
            model = b.d.model || model;
        }
    }
    return { ok: true, text: rep.text, stop: rep.stop, usage, model, tries, first_stop: first };
}
'''

FN_NEW = r'''// 047: the reply is read as a STREAM. Asking for it whole meant no byte came
// back until Claude had finished thinking and writing, and with 16000 tokens
// of room that can pass the point where the connection in front of the API
// gives up: "Claude API error 524", a timeout, with the answer thrown away.
// A stream starts answering at once and keeps the line busy to the end.
const GS_CTL_IDLE_MS = 120000;      // no byte at all for this long: the reply is dead, not slow
const GS_CTL_BEAT_MS = 10000;       // how often the console is told "still working"

// Reads Claude's event stream into the same shape a whole reply has.
// onEvent gets { type:'text', delta } as words arrive and { type:'tick' } for
// anything else (thinking, pings), so a caller can show progress.
// Returns { ok:true, d } or { ok:false, status, detail, retry }.
async function gsCtlReadStream(r, onEvent) {
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = '', text = '', blocks = 0, stop = null, usage = null, model = null, ended = false, bad = null;
    const eat = (line) => {
        line = line.trim();
        if (line.indexOf('data:') !== 0) return;
        let ev; try { ev = JSON.parse(line.slice(5).trim()); } catch (e) { return; }
        if (!ev || !ev.type) return;
        if (ev.type === 'message_start') {
            model = (ev.message && ev.message.model) || model;
            usage = gsCtlUsageAdd(null, (ev.message && ev.message.usage) || null);
        } else if (ev.type === 'content_block_start') {
            if (ev.content_block && ev.content_block.type === 'text') {
                // Separate text blocks with a newline, as the whole-reply code did.
                if (blocks++ && text) { text += '\n'; onEvent({ type: 'text', delta: '\n' }); }
                if (ev.content_block.text) { text += ev.content_block.text; onEvent({ type: 'text', delta: ev.content_block.text }); }
            } else onEvent({ type: 'tick' });
        } else if (ev.type === 'content_block_delta') {
            if (ev.delta && ev.delta.type === 'text_delta' && ev.delta.text) { text += ev.delta.text; onEvent({ type: 'text', delta: ev.delta.text }); }
            else onEvent({ type: 'tick' });
        } else if (ev.type === 'message_delta') {
            if (ev.delta && ev.delta.stop_reason) stop = ev.delta.stop_reason;
            if (ev.usage) { usage = usage || {}; Object.keys(ev.usage).forEach((k) => { if (typeof ev.usage[k] === 'number') usage[k] = ev.usage[k]; }); }
        } else if (ev.type === 'message_stop') {
            ended = true;
        } else if (ev.type === 'error') {
            bad = ev.error || { type: 'error', message: 'stream error' };
        } else onEvent({ type: 'tick' });
    };
    try {
        for (;;) {
            let timer;
            const idle = new Promise((_, rej) => { timer = setTimeout(() => rej(new Error('gs-idle')), GS_CTL_IDLE_MS); });
            let step;
            try { step = await Promise.race([reader.read(), idle]); } finally { clearTimeout(timer); }
            if (step.done) break;
            buf += dec.decode(step.value, { stream: true });
            let nl;
            while ((nl = buf.indexOf('\n')) !== -1) { eat(buf.slice(0, nl)); buf = buf.slice(nl + 1); if (bad) break; }
            if (bad) break;
        }
        if (!bad && buf) eat(buf);
    } catch (e) {
        try { reader.cancel(); } catch (e2) {}
        const stalled = String(e && e.message) === 'gs-idle';
        return { ok: false, retry: true, status: stalled ? 'stalled' : 'cut',
                 detail: stalled ? 'Claude sent nothing for ' + Math.round(GS_CTL_IDLE_MS / 1000) + ' seconds, part way through the reply.'
                                 : 'The connection to Claude dropped part way through the reply (' + String(e && e.message || e).slice(0, 160) + ').' };
    }
    if (bad) {
        try { reader.cancel(); } catch (e2) {}
        const t = String(bad.type || 'error');
        return { ok: false, retry: t === 'overloaded_error' || t === 'api_error' || t === 'rate_limit_error', status: t,
                 detail: String(bad.message || t).slice(0, 400) };
    }
    if (!ended && !stop) {
        return { ok: false, retry: true, status: 'cut', detail: 'The connection to Claude closed before the reply finished.' };
    }
    return { ok: true, d: { content: text ? [{ type: 'text', text }] : [], stop_reason: stop, usage, model } };
}

// Says what went wrong in words the console shows as they are.
function gsCtlFailText(res) {
    if (typeof res.status === 'number') return 'Claude API error ' + res.status;
    if (res.status === 'stalled') return 'Claude stopped responding part way through the reply';
    if (res.status === 'cut') return 'The connection to Claude dropped part way through the reply';
    return 'Claude stopped part way through the reply (' + res.status + ')';
}

async function gsCtlClaude(env, payload, waitMs, onEvent) {
    const tell = typeof onEvent === 'function' ? (ev) => { try { onEvent(ev); } catch (e) {} } : () => {};
    const once = async (p) => {
        const attempt = async () => {
            let r;
            try {
                r = await fetch('https://api.anthropic.com/v1/messages', {
                    method: 'POST',
                    headers: { 'x-api-key': env.CLAUDE_API_KEY, 'anthropic-version': '2023-06-01', 'content-type': 'application/json' },
                    body: JSON.stringify({ ...p, stream: true })
                });
            } catch (e) {
                return { ok: false, retry: true, status: 'cut', detail: 'Could not reach the Claude API (' + String(e && e.message || e).slice(0, 160) + ').' };
            }
            if (!r.ok) return { ok: false, retry: GS_CTL_RETRY_STATUS.indexOf(r.status) !== -1, status: r.status, detail: (await r.text()).slice(0, 400) };
            // A whole (non-stream) JSON reply is still understood.
            if (!r.body || String(r.headers.get('content-type') || '').indexOf('event-stream') === -1) return { ok: true, d: await r.json() };
            return await gsCtlReadStream(r, tell);
        };
        let a = await attempt();
        if (!a.ok && a.retry) {
            // Anything already shown from the failed attempt is withdrawn.
            tell({ type: 'retry', why: 'busy' });
            await new Promise((res) => setTimeout(res, waitMs == null ? 2000 : waitMs));
            a = await attempt();
        }
        return a;
    };

    const a = await once(payload);
    if (!a.ok) return a;
    let rep = gsCtlReplyOf(a.d);
    let usage = a.d.usage || null;
    let model = a.d.model || null;
    const first = rep.stop;
    let tries = 1;

    // A refusal is a decision, not a shortage of room: asking the identical
    // thing again at lower effort does not change it.
    if (!rep.text && rep.stop !== 'refusal') {
        tries = 2;
        tell({ type: 'retry', why: 'empty' });
        const b = await once({ ...payload, output_config: { ...(payload.output_config || {}), effort: 'low' } });
        if (b.ok) {
            rep = gsCtlReplyOf(b.d);
            usage = gsCtlUsageAdd(usage, b.d.usage || null);
            model = b.d.model || model;
        }
    }
    return { ok: true, text: rep.text, stop: rep.stop, usage, model, tries, first_stop: first };
}
'''

ASK_OLD = r'''                    const res = await gsCtlClaude(env, {
                        model: gsClaudeModel(body.model || 'claude-opus-5'),
                        max_tokens: GS_CTL_ASK_ROOM,
                        system: GS_CTL_ASK_SYSTEM,
                        messages: [...hist, { role: 'user', content }]
                    });
                    if (!res.ok) {
                        return gsCtlJson({ error: 'Claude API error ' + res.status, detail: res.detail }, 502);
                    }
                    const extra = {
                        usage: res.usage,
                        model: res.model,
                        stop_reason: res.stop || null,
                        tries: res.tries,
                        attachments: { used: att.used, skipped: att.skipped }
                    };
                    if (!res.text) {
                        // Still HTTP 200 with the reason in `answer`, so a console
                        // without the 046 page shows the reason too.
                        return gsCtlJson({ answer: gsCtlEmptyWhy(res.stop, res.tries), empty: true, ...extra });
                    }
                    const cutOff = res.stop === 'max_tokens';
                    return gsCtlJson({
                        answer: res.text + (cutOff ? '\n\n[Cut off here: the reply hit its length limit. Ask it to continue and it will pick up from this point.]' : ''),
                        ...(cutOff ? { truncated: true } : {}),
                        ...extra
                    });
'''

ASK_NEW = r'''                    const askPayload = {
                        model: gsClaudeModel(body.model || 'claude-opus-5'),
                        max_tokens: GS_CTL_ASK_ROOM,
                        system: GS_CTL_ASK_SYSTEM,
                        messages: [...hist, { role: 'user', content }]
                    };
                    // One place decides what the console is told, whichever
                    // way the answer travels back. Returns [body, http status].
                    const shape = (res) => {
                        if (!res.ok) return [{ error: gsCtlFailText(res), detail: res.detail }, 502];
                        const extra = {
                            usage: res.usage,
                            model: res.model,
                            stop_reason: res.stop || null,
                            tries: res.tries,
                            attachments: { used: att.used, skipped: att.skipped }
                        };
                        // Still HTTP 200 with the reason in `answer`, so a console
                        // without the 046 page shows the reason too.
                        if (!res.text) return [{ answer: gsCtlEmptyWhy(res.stop, res.tries), empty: true, ...extra }, 200];
                        const cutOff = res.stop === 'max_tokens';
                        return [{
                            answer: res.text + (cutOff ? '\n\n[Cut off here: the reply hit its length limit. Ask it to continue and it will pick up from this point.]' : ''),
                            ...(cutOff ? { truncated: true } : {}),
                            ...extra
                        }, 200];
                    };

                    // 047: the console asks for the answer as it is written.
                    // Same NDJSON shape the builder chat already uses: status
                    // lines, then ONE final {type:'result'} line carrying what
                    // this route used to return whole. A status line goes out
                    // every ten seconds whatever Claude is doing, so the line
                    // to the browser is never silent long enough to be cut.
                    if (body.stream === true) {
                        const enc = new TextEncoder();
                        const stream = new ReadableStream({
                            async start(controller) {
                                const send = (o) => { try { controller.enqueue(enc.encode(JSON.stringify(o) + '\n')); } catch (e) {} };
                                send({ type: 'status', message: 'thinking' });
                                const beat = setInterval(() => send({ type: 'status', message: 'working' }), GS_CTL_BEAT_MS);
                                try {
                                    const res = await gsCtlClaude(env, askPayload, null, (ev) => {
                                        if (ev.type === 'text' || ev.type === 'retry') send(ev);
                                    });
                                    const out = shape(res);
                                    send({ type: 'result', status: out[1], ...out[0] });
                                } catch (e) {
                                    send({ type: 'result', status: 500, error: String(e && e.message || e) });
                                }
                                clearInterval(beat);
                                try { controller.close(); } catch (e) {}
                            }
                        });
                        return new Response(stream, { status: 200, headers: { 'Content-Type': 'application/x-ndjson; charset=utf-8', 'Cache-Control': 'no-store', ...GS_CTL_CORS } });
                    }

                    const out = shape(await gsCtlClaude(env, askPayload));
                    return gsCtlJson(out[0], out[1]);
'''


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'worker.js'
    if not os.path.exists(path):
        sys.exit(f"FAIL: {path} not found")
    src = open(path, encoding='utf-8').read()

    if 'async function gsCtlReadStream(' in src:
        print("already patched - nothing to do")
        return
    if 'async function gsCtlClaude(' not in src:
        sys.exit("FAIL: 046 is not applied to this worker. Run patch_controller_046.py first. Nothing written.")

    hunks = [("model call", FN_OLD, FN_NEW), ("ask route", ASK_OLD, ASK_NEW)]
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
