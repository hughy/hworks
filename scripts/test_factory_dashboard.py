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
        self.assertIn('<b>$11.80</b>', text)
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
            self.assertIn('key metric: optimize: higher', merged)
            self.assertEqual(text.count('<tr class="krow">'), 6)

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
