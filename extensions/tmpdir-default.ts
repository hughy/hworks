import os from "node:os";

// Modules such as pi-subagents resolve os.tmpdir() at import, before this
// runs. When TMPDIR is unset or empty, pin it to that same value so child
// processes resolve the same temp paths as this process.
export default function (_pi: unknown) {
  if (process.env.PI_TMPDIR_DEFAULT === "0" || process.env.TMPDIR?.trim()) return;
  process.env.TMPDIR = os.tmpdir().trim() || "/tmp";
}
