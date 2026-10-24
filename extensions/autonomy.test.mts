import { mkdtempSync, readFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const logPath = join(mkdtempSync(join(tmpdir(), "autonomy-test-")), "blockers.jsonl");
process.env.HWORKS_BLOCKERS_LOG = logPath;
delete process.env.PI_AUTONOMY;
const { classify, grantsFrom, default: register } = await import("./autonomy.ts");
const block = ["git reset --hard HEAD~1","git -C repo reset --hard","git clean -fdx","git push --force origin feat","git push -f","git push --force-with-lease origin feat","git push origin +feat","git branch -D old","git stash drop","git worktree remove --force ../wt","DROP TABLE users;","kubectl delete pod x","terraform apply","psql -c \"drop table users\"","cd \"my repo\" && git reset --hard","python3 - <<'EOF'\nprint(1)\nEOF\ngit reset --hard","git commit -m 'wip' && git push --force origin x","python3 - <<'EOF' && git reset --hard\nprint(1)\nEOF","cat <<'EOF' # don't expand variables\nnotes\nEOF\ngit reset --hard HEAD~1\nprintf 'done'"];
const allow = ["git worktree remove --force /tmp/wt","rm -rf build","git checkout -- src/a.ts","rm -rf /tmp/foo","rm -f $TMPDIR/x","rm ~/.local/state/agent-tasks/t/a.md","find /tmp/x -delete","git rm src/old.ts","git status","git push origin feat","git restore --staged a.ts","git checkout -b new","git checkout main","git branch -d merged","git stash push","git reset HEAD~1","git reset --soft HEAD~1","grep -rn 'rm -rf' .","npm run format","git commit -m 'remove dead code'","echo terraform plan","agent -p \"run git reset --hard and report\"","git commit -m 'docs: never git reset --hard'","python3 - <<'EOF'\ns = 'never `git reset --hard`'\nEOF","cat > f.md <<EOF\nuse git push --force rarely\nEOF\necho ok","grep -n \"git-reset-hard\\|reset --hard\" log"];
block.push("git push --force-with-lease=feat origin feat", "git push --force-if-includes --force origin x", "git push --force-with-lease= origin x", "git reset --merge", "d=$(mktemp -d); git worktree remove --force $other", "git worktree remove -f ~/dev/repo-wt");
allow.push(
  "git push --force-with-lease=feat:e177836 origin feat",
  "B=feat; git push -q --force-with-lease=$B:5bc10d4f origin $B 2>&1 | tail -3",
  "git push --force-with-lease=\"$B:$SHA\" origin HEAD:refs/heads/x",
  "git push --force-with-lease=a:1 --force-if-includes origin a",
  "git reset --keep origin/feat",
  "d=$(mktemp -d); git worktree add -q --detach $d HEAD && (cd $d && make); git worktree remove $d --force",
  "d=$(mktemp -d); git worktree add $d/wt HEAD; git worktree remove --force $d/wt",
  "git worktree remove --force \"$TMPDIR/wt\"",
  "git worktree remove --force /private/var/folders/x/T/wt",
  "git worktree remove ../wt",
);
let bad=0;
for (const c of block) { const r=classify(c); if(!r){bad++;console.log("MISSED  ",c);} }
for (const c of allow) { const r=classify(c); if(r){bad++;console.log("FALSE+  ",c,"->",r);} }

// Operator prompts grant the rules they ask for; negated clauses deny them.
const g = (p: string) => [...grantsFrom(p)].sort().join(",");
for (const [prompt, want] of [
  ["rebase this branch onto main and push it", "git push --force-with-lease"],
  ["Squash the fixups, then force-push", "git push --force-with-lease"],
  ["Commit on the current branch with new commits only: no amend, rebase, reset, or push.", ""],
  ["Rebase onto main. Do not force-push.", ""],
  ["never git reset --hard", ""],
  ["delete the merged branches and clean up stale worktrees", "git branch -D,git worktree remove --force"],
  ["hard reset to origin/main", "git reset --hard"],
  ["fix the flaky test", ""],
] as const) {
  const got = g(prompt);
  if (got !== want) { bad++; console.log("GRANT   ", JSON.stringify(prompt), "->", got, "want", want); }
}

// Fake pi API: records every registered hook, tool, and command.
function fakePi() {
  const hooks: Record<string, any[]> = {};
  const tools: Record<string, any> = {};
  const commands: Record<string, any> = {};
  return {
    hooks, tools, commands,
    registerCommand(name: string, def: any) { commands[name] = def; },
    registerTool(def: any) { tools[def.name] = def; },
    on(name: string, fn: any) { (hooks[name] ??= []).push(fn); },
    emit(name: string, event: any = {}, c: any = ctx) { let r; for (const fn of hooks[name] ?? []) r = fn({ type: name, ...event }, c) ?? r; return r; },
  };
}
const ctx = { cwd: "/repo", sessionManager: { getSessionId: () => "s1" }, ui: { notify() {} } };
const pi = fakePi();
register(pi);
const call = (toolName: string, input: any) => pi.emit("tool_call", { toolName, input });
const setPhase = (phase: string) => pi.tools.autonomy_phase.execute("id", { phase }, undefined, undefined, ctx);
const readLog = () => existsSync(logPath) ? readFileSync(logPath, "utf8").trim().split("\n").map((l) => JSON.parse(l)) : [];
const check = (label: string, ok: boolean, info: unknown = "") => { if (!ok) { bad++; console.log("FAIL    ", label, info); } };
const ask = { questions: [{ question: "Pick a color?" }] };
const destructive = { command: "git branch -D old" };
let checks = 0;
const expectBlock = (label: string, toolName: string, input: any, shouldBlock: boolean) => {
  checks++;
  const r = call(toolName, input);
  check(label, !!r?.block === shouldBlock, `${toolName} ${JSON.stringify(input)} -> ${JSON.stringify(r)}`);
};

// Work phase (default): blocks and logs asks and destructive commands, logs decision requests, ignores the rest.
expectBlock("work ask", "ask_user_question", ask, true);
expectBlock("work destructive", "bash", destructive, true);
expectBlock("work status", "bash", { command: "git status" }, false);
expectBlock("work supervisor", "contact_supervisor", { reason: "need_decision", message: "Which API?" }, false);
expectBlock("work progress", "contact_supervisor", { reason: "progress_update", message: "half done" }, false);
let logged = readLog();
let kinds = logged.map((r) => `${r.kind}:${r.rule}:${r.blocked}`).join(",");
check("work log", kinds === "ask:ask_user_question:true,destructive:git branch -D:true,supervisor:need_decision:false"
  && logged.every((r) => r.session === "s1" && r.cwd === "/repo" && typeof r.ts === "string" && "detail" in r), kinds);

// The tool schema is a plain JSON schema with exactly the two phases.
const tool = pi.tools.autonomy_phase;
check("tool schema", JSON.stringify(tool?.parameters?.properties?.phase?.enum) === '["work","cleanup"]' && tool.parameters.required?.[0] === "phase");
let threw = false;
try { await setPhase("done"); } catch { threw = true; }
check("tool rejects unknown phase", threw);

// Cleanup: asks and classified commands pass through to other guards, logged with blocked false.
const res = await setPhase("cleanup");
check("cleanup result text", /cleanup/.test(res?.content?.[0]?.text ?? ""), res);
const before = readLog().length;
expectBlock("cleanup ask", "ask_user_question", ask, false);
expectBlock("cleanup destructive", "bash", destructive, false);
pi.emit("turn_start"); pi.emit("turn_end");
expectBlock("cleanup survives turn change", "bash", destructive, false);
kinds = readLog().slice(before).map((r) => `${r.kind}:${r.rule}:${r.blocked}`).join(",");
check("cleanup log", kinds === "ask:ask_user_question:false,destructive:git branch -D:false,destructive:git branch -D:false", kinds);

// Re-entering work restores the blocks.
await setPhase("work");
expectBlock("work re-entry ask", "ask_user_question", ask, true);
expectBlock("work re-entry destructive", "bash", destructive, true);

// Every lifecycle reset returns cleanup to work.
for (const [event, payload] of [["agent_start", {}], ["session_start", { reason: "new" }], ["session_start", { reason: "fork" }], ["session_start", { reason: "resume" }], ["session_tree", { newLeafId: "b", oldLeafId: "a" }]] as const) {
  await setPhase("cleanup");
  pi.emit(event, payload);
  expectBlock(`${event} ${JSON.stringify(payload)} resets`, "bash", destructive, true);
}

// /autonomy off lets everything through without logging destructive calls; on restores blocking.
await pi.commands.autonomy.handler("off", ctx);
const offStart = readLog().length;
expectBlock("off ask", "ask_user_question", ask, false);
expectBlock("off destructive", "bash", destructive, false);
const offLog = readLog().slice(offStart).map((r) => `${r.kind}:${r.blocked}`).join(",");
check("off log", offLog === "ask:false", offLog);
await pi.commands.autonomy.handler("on", ctx);
expectBlock("on destructive", "bash", destructive, true);

// The block reason names a task-dir.sh that exists, resolved through the extension's symlink.
const askReason = call("ask_user_question", {})?.reason ?? "";
const script = askReason.match(/`(\S+\/scripts\/task-dir\.sh) <task-slug>`/)?.[1];
check("task-dir", !!script && existsSync(script), script);
check("reason names autonomy_phase", askReason.includes("autonomy_phase"));

// A block reason carries the rule's retry hint.
const pushReason = call("bash", { command: "git push --force origin x" })?.reason ?? "";
check("push reason names lease form", pushReason.includes("--force-with-lease=<branch>:<sha>"), pushReason);

// An operator prompt grants its rules for the session; plain --force stays blocked; session_start clears grants.
pi.emit("before_agent_start", { messageType: "custom", prompt: "rebase onto main" });
expectBlock("custom message grants nothing", "bash", { command: "git push --force-with-lease origin x" }, true);
pi.emit("before_agent_start", { messageType: "user", prompt: "rebase onto main and push" });
pi.emit("agent_start");
expectBlock("granted lease push", "bash", { command: "git push --force-with-lease origin x" }, false);
expectBlock("plain force still blocked", "bash", { command: "git push --force origin x" }, true);
expectBlock("ungranted rule still blocked", "bash", destructive, true);
pi.emit("before_agent_start", { messageType: "user", prompt: "continue" });
pi.emit("agent_start");
expectBlock("grant survives later runs", "bash", { command: "git push --force-with-lease origin x" }, false);
check("grant logged once", readLog().filter((r) => r.kind === "grant").length === 1);
pi.emit("session_start", { reason: "new" });
expectBlock("session_start clears grants", "bash", { command: "git push --force-with-lease origin x" }, true);

// PI_AUTONOMY=0 registers nothing.
process.env.PI_AUTONOMY = "0";
const off = fakePi();
register(off);
check("PI_AUTONOMY=0", !Object.keys(off.hooks).length && !Object.keys(off.tools).length && !Object.keys(off.commands).length);
delete process.env.PI_AUTONOMY;

console.log(bad?`${bad} failures`:`all ${block.length+allow.length} classifier cases and ${checks} handler checks pass`);
process.exit(bad ? 1 : 0);
