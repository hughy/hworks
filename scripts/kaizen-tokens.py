#!/usr/bin/env python3
"""Report where pi sessions spend tokens, and who owns each cost: hworks, a local file, or an
upstream dependency.

Read-only. Output can quote private transcript content: do not redirect it into a repo.
usage: kaizen-tokens.py [--since YYYY-MM-DD|7d] [--min-sessions N] [--top N] [--cwd-match TEXT]... [--json]

Sections:
  totals        tokens and cost by kind (input, output, cache read, cache write), by model, and
                main sessions against subagent children (children by agent where known).
  baseline      the always-on prompt each session starts with: one row per system-prompt
                section, per project instructions file, per listed skill, per advertised agent,
                and per tool schema. Each row has its median size and its token-turns: its size
                times the turns of each session that carried it, which is what it costs in
                cache reads over a session.
  tool results  tool output grouped by tool and command shape, ranked by carried token-turns:
                each result's size times the turns left before the session ends or compacts.
  cache writes  turns whose cache read fell below half the previous turn's context, so the
                cached prefix was written again, by cause: session start,
                compaction, model or thinking change, context edit, system prompt change, idle
                past the cache lifetime, or unexplained.
  upstream      rows whose owner is upstream, plus unexplained cache rewrites: candidates to
                raise with that dependency. Flags only; nothing is filed or drafted.

Sizes: transcripts record characters, not tokens, for prompt parts. Each session's first turn
gives a measured token count for a known character count (system prompt, tool schemas, and the
messages before it); the median chars-per-token over sessions converts every part. Treat sizes
as estimates for ranking, not exact counts.

Owners: a path under this repo (after resolving links) is hworks; a path inside node_modules
is upstream:<package>; other paths are local (the operator's own files outside hworks). A
system-prompt section set by an extension in this repo's extensions/ is hworks; core pi
sections are upstream:pi; any other section is upstream:<its name up to the first - or _>.
Tools registered in extensions/ are hworks; pi's built-in tools are upstream:pi; others are
upstream:unattributed. HWORKS_OWNER_MAP overrides all of these: comma-separated
needle=owner pairs matched as substrings against "section:<name>", "tool:<name>", or the path,
first match wins, for example "section:acme-=upstream:acme,tool:fastgrep=upstream:acme".

Sources (each optional; a missing one is reported, not fatal):
  HWORKS_PI_SESSIONS   pi session transcripts, **/*.jsonl (default ~/.pi/agent/sessions).
                       subagent-artifacts/ copies are skipped; child sessions
                       (<session>/<run id>/run-N/session.jsonl) count as subagent sessions.
  HWORKS_OWNER_MAP     owner overrides, above.
adapters/local/*.env, when present, is read first; values already in the environment win.
"""
import argparse
import glob
import importlib.util
import json
import os
import re
import statistics
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
_spec = importlib.util.spec_from_file_location("kaizen_sessions", os.path.join(HERE, "kaizen-sessions.py"))
ks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ks)

PI_TOOLS = {"read", "bash", "edit", "write", "grep", "find", "ls"}
PI_SECTIONS = {"preamble", "tools", "cwd", "project_context", "skills", "date", "addendum"}
EVENTS = {"compaction": "compaction", "model_change": "model change",
          "thinking_level_change": "thinking change", "context_edit": "context edit"}
REWRITE_SHARE = 0.5
REWRITE_MIN_TOKENS = 2000
DEFAULT_CHARS_PER_TOKEN = 4.0
CHILD = re.compile(r"/([0-9a-f-]{36})/run-\d+/session\.jsonl$")
CHILD_NAME = re.compile(r"^subagent-(.+)-[0-9a-f-]{36}-\d+$")
ACTIVE_AGENT = re.compile(r'<active_agent name="([^"]+)"')
INSTR = re.compile(r'<project_instructions path="([^"]+)">(.*?)</project_instructions>', re.S)
SKILL = re.compile(r"<skill>(.*?)</skill>", re.S)
AGENT = re.compile(r"<subagent>(.*?)</subagent>", re.S)
TAG = r"<{0}>\s*(.*?)\s*</{0}>"
BASE = re.compile(r"relative to (/\S+?)/?;")


def tag(block, name):
    m = re.search(TAG.format(name), block, re.S)
    return m.group(1) if m else ""


