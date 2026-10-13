#!/usr/bin/env python3
"""Find agent-written tooling that keeps coming back in pi session transcripts.

Read-only. Reports, ranked by distinct sessions: repeated command shapes, agent-written
scripts, repeated helper definitions, and calls that failed and were retried with the same
shape. A group marked [exists] names a script or skill that already exists, so the reader
can tell a missing tool from an ignored one. Output goes to stdout and can quote private
transcript content: do not redirect it into a repo.
usage: retro-sessions.py [--since YYYY-MM-DD|7d] [--min-sessions N] [--top N] [--json]

Sources (each optional; a missing one is reported, not fatal):
  HWORKS_PI_SESSIONS   pi session transcripts, **/*.jsonl (default ~/.pi/agent/sessions)
  HWORKS_TASKS_DIR     task dirs; files written there count as scratch scripts
                       (default ~/.local/state/agent-tasks)
  HWORKS_TOOL_DIRS     extra colon-separated dirs whose entry names count as existing tools,
                       besides this repo's scripts/ and skills/ (unset by default)
adapters/local/*.env, when present, is read first to set any of these; values already in the
environment win.

Command shapes: each bash command is split into simple commands (on |, &&, ||, ;, newlines)
after heredoc bodies, comments, quoted strings, $(...), and redirections are removed. A shape
is the command word (a script's name when an interpreter runs one, digits folded), up to two
subcommand words, and its uncommon flags. A flag is dropped when it is in PLAIN_FLAGS
(selection, verbosity, and output flags that never define a tool) or when at least half the
sessions running the same command and subcommand pass it (judged only once at least
COMMON_MIN_SESSIONS sessions run it), so
`go test -count=1 -race -run X -overlay=o.json` groups as `go test -overlay`. Shapes are
dropped as ordinary when the command word is an everyday shell, text, or git tool (EVERYDAY)
or a build, test, lint, or interpreter runner (RUNNERS) left with no flag and no script.
Both lists came from the most common shapes in two weeks of real sessions, where they filled
the top of the report and hid everything else.

Scripts: files written under /tmp, $TMPDIR, or a task dir by the write tool or a cat/tee
heredoc, plus inline interpreter code (python -c, node -e, heredocs to an interpreter,
mcpScript code), each at least MIN_SCRIPT_LINES non-blank lines. A fingerprint is the helpers
a script defines, the modules it imports, the methods it calls (receiver dropped, so renamed
variables still match), and literal names passed to calls. Features in more than a fifth of
scripts or in only one session are dropped. Scripts of one language whose fingerprints
overlap by at least 0.35, weighting rare features higher, are grouped.

Helpers: functions defined in those scripts, grouped by language and name, then split by
body similarity. Failed then retried: a call whose result was an error followed within three
calls by one of the same shape (bash: the command shapes; other tools: tool name, argument
names, and tool/server/action/agent/workflow values). Bash retries made only of ordinary
shapes are dropped.
"""
import argparse
import glob
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EVERYDAY = set("""
cd ls cat head tail less more echo printf pwd true false sleep wait test [ [[ export set unset
source . eval exit return local read shift trap type which command hash alias grep egrep rg ag
sed awk sort uniq wc cut tr tee xargs find fd file stat du df date env mkdir rmdir rm cp mv
ln touch chmod basename dirname realpath readlink nl diff cmp comm column jq yq fold paste
rev seq tac od xxd hexdump sha256sum shasum md5 md5sum mktemp kill pkill pgrep ps lsof id
whoami uname hostname open for while until if then else elif fi do done case esac in break
continue function time tree bat yes printenv git tar unzip zip gzip rsync base64 perl ruby
print import from def const let var await class
""".split())

