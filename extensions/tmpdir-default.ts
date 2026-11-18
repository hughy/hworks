import childProcess from "node:child_process";
import os from "node:os";

export default function (_pi: unknown) {
  if (process.env.PI_TMPDIR_DEFAULT === "0" || process.env.TMPDIR?.trim()) return;

  let dir = "";
  if (os.platform() === "darwin") {
    try {
      dir = childProcess.execFileSync("getconf", ["DARWIN_USER_TEMP_DIR"], {
        encoding: "utf8", stdio: ["ignore", "pipe", "ignore"],
      }).trim();
    } catch {}
  }
  process.env.TMPDIR = dir || os.tmpdir().trim() || "/tmp";
}
