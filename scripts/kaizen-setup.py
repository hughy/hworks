#!/usr/bin/env python3
"""Audit the installed pi setup for drift: what pi loads, what is stale or broken, and which
hworks parts overlap what the harness already ships.

Read-only. Output names local paths and harness parts: do not redirect it into a repo.
usage: kaizen-setup.py [--since YYYY-MM-DD|7d] [--cwd DIR] [--json]

Sections:
  skills         every skill in the roots pi loads: settings.json `skills`, skill dirs of
                 settings.json `packages`, ~/.agents/skills, ~/.pi/agent/skills, and .pi/skills
                 and .agents/skills under --cwd. Name, root, description length, and whether
                 ~/.agents/.skill-lock.json manages it.
  duplicates     a skill name loaded from more than one root.
  settings       paths named in ~/.pi/agent/settings.json that do not exist or that pin a
                 versioned install directory, and subagents.agentOverrides keys that name no
                 agent in ~/.pi/agent/agents/**, a package's agents/, or .pi/agents under --cwd
                 ("may be a builtin" unless subagents.disableBuiltins is true).
  extensions     each entry in ~/.pi/agent/extensions: kind, link target, broken links.
  leftovers      *.bak, *.pre-*, *.orig, and *~ files under ~/.pi/agent (sessions skipped).
  stale refs     backticked paths, `scripts/...`, `skills/<name>`, `agents/<name>.md`,
                 ../<name>/SKILL.md, and /skill:<name> in global/AGENTS.md, agents/*.md,
                 adapters/*.md, and skills/*/SKILL.md that resolve to no file or skill. A
                 relative path resolves against the file that names it, then the repo root.
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


def frontmatter(path):
    """name and description from a markdown file's YAML frontmatter, or {} when absent."""
    try:
        with open(path, errors="replace") as f:
            text = f.read(20000)
    except OSError:
        return {}
    m = re.match(r"---\s*\n(.*?)\n---", text, re.S)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        kv = re.match(r"(name|description):\s*(.*)$", line)
        if kv:
            out[kv.group(1)] = kv.group(2).strip().strip("'\"")
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
    return v.startswith(("/", "~/", "./", "../")) or v == "~"


def resolve_setting(v, base):
    v = os.path.expanduser(v.lstrip("-!+"))
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
    """(root, origin) for each skill root pi loads, in load order."""
    roots = []
    base = pi_dir
    for v in (settings or {}).get("skills") or []:
        if isinstance(v, str) and not v.startswith(("-", "!")):
            roots.append((resolve_setting(v, base), "settings skills"))
    for v in (settings or {}).get("packages") or []:
        if not isinstance(v, str) or not pathlike(v):
            continue
        pkg = resolve_setting(v, base)
        try:
            with open(os.path.join(pkg, "package.json")) as f:
                meta = json.load(f).get("pi") or {}
        except (OSError, ValueError):
            meta = {}
        for s in meta.get("skills") or []:
            if isinstance(s, str):
                roots.append((os.path.normpath(os.path.join(pkg, s)), f"package {v}"))
        if os.path.isdir(os.path.join(pkg, "skills")):
            roots.append((os.path.join(pkg, "skills"), f"package {v}"))
    roots.append((os.path.join(home, ".agents", "skills"), "~/.agents/skills"))
    roots.append((os.path.join(pi_dir, "skills"), "~/.pi/agent/skills"))
    if cwd:
        for sub in (".pi/skills", ".agents/skills"):
            roots.append((os.path.join(cwd, sub), f"--cwd {sub}"))
    seen, out = set(), []
    for r, origin in roots:
        if r not in seen:
            seen.add(r)
            out.append((r, origin))
    return out


def find_skills(root):
    """SKILL.md files under root, at most three levels down."""
    out = []
    for depth in ("*", "*/*", "*/*/*"):
        out += glob.glob(os.path.join(root, depth, "SKILL.md"))
    if os.path.isfile(os.path.join(root, "SKILL.md")):
        out.append(os.path.join(root, "SKILL.md"))
    return sorted(set(out))


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
    for root, origin in roots:
        if not os.path.isdir(root):
            notes.append(f"skill root: not found ({root}, {origin})")
            continue
        for path in find_skills(root):
            fm = frontmatter(path)
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
    for key, v in walk_strings(settings):
        if not pathlike(v):
            continue
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
    for v in settings.get("packages") or []:
        if isinstance(v, str) and pathlike(v):
            dirs.append(os.path.join(resolve_setting(v, pi_dir), "agents"))
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
        owner = "local" if broken else owners.path(p)
        rows.append({"section": "extensions", "name": name, "kind": kind, "target": target, "broken": broken,
                     "owner": owner})
    return rows


def audit_leftovers(pi_dir, notes):
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
                rows.append({"section": "leftovers", "path": p, "mtime": mt, "owner": "local"})
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
            if first in (".", "..") or first in top:
                yield "path", tok.rstrip("/")
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
                ok = os.path.exists(os.path.join(here, ref)) or os.path.exists(os.path.join(root, ref))
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
        "leftovers": audit_leftovers(pi_dir, notes),
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