RUNNERS = {
    "gh": {"pr", "run", "repo", "auth", "issue"},
    "go": {"test", "build", "vet", "mod", "list", "env", "version", "fmt", "doc", "generate", "work", "clean"},
    "gofmt": None, "goimports": None, "golangci-lint": None, "staticcheck": None, "shellcheck": None,
    "npm": None, "npx": None, "pnpm": None, "yarn": None, "bun": {"test", "install", "run", "x"},
    "node": None, "tsc": None, "eslint": None, "prettier": None, "vitest": None, "jest": None,
    "python": None, "python3": None, "pip": None, "pip3": None, "pytest": None, "uv": None, "ruff": None,
    "mypy": None, "cargo": None, "rustc": None, "make": None, "forge": None, "anvil": None, "cast": None,
    "bash": None, "sh": None, "zsh": None, "brew": None, "podman": None, "helm": None, "gofumpt": None,
    "terraform": None, "tsx": None, "curl": None, "wget": None, "tmux": None, "docker": None, "kubectl": None,
}
PLAIN_FLAGS = set("""
-v -vv -q -run -count -race -timeout -p -short -cover -tags -failfast -x -s -k -n -C -o -e -c
--verbose --quiet --version --help -h --json --jq --repo -R --limit --state --oneline --stat
--name-only --name-status --short --porcelain --all -a -b -f -m -r -u -l -t -i -L -S -X -H -d
-w --fix --silent --no-pager --format --pretty --abbrev-ref --watch --test --experimental-strip-types
""".split())
MIN_SCRIPT_LINES = 3
COMMON_MIN_SESSIONS = 20
INLINE_FLAGS = {"-c", "-e", "--eval", "-p", "--print", "--input-type"}
TEST_FILE = re.compile(r"(^test_|_test\.|\.test\.|\.spec\.)")
SCRIPT_EXT = re.compile(r"\.(py|sh|bash|js|mjs|cjs|ts|mts|rb|pl)$")
INTERPRETERS = {"python", "python3", "node", "bun", "deno", "ruby", "perl", "bash", "sh", "zsh", "osascript"}
SCRIPT_RUNNERS = INTERPRETERS | {"tsx", "ts-node", "npx", "uv", "pnpm", "bun", "deno", "yarn"}
LANG = {"python": "py", "python3": "py", "node": "js", "bun": "js", "deno": "js", "ruby": "rb",
        "perl": "pl", "bash": "sh", "sh": "sh", "zsh": "sh", "osascript": "applescript"}
EXT_LANG = {"py": "py", "sh": "sh", "bash": "sh", "js": "js", "mjs": "js", "cjs": "js", "ts": "js",
            "mts": "js", "rb": "rb", "pl": "pl"}

HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_][\w.-]*)\1")
INLINE = re.compile(r"\b(python3?|node|bun|deno|ruby|perl)\b((?:\s+--?[\w=-]+)*?)\s+(?:-c|-e|--eval|-p|--print)"
                    r"\s+('[^']*'|\"(?:\\.|[^\"\\])*\")")
QUOTED = re.compile(r"\$?'[^']*'|\"(?:\\.|[^\"\\])*\"|`[^`]*`")
SUBST = re.compile(r"\$\([^()]*\)")
REDIR = re.compile(r"\d*>&\d+|&>>?|\d*(?:>>?|<)(?!\()\s*\S+|<<<\s*\S+|(?<!<)<<-?\s*\S+")
SPLIT = re.compile(r"\|\||&&|[|;&\n(){}]")
ASSIGN = re.compile(r"^[A-Za-z_]\w*=")
PREFIX = {"env", "sudo", "nohup", "time", "exec", "command", "then", "do", "else", "elif", "if", "while",
          "until", "!", "builtin"}
BARE = re.compile(r"[a-z][a-z0-9_-]*")
FLAG = re.compile(r"--?[A-Za-z][\w-]*")


def fold(name):
    name = re.sub(r"[0-9a-f]{7,}", "H", name)
    return re.sub(r"\d+", "N", name)


def parse_since(s):
    m = re.fullmatch(r"(\d+)d", s)
    if m:
        return datetime.now(timezone.utc) - timedelta(days=int(m.group(1)))
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def to_dt(v):
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def load_env_files(root=ROOT):
    for path in sorted(glob.glob(os.path.join(root, "adapters", "local", "*.env"))):
        try:
            lines = open(path, errors="replace").read().splitlines()
        except OSError:
            continue
        for line in lines:
            m = re.match(r"\s*(?:export\s+)?([A-Za-z_]\w*)=(.*)$", line)
            if not m:
                continue
            val = m.group(2).strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
                val = val[1:-1]
            os.environ.setdefault(m.group(1), os.path.expanduser(os.path.expandvars(val)))


