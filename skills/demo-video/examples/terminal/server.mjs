#!/usr/bin/env node
// Serves a page and streams one run of a command to it as server-sent events, recording the stream for replay.
// usage: node server.mjs [--site <dir>] [--runs <dir>] [--port <n>] [--allow-many] -- <command> [args...]
//   GET /run           spawns the command; stdout and stderr lines arrive as "out" items, lines the command writes to
//                      fd 3 (JSON, one per line) as "ev" items, then an "exit" item. Every item goes to <runs>/run-<ms>.jsonl
//                      as {t, kind, data}, t in ms since the run started. The first item is {kind:"cmd"}, the command line.
//   GET /run?replay=F  plays <runs>/F back with its original timing and starts no process.
// A second live run is refused unless --allow-many is set: a demo command may have side effects that should happen once.
import { spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import readline from "node:readline";
import { parseArgs } from "node:util";

const dashes = process.argv.indexOf("--");
const { values: o } = parseArgs({
  args: process.argv.slice(2, dashes < 0 ? undefined : dashes),
  options: { site: { type: "string" }, runs: { type: "string" }, port: { type: "string", default: "0" }, "allow-many": { type: "boolean", default: false } },
});
const command = dashes < 0 ? [] : process.argv.slice(dashes + 1);
const here = path.dirname(new URL(import.meta.url).pathname);
const site = path.resolve(o.site || here);
const runs = path.resolve(o.runs || "runs");
let liveRuns = 0;

const types = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".ttf": "font/ttf", ".woff2": "font/woff2" };

function sse(res) {
  res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache", connection: "keep-alive" });
  return (kind, data) => res.write(`event: ${kind}\ndata: ${JSON.stringify(data)}\n\n`);
}

function live(res) {
  const send = sse(res);
  if (!command.length) {
    send("out", "server: started without a command; pass one after --");
    send("exit", { code: 2 });
    return res.end();
  }
  if (liveRuns++ > 0 && !o["allow-many"]) {
    send("out", "server: this server already ran the command once; restart it or pass --allow-many");
    send("exit", { code: 2 });
    return res.end();
  }
  fs.mkdirSync(runs, { recursive: true });
  const log = fs.createWriteStream(path.join(runs, `run-${Date.now()}.jsonl`));
  const t0 = Date.now();
  const emit = (kind, data) => {
    log.write(JSON.stringify({ t: Date.now() - t0, kind, data }) + "\n");
    send(kind, data);
  };
  emit("cmd", command.join(" "));
  const child = spawn(command[0], command.slice(1), { stdio: ["ignore", "pipe", "pipe", "pipe"] });
  child.on("error", (e) => {
    emit("out", `server: cannot run ${command[0]}: ${e.message}`);
    emit("exit", { code: 127 });
    log.end();
    res.end();
  });
  readline.createInterface({ input: child.stdout }).on("line", (l) => emit("out", l));
  readline.createInterface({ input: child.stderr }).on("line", (l) => emit("out", l));
  readline.createInterface({ input: child.stdio[3] }).on("line", (l) => {
    try {
      emit("ev", JSON.parse(l));
    } catch {
      emit("out", l);
    }
  });
  child.on("close", (code) => {
    // Let the readline buffers drain before the stream ends.
    setTimeout(() => {
      emit("exit", { code });
      log.end();
      res.end();
    }, 200);
  });
}

function replay(res, file) {
  const send = sse(res);
  const full = path.join(runs, path.basename(file));
  if (!fs.existsSync(full)) {
    send("out", `server: no recording ${path.basename(file)} in ${runs}`);
    send("exit", { code: 2 });
    return res.end();
  }
  const rows = fs.readFileSync(full, "utf8").trim().split("\n").map((l) => JSON.parse(l));
  for (const r of rows) setTimeout(() => send(r.kind, r.data), r.t);
  setTimeout(() => res.end(), rows.at(-1).t + 300);
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  if (url.pathname === "/run") return url.searchParams.get("replay") ? replay(res, url.searchParams.get("replay")) : live(res);
  const file = path.join(site, url.pathname === "/" ? "index.html" : path.normalize(url.pathname));
  if (!file.startsWith(site + path.sep) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
    res.writeHead(404);
    return res.end();
  }
  res.writeHead(200, { "content-type": types[path.extname(file)] || "application/octet-stream" });
  fs.createReadStream(file).pipe(res);
});
server.listen(Number(o.port), "127.0.0.1", () => console.log(`demo server on http://127.0.0.1:${server.address().port}`));
