import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
FIX = HERE / 'testdata/factory-metrics'


class CollectorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sessions = self.root / 'sessions'
        self.sessions.mkdir()
        for name in ('main', 'future'):
            shutil.copy(FIX / (name + '.jsonl'), self.sessions)
        child = self.sessions / 'main' / '11111111-2222-3333-4444-555555555555' / 'run-1'
        child.mkdir(parents=True)
        shutil.copy(FIX / 'child.jsonl', child / 'session.jsonl')
        artifact = self.sessions / 'subagent-artifacts'
        artifact.mkdir()
        shutil.copy(FIX / 'child.jsonl', artifact / 'duplicate.jsonl')
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('HWORKS_')}
        self.env.update(HOME=str(self.root), HWORKS_PI_SESSIONS=str(self.sessions),
                        HWORKS_TASKS_DIR=str(self.root / 'missing'), HWORKS_RUN_HISTORY=str(self.root / 'missing-history'),
                        HWORKS_SUBAGENT_RUNS=str(self.root / 'missing-runs'),
                        HWORKS_FM_TZ='UTC', HWORKS_FM_SESSION_RULES='[{"pattern":"factory", "class":"factory"}]',
                        HWORKS_GH=str(FIX / 'fake-gh.sh'), FM_GH_DATA=str(FIX / 'prs.json'), FM_GH_CALLS=str(self.root / 'gh-calls'))

    def run_metrics(self, *extra):
        p = subprocess.run([sys.executable, str(HERE / 'factory-metrics.py'), '--since', '2026-01-01', '--until', '2026-01-12', '--tasks', str(FIX / 'tasks.json'), '--cache', str(self.root / 'cache'), *extra], env=self.env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def test_spend_prs_landed_and_tasks(self):
        result = self.run_metrics()
        days = {d['date']: d for d in result['days']}
        self.assertEqual([days['2026-01-01']['spend'], days['2026-01-02']['spend']], [3, 5])
        self.assertEqual(sum(d['spend'] for d in days.values()), 8)
        self.assertEqual(days['2026-01-02']['spend_factory'], 5)
        self.assertEqual(days['2026-01-01']['cw'], 1)
        self.assertEqual(days['2026-01-02']['longc'], 5)
        self.assertEqual(days['2026-01-01']['ops'], 2)
        self.assertEqual(days['2026-01-01']['sig_correction'], 1)
        self.assertEqual(days['2026-01-01']['opened'], 9)
        self.assertEqual(days['2026-01-02']['merged'], 4)
        self.assertEqual(days['2026-01-02']['abandoned'], 1)
        outcomes = {p['number']: p['landed'] for p in result['tables']['prs']}
        self.assertEqual([outcomes[n] for n in (1, 2, 3)], ['pr_fixed', 'pr_landed', 'pr_fixed'])
        self.assertEqual(days['2026-01-10']['tasks_done'], 3)
        self.assertEqual(days['2026-01-10']['tasks_landed'], 1)
        self.assertEqual(days['2026-01-10']['tasks_fixed'], 2)
        self.assertEqual(result['tables']['prs_per_task'], [1, 1, 1])
        self.assertEqual(days['2026-01-01']['queue'], 3)
        self.assertEqual(days['2026-01-02']['wip'], 3)
        self.assertEqual(days['2026-01-10']['wip'], 0)
        links = {p['number']: p.get('tasks') for p in result['tables']['prs']}
        self.assertEqual([links[n] for n in (1, 2, 3)], [['TASK-A'], ['TASK-B'], ['TASK-C']])
        self.assertEqual(sum(r['cost'] for r in result['tables']['token_report'].get('roles', [])), 5)
        payloads = json.loads((FIX / 'prs.json').read_text())
        payloads['https://github.com/example/widget/pull/4']['title'] = 'fix: regression from https://github.com/example/widget/pull/2'
        payloads['https://github.com/example/widget/pull/6']['title'] = 'Revert #3'
        changed = self.root / 'changed.json'; changed.write_text(json.dumps(payloads))
        self.env['FM_GH_DATA'] = str(changed)
        updated = self.run_metrics('--cache', str(self.root / 'fresh-cache'))
        outcomes = {p['number']: p['landed'] for p in updated['tables']['prs']}
        self.assertEqual([outcomes[n] for n in (1, 2, 3)], ['pr_landed', 'pr_fixed', 'pr_fixed'])

    def test_cache_and_open_refresh(self):
        first = self.run_metrics()
        self.assertEqual(first['coverage']['counts']['fetched'], 9)
        calls = self.root / 'gh-calls'
        calls.write_text('')
        second = self.run_metrics()
        self.assertEqual(second['days'][1]['merged'], 4)
        self.assertEqual(second['coverage']['counts']['cache_hits'], 8)
        self.assertEqual(calls.read_text(), 'https://github.com/example/widget/pull/8\n')
        self.env['HWORKS_GH'] = '/not/a/program'
        nofetch = self.run_metrics('--no-fetch')
        self.assertEqual(nofetch['coverage']['counts']['cache_hits'], 8)
        self.assertEqual([p['state'] for p in nofetch['tables']['prs'] if p['number'] == 1], ['MERGED'])
        self.assertEqual(calls.read_text(), 'https://github.com/example/widget/pull/8\n')
        self.assertEqual(nofetch['days'][1]['merged'], 4)
        self.assertEqual(len(nofetch['coverage']['missing_prs']), 1)

    def test_missing_sources_and_auth_failure(self):
        self.env['FM_GH_FAIL'] = '1'
        result = self.run_metrics()
        self.assertIsNone(result['days'][0]['opened'])
        self.assertTrue(any('authentication failed' in r['error'] for r in result['coverage']['missing_prs']))
        self.env['HWORKS_PI_SESSIONS'] = str(self.root / 'not-found')
        self.env['HWORKS_FM_REPOS'] = json.dumps([dict(path=str(self.root / 'absent-repo'), **{'class': 'factory'})])
        result = self.run_metrics('--tasks', str(self.root / 'absent-tasks'))
        self.assertIsNone(result['days'][0]['spend'])
        self.assertIsNone(result['days'][0]['tasks_done'])
        self.assertIsNone(result['days'][0]['churn21'])
        self.assertTrue(any('pi sessions:' in x for x in result['coverage']['missing_sources']))
        self.assertTrue(any('git ' in x for x in result['coverage']['missing_sources']))

    def test_partial_pr_failure_and_not_found(self):
        self.env['FM_GH_FAIL_URL'] = 'https://github.com/example/widget/pull/1'
        for error, key in [('Could not resolve to a Repository', 'dropped_pr_links'),
                           ('Could not resolve to a PullRequest with the number of 1.', 'dropped_pr_links'),
                           ('authentication failed', 'missing_prs')]:
            self.env['FM_GH_ERROR'] = error
            result = self.run_metrics('--cache', str(self.root / key))
            self.assertEqual(result['days'][1]['merged'], 3)
            self.assertEqual(result['days'][0]['opened'], 8)
            self.assertEqual(result['coverage'][key], [dict(url=self.env['FM_GH_FAIL_URL'], error=error)])
            self.assertEqual(result['coverage']['unavailable_pr_hosts'], [])
        self.env['FM_GH_FAIL'] = '1'
        result = self.run_metrics('--cache', str(self.root / 'all-fail'))
        self.assertEqual(result['coverage']['unavailable_pr_hosts'], ['github.com'])
        self.assertIsNone(result['days'][1]['merged'])

    def test_zero_duration_failed_runs_never_started(self):
        history = self.root / 'history.jsonl'
        history.write_text(''.join(json.dumps(dict(ts='2026-01-02T12:00:00Z', status='error', outcome='failed', agent=role, duration=duration)) + '\n'
                                   for role, duration in [('pr-babysitter', 0), ('coder', 0.0), ('pr-babysitter', 12), ('coder', 3)]))
        self.env['HWORKS_RUN_HISTORY'] = str(history)
        result = self.run_metrics()
        self.assertEqual([result['days'][1][k] for k in ('subagent_fail', 'babysitter_fail')], [1, 1])
        self.assertEqual(result['days'][1]['runs_never_started'], 2)

    def test_default_subagent_directory_availability(self):
        self.env.pop('HWORKS_SUBAGENT_RUNS')
        self.env['TMPDIR'] = str(self.root)
        runs = self.root / f'pi-subagents-uid-{os.getuid()}' / 'async-subagent-runs'
        run = runs / 'run-1'; run.mkdir(parents=True)
        (run / 'events.jsonl').write_text(json.dumps(dict(
            type='subagent.control', event=dict(type='needs_attention',
            ts='2026-01-02T12:00:00Z', reason='failed', agent='coder', message='help'))) + '\n')
        result = self.run_metrics()
        self.assertEqual([result['days'][1][k] for k in ('subagent_fail', 'babysitter_fail')], [1, 0])
        self.assertIn('blockers: fail', result['coverage']['sources'])
        (run / 'events.jsonl').write_text('')
        result = self.run_metrics()
        self.assertEqual(result['days'][1]['subagent_fail'], 0)
        self.env['HWORKS_SUBAGENT_RUNS'] = str(self.root / 'absent-runs')
        result = self.run_metrics()
        self.assertIsNone(result['days'][1]['subagent_fail'])
        self.assertTrue(any('subagent runs: not found' in s for s in result['coverage']['missing_sources']))

    def test_findings_from_skill_task_directories(self):
        common = subprocess.check_output(['git', '-C', str(HERE), 'rev-parse', '--path-format=absolute', '--git-common-dir'], text=True)
        checkout = str(Path(common.strip()).parent)
        for skill, suffix, content in [('hansei', 'json', json.dumps({'findings': [{'title': 'private'}, {'title': 'private'}]})),
                                       ('kaizen', 'md', '- [x] private checklist text\n- [3] K-1 title | evidence | actor | deliverable | artifact | open\n- [drop] noise | reason\n- [5] K-2 title | evidence | actor | deliverable | artifact | implemented (landed)\n')]:
            root = Path(subprocess.check_output([str(HERE / 'task-dir.sh'), skill, checkout], env=self.env, text=True).strip())
            (root / ('findings-2026-01-02.' + suffix)).write_text(content)
        result = self.run_metrics()
        self.assertEqual(result['tables']['findings'], [dict(skill='hansei', date='2026-01-02', counts={'findings': 2}), dict(skill='kaizen', date='2026-01-02', counts={'open': 1, 'dropped': 1, 'implemented': 1})])

    def test_churn_on_small_git_repo(self):
        repo = self.root / 'repo'; repo.mkdir()
        def git(*args, **env):
            p = subprocess.run(['git', '-C', str(repo), *args], env={**os.environ, **env}, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
        git('init'); git('config', 'user.email', 'test@example.com'); git('config', 'user.name', 'Test')
        (repo / 'file.py').write_text('one\ntwo\nthree\n')
        git('add', '.'); git('commit', '-m', 'feat: initial', GIT_AUTHOR_DATE='2026-01-01T12:00:00Z', GIT_COMMITTER_DATE='2026-01-01T12:00:00Z')
        (repo / 'file.py').write_text('one\nchanged\nthree\n')
        (repo / 'package-lock.json').write_text('ignored\n')
        git('add', '.'); git('commit', '-m', 'fix: update', GIT_AUTHOR_DATE='2026-01-03T12:00:00Z', GIT_COMMITTER_DATE='2026-01-03T12:00:00Z')
        git('checkout', '-b', 'unlanded')
        (repo / 'file.py').write_text('unlanded\n')
        git('add', '.'); git('commit', '-m', 'feat: not landed', GIT_AUTHOR_DATE='2026-01-04T12:00:00Z', GIT_COMMITTER_DATE='2026-01-04T12:00:00Z')
        self.env['HWORKS_FM_REPOS'] = json.dumps([dict(path=str(repo), **{'class': 'factory'})])
        result = self.run_metrics()
        day = result['days'][2]
        self.assertEqual([day[k] for k in ('added', 'deleted', 'churn21', 'churn7', 'revisit_changes', 'factory_commits')], [1, 1, 1, 1, 1, 1])
        self.assertEqual(result['tables']['churn'][str(repo)]['totals']['churn21_ratio'], .25)
        self.assertEqual(result['days'][3]['factory_commits'], 0)
        for repo_class in ('product', 'factory'):
            missing = dict(path=str(self.root / 'missing-repo'), **{'class': repo_class})
            for repos in ([missing, dict(path=str(repo), **{'class': 'factory'})],
                          [dict(path=str(repo), **{'class': 'factory'}), missing]):
                self.env['HWORKS_FM_REPOS'] = json.dumps(repos)
                partial = self.run_metrics()
                self.assertEqual([partial['days'][2][k] for k in ('added', 'deleted', 'churn21', 'churn7', 'moved', 'revisit_changes', 'changes')], [None] * 7)
                self.assertEqual(partial['days'][2]['factory_commits'], 1 if repo_class == 'product' else None)
                self.assertEqual(partial['tables']['churn'][str(repo)]['totals']['churn21_ratio'], .25)
                self.assertTrue(any('missing-repo' in s for s in partial['coverage']['missing_sources']))


if __name__ == '__main__':
    unittest.main()