def sources():
    home = os.path.expanduser("~")
    tmp = os.environ.get("TMPDIR") or "/tmp"
    return {
        "sessions": os.environ.get("HWORKS_PI_SESSIONS") or os.path.join(home, ".pi/agent/sessions"),
        "tasks": os.environ.get("HWORKS_TASKS_DIR") or os.path.join(home, ".local/state/agent-tasks"),
        "tmp": tmp,
        "tool_dirs": [d for d in (os.environ.get("HWORKS_TOOL_DIRS") or "").split(":") if d],
    }


def read_session(path, since, notes):
    """Return the tool calls in one transcript after since, each with its error flag."""
    calls, by_id, bad = [], {}, 0
    try:
        f = open(path, errors="replace")
    except OSError as e:
        notes.append(f"{path}: {e}")
        return calls
    with f:
        for line in f:
            if '"toolCall"' not in line and '"toolResult"' not in line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                bad += 1
                continue
            m = e.get("message") if isinstance(e, dict) else None
            if not isinstance(m, dict):
                continue
            if m.get("role") == "assistant":
                dt = to_dt(e.get("timestamp") or m.get("timestamp"))
                if dt is None or dt < since:
                    continue
                for c in m.get("content") or []:
                    if isinstance(c, dict) and c.get("type") == "toolCall":
                        a = c.get("arguments")
                        call = {"name": c.get("name") or "?", "args": a if isinstance(a, dict) else {}, "error": False}
                        calls.append(call)
                        if c.get("id"):
                            by_id[c["id"]] = call
            elif m.get("role") == "toolResult" and m.get("isError") and m.get("toolCallId") in by_id:
                by_id[m["toolCallId"]]["error"] = True
    if bad:
        notes.append(f"{path}: skipped {bad} malformed line(s)")
    return calls


def split_heredocs(cmd):
    """Return cmd without heredoc bodies, and (header line, body) for each heredoc."""
    lines, out, docs, i, quote = cmd.split("\n"), [], [], 0, None
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        pending, j = [], 0
        while j < len(line):
            ch = line[j]
            if quote:
                if ch == "\\" and quote == '"':
                    j += 1
                elif ch == quote:
                    quote = None
            elif ch in "'\"`":
                quote = ch
            elif ch == "\\":
                j += 1
            elif ch == "#" and (j == 0 or line[j - 1].isspace()):
                break
            else:
                m = HEREDOC.match(line, j)
                if m:
                    pending.append(m.group(2))
                    j = m.end()
                    continue
            j += 1
        for delim in pending:
            body = []
            while i < len(lines) and lines[i].strip() != delim:
                body.append(lines[i])
                i += 1
            i += 1
            docs.append((line, "\n".join(body)))
    return "\n".join(out), docs


def drop_comments(cmd):
    out = []
    for line in cmd.split("\n"):
        m = re.search(r"(^|\s)#", line)
        if m and line[:m.start()].count("'") % 2 == 0 and line[:m.start()].count('"') % 2 == 0:
            line = line[:m.start()]
        out.append(line)
    return "\n".join(out)


def strip_shell(cmd):
    s = QUOTED.sub(" Q ", drop_comments(cmd))
    for _ in range(4):
        s2 = SUBST.sub(" Q ", s)
        if s2 == s:
            break
        s = s2
    return REDIR.sub(" ", s)


def segments(cmd):
    """Yield (cmd word, subcommands, script names, flags) for each simple command in shell text."""
    for seg in SPLIT.split(strip_shell(cmd)):
        toks = seg.split()
        while toks and (ASSIGN.match(toks[0]) or toks[0] in PREFIX):
            toks.pop(0)
        if toks and toks[0] == "timeout":
            toks = toks[1:]
            while toks and (toks[0].startswith("-") or re.fullmatch(r"[\d.]+[smh]?", toks[0])):
                toks.pop(0)
        if not toks:
            continue
        word = os.path.basename(toks[0])
        if not (re.fullmatch(r"[A-Za-z_\[][\w+\[-]*(\.\d+)*", word) or SCRIPT_EXT.search(word)) or word == "Q":
            continue
        if SCRIPT_EXT.search(word):
            word = fold(word)
        subs, scripts, flags, positional = [], [], set(), False
        for t in toks[1:]:
            if t.startswith("-") and len(t) > 1:
                fl = t.split("=", 1)[0]
                if FLAG.fullmatch(fl):
                    flags.add(fl)
                continue
            if not positional and not flags and len(subs) < 2 and BARE.fullmatch(t) and word not in EVERYDAY:
                subs.append(t)
                continue
            positional = True
            if (word in SCRIPT_RUNNERS and SCRIPT_EXT.search(t) and not t.startswith("Q") and "*" not in t
                    and not TEST_FILE.search(os.path.basename(t))):
                scripts.append(fold(os.path.basename(t)))
        if scripts and word in INTERPRETERS:
            word, subs, scripts = scripts[0], [], []
        yield word, tuple(subs), tuple(scripts[:1]), frozenset(flags)


