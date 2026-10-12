import { mkdtempSync, readFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const logPath = join(mkdtempSync(join(tmpdir(), "autonomy-test-")), "blockers.jsonl");
process.env.HWORKS_BLOCKERS_LOG = logPath;
delete process.env.PI_AUTONOMY;
const { classify, default: register } = await import("./autonomy.ts");
const block = ["git reset --hard HEAD~1","git -C repo reset --hard","git clean -fdx","git push --force origin feat","git push -f","git push --force-with-lease origin feat","git push origin +feat","git branch -D old","git stash drop","git worktree remove --force ../wt","DROP TABLE users;","kubectl delete pod x","terraform apply","psql -c \"drop table users\"","cd \"my repo\" && git reset --hard","python3 - <<'EOF'\nprint(1)\nEOF\ngit reset --hard","git commit -m 'wip' && git push --force origin x"];
const allow = ["git worktree remove --force /tmp/wt","rm -rf build","git checkout -- src/a.ts","rm -rf /tmp/foo","rm -f $TMPDIR/x","rm ~/.local/state/agent-tasks/t/a.md","find /tmp/x -delete","git rm src/old.ts","git status","git push origin feat","git restore --staged a.ts","git checkout -b new","git checkout main","git branch -d merged","git stash push","git reset HEAD~1","git reset --soft HEAD~1","grep -rn 'rm -rf' .","npm run format","git commit -m 'remove dead code'","echo terraform plan","agent -p \"run git reset --hard and report\"","git commit -m 'docs: never git reset --hard'","python3 - <<'EOF'\ns = 'never `git reset --hard`'\nEOF","cat > f.md <<EOF\nuse git push --force rarely\nEOF\necho ok","grep -n \"git-reset-hard\\|reset --hard\" log"];
let bad=0;
for (const c of block) { const r=classify(c); if(!r){bad++;console.log("MISSED  ",c);} }
for (const c of allow) { const r=classify(c); if(r){bad++;console.log("FALSE+  ",c,"->",r);} }

// Handler: blocks and logs asks and destructive commands, logs decision requests, ignores the rest.
let handler: any;
register({ registerCommand() {}, on(name: string, fn: any) { if (name === "tool_call") handler = fn; } });
const ctx = { cwd: "/repo", sessionManager: { getSessionId: () => "s1" } };
const cases: Array<[string, any, boolean]> = [
  ["ask_user_question", { questions: [{ question: "Pick a color?" }] }, true],
  ["bash", { command: "git branch -D old" }, true],
  ["bash", { command: "git status" }, false],
  ["contact_supervisor", { reason: "need_decision", message: "Which API?" }, false],
  ["contact_supervisor", { reason: "progress_update", message: "half done" }, false],
];
for (const [toolName, input, shouldBlock] of cases) {
  const r = handler({ toolName, input }, ctx);
  if (!!r?.block !== shouldBlock) { bad++; console.log("HANDLER ", toolName, JSON.stringify(input), "->", r); }
}
const logged = existsSync(logPath) ? readFileSync(logPath, "utf8").trim().split("\n").map((l) => JSON.parse(l)) : [];
const kinds = logged.map((r) => `${r.kind}:${r.rule}:${r.blocked}`).join(",");
const want = "ask:ask_user_question:true,destructive:git branch -D:true,supervisor:need_decision:false";
if (kinds !== want || logged.some((r) => r.session !== "s1" || r.cwd !== "/repo")) { bad++; console.log("LOG     ", kinds); }

// The block reason names a task-dir.sh that exists, resolved through the extension's symlink.
const askReason = handler({ toolName: "ask_user_question", input: {} }, ctx)?.reason ?? "";
const script = askReason.match(/`(\S+\/scripts\/task-dir\.sh) <task-slug>`/)?.[1];
if (!script || !existsSync(script)) { bad++; console.log("TASKDIR ", script); }

console.log(bad?`${bad} failures`:`all ${block.length+allow.length+cases.length+2} pass`);
process.exit(bad ? 1 : 0);