def text_len(content):
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        n = 0
        for c in content:
            if isinstance(c, dict):
                for k in ("text", "thinking"):
                    if isinstance(c.get(k), str):
                        n += len(c[k])
                if c.get("type") == "toolCall":
                    n += len(json.dumps(c.get("arguments") or {}))
        return n
    return 0


def owner_rules():
    rules = []
    for pair in re.split(r"[,\n]", os.environ.get("HWORKS_OWNER_MAP", "")):
        if "=" in pair:
            needle, owner = pair.split("=", 1)
            if needle.strip() and owner.strip():
                rules.append((needle.strip(), owner.strip()))
    return rules


def hworks_parts(root=ROOT):
    """Section keys and tool names set by this repo's extensions, and its agent names."""
    sections, tools = set(), set()
    for path in glob.glob(os.path.join(root, "extensions", "*.ts")):
        if ".test." in path:
            continue
        try:
            with open(path, errors="replace") as f:
                src = f.read()
        except OSError:
            continue
        sections |= set(re.findall(r"sections\.(\w+)\s*=", src))
        sections |= set(re.findall(r"sections\[[\"']([\w-]+)[\"']\]\s*=", src))
        for m in re.finditer(r"registerTool\(\s*\{[^}]*?name:\s*[\"']([\w-]+)[\"']", src, re.S):
            tools.add(m.group(1))
    agents = {os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(root, "agents", "*.md"))}
    return sections, tools, agents


class Owners:
    def __init__(self, root=ROOT, rules=None, parts=None):
        self.root = os.path.realpath(root)
        self.rules = owner_rules() if rules is None else rules
        self.sections, self.tools, self.agents = hworks_parts(root) if parts is None else parts

    def rule(self, *subjects):
        for needle, owner in self.rules:
            if any(needle in s for s in subjects if s):
                return owner
        return None

    def path(self, p):
        p = os.path.expanduser(p)
        real = os.path.realpath(p)
        hit = self.rule(p, real)
        if hit:
            return hit
        if real == self.root or real.startswith(self.root + os.sep):
            return "hworks"
        m = re.search(r"node_modules/((?:@[^/]+/)?[^/]+)/", real + "/") or re.search(
            r"node_modules/((?:@[^/]+/)?[^/]+)/", p + "/")
        return f"upstream:{m.group(1)}" if m else "local"

    def section(self, name):
        hit = self.rule(f"section:{name}")
        if hit:
            return hit
        if name in self.sections:
            return "hworks"
        if name in PI_SECTIONS:
            return "upstream:pi"
        m = re.match(r"([A-Za-z0-9]+)-", name)
        return f"upstream:{m.group(1)}" if m else "upstream:unattributed"

    def tool(self, name):
        hit = self.rule(f"tool:{name}")
        if hit:
            return hit
        if name in self.tools:
            return "hworks"
        return "upstream:pi" if name in PI_TOOLS else "upstream:unattributed"

    def agent(self, name):
        return self.rule(f"agent:{name}") or ("hworks" if name in self.agents else "local")


def read_session(path, since, notes):
    """One transcript: its turns (assistant messages with usage), first system prompt, tool
    results, and the prompt characters sent before the first turn."""
    s = {"turns": [], "system": None, "tools": None, "results": [], "pre_chars": 0, "cwd": None, "agent": None}
    calls, pending, bad = {}, [], 0
    try:
        f = open(path, errors="replace")
    except OSError as e:
        notes.append(f"{path}: {e}")
        return s
    with f:
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if not isinstance(e, dict):
                continue
            t = e.get("type")
            if t == "session":
                s["cwd"] = e.get("cwd") if isinstance(e.get("cwd"), str) else None
                continue
            if t == "session_info" and isinstance(e.get("name"), str):
                m = CHILD_NAME.match(e["name"])
                if m and not s["agent"]:
                    s["agent"] = m.group(1)
                continue
            if t in EVENTS:
                pending.append(EVENTS[t])
                if t == "compaction":
                    s["results"].append({"compaction": len(s["turns"])})
                continue
            m = e.get("message")
            if t != "message" or not isinstance(m, dict):
                if t == "custom_message" and not s["turns"]:
                    s["pre_chars"] += text_len(e.get("content"))
                continue
            role = m.get("role")
            if role == "system":
                if s["system"] is None:
                    s["system"] = m.get("sections") if isinstance(m.get("sections"), dict) else {}
                    tools = m.get("toolsAdded")
                    s["tools"] = tools if isinstance(tools, list) else []
                else:
                    pending.append("system prompt change")
                continue
            if role == "assistant":
                for c in m.get("content") or []:
                    if isinstance(c, dict) and c.get("type") == "toolCall" and c.get("id"):
                        a = c.get("arguments")
                        calls[c["id"]] = (c.get("name") or "?", a if isinstance(a, dict) else {})
                u = m.get("usage")
                if not isinstance(u, dict):
                    continue
                dt = ks.to_dt(e.get("timestamp") or m.get("timestamp"))
                cost = u.get("cost") if isinstance(u.get("cost"), dict) else {}
                s["turns"].append({
                    "dt": dt, "after": dt is not None and dt >= since, "events": pending,
                    "input": u.get("input") or 0, "output": u.get("output") or 0,
                    "cr": u.get("cacheRead") or 0, "cw": u.get("cacheWrite") or 0,
                    "cw1h": u.get("cacheWrite1h") or 0, "cost": cost,
                    "model": f"{m.get('provider') or '?'}/{m.get('model') or '?'}"})
                pending = []
                continue
            if role in ("user", "toolResult") and not s["turns"]:
                s["pre_chars"] += text_len(m.get("content"))
            if role == "toolResult":
                name, args = calls.get(m.get("toolCallId"), (m.get("toolName") or "?", {}))
                s["results"].append({"turn": len(s["turns"]), "name": name, "args": args,
                                     "chars": text_len(m.get("content"))})
    if bad:
        notes.append(f"{path}: skipped {bad} malformed line(s)")
    return s


