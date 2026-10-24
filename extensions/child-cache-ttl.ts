// Gives subagent child sessions Anthropic's 5-minute prompt cache instead of the 1-hour one.
// cbcode launches pi with PI_CACHE_RETENTION=long, so every Anthropic cache write is billed at 2x
// input instead of 1.25x. Children rarely pause longer than 5 minutes between turns, so the longer
// lifetime saves them few rewrites and doubles the price of every write. The main session keeps
// the 1-hour cache: pauses between operator turns make it pay there.
// A child is a session whose file is <parent>/<run id>/run-N/session.jsonl, the pi-subagents
// layout. Only cache_control blocks change: each loses its ttl, which leaves the 5-minute default.
// pi-subagents loads ambient extensions only in background (async) children; foreground children
// load none, so they keep the 1-hour cache.
// PI_CHILD_CACHE_TTL=0 disables it.

const CHILD_FILE = /\/[0-9a-f-]{36}\/run-\d+\/session\.jsonl$/;

export function isChildSession(file: unknown): boolean {
  return typeof file === "string" && CHILD_FILE.test(file.replaceAll("\\", "/"));
}

function stripBlocks(list: unknown): { list: unknown; changed: boolean } {
  if (!Array.isArray(list)) return { list, changed: false };
  let changed = false;
  const out = list.map((block) => {
    const cc = block?.cache_control;
    if (!cc || typeof cc !== "object" || !("ttl" in cc)) return block;
    changed = true;
    const { ttl: _ttl, ...rest } = cc;
    return { ...block, cache_control: rest };
  });
  return { list: changed ? out : list, changed };
}

// Returns a copy of an Anthropic Messages payload without cache_control ttl, or undefined when
// nothing carries one (other providers' payloads, or retention already short).
export function shortenCacheTtl(payload: any): any {
  if (!payload || typeof payload !== "object") return undefined;
  const next: any = { ...payload };
  let changed = false;
  for (const key of ["system", "tools"]) {
    if (!(key in payload)) continue;
    const r = stripBlocks(payload[key]);
    next[key] = r.list;
    changed ||= r.changed;
  }
  if (Array.isArray(payload.messages)) {
    next.messages = payload.messages.map((m: any) => {
      const r = stripBlocks(m?.content);
      if (!r.changed) return m;
      changed = true;
      return { ...m, content: r.list };
    });
  }
  return changed ? next : undefined;
}

export default function (pi: any) {
  if (process.env.PI_CHILD_CACHE_TTL === "0") return;
  pi.on("before_provider_request", (event: any, ctx: any) => {
    if (!isChildSession(ctx?.sessionManager?.getSessionFile?.())) return undefined;
    return shortenCacheTtl(event.payload);
  });
}
