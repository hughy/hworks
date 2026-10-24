// Puts subagent children on Anthropic's 5-minute prompt cache while the main session keeps the
// 1-hour one. cbcode launches pi with PI_CACHE_RETENTION=long, which bills every Anthropic cache
// write at 2x input instead of 1.25x. Children rarely pause past 5 minutes, so the longer lifetime
// saves them few rewrites. pi-subagents applies PI_SUBAGENT_CACHE_RETENTION to children only,
// reading it from this process's environment at each launch, foreground and background alike. It
// is environment-only and cbcode does not set it, so this sets the default when pi loads.
// An exported value wins: PI_SUBAGENT_CACHE_RETENTION=long keeps children on the 1-hour cache.

export function defaultChildRetention(env: Record<string, string | undefined> = process.env): void {
  if (!env.PI_SUBAGENT_CACHE_RETENTION) env.PI_SUBAGENT_CACHE_RETENTION = "short";
}

export default function (_pi: unknown) {
  defaultChildRetention();
}