def system_chars(s):
    return sum(len(v) if isinstance(v, str) else len(json.dumps(v)) for v in (s["system"] or {}).values())


def tool_chars(s):
    return sum(len(json.dumps(t)) for t in s["tools"] or [])


def first_turn_tokens(s):
    t = s["turns"][0]
    return t["input"] + t["cr"] + t["cw"]


def components(s, owners):
    """(kind, name, owner, chars) for each part of the first system prompt and tool list."""
    out = []
    for name, val in (s["system"] or {}).items():
        val = val if isinstance(val, str) else json.dumps(val)
        active = ACTIVE_AGENT.search(val) if name == "preamble" else None
        if active:
            out.append(("agent prompt", active.group(1), owners.agent(active.group(1)), len(val)))
            continue
        rest = val
        for path, body in INSTR.findall(val):
            out.append(("instructions", path, owners.path(path), len(body)))
            rest = rest.replace(body, "", 1)
        base = BASE.search(val)
        for block in SKILL.findall(val):
            loc = tag(block, "location")
            full = loc if os.path.isabs(os.path.expanduser(loc)) else os.path.join(
                base.group(1) if base else os.path.expanduser("~"), loc)
            out.append(("skill", tag(block, "name") or loc, owners.path(full) if loc else "upstream:unattributed",
                        len(block)))
            rest = rest.replace(block, "", 1)
        for block in AGENT.findall(val):
            n = tag(block, "name")
            out.append(("agent", n, owners.agent(n), len(block)))
            rest = rest.replace(block, "", 1)
        out.append(("section", name, owners.section(name), len(rest)))
    for t in s["tools"] or []:
        if isinstance(t, dict):
            out.append(("tool", str(t.get("name") or "?"), owners.tool(str(t.get("name") or "?")), len(json.dumps(t))))
    return out


def result_shape(r):
    name, a = r["name"], r["args"]
    if name == "bash" and isinstance(a.get("command"), str):
        rest, _ = ks.split_heredocs(a["command"])
        words = []
        for word, subs, scripts, _flags in ks.segments(rest):
            w = " ".join((word,) + subs + scripts)
            if word != "cd" and w not in words:
                words.append(w)
        return "bash: " + (" | ".join(words[:3]) or "?")
    parts = [name] + sorted(a)
    for k in ("tool", "server", "action", "agent", "workflow"):
        if isinstance(a.get(k), str) and len(a[k]) < 60:
            parts.append(f"{k}={a[k]}")
    return " ".join(parts)


def p90(xs):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * 0.9))] if xs else 0


def rewrite_cause(prev, t):
    if prev is None:
        return "session start"
    for ev in ("compaction", "model change", "thinking change", "context edit", "system prompt change"):
        if ev in t["events"]:
            return ev
    ttl = 3600 if prev["cw1h"] or t["cw1h"] else 300
    if prev["dt"] and t["dt"] and (t["dt"] - prev["dt"]).total_seconds() > ttl:
        return "idle past cache lifetime"
    return "unexplained"