def excerpt(cmd, word, subs):
    """The part of cmd where the shape's command starts, so samples show the command itself."""
    pat = r"(?<![\w.-])" + re.escape(word) + "".join(r"\s+" + re.escape(x) for x in subs[:1])
    m = re.search(pat, cmd)
    return cmd[m.start():] if m else cmd


def is_scratch(path, src):
    if not path:
        return False
    p = os.path.expanduser(os.path.expandvars(path.strip("'\"")))
    roots = ["/tmp/", "/private/tmp/", "/var/folders/", "/private/var/folders/", src["tmp"].rstrip("/") + "/",
             src["tasks"].rstrip("/") + "/"]
    return any(p.startswith(r) for r in roots)


def heredoc_script(header, body, src):
    """Classify a heredoc: a scratch file write or interpreter input; None for anything else."""
    head = strip_shell(header)
    m = re.search(r"\b(cat|tee)\b[^|;&]*?(?:>>?\s*|\btee\s+(?:-a\s+)?)([^\s<>|;&]+)", header)
    if m and is_scratch(m.group(2), src):
        ext = os.path.splitext(m.group(2).strip("'\""))[1].lstrip(".")
        lang = EXT_LANG.get(ext) or shebang_lang(body)
        if lang:
            return {"kind": "file", "path": m.group(2), "lang": lang, "code": body}
        return None
    m = re.search(r"(?:^|[\s;&|(])((?:\S*/)?(python3?|node|bun|deno|ruby|perl|bash|sh|zsh|osascript))\b[^|;&]*<<", head)
    if m:
        return {"kind": "inline", "path": None, "lang": LANG[m.group(2)], "code": body}
    return None


def shebang_lang(code):
    m = re.match(r"#!\S*?(?:env\s+)?(\w+)", code)
    return LANG.get(m.group(1)) if m else None


def call_scripts(call, src):
    """Scripts written or run inline by one tool call."""
    name, a = call["name"], call["args"]
    out = []
    if name == "write" and is_scratch(a.get("path"), src) and isinstance(a.get("content"), str):
        ext = os.path.splitext(a["path"])[1].lstrip(".")
        lang = EXT_LANG.get(ext) or shebang_lang(a["content"])
        if lang:
            out.append({"kind": "file", "path": a["path"], "lang": lang, "code": a["content"]})
    elif name == "mcpScript" and isinstance(a.get("code"), str):
        out.append({"kind": "inline", "path": None, "lang": "js", "code": a["code"]})
    elif name == "bash" and isinstance(a.get("command"), str):
        rest, docs = split_heredocs(a["command"])
        for header, body in docs:
            s = heredoc_script(header, body, src)
            if s:
                out.append(s)
        for m in INLINE.finditer(rest):
            q = m.group(3)
            code = q[1:-1].replace('\\"', '"') if q[0] == '"' else q[1:-1]
            out.append({"kind": "inline", "path": None, "lang": LANG[m.group(1)], "code": code})
    return out


