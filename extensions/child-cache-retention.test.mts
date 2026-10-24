const { default: install, defaultChildRetention } = await import("./child-cache-retention.ts");

let bad = 0;
const check = (name: string, ok: boolean, detail?: unknown) => { if (!ok) { bad++; console.log("FAIL", name, detail ?? ""); } };

{
  const env: Record<string, string | undefined> = { PI_CACHE_RETENTION: "long" };
  defaultChildRetention(env);
  check("unset becomes short", env.PI_SUBAGENT_CACHE_RETENTION === "short", env);
  check("parent retention untouched", env.PI_CACHE_RETENTION === "long", env);
}
{
  const env: Record<string, string | undefined> = { PI_SUBAGENT_CACHE_RETENTION: "long" };
  defaultChildRetention(env);
  check("exported value wins", env.PI_SUBAGENT_CACHE_RETENTION === "long", env);
}
{
  const env: Record<string, string | undefined> = { PI_SUBAGENT_CACHE_RETENTION: "" };
  defaultChildRetention(env);
  check("empty counts as unset", env.PI_SUBAGENT_CACHE_RETENTION === "short", env);
}
{
  const old = process.env.PI_SUBAGENT_CACHE_RETENTION;
  delete process.env.PI_SUBAGENT_CACHE_RETENTION;
  install({});
  check("load sets the process default", process.env.PI_SUBAGENT_CACHE_RETENTION === "short");
  if (old === undefined) delete process.env.PI_SUBAGENT_CACHE_RETENTION; else process.env.PI_SUBAGENT_CACHE_RETENTION = old;
}

if (bad) { console.log(`${bad} check(s) failed`); process.exit(1); }
console.log("ok");
