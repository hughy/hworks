import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync, symlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync, spawnSync } from 'node:child_process';
import { parseFrontmatter, rewriteRelativeLinks } from '../scripts/lib/render-common.mjs';

const engine = fileURLToPath(new URL('../', import.meta.url));
const web = 'https://code.example.test/org/context';
function fixture(t) {
  const root = mkdtempSync(join(tmpdir(), 'hoffice-render-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const git = (...args) => execFileSync('git', args, { cwd: root, encoding: 'utf8' }).trim();
  git('init', '-b', 'main');
  git('remote', 'add', 'origin', `${web}.git`);
  const write = (path, text) => {
    const full = join(root, path);
    mkdirSync(resolve(full, '..'), { recursive: true });
    writeFileSync(full, text);
    return full;
  };
  const run = (script, ...args) => spawnSync(process.execPath, [join(engine, 'scripts', script), ...args], {
    cwd: tmpdir(), encoding: 'utf8', env: { ...process.env, MARKED_PATH: '' },
  });
  return { root, git, write, run };
}
const digest = (end, status, summary, extra = '') => `---
period_start: 2026-05-01T00:00:00Z
period_end: ${end}
baseline: true
---
# Daily digest
## Current status
${status}
## Summary
${summary}
## Discussion
None.
${extra}`;

function success(result) {
  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
}

for (const authority of ['draft', 'authoritative: deployment policy']) {
  test(`published CLI renders ${authority} metadata, tables, diagrams, and source-relative links outside the engine`, (t) => {
    const f = fixture(t);
    f.git('symbolic-ref', 'refs/remotes/origin/HEAD', 'refs/remotes/origin/trunk');
    const src = f.write('projects/demo/published/report.md', `---
title: Progress <review>
audience: Readers & writers
authority: ${authority}
---
# Progress
As of 2026-05-02.
## Changes
| Item | Status |
| --- | --- |
| Work | Ready |

[Notes](../notes/design.md#choice) and [web](https://docs.example.test/).
<figure class="fig"><div class="node base">Flow</div></figure>
`);
    const out = join(f.root, 'report.html');
    symlinkSync(join(f.root, 'projects'), join(f.root, 'alias'), 'dir');
    const result = f.run('render-published.mjs', src.replace('/projects/', '/alias/'), out);
    success(result);
    const html = readFileSync(out, 'utf8');
    assert.match(html, /<h1>Progress &lt;review><\/h1>/);
    assert.ok(html.includes(`Audience: Readers &amp; writers. Authority: ${authority}.`));
    assert.match(html, /<h2>Changes<\/h2>/);
    assert.match(html, /<td>Ready<\/td>/);
    assert.match(html, /<figure class="fig"><div class="node base">Flow/);
    assert.ok(html.includes(`href="${web}/blob/trunk/projects/demo/notes/design.md#choice"`));
    assert.ok(html.includes('href="https://docs.example.test/"'));
    assert.match(result.stdout, /1 h2, 1 figures, 1 tables/);
  });
}

test('relative-link rewriting preserves anchors, external links, and source paths with parent segments', (t) => {
  const f = fixture(t);
  const src = f.write('projects/demo/published/a.md', 'Source');
  const actual = rewriteRelativeLinks('[parent](../notes/a.md#part) [local](./b.md) [anchor](#here) [remote](https://docs.example.test/x)',
    src, { root: f.root, blobBase: `${web}/blob/main/` });
  assert.equal(actual, `[parent](${web}/blob/main/projects/demo/notes/a.md#part) [local](${web}/blob/main/projects/demo/published/b.md) [anchor](#here) [remote](https://docs.example.test/x)`);
});

for (const [format, patterns] of [
  ['JSON', String.raw`[{"kind":"work item","pattern":"TASK-\\d+"},{"kind":"room","pattern":"room: #[a-z]+"}]`],
  ['YAML', String.raw`
  - kind: work item
    pattern: 'TASK-\d+'
  - kind: room
    pattern: 'room: #[a-z]+'`],
]) {
  test(`digest check uses ${format} patterns to report source lines and accept linked forms`, (t) => {
    const f = fixture(t);
    const cfg = f.write('DIGEST.md', `---\nlink_patterns: ${patterns}\n---\n`);
    const src = f.write('entry.md', digest('2026-05-02', 'TASK-42', 'room: #design'));
    const failed = f.run('render-digest.mjs', '--check', src, '--config', cfg);
    assert.equal(failed.status, 1);
    assert.ok(failed.stderr.includes(`${src}:8: unlinked work item: TASK-42`));
    assert.match(failed.stderr, /unlinked room: room: #design/);
    assert.match(failed.stdout, /2 unlinked artifact\(s\)/);
    f.write('entry.md', digest('2026-05-02', '[TASK-42](https://tracker.example.test/42)', '[room: #design](https://chat.example.test/room) #32'));
    const passed = f.run('render-digest.mjs', '--check', src, '--config', cfg);
    success(passed);
    assert.match(passed.stdout, /0 unlinked artifact\(s\)/);
  });
}

test('frontmatter preserves scalar text and body while parsing nested YAML settings', () => {
  const { fm, body } = parseFrontmatter(`---
title: "A # title"
baseline: true
rolling_days: 014
url: null
period_end: 2026-05-02T00:00:00Z
publisher:
  staging_id: 'local-42'
  options:
    enabled: true
    revision: 2
---
# Body
`);
  assert.deepEqual(fm, {
    title: 'A # title', baseline: 'true', rolling_days: '014', url: 'null',
    period_end: '2026-05-02T00:00:00Z',
    publisher: { staging_id: 'local-42', options: { enabled: true, revision: 2 } },
  });
  assert.equal(body, '# Body\n');
});

test('default link check catches PR numbers and bare URLs and ignores linked artifacts', (t) => {
  const f = fixture(t);
  const src = f.write('entry.md', digest('2026-05-02', '#32', 'https://docs.example.test/new'));
  const failed = f.run('render-digest.mjs', '--check', src);
  assert.equal(failed.status, 1);
  assert.match(failed.stderr, /unlinked PR or issue number: #32/);
  assert.match(failed.stderr, /unlinked bare URL: https:\/\/docs.example.test\/new/);
  f.write('entry.md', digest('2026-05-02', '[#32](https://code.example.test/32)', '[doc](https://docs.example.test/new)'));
  const passed = f.run('render-digest.mjs', '--check', src);
  success(passed);
  assert.match(passed.stdout, /0 unlinked artifact\(s\)/);
});

test('digest renders rolling history, newest status, quiet note, and open-ref sources with relative links', (t) => {
  const f = fixture(t);
  f.write('digests/demo/DIGEST.md', '---\ntitle: Demo log\nrolling_days: 2\n---\n');
  f.write('digests/demo/2026-05-01-daily.md', digest('2026-05-01', 'Old status', 'Old summary'));
  f.write('digests/demo/2026-05-02-daily.md', digest('2026-05-02', 'Middle status', 'Middle summary'));
  f.git('add', '.');
  f.git('-c', 'user.name=Test', '-c', 'user.email=test@example.test', 'commit', '-m', 'test: baseline');
  f.git('switch', '-c', 'digest/demo/pending');
  f.write('digests/demo/2026-05-03-daily.md', digest('2026-05-03', 'Latest status', '[Decision](../../projects/demo/decisions/one.md#why)'));
  f.write('digests/demo/archive/2026-05-10-daily.md', digest('2026-05-10', 'Archived status', 'Archived summary'));
  f.git('add', '.');
  f.git('-c', 'user.name=Test', '-c', 'user.email=test@example.test', 'commit', '-m', 'test: pending digest');
  f.git('switch', 'main');
  const out = join(f.root, 'digest.html');
  const rendered = f.run('render-digest.mjs', 'demo', out, '--instance', f.root, '--ref', 'digest/demo/pending', '--quiet', 'No changes <today>');
  success(rendered);
  const html = readFileSync(out, 'utf8');
  assert.match(html, /<h1>Demo log<\/h1>/);
  assert.match(html, /No changes &lt;today>/);
  assert.match(html, /Latest status/);
  assert.doesNotMatch(html, /Middle status|Old status|Old summary|Archived status|Archived summary/);
  assert.match(html, /Middle summary/);
  assert.match(html, /PR open/);
  assert.match(html, /<span class="chip">baseline<\/span>/);
  assert.ok(html.includes(`href="${web}/blob/digest/demo/pending/digests/demo/2026-05-03-daily.md">source</a>`));
  assert.ok(html.includes(`href="${web}/blob/digest/demo/pending/projects/demo/decisions/one.md#why"`));
  assert.ok(html.indexOf('2026-05-03-daily') < html.indexOf('2026-05-02-daily'));
  assert.match(rendered.stdout, /2 digest\(s\), newest 2026-05-03-daily.md, quiet note/);
  assert.match(html, /Older digests:/);
  f.write('digests/demo/2026-05-04-daily.md', digest('2026-05-04', '#99', 'New summary'));
  const stopped = f.run('render-digest.mjs', 'demo', out, '--instance', f.root);
  assert.equal(stopped.status, 1);
  assert.match(stopped.stderr, /render stopped: 2026-05-04-daily.md has 1 unlinked artifact/);
});

test('explicit missing or invalid pattern config fails rather than silently using defaults', (t) => {
  const f = fixture(t);
  const src = f.write('entry.md', digest('2026-05-02', 'Ready', 'Done'));
  const missing = f.run('render-digest.mjs', '--check', src, '--config', join(f.root, 'missing.md'));
  assert.equal(missing.status, 1);
  assert.match(missing.stderr, /ENOENT/);
  const cfg = f.write('DIGEST.md', '---\nlink_patterns: [{"kind":"invalid","pattern":"["}]\n---\n');
  const invalid = f.run('render-digest.mjs', '--check', src, '--config', cfg);
  assert.equal(invalid.status, 1);
  assert.match(invalid.stderr, /Invalid regular expression/);
  for (const patterns of [
    '{}',
    '\n  - kind: missing pattern',
    '\n  - null',
    '\n  - kind: invalid\n    pattern: 42',
  ]) {
    f.write('DIGEST.md', `---\nlink_patterns: ${patterns}\n---\n`);
    const malformed = f.run('render-digest.mjs', '--check', src, '--config', cfg);
    assert.equal(malformed.status, 1);
    assert.match(malformed.stderr, /link_patterns.*(list|nonempty kind and pattern)/);
  }
  f.write('DIGEST.md', '---\nlink_patterns: [\n---\n');
  const malformedYaml = f.run('render-digest.mjs', '--check', src, '--config', cfg);
  assert.equal(malformedYaml.status, 1);
  assert.match(malformedYaml.stderr, /invalid frontmatter:/);
});
