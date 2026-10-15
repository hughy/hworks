#!/usr/bin/env python3
"""Audit the installed pi setup for drift: what pi loads, what is stale or broken, and which
hworks parts overlap what the harness already ships.

Read-only. Output names local paths and harness parts: do not redirect it into a repo.
usage: kaizen-setup.py [--since YYYY-MM-DD|7d] [--cwd DIR] [--json]

Sections:
  skills         every skill in the roots pi loads: settings.json `skills`, skill dirs of
                 settings.json `packages`, ~/.agents/skills, ~/.pi/agent/skills, and .pi/skills
                 and .agents/skills under --cwd, found the way pi's loader finds them. Name,
                 root, description length, and whether ~/.agents/.skill-lock.json manages it.
  duplicates     a skill name loaded from more than one root.
  settings       paths named in ~/.pi/agent/settings.json (resource lists, local packages,
                 agentOverrides extension lists, other path-like strings) that do not exist or pin a
                 versioned install directory, and subagents.agentOverrides keys that name no
                 agent in ~/.pi/agent/agents/**, a package's agents/, or .pi/agents under --cwd
                 ("may be a builtin" unless subagents.disableBuiltins is true).
  extensions     each entry in ~/.pi/agent/extensions: kind, link target, broken links.
  leftovers      *.bak, *.pre-*, *.orig, and *~ files under ~/.pi/agent (sessions skipped).
  stale refs     backticked paths, scripts/..., skills/<name>, agents/<name>.md (backticked or
                 not), ../<name>/SKILL.md, and /skill:<name> in global/AGENTS.md, agents/*.md,
                 adapters/*.md, and skills/*/SKILL.md that resolve to no file or skill. A
                 relative path resolves against the file that names it, then the repo root, then
                 skills/ (a path that starts with a skill name).
  overlap        for each hworks skill, agent, and extension, the harness tools, skills, and
                 agents whose name and description share words with it, from the baseline prompt
                 of pi sessions since --since (default 14d). The score is word-set overlap
                 (Jaccard): a lead for keep/replace/remove, not a verdict.

Every row names an owner (hworks, local, or upstream:<name>) by the rules and HWORKS_OWNER_MAP
of kaizen-tokens.py.

Sources (each optional; a missing one is reported, not fatal):
  ~/.pi/agent          settings.json, agents/, extensions/, skills/
  ~/.agents            skills/ and .skill-lock.json
  HWORKS_PI_SESSIONS   pi session transcripts for the overlap section (default ~/.pi/agent/sessions)
  HWORKS_OWNER_MAP     owner overrides, as in kaizen-tokens.py
adapters/local/*.env, when present, is read first; values already in the environment win.
"""
import argparse
import fnmatch
import glob
import importlib.util
import json
import os
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from urllib.parse import urlparse
from urllib.request import url2pathname

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
_spec = importlib.util.spec_from_file_location("kaizen_tokens", os.path.join(HERE, "kaizen-tokens.py"))
kt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kt)
ks = kt.ks

LEFTOVER = ("*.bak", "*.pre-*", "*.orig", "*~")
VERSIONED = re.compile(r"(?:^|/)(?:v?\d+\.\d+\.\d+[^/]*|[\w.-]+@\d+(?:\.\d+)*[^/]*)(?=/|$)")
BASELINE_SESSIONS = 50
OVERLAP_MIN = 0.12
OVERLAP_TOP = 3
STOP = set("""a an and are as at be by can do does for from has have in into is it its of on or
that the this to use used uses using when with without will your you not any all each one per
via run runs only more than then them they their which what who how where why also other""".split())
GUIDANCE = ("global/AGENTS.md", "agents/*.md", "adapters/*.md", "skills/*/SKILL.md")
BACKTICK = re.compile(r"`([^`\n]+)`")
SKILL_LINK = re.compile(r"(?<![\w.])((?:\.\./)+[\w.-]+/SKILL\.md)")
SKILL_CMD = re.compile(r"/skill:([\w-]+)")
PATHLIKE = re.compile(r"^(?:\.{1,2}/)*[\w.-]+(?:/[\w.-]+)+/?$")
PLAIN_REF = re.compile(r"(?<![\w./~$<-])(scripts/[\w.-]*\w(?:/[\w.-]*\w)*|skills/[\w-]*\w|agents/[\w.-]*\w\.md)(?![\w/*<{-])")