def analyze(src, since, min_sessions=3, top=15, root=ROOT, cwd_match=(), owners=None):
    notes = []
    sroot = src["sessions"]
    if not os.path.isdir(sroot):
        notes.append(f"pi sessions: not found ({sroot})")
        return {}, notes
    owners = owners or Owners(root)
    cutoff = since.timestamp()
    sessions = {}
    for p in sorted(glob.glob(os.path.join(sroot, "**", "*.jsonl"), recursive=True)):
        if "/subagent-artifacts/" in p:
            continue
        try:
            if os.path.getmtime(p) < cutoff:
                continue
        except OSError:
            continue
        s = read_session(p, since, notes)
        if not any(t["after"] for t in s["turns"]):
            continue
        if cwd_match and not any(m.lower() in (s["cwd"] or os.path.relpath(p, sroot)).lower() for m in cwd_match):
            continue
        if CHILD.search(p):
            sec = (s["system"] or {}).get("preamble")
            active = ACTIVE_AGENT.search(sec) if isinstance(sec, str) else None
            s["kind"] = f"child:{s['agent'] or (active.group(1) if active else '?')}"
        else:
            s["kind"] = "main"
        sessions[p] = s

    rel = lambda p: os.path.relpath(p, sroot)

    # Totals over turns inside the window.
    tot = Counter()
    by_model, by_kind = defaultdict(Counter), defaultdict(Counter)
    for p, s in sessions.items():
        by_kind["main" if s["kind"] == "main" else "subagent"]["sessions"] += 1
        if s["kind"] != "main":
            by_kind[s["kind"]]["sessions"] += 1
        for t in s["turns"]:
            if not t["after"]:
                continue
            row = Counter({"turns": 1, "input": t["input"], "output": t["output"], "cache read": t["cr"],
                           "cache write": t["cw"], "cost": t["cost"].get("total") or 0,
                           "cost input": t["cost"].get("input") or 0, "cost output": t["cost"].get("output") or 0,
                           "cost cache read": t["cost"].get("cacheRead") or 0,
                           "cost cache write": t["cost"].get("cacheWrite") or 0})
            tot.update(row)
            by_model[t["model"]].update(row)
            by_kind["main" if s["kind"] == "main" else "subagent"].update(row)
            if s["kind"] != "main":
                by_kind[s["kind"]].update(row)
    totals = [{"section": "totals", "group": "all", **_round(tot)}]
    totals += [{"section": "totals", "group": f"kind {k}", **_round(v)}
               for k, v in sorted(by_kind.items(), key=lambda x: -x[1]["cost"])]
    totals += [{"section": "totals", "group": f"model {k}", **_round(v)}
               for k, v in sorted(by_model.items(), key=lambda x: -x[1]["cost"])]

    # Calibrate chars per token on first turns.
    ratios = []
    for s in sessions.values():
        if s["system"] is not None and s["turns"]:
            toks = first_turn_tokens(s)
            chars = system_chars(s) + tool_chars(s) + s["pre_chars"]
            if toks > 1000 and chars:
                ratios.append(chars / toks)
    cpt = statistics.median(ratios) if ratios else DEFAULT_CHARS_PER_TOKEN
    if not ratios:
        notes.append(f"no first turn to calibrate on; assuming {DEFAULT_CHARS_PER_TOKEN} chars per token")
    tok = lambda chars: int(round(chars / cpt))

    # Baseline components.
    comp = defaultdict(lambda: {"sizes": [], "token_turns": 0, "sessions": set()})
    firsts = []
    for p, s in sessions.items():
        if s["system"] is None or not s["turns"]:
            continue
        firsts.append(first_turn_tokens(s))
        turns = sum(1 for t in s["turns"] if t["after"])
        for kind, name, owner, chars in components(s, owners):
            c = comp[(kind, name, owner)]
            c["sizes"].append(tok(chars))
            c["token_turns"] += tok(chars) * turns
            c["sessions"].add(p)
    baseline = []
    for (kind, name, owner), c in comp.items():
        if len(c["sessions"]) < min_sessions:
            continue
        baseline.append({"section": "baseline", "kind": kind, "name": name, "owner": owner,
                         "sessions": len(c["sessions"]), "median_tokens": int(statistics.median(c["sizes"])),
                         "token_turns": c["token_turns"], "examples": [rel(x) for x in sorted(c["sessions"])[:3]]})
    baseline.sort(key=lambda r: (-r["token_turns"], r["kind"], r["name"]))
    by_owner = defaultdict(lambda: [0, 0])
    for r in baseline:
        by_owner[r["owner"]][0] += r["median_tokens"]
        by_owner[r["owner"]][1] += r["token_turns"]
    baseline_owners = [{"section": "baseline by owner", "owner": o, "median_tokens": v[0], "token_turns": v[1]}
                       for o, v in sorted(by_owner.items(), key=lambda x: -x[1][1])]

    # Tool results, carried until the session ends or compacts.
    groups = defaultdict(lambda: {"calls": 0, "tokens": [], "carried": 0, "sessions": set(), "sample": ""})
    for p, s in sessions.items():
        n = len(s["turns"])
        events = s["results"]
        for i, r in enumerate(events):
            if "compaction" in r or r["turn"] >= n or not s["turns"][r["turn"]]["after"]:
                continue
            end = next((x["compaction"] for x in events[i + 1:] if "compaction" in x), n)
            t = tok(r["chars"])
            g = groups[(owners.tool(r["name"]), result_shape(r))]
            g["calls"] += 1
            g["tokens"].append(t)
            g["carried"] += t * max(0, end - r["turn"])
            g["sessions"].add(p)
            sample = ks.short(json.dumps(r["args"]))
            if not g["sample"] or len(sample) < len(g["sample"]):
                g["sample"] = sample
    results = []
    for (owner, shape), g in groups.items():
        if len(g["sessions"]) < min_sessions:
            continue
        results.append({"section": "tool results", "shape": shape, "tool_owner": owner, "sessions": len(g["sessions"]),
                        "calls": g["calls"], "tokens": sum(g["tokens"]), "p90_tokens": p90(g["tokens"]),
                        "carried_token_turns": g["carried"], "sample": g["sample"],
                        "examples": [rel(x) for x in sorted(g["sessions"])[:3]]})
    results.sort(key=lambda r: (-r["carried_token_turns"], r["shape"]))

    # Cache rewrites.
    causes = defaultdict(lambda: {"turns": 0, "tokens": 0, "cost": 0.0, "sessions": set()})
    for p, s in sessions.items():
        prev = None
        for t in s["turns"]:
            ctx = t["input"] + t["cr"] + t["cw"]
            prev_ctx = prev["input"] + prev["cr"] + prev["cw"] if prev else 0
            lost = prev is None or t["cr"] < REWRITE_SHARE * prev_ctx
            if t["after"] and lost and t["cw"] >= REWRITE_MIN_TOKENS:
                cause = rewrite_cause(prev, t)
                if cause == "session start" and s["kind"] != "main":
                    cause = "subagent start"
                c = causes[cause]
                c["turns"] += 1
                c["tokens"] += t["cw"]
                c["cost"] += t["cost"].get("cacheWrite") or 0
                c["sessions"].add(p)
            prev = t
    cache = [{"section": "cache writes", "cause": k, "sessions": len(v["sessions"]), "turns": v["turns"],
              "tokens": v["tokens"], "cost": round(v["cost"], 2), "examples": [rel(x) for x in sorted(v["sessions"])[:3]]}
             for k, v in sorted(causes.items(), key=lambda x: -x[1]["cost"])]

    upstream = [{"section": "upstream", "owner": r["owner"], "what": f"{r['kind']} {r['name']}",
                 "evidence": f"{r['median_tokens']} tokens in every prompt of {r['sessions']} sessions, "
                             f"{r['token_turns']} token-turns"}
                for r in baseline if r["owner"].startswith("upstream:")]
    for r in cache:
        if r["cause"] == "unexplained" and r["sessions"] >= min_sessions:
            upstream.append({"section": "upstream", "owner": "upstream:pi or provider",
                             "what": "cache rewrite with no prefix change or idle gap",
                             "evidence": f"{r['turns']} turns in {r['sessions']} sessions, {r['tokens']} tokens written, "
                                         f"${r['cost']}"})

    stats = {"sessions": len(sessions), "main": sum(1 for s in sessions.values() if s["kind"] == "main"),
             "chars_per_token": round(cpt, 2), "calibrated_on": len(ratios),
             "first_turn_p50": int(statistics.median(firsts)) if firsts else 0, "first_turn_p90": p90(firsts)}
    return {"stats": stats, "totals": totals, "baseline by owner": baseline_owners, "baseline": baseline[:top],
            "tool results": results[:top], "cache writes": cache, "upstream": upstream[:top]}, notes


