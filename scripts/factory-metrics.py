#!/usr/bin/env python3
"""Read-only daily factory metrics. JSON stdout, diagnostics stderr; keep output private.

Usage: factory-metrics.py [--since YYYY-MM-DD|Nd] [--until YYYY-MM-DD]
                         [--tasks FILE] [--no-fetch] [--cache DIR]
Dates are inclusive, default 33 calendar days ending today in HWORKS_FM_TZ.
Configuration: adapters/local/factory-metrics.env is sourced as shell, including
linked-worktree fallback. Existing environment values win. Reporter *.env files
are also loaded by the existing reporter loader.
  HWORKS_FM_TZ: IANA timezone, default system local timezone (including DST).
  HWORKS_FM_REPOS: JSON list of {path, class: product|factory, exclude: [dirs]}.
    Uses local origin/HEAD branch, then main/master, remote origin/HEAD, or HEAD.
    Factory counts all first-parent commits; product counts fetched PR mergeCommit
    OIDs. No git fetch is run.
  HWORKS_FM_LOGINS: comma-separated operator logins; filters fetched PR authors.
    Empty accepts every transcript-linked PR, including authors unavailable in gh.
  HWORKS_FM_SESSION_RULES: JSON ordered [{pattern: regex, class: product|factory|
    home|automation}]; matches cwd; first wins. Default class product, absent cwd home.
  HWORKS_PI_SESSIONS, HWORKS_PR_TOOLS, HWORKS_GH, HWORKS_OPERATOR_SKIP,
  HWORKS_INJECTED_PREFIX, HWORKS_REDACT, HWORKS_TASKS_DIR, HWORKS_BLOCKERS_LOG,
  HWORKS_SUBAGENT_RUNS, HWORKS_RUN_HISTORY, HWORKS_HARNESS_AUDIT_LOG:
    existing reporter variables, with their existing defaults and definitions.
Cache defaults to ${XDG_CACHE_HOME:-$HOME/.cache}/hworks/factory-metrics.
Closed/merged PR payloads are immutable cache entries; open PRs always refetch.
--no-fetch uses cached terminal PRs only. PR discovery uses kaizen-prs transcript
links, not an organization-wide search. Unlinked PRs/fixes are not observable.

Output fields:
 generated: ISO generation timestamp; tz: configured zone; start/end: inclusive dates.
 days: one row per date, with these fields (null means source unavailable):
 opened/merged/abandoned: PRs by creation/merge/closed-unmerged local date.
 pr_landed/pr_fixed/pr_holding: merged cohorts by merge date. After 7 days a PR
   lands unless reverted or explicitly named by a later fix: PR in the same repo
   within 7 days. A cue and #N or URL must be within 40 characters, either order.
   Reverts may also name the original title. Unnamed fixes go undetected.
 spend/spend_product/spend_factory/spend_home/spend_auto: provider cost.total by
   turn date, all pi main and child sessions; artifact copies excluded. Children
   inherit their parent's class. cw: cost.cacheWrite. longc: entire turn cost when
   input+cacheRead+cacheWrite >150000 tokens. linked: spend in PR-linked root trees.
 ops/sig_correction/sig_abort/sig_approval/sig_status-check: operator-signals
   messages and signals; main pi sessions only, INCLUDING first prompts (reporter
   definition, unlike prototype). No prompt text is emitted.
 pr_cost: direct costs of merged PRs, root-tree window spend split equally over
   linked PRs; abandoned_spend: same for closed-unmerged PRs by close day.
 open_prs/open_age: end-of-day open PR count and median age in days.
 human_reviews: submitted non-bot reviews not by configured operator logins.
 htm: hours-to-merge samples by merge day.
 tasks_done/tasks_landed/tasks_fixed/tasks_nopr/tasks_holding/tasks_canceled:
   completed/canceled task counts by event date; outcomes depend on ALL linked PRs.
   queue/wip: created but not ended at day end, unstarted/started. Tasks input is
   a JSON list of {id,created,started,completed,canceled,status,project}; ISO or null.
 friction: caught-by counts normalized to operator/reviewer/test/ci/self.
 fr_rows/fr_inschema: total friction rows/exact allowed caught-by rows.
 guard: autonomy and harness blocks; oq/oq_kept/oq_reversed: decision rows/verdicts.
 subagent_fail/babysitter_fail: failed, timed_out, needs_attention run events;
   babysitter role separated. Zero-duration failures count as runs_never_started.
 factory_commits: first-parent commits in configured factory checkouts.
 added/deleted/churn21/churn7/moved/revisit_changes/changes: summed git churn;
   see factory-churn.py for blame definitions and exclusions. No overlap matching.
 cloud/revcost/effective/automations: null, reserved for extension collectors.
 findings table: counts by run from task-dir hansei JSON and kaizen markdown.
 tables: prs (gh payload, landed outcome and linked task ids), repo_cost (direct
   median/p90/n), prs_per_task (completed linked-task counts), token_report (existing
   kaizen-tokens window sections), time (kaizen-prs main time buckets in seconds),
   churn (per checkout daily counts, totals, excluded paths).
 coverage: sources read, counts, failures, missing_sources, dropped_pr_links,
   missing_prs and unavailable_pr_hosts. PR series cover successfully read PRs;
   entirely unavailable hosts are recorded separately, not reported as zero.
   Failed git sources null aggregate churn fields; a failed factory checkout also
   nulls factory_commits. Successful per-checkout tables remain available.
"""
import argparse
import glob
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import statistics as st
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), HERE / (name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


kp = load('kaizen-prs')
kt = kp.kt
ks = kp.ks
ops = load('operator-signals')
churn = load('factory-churn')


def environment():
    path = Path(ks.local_dir()) / 'factory-metrics.env'
    if path.is_file():
        p = subprocess.run(['bash', '-c', 'set -ae; . "$1" >&2; env -0', 'bash', str(path)],
                           capture_output=True, check=True)
        env = dict(x.decode().split('=', 1) for x in p.stdout.split(b'\0') if b'=' in x)
        for k, v in env.items():
            os.environ.setdefault(k, v)
    ks.load_env_files()


def zone():
    name = os.environ.get('HWORKS_FM_TZ') or os.environ.get('TZ')
    if name:
        return ZoneInfo(name)
    local = Path('/etc/localtime').resolve()
    if 'zoneinfo/' in str(local):
        return ZoneInfo(str(local).split('zoneinfo/', 1)[1])
    return datetime.now().astimezone().tzinfo


def day(ts, tz):
    dt = ks.to_dt(ts)
    return dt.astimezone(tz).date().isoformat() if dt else None


def validate_pr(data):
    if not isinstance(data, dict) or data.get('state') not in ('MERGED', 'CLOSED', 'OPEN'):
        raise ValueError('invalid PR state')
    if not ks.to_dt(data.get('createdAt')):
        raise ValueError('PR needs a creation timestamp')
    for field in ('mergedAt', 'closedAt'):
        if data.get(field) is not None and not ks.to_dt(data[field]):
            raise ValueError('invalid PR ' + field)
    if data['state'] == 'MERGED' and not data.get('mergedAt'):
        raise ValueError('merged PR needs mergedAt')
    if data['state'] == 'CLOSED' and not data.get('closedAt'):
        raise ValueError('closed PR needs closedAt')
    for field in ('commits', 'reviews', 'comments', 'files', 'statusCheckRollup'):
        if data.get(field) is not None and (not isinstance(data[field], list) or any(not isinstance(x, dict) for x in data[field])):
            raise ValueError('invalid PR ' + field)
    if os.environ.get('HWORKS_FM_LOGINS') and not kp.login(data):
        raise ValueError('PR author unavailable')


def read_pr(url, cache, no_fetch, coverage):
    path = cache / (hashlib.sha256(url.encode()).hexdigest() + '.json')
    try:
        data = json.loads(path.read_text())
        validate_pr(data)
        if data['state'] not in ('MERGED', 'CLOSED'):
            raise ValueError('invalid terminal PR cache')
        coverage['counts']['cache_hits'] += 1
        return data
    except (OSError, ValueError) as e:
        if path.exists():
            coverage['failures'].append(f'cache {path}: {e}')
    if no_fetch:
        coverage['missing_prs'].append(dict(url=url, error='uncached PR'))
        return None
    try:
        p = subprocess.run([os.environ.get('HWORKS_GH', 'gh'), 'pr', 'view', url, '--json',
                            kp.FIELDS + ',url,body,headRefName,mergeCommit'],
                           capture_output=True, text=True, timeout=kp.GH_TIMEOUT)
        if p.returncode:
            error = p.stderr.strip()
            if re.search(r'Could not resolve to (?:a Repository|a PullRequest)|could not find (?:repository|pull request)|(?:repository|pull request).*not found', error, re.I):
                coverage['dropped_pr_links'].append(dict(url=url, error=error))
                return None
            raise ValueError(p.stderr.strip().splitlines()[0] if p.stderr.strip() else f'exit {p.returncode}')
        data = json.loads(p.stdout)
        validate_pr(data)
        coverage['counts']['fetched'] += 1
        if data['state'] != 'OPEN':
            try:
                cache.mkdir(parents=True, exist_ok=True)
                temp = path.with_suffix(f'.{os.getpid()}.tmp')
                temp.write_text(json.dumps(data))
                temp.replace(path)
            except OSError as e:
                coverage['failures'].append(f'cache write: {e}')
        return data
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        coverage['missing_prs'].append(dict(url=url, error=str(e)))
        return None


def landed(prs, end):
    result = {}
    for url, p in prs.items():
        t0 = ks.to_dt(p.get('mergedAt'))
        if not t0:
            continue
        result[url] = 'pr_landed' if t0 + timedelta(days=7) <= end else 'pr_holding'
        num = url.rsplit('/', 1)[-1]
        ref = rf'(?:#{re.escape(num)}\b|{re.escape(url)}(?!\d))'
        cue = r'\b(?:fix(?:es|ed)?|follow[- ]?up(?: to| on)?|regress\w*(?: from| in)?|broken by|revert\w*|corrects?|amends?)\b'
        for other, q in prs.items():
            t1 = ks.to_dt(q.get('mergedAt'))
            if other == url or other.rsplit('/pull/', 1)[0] != url.rsplit('/pull/', 1)[0] or not t1 or not t0 < t1 <= t0 + timedelta(days=7) or t1 >= end:
                continue
            text = q.get('title', '') + '\n' + (q.get('body') or '')
            explicit = re.search(cue + r'.{0,40}?' + ref + '|' + ref + r'.{0,40}?' + cue, text, re.I | re.S)
            revert = re.match(r'^revert\b', q.get('title', ''), re.I)
            if (re.match(r'^fix(?:\([^)]*\))?!?:', q.get('title', ''), re.I) and explicit) or (revert and (explicit or p.get('title', '').lower() in text.lower())):
                result[url] = 'pr_fixed'
                break
    return result


SESSION = 'spend spend_product spend_factory spend_home spend_auto cw longc linked ops sig_correction sig_abort sig_approval sig_status-check'.split()
PR = 'opened merged abandoned pr_landed pr_fixed pr_holding pr_cost abandoned_spend open_prs open_age human_reviews htm'.split()
TASK = 'tasks_done tasks_landed tasks_fixed tasks_nopr tasks_holding tasks_canceled queue wip'.split()
BLOCK = 'friction fr_rows fr_inschema guard oq oq_kept oq_reversed subagent_fail babysitter_fail runs_never_started'.split()
GIT = 'factory_commits added deleted churn21 churn7 moved revisit_changes changes'.split()


def initialize(days, fields):
    for d in days.values():
        for k in fields:
            d[k] = {} if k == 'friction' else [] if k in ('pr_cost', 'htm') else 0


def tasks_read(path):
    data = json.loads(Path(path).read_text())
    if not isinstance(data, list):
        raise ValueError('tasks must be a list')
    for row in data:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id']:
            raise ValueError('each task needs a nonempty string id')
        for k in ('created', 'started', 'completed', 'canceled'):
            if row.get(k) is not None and not ks.to_dt(row[k]):
                raise ValueError(f'invalid task {k}')
    return data


def collect(start, end, tz, tasks_path, no_fetch, cache):
    since = datetime.combine(start, time(), tz)
    until = datetime.combine(end + timedelta(days=1), time(), tz)
    days = {}
    for i in range((end - start).days + 1):
        key = (start + timedelta(days=i)).isoformat()
        days[key] = dict.fromkeys(SESSION + PR + TASK + BLOCK + GIT + ['cloud', 'revcost', 'effective', 'automations', 'kaizen'])
        days[key]['date'] = key
    cov = dict(sources=[], counts=Counter(), failures=[], missing_sources=[], dropped_pr_links=[], missing_prs=[], unavailable_pr_hosts=[])
    tables = dict(prs=[], repo_cost={}, prs_per_task=[], token_report={}, time={}, churn={})
    notes, sessions, links = [], {}, defaultdict(set)
    root = ks.sources()['sessions']
    rules = json.loads(os.environ.get('HWORKS_FM_SESSION_RULES', '[]'))
    if not isinstance(rules, list) or any(not isinstance(r, dict) or not isinstance(r.get('pattern'), str) for r in rules):
        raise ValueError('session rules must be a list of pattern/class objects')
    for r in rules:
        if r.get('class') not in ('product', 'factory', 'home', 'automation'):
            raise ValueError('invalid session class')
        re.compile(r['pattern'])
    if os.path.isdir(root):
        cov['sources'].append('pi')
        initialize(days, SESSION)
        for path in sorted(glob.glob(os.path.join(root, '**', '*.jsonl'), recursive=True)):
            if '/subagent-artifacts/' in path:
                continue
            s = kt.read_session(path, since, notes)
            s['kind'] = 'child' if ops.SUBAGENT.search(path) else 'main'
            s['class'] = next((r['class'] for r in rules if re.search(r['pattern'], s['cwd'] or '')), 'product' if s['cwd'] else 'home')
            s['pr'] = kp.read_session(path, datetime(1970, 1, 1, tzinfo=timezone.utc), os.environ.get('HWORKS_PR_TOOLS', '').split(','), notes)
            s['pr']['links'] = {k: ts for k, ts in s['pr']['links'].items() if ts < until}
            sessions[path] = s
        # Child paths nest under the parent's transcript stem.
        parents = {str(Path(p).with_suffix('')): p for p, s in sessions.items() if s['kind'] == 'main'}
        for path, s in sessions.items():
            parent = next((p for stem, p in parents.items() if path.startswith(stem + '/')), path)
            s['root'] = parent
            if parent != path:
                s['class'] = sessions[parent]['class']
            for url, role in s['pr']['links']:
                links[parent].add(url)
        total_time = {}
        for path, s in sessions.items():
            for t in s['turns']:
                if not t['dt'] or not since <= t['dt'] < until:
                    continue
                d = days[day(t['dt'].isoformat(), tz)]
                cost = t['cost'].get('total') or 0
                d['spend'] += cost
                d['spend_' + ('auto' if s['class'] == 'automation' else s['class'])] += cost
                d['cw'] += t['cost'].get('cacheWrite') or 0
                d['longc'] += cost if t['input'] + t['cr'] + t['cw'] > 150000 else 0
            if s['kind'] == 'main':
                _, _, messages = ops.read_session(path, since, ops.sources(), notes)
                for op in messages:
                    key = day(op['ts'], tz)
                    if key in days:
                        days[key]['ops'] += 1
                        for name, fn in ops.SIGNALS.items():
                            days[key]['sig_' + name] += bool(fn(op))
                kp.add_split(total_time, kp.time_split([m for m in s['pr']['messages'] if since <= m['ts'] < until], ops.sources()['skip']))
        tables['time'] = {k: total_time.get(k, 0) for k in ('model', 'tool', 'human', 'harness')}
        # Existing reporter owns cache rewrite and review loop definitions.
        report, more = kt.analyze(ks.sources(), since, min_sessions=1, top=10000, until=until)
        tables['token_report'] = {k: report.get(k, []) for k in ('loop rounds', 'roles', 'cache writes')}
        notes.extend(more)
        cov['counts']['sessions'] = len(sessions)
    else:
        cov['missing_sources'].append('pi sessions: ' + root)
    urls = sorted({u for us in links.values() for u in us})
    # Include cached terminal PRs previously discovered, even when their transcript ages out.
    for path in cache.glob('*.json'):
        try:
            cached = json.loads(path.read_text())
            if kp.PR_URL.fullmatch(cached.get('url', '')):
                urls.append(cached['url'])
        except (OSError, ValueError, AttributeError):
            cov['failures'].append(f'invalid cache: {path}')
    urls = sorted(set(urls))
    prs, read_hosts = {}, set()
    logins = {x.strip().lower() for x in os.environ.get('HWORKS_FM_LOGINS', '').split(',') if x.strip()}
    for url in urls:
        p = read_pr(url, cache, no_fetch, cov)
        if p is not None:
            read_hosts.add(kp.host_of(url))
        if p is not None and (not logins or (kp.login(p) or '').lower() in logins):
            p['url'] = url
            prs[url] = p
    cov['counts']['prs_found'] = len(urls)
    cov['counts']['prs_read'] = len(prs)
    complete = os.path.isdir(root) and not cov['missing_prs']
    dropped = {r['url'] for r in cov['dropped_pr_links']}
    for host in sorted({kp.host_of(u) for u in urls if u not in dropped}):
        failures = [r for r in cov['missing_prs'] if kp.host_of(r['url']) == host]
        if failures and host not in read_hosts:
            cov['unavailable_pr_hosts'].append(host)
    pr_available = os.path.isdir(root) and (bool(read_hosts) or not cov['missing_prs'])
    for us in links.values():
        us.difference_update(dropped)
    if os.path.isdir(root):
        for d in days.values():
            d['linked'] = 0
        for s in sessions.values():
            if links[s['root']]:
                for t in s['turns']:
                    if t['dt'] and since <= t['dt'] < until:
                        days[day(t['dt'].isoformat(), tz)]['linked'] += t['cost'].get('total') or 0
    states = landed(prs, until)
    costs = Counter()
    for path, s in sessions.items():
        us = links[s['root']]
        if us:
            cost = sum(t['cost'].get('total') or 0 for t in s['turns'] if t['dt'] and since <= t['dt'] < until)
            for u in us:
                costs[u] += cost / len(us)
    if pr_available:
        cov['sources'].append('gh/cache')
        initialize(days, PR)
        for url, p in prs.items():
            for key, ts in [('opened', p['createdAt']), ('merged', p.get('mergedAt')), ('abandoned', p.get('closedAt') if not p.get('mergedAt') else None)]:
                dd = day(ts, tz)
                if dd in days:
                    days[dd][key] += 1
                    if key == 'merged':
                        days[dd][states[url]] += 1
                        days[dd]['htm'].append(kp.hours(p['createdAt'], p['mergedAt']))
                        if url in costs:
                            days[dd]['pr_cost'].append(costs[url])
                    if key == 'abandoned':
                        days[dd]['abandoned_spend'] += costs[url]
            for rv in p.get('reviews') or []:
                login = kp.login(rv) or ''
                dd = day(rv.get('submittedAt'), tz)
                if dd in days and login and login.lower() not in logins and 'bot' not in login.lower():
                    days[dd]['human_reviews'] += 1
        for dd, d in days.items():
            stop = datetime.combine(date.fromisoformat(dd) + timedelta(days=1), time(), tz)
            ages = [(stop - ks.to_dt(p['createdAt'])).total_seconds() / 86400 for p in prs.values() if ks.to_dt(p['createdAt']) < stop and (not p.get('closedAt') or ks.to_dt(p['closedAt']) >= stop)]
            d['open_prs'] = len(ages)
            d['open_age'] = st.median(ages) if ages else None
        by_repo = defaultdict(list)
        for u, p in prs.items():
            if day(p.get('mergedAt'), tz) in days and u in costs:
                by_repo[u.split('/pull/')[0]].append(costs[u])
        tables['repo_cost'] = {k: dict(n=len(v), median=st.median(v), p90=sorted(v)[int(.9 * (len(v)-1))]) for k, v in by_repo.items() if len(v) >= 5}
    else:
        cov['missing_sources'].append('complete PR source unavailable')
    try:
        tasks = tasks_read(tasks_path) if tasks_path else None
        if tasks is None:
            raise ValueError('no tasks file')
        cov['sources'].append('tasks')
        initialize(days, TASK)
        cov['counts']['tasks'] = len(tasks)
        for task in tasks:
            pattern = re.compile(r'(?<![\w])' + re.escape(task['id']) + r'(?![\w])', re.I)
            us = [u for u, p in prs.items() if pattern.search(' '.join(p.get(k) or '' for k in ('title', 'headRefName', 'body')))]
            for u in us:
                prs[u].setdefault('tasks', []).append(task['id'])
            dd = day(task.get('completed'), tz)
            if dd in days:
                days[dd]['tasks_done'] += 1
                outcome = 'tasks_nopr' if not us else 'tasks_fixed' if any(states.get(u) == 'pr_fixed' for u in us) else 'tasks_landed' if all(states.get(u) == 'pr_landed' for u in us) else 'tasks_holding'
                days[dd][outcome] += 1
                if us:
                    tables['prs_per_task'].append(len(us))
            dd = day(task.get('canceled'), tz)
            if dd in days:
                days[dd]['tasks_canceled'] += 1
        for dd, d in days.items():
            stop = datetime.combine(date.fromisoformat(dd) + timedelta(days=1), time(), tz)
            for task in tasks:
                if task.get('created') and ks.to_dt(task['created']) < stop and not any(task.get(k) and ks.to_dt(task[k]) < stop for k in ('completed', 'canceled')):
                    d['wip' if task.get('started') and ks.to_dt(task['started']) < stop else 'queue'] += 1
            if not complete:
                for k in ('tasks_landed', 'tasks_fixed', 'tasks_nopr', 'tasks_holding'):
                    d[k] = None
    except (OSError, ValueError) as e:
        cov['missing_sources'].append('tasks: ' + str(e))
    tables['prs'] = []
    for u, p in prs.items():
        outcome = kp.outcome(p)
        tables['prs'].append({**p, 'landed': states.get(u), 'no_rework': outcome['commits_after_create'] == 0 and outcome['changes_requested'] == 0 and not outcome['failing_checks']})
    blockers(days, since, tz, cov)
    tables['findings'] = findings(start, end, cov)
    repos = json.loads(os.environ.get('HWORKS_FM_REPOS', '[]'))
    if not isinstance(repos, list) or any(not isinstance(r, dict) for r in repos):
        raise ValueError('repos must be a list of path/class objects')
    if not repos:
        cov['missing_sources'].append('git checkouts: not configured')
    missing_git = set()
    for repo in repos:
        if repo.get('class') not in ('factory', 'product') or not isinstance(repo.get('path'), str):
            raise ValueError('repo needs path and class product|factory')
        if not isinstance(repo.get('exclude', []), list) or any(not isinstance(x, str) for x in repo.get('exclude', [])):
            raise ValueError('repo exclude must be a list of directories')
        path = os.path.expanduser(repo['path'])
        try:
            ids = None if repo['class'] == 'factory' else {p['mergeCommit']['oid'] for p in prs.values() if p.get('mergeCommit')}
            if ids == set() and not complete:
                raise RuntimeError('product merge OIDs unavailable')
            result = churn.collect(path, since, until, tz, ids, repo.get('exclude', []))
            tables['churn'][path] = result
            cov['sources'].append('git: ' + path)
            for dd in days.values():
                for k in GIT:
                    if dd[k] is None:
                        dd[k] = 0
            for row in result['daily']:
                dd = days[row['date']]
                for k in GIT[1:]:
                    dd[k] += row[k]
                if repo['class'] == 'factory':
                    dd['factory_commits'] += row['changes']
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            cov['missing_sources'].append(f'git {path}: {e}')
            missing_git.update(GIT if repo['class'] == 'factory' else GIT[1:])
    for d in days.values():
        for field in missing_git:
            d[field] = None
    cov['failures'].extend(notes)
    for row in cov['missing_prs']:
        print(f"PR unavailable {row['url']}: {row['error']}", file=sys.stderr)
    for note in cov['missing_sources'] + cov['failures']:
        print(note, file=sys.stderr)
    return dict(generated=datetime.now(tz).isoformat(), tz=str(tz), start=start.isoformat(), end=end.isoformat(), days=list(days.values()), tables=tables, coverage=cov)


def findings(start, end, cov):
    rows = []
    common = subprocess.run(['git', '-C', str(HERE), 'rev-parse', '--path-format=absolute', '--git-common-dir'], capture_output=True, text=True)
    checkout = str(Path(common.stdout.strip()).parent) if common.returncode == 0 else str(HERE.parent)
    for skill, suffix in [('hansei', 'json'), ('kaizen', 'md')]:
        p = subprocess.run([str(HERE / 'task-dir.sh'), skill, checkout], capture_output=True, text=True)
        if p.returncode:
            cov['missing_sources'].append(f'{skill} task dir: {p.stderr.strip()}')
            continue
        root = Path(p.stdout.strip())
        paths = sorted(root.glob(f'findings-*.{suffix}'))
        if not paths:
            cov['missing_sources'].append(f'{skill} findings: none in {root}')
        for path in paths:
            try:
                dd = date.fromisoformat(path.stem.removeprefix('findings-'))
                if not start <= dd <= end:
                    continue
                if skill == 'hansei':
                    data = json.loads(path.read_text())
                    if not isinstance(data, dict):
                        raise ValueError('hansei findings must be an object')
                    if not isinstance(data.get('findings'), list):
                        raise ValueError('findings must be a list')
                    counts = {'findings': len(data['findings'])}
                else:
                    counts = Counter()
                    for line in path.read_text().splitlines():
                        m = re.match(r'^- \[([^]]+)\] ', line)
                        if not m or m[1] not in ('1', '2', '3', '4', '5', 'investigate', 'drop'):
                            continue
                        if m[1] == 'drop':
                            counts['dropped'] += 1
                        else:
                            fields = line.split('|')
                            if len(fields) != 6:
                                raise ValueError('kaizen finding needs six fields')
                            state = fields[-1].strip().split(' ', 1)[0].split(':', 1)[0]
                            if state not in ('open', 'awaiting-user', 'implemented', 'effective', 'unproven', 'pending'):
                                raise ValueError('invalid kaizen finding state')
                            counts[state] += 1
                rows.append(dict(skill=skill, date=dd.isoformat(), counts=dict(counts)))
                cov['sources'].append(f'{skill}: {path.name}')
            except (OSError, ValueError, KeyError, TypeError) as e:
                cov['failures'].append(f'findings {path}: {e}')
    return rows


def blockers(days, since, tz, cov):
    p = subprocess.run(['bash', str(HERE / 'blockers.sh'), '--since', since.isoformat(), '--json'], capture_output=True, text=True)
    cov['missing_sources'].extend(s.removeprefix('note: ') for s in p.stderr.splitlines() if s.strip())
    if p.returncode:
        cov['failures'].append('blockers: ' + p.stderr)
        return
    missing = {s.removeprefix('note: ').split(': not found', 1)[0] for s in p.stderr.splitlines() if ': not found' in s}
    available = {
        'friction': 'open questions' not in missing,
        'oq': 'open questions' not in missing,
        'guard': not {'autonomy log', 'harness audit log'} <= missing,
        'fail': not {'run history', 'subagent runs'} <= missing,
    }
    fields = {'friction': ['friction', 'fr_rows', 'fr_inschema'], 'oq': ['oq', 'oq_kept', 'oq_reversed'], 'guard': ['guard'], 'fail': ['subagent_fail', 'babysitter_fail', 'runs_never_started']}
    for source, present in available.items():
        if present:
            initialize(days, fields[source])
            cov['sources'].append('blockers: ' + source)
    for line in p.stdout.splitlines():
        row = json.loads(line)
        dd = day(row['ts'], tz)
        if dd not in days:
            continue
        d, source, kind = days[dd], row['source'], row['kind']
        if source == 'friction' and available['friction']:
            normal = next((k for k in ('operator', 'reviewer', 'ci', 'test') if k in kind.lower()), 'self')
            d['friction'][normal] = d['friction'].get(normal, 0) + 1
            d['fr_rows'] += 1
            d['fr_inschema'] += kind in ('operator', 'reviewer', 'test', 'ci', 'self')
        elif source == 'open-questions' and available['oq']:
            d['oq'] += 1
            if row.get('verdict') in ('kept', 'reversed'):
                d['oq_' + row['verdict']] += 1
        elif source in ('autonomy', 'harness') and available['guard']:
            d['guard'] += 1
        elif source in ('run-history', 'subagents') and kind in ('failed', 'timed_out', 'needs_attention') and available['fail']:
            if re.fullmatch(r'duration 0(?:\.0+)?', row.get('detail', '')):
                d['runs_never_started'] += 1
            else:
                d['babysitter_fail' if row['rule'] == 'pr-babysitter' else 'subagent_fail'] += 1


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--since', default='33d')
    parser.add_argument('--until')
    parser.add_argument('--tasks')
    parser.add_argument('--no-fetch', action='store_true')
    parser.add_argument('--cache', default=os.path.join(os.environ.get('XDG_CACHE_HOME', os.path.expanduser('~/.cache')), 'hworks/factory-metrics'))
    args = parser.parse_args()
    try:
        environment()
        tz = zone()
        end = date.fromisoformat(args.until) if args.until else datetime.now(tz).date()
        match = re.fullmatch(r'(\d+)d', args.since)
        start = end - timedelta(days=int(match[1]) - 1) if match else date.fromisoformat(args.since)
        if start > end:
            raise ValueError('since must not follow until')
        print(json.dumps(collect(start, end, tz, args.tasks, args.no_fetch, Path(args.cache)), allow_nan=False))
    except (ValueError, KeyError, TypeError, subprocess.SubprocessError) as e:
        parser.error(str(e))


if __name__ == '__main__':
    main()