_ESC = {"0": "\0", "a": "\a", "b": "\b", "t": "\t", "\t": "\t", "n": "\n", "v": "\v", "f": "\f",
        "r": "\r", "e": "\x1b", " ": " ", '"': '"', "/": "/", "\\": "\\", "N": "\x85",
        "_": "\xa0", "L": "\u2028", "P": "\u2029"}
_ESC_RE = re.compile(r"\\(x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8}|.)", re.S)


def _unescape(s):
    def sub(m):
        e = m.group(1)
        return chr(int(e[1:], 16)) if len(e) > 1 else _ESC.get(e, e)
    return _ESC_RE.sub(sub, s)


def _fold_block(lines, folded):
    out, prev, blanks = "", None, 0
    for ln in lines:
        if not ln.strip(" \t") and not (ln and not folded):
            blanks += 1
            continue
        if prev is None:
            out = "\n" * blanks + ln
        elif not folded:
            out += "\n" * (blanks + 1) + ln
        else:
            plain = prev[:1] not in " \t" and ln[:1] not in " \t"
            out += ("\n" * (blanks + (0 if plain else 1))) if blanks else (" " if plain else "\n")
            out += ln
        prev, blanks = ln, 0
    return out, blanks


def _fold_flow(lines, escapes):
    out, k, joined = "", 0, False
    for i, ln in enumerate(lines):
        last = i == len(lines) - 1
        if i:
            ln = ln.lstrip(" \t")
        esc = False
        if not last:
            if escapes and (len(ln) - len(ln.rstrip("\\"))) % 2:
                ln, esc = ln[:-1], True
            else:
                ln = ln.rstrip(" \t")
        if i and not last and not ln and not esc:
            k += 1
            continue
        if i:
            out += "" if joined and not k else ("\n" * k if k else " ")
        out += ln
        k, joined = 0, esc
    return out


def yaml_scalar(first, rest):
    """A top-level YAML scalar from its first-line text and its continuation lines: block (| or
    >, with indentation and chomping indicators), single- or double-quoted (escapes, folding),
    or plain folded across lines."""
    block = re.match(r"([|>])([1-9][+-]?|[+-][1-9]?)?[ \t]*(?:#.*)?$", first)
    if block:
        style, ind_chomp = block.group(1), block.group(2) or ""
        chomp = "".join(c for c in ind_chomp if c in "+-")
        digit = "".join(c for c in ind_chomp if c.isdigit())
        lines = list(rest)
        if digit:
            ind = int(digit)
        else:
            ind = next((len(ln) - len(ln.lstrip(" ")) for ln in lines if ln.strip(" \t")), 0)
        lines = [ln[ind:] if len(ln) >= ind else "" for ln in lines]
        text, trailing = _fold_block(lines, style == ">")
        if chomp == "-" or not text:
            return text if chomp != "+" else text + "\n" * trailing
        return text + "\n" + ("\n" * trailing if chomp == "+" else "")
    raw = "\n".join([first.lstrip(" \t")] + list(rest))
    q = raw[:1]
    if q in "'\"" and q:
        i, n = 1, len(raw)
        while i < n:
            c = raw[i]
            if q == '"' and c == "\\":
                i += 2
                continue
            if c == q:
                if q == "'" and raw[i + 1:i + 2] == "'":
                    i += 2
                    continue
                break
            i += 1
        body = _fold_flow(raw[1:i].split("\n"), q == '"')
        return _unescape(body) if q == '"' else body.replace("''", "'")
    lines = []
    for ln in raw.split("\n"):
        cut = re.search(r"(?:^|[ \t])#", ln)
        if cut:
            ln = ln[:cut.start()]
            lines.append(ln)
            break
        lines.append(ln)
    out, k = "", 0
    for ln in lines:
        ln = ln.strip(" \t")
        if not ln:
            k += 1
            continue
        out += ("\n" * k if k else " ") if out else ""
        out += ln
        k = 0
    return out


