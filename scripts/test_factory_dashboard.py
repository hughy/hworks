import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser

HERE = Path(__file__).resolve().parent
FIX = HERE / 'testdata/factory-metrics'


class Parser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tile_classes = []
        self.details = 0
        self.summary_text = []
        self.in_summary = False
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'div' and 'tile' in attrs.get('class', '').split():
            self.tile_classes.append(attrs['class'])
        if tag == 'details':
            self.details += 1
        if tag == 'summary':
            self.in_summary = True
    def handle_endtag(self, tag):
        if tag == 'summary':
            self.in_summary = False
    def handle_data(self, data):
        if self.in_summary:
            self.summary_text.append(data)


class RendererTest(unittest.TestCase):
    def run_dashboard(self, metrics=FIX / 'metrics.json', *extra):
        p = subprocess.run([sys.executable, str(HERE / 'factory-dashboard.py'), str(metrics), '--tiles', str(FIX / 'tiles.json'), *extra], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def test_layout_extensions_and_empty_tiles(self):
        text = self.run_dashboard()
        parser = Parser(); parser.feed(text)
        self.assertLess(text.index('<h2>Scorecard'), text.index('<h2>Output'))
        self.assertLess(text.index('<th>prior 7d'), text.index('<th>last 7d'))
        self.assertEqual(sum('key' in c.split() for c in parser.tile_classes), 6)
        self.assertEqual(text.count('<tr class="krow">'), 6)
        self.assertIn('<b>$11.80, $826 of 70</b>', text)
        self.assertIn('<span class="tag t-companion">companion</span>', text)
        self.assertIn('Generic test &lt;definition&gt;', text)
        quality = text[text.index('<h2>Review and quality'):text.index('<h2>Churn')]
        self.assertIn('Dispatch verdicts', quality)
        self.assertIn('<rect', quality)
        self.assertIn('<td>example</td><td>12</td>', text)
        self.assertIn('<td>2026-01-21</td><td>7</td>', text)
        self.assertIn('no collector yet', text)
        self.assertIn('tile dim', text)
        self.assertIn('7</span>', text)
        self.assertNotIn('<script', text.lower())
        self.assertTrue(text.isascii())
        self.assertEqual(parser.summary_text, ['About the data'])
        self.assertEqual(parser.details, len(parser.tile_classes) + 1)

    def test_output_key_falls_back_to_merged_and_writes_file(self):
        data = json.loads((FIX / 'metrics.json').read_text())
        for d in data['days']:
            for k in list(d):
                if k.startswith('tasks_'):
                    d[k] = None
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'metrics.json'; path.write_text(json.dumps(data))
            output = Path(temp) / 'dashboard.html'
            self.run_dashboard(path, '-o', str(output))
            text = output.read_text()
            fragment = text[text.index('<h2>Output'):text.index('<h2>Cost')]
            task = fragment[:fragment.index('PRs merged per day')]
            self.assertIn('tile dim', task)
            merged = fragment[fragment.index('PRs merged per day'):fragment.index('PRs opened per day')]
            self.assertIn('key metric: higher is better', merged)
            self.assertEqual(text.count('<tr class="krow">'), 6)

    def test_stack_labels_are_escaped(self):
        data = json.loads((FIX / 'tiles.json').read_text())
        data['tiles'][1]['names'] = ['</title><script>alert(1)</script><title>', 'ok']
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'tiles.json'; path.write_text(json.dumps(data))
            text = self.run_dashboard(FIX / 'metrics.json', '--tiles', str(path))
        self.assertIn('&lt;/title&gt;&lt;script&gt;alert(1)&lt;/script&gt;&lt;title&gt; 4', text)
        self.assertNotIn('<script', text.lower())

    def test_weekly_no_rework_uses_local_reporting_window(self):
        data = json.loads((FIX / 'metrics.json').read_text())
        data['tz'] = 'America/Los_Angeles'
        data['tables']['prs'] = [
            dict(mergedAt=ts, no_rework=ts not in ('2026-01-01T07:59:59Z', '2026-01-22T08:00:00Z'))
            for ts in ('2025-01-01T12:00:00Z', '2027-01-01T12:00:00Z',
                       '2026-01-01T07:59:59Z', '2026-01-05T01:00:00Z',
                       '2026-01-22T07:59:59Z', '2026-01-22T08:00:00Z')
            for _ in range(5)]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'metrics.json'; path.write_text(json.dumps(data))
            text = self.run_dashboard(path)
        fragment = text[text.index('Merged with no rework, by week'):text.index('Review dispatcher verdicts against outcome')]
        self.assertIn('week of Dec 29 (5)', fragment)
        self.assertIn('week of Jan 19 (5)', fragment)
        self.assertEqual(fragment.count('>100%, 5 of 5</text>'), 2)
        for week in ('2024-12-30', '2026-12-28', '2026-01-05'):
            self.assertNotIn(week, fragment)

    def test_measured_prototype_annotations(self):
        data = json.loads((FIX / 'metrics.json').read_text())
        data['tables']['prs_per_task'] = [2, 4]
        for d in data['days']:
            d.update(abandoned=1, abandoned_spend=0, open_prs=2, open_age=1,
                     human_reviews=54321, ops=20, sig_correction=1, sig_abort=0,
                     sig_approval=0, **{'sig_status-check': 0})
        data['days'][-1].update(abandoned_spend=123.45, open_age=987.6)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'metrics.json'; path.write_text(json.dumps(data))
            text = self.run_dashboard(path)
        self.assertIn('PRs per task: -<br>2 of 5 needed', text)
        self.assertIn('Direct cost of these PRs: $123 over the period', text)
        self.assertIn('median open-PR age 988 days', text)
        fragment = text[text.index('Operator touches per day, by type'):text.index('Friction per merged PR', text.index('<h2>Human touches'))]
        self.assertIn('PR reviews by others', fragment)
        self.assertIn('54,321', fragment)

    def test_curated_score_units_rounds_and_coverage(self):
        data = json.loads((FIX / 'metrics.json').read_text())
        data['tables']['token_report'] = {'loop rounds': [dict(round=1, runs=4, rounds_with_blocker=1, cost=393)],
                                         'roles': [dict(model='test/model', first_round_clean=5, first_rounds=10)]}
        data['coverage'] = dict(missing_prs=[dict(url='https://example.com/repo/pull/1', error='authentication failed')], unavailable_pr_hosts=['example.com'])
        for d in data['days']:
            d.update(pr_cost=[2], pr_fixed=1, sig_correction=1, sig_abort=0, linked=10)
        data['days'][-1]['runs_never_started'] = 8190
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'metrics.json'; path.write_text(json.dumps(data))
            text = self.run_dashboard(path)
        score = text[text.index('<h2>Scorecard'):text.index('<h2>Output')]
        for label in ('Cost per merged PR, all spend', 'Cost per merged PR, direct (median)', 'Corrections and aborts per merged PR', 'PRs fixed within 7 days', 'Spend linked to a PR'):
            self.assertIn('<td>' + label + '</td>', score)
        self.assertNotIn('PRs opened per day', score)
        self.assertNotIn('Automation runs failed', score)
        self.assertIn('<td>Reviews</td>', score)
        self.assertIn('PR coverage: 1 PRs missing; unavailable hosts: example.com', text)
        self.assertIn('8,190 runs never started', text)
        cost = text[text.index('Review-loop spend by round'):text.index('Cloud agent spend')]
        self.assertIn('round 1', cost)
        self.assertIn('$393', cost)
        funnel = text[text.index('Review-loop rounds'):text.index('First review clean, by coder model')]
        self.assertIn('fill="#222"', funnel)
        self.assertIn('fill="#cfcfcf"', funnel)
        self.assertIn('blocked 1', funnel)
        self.assertIn('clean 3', funnel)
        first = text[text.index('First review clean, by coder model'):text.index('Merged with no rework, by week')]
        self.assertIn('model (10)', first)
        self.assertIn('50%', first)

    def test_rate_sample_floor_counts_and_delta(self):
        for previous, current in ((5, 4), (4, 5), (5, 5)):
            with self.subTest(previous=previous, current=current):
                data = json.loads((FIX / 'metrics.json').read_text())
                for d in data['days']:
                    d.update(fr_rows=0, fr_inschema=0)
                data['days'][-8].update(fr_rows=previous, fr_inschema=previous)
                data['days'][-1].update(fr_rows=current, fr_inschema=1)
                with tempfile.TemporaryDirectory() as temp:
                    path = Path(temp) / 'metrics.json'; path.write_text(json.dumps(data))
                    text = self.run_dashboard(path)
                tile = text[text.index('Friction rows in schema'):text.index('</section>', text.index('Friction rows in schema'))]
                if current == 4:
                    self.assertIn('<span class="lv">-<br>4 of 5 needed</span>', tile)
                    self.assertNotIn('25%', tile)
                else:
                    self.assertIn('<span class="lv">20%, 1 of 5</span>', tile)
                    self.assertIn('Jan 21: 20%, 1 of 5</title>', tile)
                if previous == 4:
                    self.assertIn('prior 7d -<br>4 of 5 needed', tile)
                if min(previous, current) < 5:
                    self.assertNotIn('class="chg', tile)
                else:
                    self.assertIn('>-80%</span>', tile)

    def test_duration_median_and_p90_not_mean(self):
        data = json.loads((FIX / 'metrics.json').read_text())
        data['days'][-1]['htm'] = [1, 1, 1, 1, 96]
        ext = {'series': {'latency': {f'2026-01-{day}': value for day, value in zip(range(17, 22), [1, 1, 1, 1, 96])}},
               'tiles': [dict(key='latency', band='Output', title='Latency', home='test', about='Duration samples', kind='bars', series=['latency'],
                              kpi=dict(series='latency', how='mean', format='h'),
                              score_row=dict(series='latency', how='mean', format='h'))]}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'metrics.json'; path.write_text(json.dumps(data))
            extension = Path(temp) / 'tiles.json'; extension.write_text(json.dumps(ext))
            text = self.run_dashboard(path, '--tiles', str(extension))
        score = text[text.index('<h2>Scorecard'):text.index('<h2>Output')]
        self.assertIn('<td>Hours to merge (median)</td>', score)
        self.assertIn('<td>Hours to merge (p90)</td>', score)
        self.assertIn('<b>1.0 h</b>', score)
        self.assertIn('<b>96 h</b>', score)
        latency = text[text.index('Latency</span>'):text.index('<h2>Cost')]
        self.assertIn('median, prior 7d', latency)
        self.assertIn('p90, prior 7d', latency)
        self.assertIn('<span class="lv">1.0 h</span>', latency)
        self.assertIn('<span class="lv">96 h</span>', latency)
        self.assertNotIn('20 h', latency)
        self.assertNotIn('mean', latency)

    def test_rate_counts_in_tables_bars_score_and_unknown_extensions(self):
        data = json.loads((FIX / 'metrics.json').read_text())
        for d in data['days']:
            d.update(cw=2, spend=4, ops=1)
        data['tables']['churn'] = {'test/repo': dict(totals=dict(added=5, churn21=1, moved=2, revisit_changes=1, changes=4))}
        data['tables']['prs'] = [dict(mergedAt='2026-01-20T12:00:00Z', no_rework=True) for _ in range(4)]
        ext = {'series': {'unknown': {'2026-01-21': .9}},
               'tiles': [dict(key='unknown', band='Output', title='Unknown rate', home='test', about='No counts supplied', kind='lines', series=['unknown'], format='%',
                              kpi=dict(series='unknown', how='last', format='%'))]}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'metrics.json'; path.write_text(json.dumps(data))
            extension = Path(temp) / 'tiles.json'; extension.write_text(json.dumps(ext))
            text = self.run_dashboard(path, '--tiles', str(extension))
        self.assertIn('50%, $14.00 of $28.00, 7 days', text)
        self.assertIn('0.1, 7 of 70', text)
        self.assertIn('<td>20%, 1 of 5</td><td>40%, 2 of 5</td><td>-\n4 of 5 needed</td>', text)
        weekly = text[text.index('Merged with no rework, by week'):text.index('Review dispatcher verdicts against outcome')]
        self.assertIn('4 of 5 needed', weekly)
        self.assertNotIn('100%', weekly)
        unknown = text[text.index('Unknown rate</span>'):text.index('<h2>Cost')]
        self.assertIn('-<br>count unavailable', unknown)
        self.assertNotIn('90%', unknown)

    def test_spend_shares_count_observed_days_not_rolling_outputs(self):
        for previous, current in ((1, 1), (4, 5), (5, 4), (5, 5), (7, 7)):
            with self.subTest(previous=previous, current=current):
                data = json.loads((FIX / 'metrics.json').read_text())
                for d in data['days']:
                    d.update(cw=None, longc=None, linked=None, spend_factory=None, spend=None)
                for end, amount, count in ((-7, 1, previous), (0, 2, current)):
                    start = len(data['days']) + end - 7
                    for i in range(start, start + count):
                        data['days'][i].update(cw=amount, longc=amount, linked=amount, spend_factory=amount, spend=4)
                with tempfile.TemporaryDirectory() as temp:
                    path = Path(temp) / 'metrics.json'; path.write_text(json.dumps(data))
                    text = self.run_dashboard(path)
                score = text[text.index('<td>Cache-write share of spend</td>'):]
                fragments = [score[:score.index('</tr>')]]
                for title in ('Cache-write share of spend', 'Long-context share of spend', 'Spend linked to a PR', 'Factory share of spend'):
                    start = text.index(title + '</span>')
                    fragments.append(text[start:text.index('</details>', start)])
                for fragment in fragments:
                    if current < 5:
                        self.assertIn(f'-<br>{current} of 5 needed', fragment)
                        self.assertNotIn('50%', fragment)
                    else:
                        self.assertIn(f'50%, ${2*current:.2f} of ${4*current:.2f}, {current} days', fragment)
                    if previous < 5:
                        self.assertIn(f'-<br>{previous} of 5 needed', fragment)
                        self.assertNotIn('25%', fragment)
                    else:
                        self.assertIn(f'25%, ${previous:.2f} of ${4*previous:.2f}, {previous} days', fragment)
                    if min(previous, current) < 5:
                        self.assertNotIn('class="chg', fragment)
                    else:
                        self.assertIn('>+100%</span>', fragment)

    def test_extension_names_do_not_collide_with_internal_metadata(self):
        data = json.loads((FIX / 'metrics.json').read_text())
        for d in data['days']:
            d.update(fr_rows=1, fr_inschema=1, htm=[1])
        ext = {'series': {name: {'2026-01-21': value} for name, value in
                          [('schema_rate', 123), ('htm7_n', 456)]},
               'tiles': [dict(key='metadata_names', band='Output', title='Extension values', home='test',
                              about='Numeric extension series', kind='table', series=['schema_rate', 'htm7_n'])]}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'metrics.json'; path.write_text(json.dumps(data))
            extension = Path(temp) / 'tiles.json'; extension.write_text(json.dumps(ext))
            text = self.run_dashboard(path, '--tiles', str(extension))
            ext['series']['schema'] = {'2026-01-21': .9}
            extension.write_text(json.dumps(ext))
            overridden = self.run_dashboard(path, '--tiles', str(extension))
        self.assertIn('<td>2026-01-21</td><td>123</td><td>456</td>', text)
        schema = text[text.index('Friction rows in schema'):]
        self.assertIn('<span class="lv">100%, 7 of 7</span>', schema)
        duration = text[text.index('Hours to merge</span>'):text.index('Main-session time by who held the turn')]
        self.assertIn('<span class="lv">1.0 h</span><span class="chg', duration)
        schema = overridden[overridden.index('Friction rows in schema'):]
        self.assertIn('<span class="lv">-<br>count unavailable</span>', schema)
        self.assertNotIn('90%', schema)

    def test_rejects_invalid_extension_at_boundary(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'bad.json'
            data = json.loads((FIX / 'tiles.json').read_text())
            data['tiles'][0]['band'] = 'Unknown'
            p.write_text(json.dumps(data))
            result = subprocess.run([sys.executable, str(HERE / 'factory-dashboard.py'), str(FIX / 'metrics.json'), '--tiles', str(p)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('unknown extension band', result.stderr)
            self.assertIn('Dispatch verdicts', self.run_dashboard())


if __name__ == '__main__':
    unittest.main()
