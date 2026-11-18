import os from "node:os";

// Modules such as pi-subagents resolve os.tmpdir() at import, before this
// runs. Pin TMPDIR to that same value so child processes resolve the same
// temp paths as this process; a different directory splits them.
export default function (_pi: unknown) {
  if (process.env.PI_TMPDIR_DEFAULT === "0" || process.env.TMPDIR?.trim()) return;
  process.env.TMPDIR = os.tmpdir().trim() || "/tmp";
}
