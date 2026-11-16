import childProcess from "node:child_process";
import { statSync } from "node:fs";
import os from "node:os";
import { isAbsolute } from "node:path";
import { mock } from "node:test";

const { default: install } = await import("./tmpdir-default.ts");

let bad = 0;
const check = (name: string, ok: boolean, detail?: unknown) => { if (!ok) { bad++; console.log("FAIL", name, detail ?? ""); } };

const oldTmpdir = process.env.TMPDIR;
const oldSwitch = process.env.PI_TMPDIR_DEFAULT;
try {
  delete process.env.PI_TMPDIR_DEFAULT;
  for (const value of [undefined, "", " \t\n"]) {
    if (value === undefined) delete process.env.TMPDIR; else process.env.TMPDIR = value;
    install({});
    const dir = process.env.TMPDIR ?? "";
    check(`load replaces ${JSON.stringify(value)}`, isAbsolute(dir) && statSync(dir).isDirectory(), dir);
  }

  process.env.TMPDIR = " /tmp/custom-scratch ";
  install({});
  check("non-empty value kept verbatim", process.env.TMPDIR === " /tmp/custom-scratch ");

  process.env.PI_TMPDIR_DEFAULT = "0";
  delete process.env.TMPDIR;
  install({});
  check("disabled leaves TMPDIR unset", process.env.TMPDIR === undefined);
  delete process.env.PI_TMPDIR_DEFAULT;
  install({});
  check("enabled sets TMPDIR", isAbsolute(process.env.TMPDIR ?? ""));

  mock.method(os, "platform", () => "darwin");
  mock.method(os, "tmpdir", () => "/tmp/portable-scratch");
  const getconf = mock.method(childProcess, "execFileSync", () => "/tmp/per-user-scratch/\n");
  delete process.env.TMPDIR;
  install({});
  check("macOS prefers per-user directory", process.env.TMPDIR === "/tmp/per-user-scratch/");

  getconf.mock.mockImplementation(() => { throw new Error("getconf unavailable"); });
  delete process.env.TMPDIR;
  install({});
  check("getconf failure uses OS fallback", process.env.TMPDIR === "/tmp/portable-scratch");

  getconf.mock.mockImplementation(() => " \n");
  delete process.env.TMPDIR;
  install({});
  check("empty getconf output uses OS fallback", process.env.TMPDIR === "/tmp/portable-scratch");

  mock.method(os, "platform", () => "linux");
  getconf.mock.mockImplementation(() => "/tmp/mac-only-scratch/");
  delete process.env.TMPDIR;
  install({});
  check("other platforms use OS directory", process.env.TMPDIR === "/tmp/portable-scratch");

  for (const value of ["", " \t\n"]) {
    mock.method(os, "tmpdir", () => value);
    delete process.env.TMPDIR;
    install({});
    check("empty OS directory uses /tmp", process.env.TMPDIR === "/tmp");
  }
} finally {
  mock.restoreAll();
  if (oldTmpdir === undefined) delete process.env.TMPDIR; else process.env.TMPDIR = oldTmpdir;
  if (oldSwitch === undefined) delete process.env.PI_TMPDIR_DEFAULT; else process.env.PI_TMPDIR_DEFAULT = oldSwitch;
}

if (bad) { console.log(`${bad} check(s) failed`); process.exit(1); }
console.log("ok");
