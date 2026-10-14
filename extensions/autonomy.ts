// Keeps the agent from stalling on mid-task questions or running commands git cannot undo.
// The block reason is returned to the model as the tool result, so it doubles as the redirect.
// `/autonomy off` relaxes both checks for the current session; `/autonomy on` restores them.
// Every block, and every ask or supervisor decision request, is appended to a JSONL log for
// scripts/blockers.sh. PI_AUTONOMY=0 disables the guard and the log.

import { appendFileSync, mkdirSync, realpathSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const TASKS_ROOT =
  process.env.HWORKS_TASKS_DIR || join(process.env.XDG_STATE_HOME || join(homedir(), ".local/state"), "agent-tasks");
const LOG = process.env.HWORKS_BLOCKERS_LOG || join(TASKS_ROOT, "blockers.jsonl");

const TASK_DIR_SCRIPT = (() => {
  try {
    return join(dirname(dirname(realpathSync(fileURLToPath(import.meta.url)))), "scripts/task-dir.sh");
  } catch {
    return "~/dev/hworks/scripts/task-dir.sh";
  }
})();

const ENTRY_FORMAT =
  `one line per entry in $TASK_DIR/open-questions.md (\`${TASK_DIR_SCRIPT} <task-slug>\` prints $TASK_DIR): ` +
  "`- [<category>] <question> | <choice> | <evidence> | <how to reverse>`, where category is one of " +
  "missing-info, permission, irreversible, tooling, ambiguous-brief, external-wait.";

const ASK_REASON =
  "Autonomy: do not ask mid-task. Settle the question from code, docs, git history, or a quick experiment, " +
  "pick the best-evidenced option, and record it as " + ENTRY_FORMAT + " Finish the task, then list only the " +
  "questions evidence could not settle at the end of your final reply, with options and a recommendation.";

const DESTRUCTIVE_REASON =
  "Autonomy: blocked a command git on the working branch cannot undo. Use a reversible alternative " +
  "(commit first, `git revert`, `git stash push`, move files to a backup path) or skip this step, finish the " +
  "rest, record it as an [irreversible] entry, " + ENTRY_FORMAT + " List the skipped step first in your final " +
  "reply. Pattern: ";

const PATTERNS: Array<[string, RegExp]> = [
  ["git reset --hard", /\bgit\s+(?:-C\s+\S+\s+)?reset\b[^;&|]*--(?:hard|merge|keep)\b/],
  ["git clean -f", /\bgit\s+(?:-C\s+\S+\s+)?clean\b[^;&|]*\s-[a-zA-Z]*f/],
  ["git push --force", /\bgit\s+(?:-C\s+\S+\s+)?push\b[^;&|]*(?:\s--force(?:-with-lease)?\b|\s-[a-zA-Z]*f\b|\s\+\S)/],
  ["git branch -D", /\bgit\s+(?:-C\s+\S+\s+)?branch\b[^;&|]*\s(?:-D\b|--delete\s+--force|-d\s+-f)/],
  ["git stash drop/clear", /\bgit\s+(?:-C\s+\S+\s+)?stash\s+(?:drop|clear)\b/],
  ["git worktree remove --force", /\bgit\s+(?:-C\s+\S+\s+)?worktree\s+remove\b(?=[^;&|]*--force)(?![^;&|]*\s(?:\/tmp\/|\/private\/tmp\/|\/var\/folders\/))/],
  ["git update-ref -d / reflog expire", /\bgit\s+(?:-C\s+\S+\s+)?(?:update-ref\s+-d|reflog\s+(?:expire|delete))\b/],
  ["git filter-branch / filter-repo", /\bgit\s+(?:-C\s+\S+\s+)?filter-(?:branch|repo)\b/],
  ["gh repo/release delete", /\bgh\s+(?:repo|release)\s+delete\b/],
  ["SQL drop/truncate", /\b(?:drop\s+(?:table|database|schema)|truncate\s+table)\b/i],
  ["kubectl delete", /\bkubectl\s+delete\b/],
  ["terraform apply/destroy", /\bterraform\s+(?:apply|destroy)\b/],
  ["shred / dd", /(?:^|[;&|]\s*)(?:shred|dd)\s/],
];

// Heredoc bodies and quoted strings are data (prompts, commit messages, doc edits), not commands.
// Dropping them misses `sh -c "..."`; a harness guard that matches the full string is the backstop.
function stripData(command: string): string {
  return command
    .replace(/<<-?\s*(['"]?)(\w+)\1[^\n]*\n[\s\S]*?\n\s*\2\s*(?=\n|$)/g, "")
    .replace(/'[^']*'/g, "''")
    .replace(/"(?:[^"\\]|\\.)*"/g, '""');
}

export function classify(command: string): string | null {
  const code = stripData(command);
  // SQL arrives quoted (`psql -c "..."`), so it is matched against the raw command.
  for (const [name, re] of PATTERNS) if (re.test(name.startsWith("SQL") ? command : code)) return name;
  return null;
}

function record(ctx: any, kind: string, rule: string, blocked: boolean, detail: unknown) {
  try {
    mkdirSync(dirname(LOG), { recursive: true });
    const row = {
      ts: new Date().toISOString(),
      session: ctx?.sessionManager?.getSessionId?.() ?? process.env.PI_SESSION_ID ?? null,
      cwd: ctx?.cwd ?? process.cwd(),
      kind,
      rule,
      blocked,
      detail: String(detail ?? "").replace(/\s+/g, " ").slice(0, 300),
    };
    appendFileSync(LOG, JSON.stringify(row) + "\n");
  } catch {
    // Logging must never change whether a call runs.
  }
}

export default function (pi: any) {
  if (process.env.PI_AUTONOMY === "0") return;
  let enabled = true;

  pi.registerCommand("autonomy", {
    description: "on|off: block mid-task questions and irreversible commands (default on)",
    handler: async (arg: string, ctx: any) => {
      const a = (arg ?? "").trim();
      if (a === "off") enabled = false;
      else if (a === "on") enabled = true;
      ctx.ui.notify(`Autonomy guard ${enabled ? "on" : "off"} for this session`, "info");
    },
  });

  pi.on("tool_call", (event: any, ctx: any) => {
    const input = event.input ?? {};
    if (event.toolName === "ask_user_question") {
      const qs = Array.isArray(input.questions) ? input.questions.map((q: any) => q?.question).join(" / ") : "";
      record(ctx, "ask", "ask_user_question", enabled, qs);
      if (enabled) return { block: true, reason: ASK_REASON };
      return;
    }
    if (event.toolName === "contact_supervisor" && input.reason !== "progress_update") {
      record(ctx, "supervisor", String(input.reason ?? "unknown"), false, input.message);
      return;
    }
    if (enabled && event.toolName === "bash") {
      const command = String(input.command ?? "");
      const hit = classify(command);
      if (hit) {
        record(ctx, "destructive", hit, true, command);
        return { block: true, reason: DESTRUCTIVE_REASON + hit };
      }
    }
  });
}
