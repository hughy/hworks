// Keeps the agent from stalling on mid-task questions or running commands git cannot undo.
// The block reason is returned to the model as the tool result, so it doubles as the redirect.
// The guard applies only in guarded runs: hughy-mode on, a prompt that invokes the hughy-router or orchestrate skill,
// an orchestrate.py bookkeeping call, or a pi-subagents child. Elsewhere asks and classified commands pass to the
// harness's own approvals. A skill or orchestrate.py trigger lasts for the session and survives resume and fork.
// `/autonomy on|off|auto|status` overrides that for the session; PI_AUTONOMY=1 starts sessions with it on.
// A rule the operator's own prompt asks for ("rebase onto main", "delete the merged branches") is granted for
// the rest of the session, so a run does not stop on the step it was asked to do. A negated mention denies it.
// The model can call autonomy_phase with phase "cleanup" once the work is done, so end-of-run asks and
// classified commands pass on to the harness's own guards and approvals. The phase returns to "work" at
// every agent_start, session_start, and session_tree.
// Every block, every call let through in cleanup, and every ask or supervisor decision request is
// appended to a JSONL log for scripts/blockers.sh; asks and commands only while the guard is active. PI_AUTONOMY=0 disables the guard and the log.

import { appendFileSync, mkdirSync, realpathSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { enabledFrom as hughyModeFrom } from "./hughy-mode.ts";

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
  "`- [<category>] <question> | <choice> | <evidence> | <how to reverse> | deferred`, where category is one of " +
  "missing-info, permission, irreversible, tooling, ambiguous-brief, external-wait.";

const CLEANUP_HINT =
  " If the requested work, verification, and reviews are finished and this is end-of-run cleanup, call " +
  "autonomy_phase with phase \"cleanup\" first.";

const ASK_REASON =
  "Autonomy: do not ask mid-task. Settle the question from code, docs, git history, or a quick experiment, " +
  "pick the best-evidenced option, and record it as " + ENTRY_FORMAT + " Finish the task, then list only the " +
  "questions evidence could not settle at the end of your final reply, with options and a recommendation. " +
  "The one exception is the up-front round in the Autonomy section of global AGENTS.md (operator present, " +
  "large work, a product call no experiment can settle that changes most of the plan): ask it in your reply " +
  "text, record each question with state `asked`, and end the turn." + CLEANUP_HINT;

const DESTRUCTIVE_REASON =
  "Autonomy: blocked a command git on the working branch cannot undo. ";

const SKIP_REASON =
  "If no reversible form does the job, skip this step, finish the rest, record it as an [irreversible] entry, " +
  ENTRY_FORMAT + " List the skipped step first in your final reply." + CLEANUP_HINT + " Pattern: ";

const LEASE_HINT =
  "Retry now with `git push --force-with-lease=<branch>:<sha>`, where <sha> is the remote head you expect " +
  "(`git ls-remote origin <branch>`). That form passes: it names the old head, so the push is undoable, and it " +
  "refuses to overwrite commits you have not seen. ";

// The redirect for each rule, so the model can retry in the same turn instead of stopping.
const HINTS: Record<string, string> = {
  "git push --force": LEASE_HINT,
  "git push --force-with-lease": LEASE_HINT,
  "git reset --hard":
    "Commit the work you want to keep, then use `git reset --keep <rev>`, which passes because it refuses to " +
    "discard uncommitted changes. ",
  "git branch -D": "Use `git branch -d` for a merged branch; it passes. ",
  "git worktree remove --force":
    "Commit what the worktree holds and drop `--force`, or make throwaway worktrees under `$(mktemp -d)` or " +
    "$TMPDIR, which pass. ",
  "git stash drop/clear": "Leave the stash entry in place; it costs nothing. ",
  "git clean -f": "Move the files to a backup path under $TMPDIR instead. ",
};

const blockReason = (rule: string) => DESTRUCTIVE_REASON + (HINTS[rule] ?? "") + SKIP_REASON + rule;

const PATTERNS: Array<[string, RegExp]> = [
  ["git reset --hard", /\bgit\s+(?:-C\s+\S+\s+)?reset\b[^;&|]*--(?:hard|merge)\b/],
  ["git clean -f", /\bgit\s+(?:-C\s+\S+\s+)?clean\b[^;&|]*\s-[a-zA-Z]*f/],
  ["git branch -D", /\bgit\s+(?:-C\s+\S+\s+)?branch\b[^;&|]*\s(?:-D\b|--delete\s+--force|-d\s+-f)/],
  ["git stash drop/clear", /\bgit\s+(?:-C\s+\S+\s+)?stash\s+(?:drop|clear)\b/],
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
export function stripData(command: string): string {
  return command
    .replace(/--force-with-lease=(['"])([^'"\s]*)\1/g, "--force-with-lease=$2")
    .replace(/"(\$[^"\s]*)"/g, "$1")
    .replace(/<<-?\s*(['"]?)(\w+)\1[^\n]*\n[\s\S]*?\n\s*\2\s*(?=\n|$)/g, "")
    .replace(/'[^']*'/g, "''")
    .replace(/"(?:[^"\\]|\\.)*"/g, '""');
}

// A lease that names the expected remote head (`--force-with-lease=<ref>:<sha>`) is undoable: the old head is in
// the command, and the push fails if the remote moved. A bare lease checks the remote-tracking ref, which a
// background fetch can advance, so it can still overwrite unseen commits.
function classifyPush(segment: string): string | null {
  if (!/\bgit\s+(?:-C\s+\S+\s+)?push\b/.test(segment)) return null;
  if (/\s--force(?=\s|$)|\s-[a-zA-Z]*f\b|\s\+\S/.test(segment)) return "git push --force";
  for (const m of segment.matchAll(/\s--force-with-lease(?:=(\S*))?/g)) {
    if (!/^[^:\s]+:\S+$/.test(m[1] ?? "")) return "git push --force-with-lease";
  }
  return null;
}

const TMP_PATH = /^(?:\/tmp\/|\/private\/tmp\/|\/var\/folders\/|\/private\/var\/folders\/|\$\{?TMPDIR\b)/;

// `git worktree remove --force` only loses the worktree's uncommitted files, which are scratch under a temp dir,
// including a path held in a variable the same command set from `mktemp`.
function forcesNonTmpWorktree(segment: string, tmpVars: Set<string>): boolean {
  const m = segment.match(/\bgit\s+(?:-C\s+\S+\s+)?worktree\s+remove\b(.*)/);
  if (!m || !/\s--force\b|\s-f\b/.test(m[1])) return false;
  const target = m[1].split(/\s+/).find((a) => a && !a.startsWith("-"));
  if (!target) return true;
  if (TMP_PATH.test(target)) return false;
  const v = target.match(/^\$\{?(\w+)/)?.[1];
  return !(v && tmpVars.has(v));
}

export function classify(command: string): string | null {
  const code = stripData(command);
  const tmpVars = new Set([...code.matchAll(/\b(\w+)=\$\(mktemp\b/g)].map((m) => m[1]));
  for (const segment of code.split(/[;&|\n]+/)) {
    const push = classifyPush(segment);
    if (push) return push;
    if (forcesNonTmpWorktree(segment, tmpVars)) return "git worktree remove --force";
  }
  // SQL arrives quoted (`psql -c "..."`), so it is matched against the raw command.
  for (const [name, re] of PATTERNS) if (re.test(name.startsWith("SQL") ? command : code)) return name;
  return null;
}

// Operator phrases that ask for a guarded step. Plain `--force` is never granted: the lease form always works.
const INTENTS: Array<[string, RegExp]> = [
  ["git push --force-with-lease", /\brebas(?:e|ed|es|ing)\b|\bforce[- ]?push|\bforce-with-lease\b|\bpush\s+(?:--force|-f)\b|\bsquash|\bamend\b|\brewrite\s+(?:the\s+)?(?:git\s+)?history\b/i],
  ["git reset --hard", /\breset\s+--hard\b|\bhard[- ]reset\b/i],
  ["git branch -D", /\bbranch\s+-D\b|\bdelete\s+(?:the\s+|these\s+|those\s+|stale\s+|old\s+|merged\s+|local\s+|unused\s+)*branch(?:es)?\b|\bprune\s+(?:local\s+|stale\s+)*branches\b/i],
  ["git worktree remove --force", /\bworktree\s+remove\b|\b(?:remove|delete|clean\s*up|prune)\s+(?:the\s+|these\s+|stale\s+|old\s+|all\s+)*worktrees?\b/i],
  ["git stash drop/clear", /\bstash\s+(?:drop|clear)\b|\bdrop\s+(?:the\s+|that\s+|my\s+)?stash/i],
  ["git clean -f", /\bgit\s+clean\b|\bremove\s+(?:all\s+)?untracked\s+files\b/i],
  ["git filter-branch / filter-repo", /\bfilter-(?:branch|repo)\b|\brewrite\s+(?:the\s+)?(?:commit\s+|git\s+)?history\b/i],
];

const NEGATION = /\b(?:don'?t|do\s+not|never|no|not|without|avoid)\b/i;

// Grants every rule some clause asks for, minus any rule a negated clause mentions, so "no amend, rebase, or push"
// grants nothing and "rebase onto main. Do not force-push" grants no push.
export function grantsFrom(prompt: string): Set<string> {
  const want = new Set<string>();
  const deny = new Set<string>();
  for (const clause of prompt.split(/[.;:!?\n]+/)) {
    const target = NEGATION.test(clause) ? deny : want;
    for (const [rule, re] of INTENTS) if (re.test(clause)) target.add(rule);
  }
  for (const rule of deny) want.delete(rule);
  return want;
}

// pi expands `/skill:<name>` into this block before before_agent_start, so the prompt names the skill exactly.
const SKILL_BLOCK = /<skill name="([^"]+)"[^>]*>[\s\S]*?<\/skill>/g;
const GUARDED_SKILLS = new Set(["hughy-router", "orchestrate"]);
// The orchestrate skill calls its script as `python3 $O --store "$S" <command>`.
const ORCHESTRATE_CALL = /(?:orchestrate\.py|\$\{?O\}?)\s+--store\b/;

export function guardedSkill(prompt: string): string | null {
  for (const m of prompt.matchAll(SKILL_BLOCK)) if (GUARDED_SKILLS.has(m[1])) return m[1];
  return null;
}

// Grants come from the operator's words, not from the text of a skill the prompt expanded.
export const operatorText = (prompt: string) => prompt.replace(SKILL_BLOCK, "");

export const isOrchestrateCall = (command: string) => ORCHESTRATE_CALL.test(stripData(command));

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
  type Mode = "auto" | "on" | "off";
  const ENTRY = "autonomy";
  const child = process.env.PI_SUBAGENT_CHILD === "1";
  const initialMode: Mode = process.env.PI_AUTONOMY === "1" ? "on" : "auto";
  let mode: Mode = initialMode;
  let trigger: string | null = null;
  let hughyMode = false;
  let phase: "work" | "cleanup" = "work";
  const grants = new Set<string>();
  const active = () => mode === "on" || (mode === "auto" && (child || hughyMode || trigger !== null));
  const why = () =>
    mode !== "auto" ? `/autonomy ${mode}` : child ? "subagent child" : hughyMode ? "hughy-mode" : trigger ?? "no trigger";
  const show = (ctx: any) => ctx?.ui?.setStatus?.("autonomy", active() ? "autonomy" : undefined);
  const branch = (ctx: any) => ctx?.sessionManager?.getBranch?.() ?? [];
  const restore = (ctx: any) => {
    const entries = branch(ctx);
    mode = initialMode;
    trigger = null;
    for (const e of entries) {
      if (e.type !== "custom" || e.customType !== ENTRY) continue;
      if (e.data?.mode === "auto" || e.data?.mode === "on" || e.data?.mode === "off") mode = e.data.mode;
      if (typeof e.data?.trigger === "string") trigger = e.data.trigger;
    }
    hughyMode = hughyModeFrom(entries, process.env.PI_HUGHY_MODE === "1");
    show(ctx);
  };
  const activate = (ctx: any, reason: string) => {
    if (trigger !== null) return;
    trigger = reason;
    pi.appendEntry?.(ENTRY, { trigger });
    record(ctx, "activate", reason, false, "");
    show(ctx);
  };
  const resetPhase = () => {
    phase = "work";
  };
  pi.on("agent_start", resetPhase);
  // A new, forked, or resumed session, or a jump in the tree, may no longer hold the prompt that granted a rule.
  for (const event of ["session_start", "session_tree"]) {
    pi.on(event, (_event: any, ctx: any) => {
      resetPhase();
      grants.clear();
      restore(ctx);
    });
  }

  pi.on("before_agent_start", (event: any, ctx: any) => {
    if (event?.messageType !== "user" || typeof event.prompt !== "string") return;
    // /hughy-mode appends its entry when toggled; it takes effect from the next turn, as its prompt section does.
    hughyMode = hughyModeFrom(branch(ctx), process.env.PI_HUGHY_MODE === "1");
    const skill = guardedSkill(event.prompt);
    if (skill) activate(ctx, `skill:${skill}`);
    show(ctx);
    for (const rule of grantsFrom(operatorText(event.prompt))) {
      if (grants.has(rule)) continue;
      grants.add(rule);
      if (active()) record(ctx, "grant", rule, false, event.prompt);
    }
  });

  pi.registerCommand("autonomy", {
    description: "on|off|auto|status: block mid-task questions and irreversible commands (auto: only in guarded runs)",
    handler: async (arg: string, ctx: any) => {
      const a = (arg ?? "").trim();
      if (a === "on" || a === "off" || a === "auto") {
        mode = a;
        pi.appendEntry?.(ENTRY, { mode });
        show(ctx);
      } else if (a !== "" && a !== "status") {
        ctx.ui.notify("usage: /autonomy [on|off|auto|status]", "warning");
        return;
      }
      ctx.ui.notify(`Autonomy guard ${active() ? "active" : "inactive"} (${why()})`, "info");
    },
  });

  pi.registerTool({
    name: "autonomy_phase",
    label: "Autonomy phase",
    description:
      "Set the autonomy guard phase. Use \"cleanup\" only after the requested work, verification, and reviews " +
      "are finished, to attempt end-of-run cleanup (stale branches, worktrees) that may ask the operator for " +
      "approval. Cleanup lets ask_user_question and commands the guard classifies as irreversible pass to the " +
      "harness's other guards and approvals; it authorizes no deletion and bypasses no other guard. Use \"work\" " +
      "before resuming substantive work. Each new run starts in \"work\". Call this tool alone, not alongside " +
      "the calls it should affect.",
    parameters: {
      type: "object",
      properties: { phase: { type: "string", enum: ["work", "cleanup"] } },
      required: ["phase"],
      additionalProperties: false,
    },
    executionMode: "sequential",
    async execute(_id: string, params: any) {
      if (params?.phase !== "work" && params?.phase !== "cleanup") throw new Error('phase must be "work" or "cleanup"');
      phase = params.phase;
      const text = !active()
        ? "Autonomy guard inactive in this session; it blocks nothing, so no phase change is needed."
        : phase === "cleanup"
          ? "Autonomy phase: cleanup. Asks and classified commands now reach the harness's other guards and " +
            "approvals, which still decide. Call autonomy_phase with phase \"work\" before any substantive work."
          : "Autonomy phase: work. Mid-task asks and irreversible commands are blocked.";
      return { content: [{ type: "text", text }], details: undefined };
    },
  });

  pi.on("tool_call", (event: any, ctx: any) => {
    const input = event.input ?? {};
    if (event.toolName === "bash" && isOrchestrateCall(String(input.command ?? ""))) activate(ctx, "orchestrate.py");
    if (event.toolName === "contact_supervisor" && input.reason !== "progress_update") {
      record(ctx, "supervisor", String(input.reason ?? "unknown"), false, input.message);
      return;
    }
    if (!active()) return;
    if (event.toolName === "ask_user_question") {
      const qs = Array.isArray(input.questions) ? input.questions.map((q: any) => q?.question).join(" / ") : "";
      const block = phase === "work";
      record(ctx, "ask", "ask_user_question", block, qs);
      if (block) return { block: true, reason: ASK_REASON };
      return;
    }
    if (event.toolName === "bash") {
      const command = String(input.command ?? "");
      const hit = classify(command);
      if (hit) {
        const block = phase === "work" && !grants.has(hit);
        record(ctx, "destructive", hit, block, command);
        if (block) return { block: true, reason: blockReason(hit) };
      }
    }
  });
}