def _round(c):
    return {k: (round(v, 2) if isinstance(v, float) else v) for k, v in c.items()}


def fmt(n):
    n = float(n)
    for unit, d in (("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if abs(n) >= d:
            return f"{n / d:.1f}{unit}"
    return f"{int(n)}"


def print_text(report, since):
    st = report["stats"]
    print(f"Token use since {since.date()}: {st['sessions']} sessions ({st['main']} main), first-turn context "
          f"p50 {fmt(st['first_turn_p50'])} p90 {fmt(st['first_turn_p90'])} tokens, "
          f"{st['chars_per_token']} chars/token from {st['calibrated_on']} first turns")
    print("\n== totals ==")
    print(f"{'group':40} {'turns':>7} {'cost':>9} {'in':>7} {'out':>7} {'c.read':>7} {'c.write':>7} "
          f"{'$read':>8} {'$write':>8}")
    for r in report["totals"]:
        print(f"{r['group'][:40]:40} {r.get('turns', 0):>7} {r.get('cost', 0):>9.2f} {fmt(r.get('input', 0)):>7} "
              f"{fmt(r.get('output', 0)):>7} {fmt(r.get('cache read', 0)):>7} {fmt(r.get('cache write', 0)):>7} "
              f"{r.get('cost cache read', 0):>8.2f} {r.get('cost cache write', 0):>8.2f}")
    print("\n== baseline by owner ==  (sums of the rows shown below the cut too)")
    for r in report["baseline by owner"]:
        print(f"  {r['owner']:32} {fmt(r['median_tokens']):>7} tokens  {fmt(r['token_turns']):>7} token-turns")
    print("\n== baseline ==")
    print(f"{'sess':>5} {'tokens':>7} {'tok-turns':>9}  part  [owner]")
    for r in report["baseline"]:
        print(f"{r['sessions']:>5} {fmt(r['median_tokens']):>7} {fmt(r['token_turns']):>9}  "
              f"{r['kind']} {r['name']}  [{r['owner']}]")
    print("\n== tool results ==")
    print(f"{'sess':>5} {'calls':>5} {'tokens':>7} {'p90':>6} {'carried':>8}  shape  [tool owner]")
    for r in report["tool results"]:
        print(f"{r['sessions']:>5} {r['calls']:>5} {fmt(r['tokens']):>7} {fmt(r['p90_tokens']):>6} "
              f"{fmt(r['carried_token_turns']):>8}  {r['shape']}  [{r['tool_owner']}]")
        print(f"             e.g. {', '.join(r['examples'])}")
        print(f"             sample: {r['sample']}")
    print("\n== cache writes ==")
    for r in report["cache writes"]:
        print(f"  {r['cause']:26} {r['turns']:>6} turns {r['sessions']:>5} sess {fmt(r['tokens']):>7} tokens "
              f"${r['cost']:.2f}")
    print("\n== upstream ==  (flags only: nothing filed or drafted)")
    if not report["upstream"]:
        print("  (none)")
    for r in report["upstream"]:
        print(f"  [{r['owner']}] {r['what']}: {r['evidence']}")


def main(argv=None):
    ks.load_env_files(ROOT)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 usage=argparse.SUPPRESS)
    ap.add_argument("--since", default="14d", help="YYYY-MM-DD or Nd (default 14d)")
    ap.add_argument("--min-sessions", type=int, default=3, help="hide rows seen in fewer sessions (default 3)")
    ap.add_argument("--top", type=int, default=15, help="rows per ranked section (default 15)")
    ap.add_argument("--cwd-match", action="append", default=[], metavar="TEXT",
                    help="keep sessions whose cwd contains TEXT (repeatable)")
    ap.add_argument("--json", action="store_true", help="one JSON object per row")
    args = ap.parse_args(argv)
    since = ks.parse_since(args.since)
    src = {"sessions": os.environ.get("HWORKS_PI_SESSIONS") or os.path.expanduser("~/.pi/agent/sessions")}
    report, notes = analyze(src, since, args.min_sessions, args.top, cwd_match=args.cwd_match)
    if args.json:
        for section, rows in report.items():
            if section == "stats":
                print(json.dumps({"section": "stats", **rows}))
            else:
                for r in rows:
                    print(json.dumps(r))
    elif report:
        print_text(report, since)
    for n in notes:
        print(f"note: {n}", file=sys.stderr)


if __name__ == "__main__":
    main()