def frontmatter(path):
    """Top-level scalar keys of a markdown file's YAML frontmatter, or {} when absent. Handles the
    scalar forms skills use (plain, quoted, block, folded); not a full YAML parser."""
    try:
        with open(path, errors="replace") as f:
            text = f.read(20000)
    except OSError:
        return {}
    text = text.lstrip("\ufeff").replace("\r\n", "\n")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    out, key, first, rest = {}, None, "", []
    for line in text[4:end].splitlines():
        kv = re.match(r"([A-Za-z_][\w-]*):(?:\s+(.*))?$", line)
        if kv and not line[:1].isspace():
            if key:
                out[key] = yaml_scalar(first, rest)
            key, first, rest = kv.group(1), kv.group(2) or "", []
        elif key and not line.startswith("#"):
            rest.append(line)
    if key:
        out[key] = yaml_scalar(first, rest)
    return out


def load_json(path, notes, label):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        notes.append(f"{label}: not found ({path})")
    except (OSError, ValueError) as e:
        notes.append(f"{label}: unreadable ({path}: {e})")
    return None


def pathlike(v):
    v = v.lstrip("-!+")
    return v.startswith(("/", "~/", "./", "../", "file://")) or v == "~"


def is_pattern(v):
    """pi treats these resource entries as filters or builtin names, not paths to load."""
    return v.startswith(("!", "+", "-", "builtin:")) or "*" in v or "?" in v


def is_local_source(v):
    """A package source pi resolves as a local path (pi's isLocalPath)."""
    return not v.strip().startswith(("npm:", "git:", "github:", "http:", "https:", "ssh:", "builtin:"))


RESOURCE_KEYS = ("skills", "extensions", "prompts", "themes")
OVERRIDE_PATH_KEYS = ("extensions", "subagentOnlyExtensions")


def setting_paths(settings):
    """(key, value) for every settings string pi resolves as a filesystem path: plain entries of
    the resource lists, local package sources, agentOverrides extension lists, and any other
    string that starts like a path."""
    seen = set()
    for k in RESOURCE_KEYS:
        for i, v in enumerate(settings.get(k) or []):
            if isinstance(v, str) and not is_pattern(v):
                seen.add(f"{k}[{i}]")
                yield f"{k}[{i}]", v
    for i, v in enumerate(settings.get("packages") or []):
        src = v.get("source") if isinstance(v, dict) else v
        if isinstance(src, str) and is_local_source(src):
            key = f"packages[{i}]" + (".source" if isinstance(v, dict) else "")
            seen.add(key)
            yield key, src
    sub = settings.get("subagents") if isinstance(settings.get("subagents"), dict) else {}
    overrides = sub.get("agentOverrides") if isinstance(sub.get("agentOverrides"), dict) else {}
    for name, o in overrides.items():
        for k in OVERRIDE_PATH_KEYS:
            vals = o.get(k) if isinstance(o, dict) else None
            for i, v in enumerate(vals if isinstance(vals, list) else []):
                if isinstance(v, str) and not is_pattern(v):
                    key = f"subagents.agentOverrides.{name}.{k}[{i}]"
                    seen.add(key)
                    yield key, v
    for key, v in walk_strings(settings):
        if key not in seen and pathlike(v):
            yield key, v


def local_packages(settings, base):
    for v in (settings or {}).get("packages") or []:
        src = v.get("source") if isinstance(v, dict) else v
        if isinstance(src, str) and is_local_source(src):
            yield src, resolve_setting(src, base)