DEF_PATTERNS = [
    re.compile(r"^[ \t]*(?:async\s+)?def\s+(\w+)", re.M),
    re.compile(r"\b(?:async\s+)?function\s*\*?\s*(\w+)\s*\("),
    re.compile(r"\b(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^()]*\)|\w+)\s*=>"),
    re.compile(r"\b(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?function\b"),
    re.compile(r"^[ \t]*(\w+)\s*=\s*lambda\b", re.M),
    re.compile(r"^[ \t]*(?:function\s+)?([A-Za-z_][\w-]*)\s*\(\)\s*\{", re.M),
]
IMPORTS = [
    re.compile(r"^\s*import\s+([\w.]+)", re.M),
    re.compile(r"^\s*from\s+([\w.]+)\s+import", re.M),
    re.compile(r"\bfrom\s+['\"]([^'\"]+)['\"]"),
    re.compile(r"\b(?:require|import)\(\s*['\"]([^'\"]+)['\"]"),
]
DOTTED = re.compile(r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\s*\(")
LITERAL_ARG = re.compile(r"\b(\w+)\(\s*['\"]([\w.:/@-]{3,60})['\"]")
IDENT = re.compile(r"[A-Za-z_]\w*|'[^'\n]{1,60}'|\"[^\"\n]{1,60}\"")
NOISE = {"self", "return", "const", "let", "var", "await", "async", "function", "def", "if", "else", "for",
         "in", "of", "true", "false", "null", "None", "True", "False", "new", "this", "import", "from"}


def defs(code):
    """(name, start offset) for each function or helper defined in code."""
    found = {}
    for pat in DEF_PATTERNS:
        for m in pat.finditer(code):
            found.setdefault(m.group(1), m.start())
    return sorted(found.items(), key=lambda kv: kv[1])


def def_body(code, start):
    lines = code[start:].split("\n")
    first = lines[0]
    indent = len(first) - len(first.lstrip())
    body = [first]
    for line in lines[1:15]:
        if line.strip() and len(line) - len(line.lstrip()) <= indent and not line.lstrip().startswith(("}", ")")):
            break
        body.append(line)
    return "\n".join(body)


def module_name(m):
    if not m.startswith((".", "/", "~")):
        return m
    parts = [x for x in m.split("/") if x]
    name = os.path.splitext(parts[-1])[0] if parts else m
    if name == "index" and len(parts) > 1:
        name = parts[-2]
    return fold(name)


def features(script):
    code, lang = script["code"], script["lang"]
    f = set()
    for name, _ in defs(code):
        f.add(f"def {name}")
    for pat in IMPORTS:
        f.update(f"import {module_name(m)}" for m in pat.findall(code))
    for m in DOTTED.findall(code):
        f.add("." + m.rsplit(".", 1)[1] + "()")
    for fn, lit in LITERAL_ARG.findall(code):
        f.add(f'{fn}("{fold(lit)}")')
    if lang == "sh":
        for word, subs, scripts, _ in segments(code):
            if word not in EVERYDAY:
                f.add("$ " + " ".join((word,) + subs + scripts))
    return f


def body_tokens(body, name):
    return frozenset(t for t in IDENT.findall(body) if t != name and t not in NOISE)


def jaccard(a, b, weight=None):
    if weight is None:
        return len(a & b) / len(a | b) if a or b else 1.0
    union = sum(weight[x] for x in a | b)
    return sum(weight[x] for x in a & b) / union if union else 1.0


class UnionFind:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def cluster(sets, threshold=0.5, max_df=400, weight=None):
    """Group indexes of sets whose Jaccard similarity reaches threshold; candidates share a rare item."""
    uf, index = UnionFind(len(sets)), defaultdict(list)
    for i, s in enumerate(sets):
        for x in s:
            index[x].append(i)
    seen = set()
    for i, s in enumerate(sets):
        rare = sorted((x for x in s if len(index[x]) <= max_df), key=lambda x: len(index[x]))[:3]
        for x in rare:
            for j in index[x]:
                if j <= i or (i, j) in seen:
                    continue
                seen.add((i, j))
                if uf.find(i) != uf.find(j) and jaccard(s, sets[j], weight) >= threshold:
                    uf.union(i, j)
    groups = defaultdict(list)
    for i in range(len(sets)):
        groups[uf.find(i)].append(i)
    return list(groups.values())


def short(text, n=160):
    return re.sub(r"\s+", " ", text or "").strip()[:n]


def existing_names(src, root=ROOT):
    """Entry names in scripts/, skills/, and the extra tool dirs, plus files in each skill's scripts/."""
    names = set()
    for d in [os.path.join(root, "scripts"), os.path.join(root, "skills")] + src["tool_dirs"]:
        d = os.path.expanduser(d)
        paths = glob.glob(os.path.join(d, "*")) + glob.glob(os.path.join(d, "*", "scripts", "*"))
        for path in paths:
            e = os.path.basename(path)
            if not e.startswith((".", "_", "test_")) and e != "testdata":
                names.add(e)
    return names


def tool_hits(text, names):
    return sorted({t for t in re.split(r"[^\w.-]+", text) if t in names})


class Groups:
    def __init__(self):
        self.calls = Counter()
        self.sessions = defaultdict(set)
        self.samples = {}

    def add(self, key, session, sample):
        self.calls[key] += 1
        self.sessions[key].add(session)
        if key not in self.samples or (len(self.sessions[key]) == 1 and len(sample) < len(self.samples[key])):
            self.samples[key] = sample


def ranked(section, groups, label, min_sessions, top, names, root):
    rows = []
    for key, sess in groups.sessions.items():
        if len(sess) < min_sessions:
            continue
        text = label(key)
        rows.append({"section": section, "shape": text, "sessions": len(sess), "calls": groups.calls[key],
                     "examples": [os.path.relpath(p, root) for p in sorted(sess)[:3]],
                     "sample": short(groups.samples[key]), "existing": tool_hits(text, names)})
    rows.sort(key=lambda r: (-r["sessions"], -r["calls"], r["shape"]))
    return rows[:top]


def ordinary(word, subs, scripts, flags):
    """flags here are the shape's flags: uncommon for this command and not in PLAIN_FLAGS."""
    if word in EVERYDAY:
        return True
    if word not in RUNNERS or scripts:
        return False
    if word in INTERPRETERS and flags & INLINE_FLAGS:
        return True
    allowed = RUNNERS[word]
    if allowed is not None and (not subs or subs[0] not in allowed):
        return False
    return not flags


def analyze(src, since, min_sessions=3, top=15, root=ROOT):
    notes = []
    sroot = src["sessions"]
    if not os.path.isdir(sroot):
        notes.append(f"pi sessions: not found ({sroot})")
        return {}, notes
    cutoff = since.timestamp()
    sessions = {}
    for p in sorted(glob.glob(os.path.join(sroot, "**", "*.jsonl"), recursive=True)):
        try:
            if os.path.getmtime(p) < cutoff:
                continue
        except OSError:
            continue
        calls = read_session(p, since, notes)
        if calls:
            sessions[p] = calls

    # Pass 1: how often each flag goes with each command, by session.
    base_sessions, flag_sessions = defaultdict(set), defaultdict(set)
    parsed = {}
    for p, calls in sessions.items():
        for i, c in enumerate(calls):
            if c["name"] != "bash" or not isinstance(c["args"].get("command"), str):
                continue
            rest, _ = split_heredocs(c["args"]["command"])
            segs = list(segments(rest))
            parsed[(p, i)] = segs
            for word, subs, scripts, flags in segs:
                base = (word, subs, scripts)
                base_sessions[base].add(p)
                for fl in flags:
                    flag_sessions[(base, fl)].add(p)

    def key_of(seg):
        word, subs, scripts, flags = seg
        base = (word, subs, scripts)
        n = len(base_sessions[base])
        rare = frozenset(fl for fl in flags if fl not in PLAIN_FLAGS
                         and (n < COMMON_MIN_SESSIONS or len(flag_sessions[(base, fl)]) * 2 < n))
        return base, rare

    def shape_text(key):
        (word, subs, scripts), rare = key
        return " ".join((word,) + subs + scripts + tuple(sorted(rare)))

    def call_shape(p, i, c):
        if c["name"] == "bash":
            keys = [key_of(s) for s in parsed.get((p, i), [])]
            if all(ordinary(*k[0], k[1]) for k in keys):
                return None
            return "bash: " + " ; ".join(shape_text(k) for k in keys)
        a = c["args"]
        parts = [c["name"]] + sorted(a)
        for k in ("tool", "server", "action", "agent", "workflow"):
            if isinstance(a.get(k), str) and len(a[k]) < 60:
                parts.append(f"{k}={a[k]}")
        return " ".join(parts)

    shapes, scripts_g, helpers_raw, retries = Groups(), [], defaultdict(list), Groups()
    for p, calls in sessions.items():
        for i, c in enumerate(calls):
            for seg in parsed.get((p, i), []):
                key = key_of(seg)
                if not ordinary(*key[0], key[1]):
                    shapes.add(key, p, excerpt(c["args"]["command"], key[0][0], key[0][1]))
            for s in call_scripts(c, src):
                if len([x for x in s["code"].splitlines() if x.strip()]) >= MIN_SCRIPT_LINES:
                    s["session"] = p
                    scripts_g.append(s)
            if c["error"]:
                shape = call_shape(p, i, c)
                if shape and any(call_shape(p, j, calls[j]) == shape for j in range(i + 1, min(i + 4, len(calls)))):
                    retries.add(shape, p, json.dumps(c["args"])[:400])

    feats = [features(s) for s in scripts_g]
    df = Counter(x for f in feats for x in f)
    fsess = defaultdict(set)
    for s, f in zip(scripts_g, feats):
        for x in f:
            fsess[x].add(s["session"])
    cap = max(5, len(scripts_g) // 5)
    kept = [frozenset(x for x in f if df[x] <= cap and len(fsess[x]) >= 2) for f in feats]
    by_lang = defaultdict(list)
    for i, s in enumerate(scripts_g):
        if kept[i]:
            by_lang[s["lang"]].append(i)
    script_groups = Groups()
    idf = {x: math.log(len(scripts_g) / n) for x, n in df.items()}
    for lang, idx in by_lang.items():
        for members in cluster([kept[i] for i in idx], threshold=0.35, weight=idf):
            members = [idx[m] for m in members]
            common = Counter(x for m in members for x in kept[m])
            top_f = sorted((x for x, n in common.items() if n * 2 >= len(members)),
                           key=lambda x: (-idf[x], x))[:6]
            if not top_f:
                top_f = [x for x, _ in common.most_common(3)]
            label = f"[{lang}] " + ", ".join(top_f)
            for m in members:
                s = scripts_g[m]
                script_groups.add(label, s["session"], (f"{s['path']}: " if s["path"] else "") + s["code"])

        for i in idx:
            code = scripts_g[i]["code"]
            for name, start in defs(code):
                body = def_body(code, start)
                helpers_raw[(lang, name)].append((body_tokens(body, name), scripts_g[i]["session"], body))

    helper_groups = Groups()
    for (lang, name), items in helpers_raw.items():
        if len({sess for _, sess, _ in items}) < min_sessions:
            continue
        clusters = [(len({items[m][1] for m in c}), c) for c in cluster([t for t, _, _ in items], max_df=10**9)]
        clusters.sort(key=lambda x: (-x[0], x[1][0]))
        for n, (count, members) in enumerate(clusters):
            if count < min_sessions:
                continue
            label = f"[{lang}] {name}" + (f" #{n + 1}" if n else "")
            for m in members:
                helper_groups.add(label, items[m][1], items[m][2])

    names = existing_names(src, root)
    report = {
        "command shapes": ranked("command shapes", shapes, shape_text, min_sessions, top, names, sroot),
        "agent-written scripts": ranked("agent-written scripts", script_groups, str, min_sessions, top, names, sroot),
        "repeated helpers": ranked("repeated helpers", helper_groups, str, min_sessions, top, names, sroot),
        "failed then retried": ranked("failed then retried", retries, str, min_sessions, top, names, sroot),
    }
    stats = {"sessions": len(sessions), "calls": sum(len(c) for c in sessions.values()), "scripts": len(scripts_g)}
    return {"stats": stats, **report}, notes


def main(argv=None):
    load_env_files()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 usage=argparse.SUPPRESS)
    ap.add_argument("--since", default="14d", help="YYYY-MM-DD or Nd (default 14d)")
    ap.add_argument("--min-sessions", type=int, default=3, help="hide groups seen in fewer sessions (default 3)")
    ap.add_argument("--top", type=int, default=15, help="groups per section (default 15)")
    ap.add_argument("--json", action="store_true", help="one JSON object per group")
    args = ap.parse_args(argv)
    since = parse_since(args.since)
    report, notes = analyze(sources(), since, args.min_sessions, args.top)
    if args.json:
        for section, rows in report.items():
            if section != "stats":
                for r in rows:
                    print(json.dumps(r))
    elif report:
        st = report["stats"]
        print(f"Agent tooling since {since.date()}: {st['sessions']} sessions, {st['calls']} tool calls, "
              f"{st['scripts']} scripts")
        for section, rows in report.items():
            if section == "stats":
                continue
            print(f"\n== {section} ==")
            if not rows:
                print("  (none)")
                continue
            print(f"{'sess':>5} {'calls':>5}  shape")
            for r in rows:
                flag = f"  [exists: {', '.join(r['existing'])}]" if r["existing"] else ""
                print(f"{r['sessions']:>5} {r['calls']:>5}  {r['shape']}{flag}")
                print(f"             e.g. {', '.join(r['examples'])}")
                print(f"             sample: {r['sample']}")
    for n in notes:
        print(f"note: {n}", file=sys.stderr)


if __name__ == "__main__":
    main()