def resolve_setting(v, base):
    """A settings path the way pi's resolvePath reads it: trimmed, ~ expanded, file:// URLs
    converted, relative to base."""
    v = v.lstrip("-!+").strip()
    if v == "~" or v.startswith("~/"):
        v = os.path.expanduser(v)
    elif v.startswith("file://"):
        v = url2pathname(urlparse(v).path)
    return os.path.normpath(v if os.path.isabs(v) else os.path.join(base, v))


def walk_strings(obj, key=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk_strings(v, f"{key}.{k}" if key else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_strings(v, f"{key}[{i}]")
    elif isinstance(obj, str):
        yield key, obj


def skill_roots(home, settings, cwd, pi_dir):
    """(root, origin, mode) for each skill root pi loads, in load order. A root can be a single
    Markdown file. mode is pi's discovery mode: "pi" loads root-level .md files, "agents" loads
    .md files only below the root."""
    roots = []
    base = pi_dir
    for v in (settings or {}).get("skills") or []:
        if isinstance(v, str) and not is_pattern(v):
            roots.append((resolve_setting(v, base), "settings skills", "pi"))
    for v, pkg in local_packages(settings, base):
        try:
            with open(os.path.join(pkg, "package.json")) as f:
                meta = json.load(f).get("pi") or {}
        except (OSError, ValueError):
            meta = {}
        for s in meta.get("skills") or []:
            if isinstance(s, str):
                roots.append((os.path.normpath(os.path.join(pkg, s)), f"package {v}", "pi"))
        if os.path.isdir(os.path.join(pkg, "skills")):
            roots.append((os.path.join(pkg, "skills"), f"package {v}", "pi"))
    roots.append((os.path.join(home, ".agents", "skills"), "~/.agents/skills", "agents"))
    roots.append((os.path.join(pi_dir, "skills"), "~/.pi/agent/skills", "pi"))
    if cwd:
        roots.append((os.path.join(cwd, ".pi/skills"), "--cwd .pi/skills", "pi"))
        roots.append((os.path.join(cwd, ".agents/skills"), "--cwd .agents/skills", "agents"))
    seen, out = set(), []
    for r, origin, mode in roots:
        if r not in seen:
            seen.add(r)
            out.append((r, origin, mode))
    return out


def find_skills(root, mode="pi", _top=None):
    """Skill files pi discovers under root (pi's collectSkillEntries, without ignore files): a
    dir holding SKILL.md is one skill and is not searched further; other dirs are searched to any
    depth, skipping dot entries and node_modules; loose .md files load at the root in "pi" mode
    and below it in "agents" mode."""
    top = root if _top is None else _top
    if os.path.isfile(os.path.join(root, "SKILL.md")):
        return [os.path.join(root, "SKILL.md")]
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return []
    out = []
    for name in names:
        if name.startswith(".") or name == "node_modules":
            continue
        p = os.path.join(root, name)
        if os.path.isdir(p):
            out += find_skills(p, mode, top)
        elif os.path.isfile(p) and name.endswith(".md") and (root == top) == (mode == "pi"):
            out.append(p)
    return out


def lock_names(lock):
    names = set()
    for key, e in ((lock or {}).get("skills") or {}).items():
        names |= {key, key.replace("/", "-"), key.rsplit("/", 1)[-1]}
        sp = e.get("skillPath") if isinstance(e, dict) else None
        if isinstance(sp, str) and "/" in sp:
            names.add(os.path.basename(os.path.dirname(sp)))
    return names


def audit_skills(roots, lock, owners, notes, lock_root=""):
    """Skills per root; lock-managed means named in the lock and installed (or linked) into lock_root."""
    managed = lock_names(lock)
    lock_root = os.path.realpath(lock_root) + os.sep if lock_root else None
    rows = []
    for root, origin, mode in roots:
        if os.path.isfile(root):
            paths = [root]
        elif os.path.isdir(root):
            paths = find_skills(root, mode)
        else:
            notes.append(f"skill root: not found ({root}, {origin})")
            continue
        for path in paths:
            fm = frontmatter(path)
            if os.path.basename(path) != "SKILL.md" and not str(fm.get("description") or "").strip():
                continue
            d = os.path.basename(os.path.dirname(path))
            name = fm.get("name") or d
            rows.append({"section": "skills", "name": name, "root": root, "origin": origin, "path": path,
                         "description_chars": len(fm.get("description") or ""),
                         "lock_managed": bool(lock_root) and (name in managed or d in managed)
                         and os.path.realpath(path).startswith(lock_root), "owner": owners.path(path)})
    by_name = defaultdict(list)
    for r in rows:
        by_name[r["name"]].append(r)
    dups = []
    for name, rs in sorted(by_name.items()):
        if len({r["root"] for r in rs}) > 1:
            dups.append({"section": "duplicates", "name": name, "roots": [r["root"] for r in rs],
                         "same_file": len({os.path.realpath(r["path"]) for r in rs}) == 1,
                         "owners": sorted({r["owner"] for r in rs}), "owner": rs[0]["owner"]})
    return rows, dups


def agent_names(dirs):
    names = set()
    for d in dirs:
        for p in glob.glob(os.path.join(d, "**", "*.md"), recursive=True):
            names.add(frontmatter(p).get("name") or os.path.splitext(os.path.basename(p))[0])
    return names


def audit_settings(settings, settings_path, pi_dir, cwd, owners):
    rows = []
    if settings is None:
        return rows
    own = owners.path(settings_path)
    for key, v in setting_paths(settings):
        p = resolve_setting(v, pi_dir)
        if not os.path.exists(p):
            rows.append({"section": "settings", "issue": "missing path", "key": key, "path": p,
                         "names": owners.path(p), "owner": own})
        m = VERSIONED.search(p)
        if m:
            rows.append({"section": "settings", "issue": "version-pinned path", "key": key, "path": p,
                         "segment": m.group(0).strip("/"), "names": owners.path(p), "owner": own})
    sub = settings.get("subagents") if isinstance(settings.get("subagents"), dict) else {}
    overrides = sub.get("agentOverrides") if isinstance(sub.get("agentOverrides"), dict) else {}
    dirs = [os.path.join(pi_dir, "agents")]
    for _v, pkg in local_packages(settings, pi_dir):
        dirs.append(os.path.join(pkg, "agents"))
    if cwd:
        dirs.append(os.path.join(cwd, ".pi", "agents"))
    known = agent_names(dirs)
    builtins_off = sub.get("disableBuiltins") is True
    for name in sorted(overrides):
        if name not in known:
            rows.append({"section": "settings", "issue": "stale override" if builtins_off else "may be a builtin",
                         "key": f"subagents.agentOverrides.{name}", "path": "", "names": owners.agent(name),
                         "owner": own})
    return rows


def audit_extensions(ext_dir, owners, notes):
    if not os.path.isdir(ext_dir):
        notes.append(f"extensions: not found ({ext_dir})")
        return []
    rows = []
    for name in sorted(os.listdir(ext_dir)):
        p = os.path.join(ext_dir, name)
        link = os.path.islink(p)
        target = os.readlink(p) if link else ""
        broken = link and not os.path.exists(p)
        kind = "broken link" if broken else ("link" if link else "dir" if os.path.isdir(p) else "file")
        owner = owners.path(p)
        rows.append({"section": "extensions", "name": name, "kind": kind, "target": target, "broken": broken,
                     "owner": owner})
    return rows


def audit_leftovers(pi_dir, owners, notes):
    if not os.path.isdir(pi_dir):
        notes.append(f"pi agent dir: not found ({pi_dir})")
        return []
    rows = []
    for d, subdirs, files in os.walk(pi_dir):
        subdirs[:] = [s for s in subdirs if s not in ("sessions", "node_modules", ".git")]
        for f in files:
            if any(fnmatch.fnmatch(f, pat) for pat in LEFTOVER):
                p = os.path.join(d, f)
                try:
                    mt = datetime.fromtimestamp(os.path.getmtime(p), timezone.utc).strftime("%Y-%m-%d")
                except OSError:
                    mt = "?"
                rows.append({"section": "leftovers", "path": p, "mtime": mt, "owner": owners.path(p)})
    return sorted(rows, key=lambda r: r["path"])


def guidance_files(root):
    out = []
    for pat in GUIDANCE:
        out += sorted(glob.glob(os.path.join(root, pat)))
    return out


def ref_candidates(text, top):
    """(kind, ref) pairs worth resolving in a guidance file."""
    for span in BACKTICK.findall(text):
        for tok in span.split():
            tok = tok.strip("\"'(),;:")
            if tok.startswith("<hworks>/"):
                tok = tok[len("<hworks>/"):]
            if any(c in tok for c in "<>{}$*?[]|=\u2026") or "://" in tok or "..." in tok or not PATHLIKE.match(tok):
                continue
            first = tok.split("/", 1)[0]
            if first in (".", "..") or first in top or re.search(r"\.\w+$", tok):
                yield "path", tok.rstrip("/")
    for m in PLAIN_REF.findall(text):
        yield "path", m
    for m in SKILL_LINK.findall(text):
        yield "path", m
    for m in SKILL_CMD.findall(text):
        yield "skill", m


def audit_refs(root, skill_names, owners):
    top = {e for e in os.listdir(root) if not e.startswith(".")} if os.path.isdir(root) else set()
    rows, seen = [], set()
    for path in guidance_files(root):
        try:
            with open(path, errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        here = os.path.dirname(path)
        for kind, ref in ref_candidates(text, top):
            if (path, kind, ref) in seen:
                continue
            seen.add((path, kind, ref))
            if kind == "skill":
                ok = ref in skill_names
            elif ref.startswith(("./", "../")):
                ok = os.path.exists(os.path.normpath(os.path.join(here, ref)))
            else:
                ok = any(os.path.exists(os.path.join(d, ref)) for d in (here, root, os.path.join(root, "skills")))
            if not ok:
                rows.append({"section": "stale refs", "file": os.path.relpath(path, root), "kind": kind,
                             "ref": ("/skill:" if kind == "skill" else "") + ref, "owner": owners.path(path)})
    return rows


def words(*texts):
    out = set()
    for t in texts:
        for w in re.findall(r"[a-z][a-z0-9]+", (t or "").lower().replace("_", " ").replace("-", " ")):
            if len(w) >= 3 and w not in STOP:
                out.add(w)
    return out


def ext_description(path):
    lines = []
    try:
        with open(path, errors="replace") as f:
            for line in f:
                s = line.strip()
                if not s.startswith(("//", "/*", "*")):
                    break
                lines.append(s.lstrip("/* "))
    except OSError:
        pass
    return " ".join(lines)


def hworks_items(root):
    items = []
    for p in sorted(glob.glob(os.path.join(root, "skills", "*", "SKILL.md"))):
        fm = frontmatter(p)
        items.append(("skill", fm.get("name") or os.path.basename(os.path.dirname(p)), fm.get("description") or ""))
    for p in sorted(glob.glob(os.path.join(root, "agents", "*.md"))):
        fm = frontmatter(p)
        items.append(("agent", fm.get("name") or os.path.splitext(os.path.basename(p))[0], fm.get("description") or ""))
    for p in sorted(glob.glob(os.path.join(root, "extensions", "*.ts"))):
        if ".test." not in p:
            items.append(("extension", os.path.splitext(os.path.basename(p))[0], ext_description(p)))
    return items


def harness_parts(sroot, since, owners, notes):
    """Distinct skills, agents, and tools not owned by hworks, from the first system prompt of the
    newest main pi sessions in the window."""
    if not os.path.isdir(sroot):
        notes.append(f"pi sessions: not found ({sroot})")
        return []
    cutoff = since.timestamp()
    files = []
    for p in glob.glob(os.path.join(sroot, "**", "*.jsonl"), recursive=True):
        if "/subagent-artifacts/" in p or kt.CHILD.search(p):
            continue
        try:
            mt = os.path.getmtime(p)
        except OSError:
            continue
        if mt >= cutoff:
            files.append((mt, p))
    files.sort(reverse=True)
    parts, read = {}, 0
    for _mt, p in files:
        if read >= BASELINE_SESSIONS:
            break
        sections, tools = kt.first_system(p)
        if sections is None:
            continue
        read += 1
        for part in kt.listed_parts(sections, tools):
            if part["kind"] == "skill":
                owner = owners.path(part["location"]) if part["location"] else "upstream:unattributed"
            elif part["kind"] == "agent":
                owner = owners.agent(part["name"])
            else:
                owner = owners.tool(part["name"])
            if owner == "hworks":
                continue
            parts.setdefault((part["kind"], part["name"]), {**part, "owner": owner})
    if not read:
        notes.append(f"pi sessions: no main session with a system prompt since {since.date()}")
    return list(parts.values())


def audit_overlap(root, harness):
    rows = []
    hw = [(k, n, d, words(n, d)) for k, n, d in hworks_items(root)]
    hs = [(p, words(p["name"], p["description"])) for p in harness]
    for kind, name, _desc, w in hw:
        if not w:
            continue
        cands = []
        for p, pw in hs:
            if not pw:
                continue
            score = len(w & pw) / len(w | pw)
            if score >= OVERLAP_MIN:
                cands.append({"kind": p["kind"], "name": p["name"], "owner": p["owner"], "score": round(score, 2),
                              "shared": sorted(w & pw)[:8]})
        cands.sort(key=lambda c: (-c["score"], c["name"]))
        if cands:
            rows.append({"section": "overlap", "kind": kind, "name": name, "owner": "hworks",
                         "candidates": cands[:OVERLAP_TOP]})
    rows.sort(key=lambda r: (-r["candidates"][0]["score"], r["name"]))
    return rows


def analyze(home, since, cwd=None, root=ROOT, sroot=None, owners=None):
    notes = []
    owners = owners or kt.Owners(root)
    pi_dir = os.path.join(home, ".pi", "agent")
    settings_path = os.path.join(pi_dir, "settings.json")
    settings = load_json(settings_path, notes, "pi settings")
    if settings is not None and not isinstance(settings, dict):
        notes.append(f"pi settings: not an object ({settings_path})")
        settings = None
    lock_path = os.path.join(home, ".agents", ".skill-lock.json")
    lock = load_json(lock_path, notes, "skill lock") if os.path.exists(lock_path) else None
    if lock is None and not os.path.exists(lock_path):
        notes.append(f"skill lock: not found ({lock_path})")
    roots = skill_roots(home, settings, cwd, pi_dir)
    skills, dups = audit_skills(roots, lock if isinstance(lock, dict) else None, owners, notes,
                                os.path.join(home, ".agents", "skills"))
    names = {r["name"] for r in skills} | {os.path.basename(os.path.dirname(p))
                                          for p in glob.glob(os.path.join(root, "skills", "*", "SKILL.md"))}
    harness = harness_parts(sroot or os.path.join(pi_dir, "sessions"), since, owners, notes)
    report = {
        "skills": skills,
        "duplicates": dups,
        "settings": audit_settings(settings, settings_path, pi_dir, cwd, owners),
        "extensions": audit_extensions(os.path.join(pi_dir, "extensions"), owners, notes),
        "leftovers": audit_leftovers(pi_dir, owners, notes),
        "stale refs": audit_refs(root, names, owners),
        "overlap": audit_overlap(root, harness),
    }
    report["stats"] = {"skill_roots": len(roots), "skills": len(skills), "harness_parts": len(harness),
                       **{k: len(v) for k, v in report.items() if k not in ("skills",)}}
    return report, notes


def print_text(report, notes):
    st = report["stats"]
    print(f"Setup audit: {st['skills']} skills in {st['skill_roots']} roots, {st['harness_parts']} harness parts "
          f"seen in session baselines")
    print("\n== sources ==")
    for n in notes or ["(all found)"]:
        print(f"  {n}")
    print("\n== skills ==")
    print(f"{'desc':>5} {'lock':>4}  name  root  [owner]")
    for r in report["skills"]:
        print(f"{r['description_chars']:>5} {'yes' if r['lock_managed'] else '-':>4}  {r['name']}  {r['root']}  "
              f"[{r['owner']}]")
    print("\n== duplicates ==  (one skill name loaded from more than one root)")
    for r in report["duplicates"] or [None]:
        if r is None:
            print("  (none)")
            continue
        same = " (same file)" if r["same_file"] else ""
        print(f"  {r['name']}{same}: {', '.join(r['roots'])}  [{', '.join(r['owners'])}]")
    print("\n== settings ==")
    for r in report["settings"] or [None]:
        if r is None:
            print("  (none)")
            continue
        extra = f" ({r['segment']})" if r.get("segment") else ""
        print(f"  {r['issue']}{extra}: {r['key']} {r['path']}  [{r['owner']}; names {r['names']}]")
    print("\n== extensions ==")
    for r in report["extensions"]:
        tgt = f" -> {r['target']}" if r["target"] else ""
        print(f"  {r['kind']:11} {r['name']}{tgt}  [{r['owner']}]")
    print("\n== leftovers ==")
    for r in report["leftovers"] or [None]:
        print("  (none)" if r is None else f"  {r['mtime']}  {r['path']}  [{r['owner']}]")
    print("\n== stale refs ==  (a hit can be an intentional example)")
    for r in report["stale refs"] or [None]:
        print("  (none)" if r is None else f"  {r['file']}: {r['ref']}  [{r['owner']}]")
    print("\n== overlap ==  (word-set overlap: leads for keep/replace/remove, not verdicts)")
    for r in report["overlap"] or [None]:
        if r is None:
            print("  (none)")
            continue
        print(f"  {r['kind']} {r['name']}  [{r['owner']}]")
        for c in r["candidates"]:
            print(f"      {c['score']:.2f}  {c['kind']} {c['name']}  [{c['owner']}]  shared: {' '.join(c['shared'])}")


def main_checkout(root=ROOT):
    """The repo's main worktree when root is a linked worktree, else None. Installs link into
    the main checkout, so its paths are hworks too."""
    try:
        out = subprocess.run(["git", "-C", root, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    main = os.path.dirname(out) if os.path.basename(out) == ".git" else None
    return main if main and os.path.realpath(main) != os.path.realpath(root) else None


def main(argv=None):
    ks.load_env_files(ROOT)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 usage=argparse.SUPPRESS)
    ap.add_argument("--since", default="14d", help="session window for the overlap section (default 14d)")
    ap.add_argument("--cwd", help="project dir whose .pi/skills, .agents/skills, and .pi/agents also load")
    ap.add_argument("--json", action="store_true", help="one JSON object per row")
    args = ap.parse_args(argv)
    home = os.path.expanduser("~")
    sroot = os.environ.get("HWORKS_PI_SESSIONS") or os.path.join(home, ".pi", "agent", "sessions")
    rules = kt.owner_rules()
    other = main_checkout()
    if other:
        rules.append((os.path.realpath(other) + os.sep, "hworks"))
    report, notes = analyze(home, ks.parse_since(args.since), cwd=args.cwd and os.path.abspath(args.cwd), sroot=sroot,
                            owners=kt.Owners(ROOT, rules=rules))
    if args.json:
        print(json.dumps({"section": "stats", **report["stats"]}))
        for section, rows in report.items():
            if section != "stats":
                for r in rows:
                    print(json.dumps(r))
        for n in notes:
            print(json.dumps({"section": "note", "note": n}))
    else:
        print_text(report, notes)


if __name__ == "__main__":
    main()
