import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync, symlinkSync, cpSync, realpathSync, readdirSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { execFileSync, spawnSync } from 'node:child_process';
import { parseFrontmatter, rewriteRelativeLinks } from '../scripts/lib/render-common.mjs';

const engine = fileURLToPath(new URL('../', import.meta.url));
const web = 'https://code.example.test/org/context';
function fixture(t) {
  const root = realpathSync(mkdtempSync(join(tmpdir(), 'hoffice-render-')));
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

for (const prefix of ['', 'memory space/hoffice/']) {
for (const authority of ['draft', 'authoritative: deployment policy']) {
  test(`published CLI at ${prefix || "root"} renders ${authority} metadata, tables, diagrams, and source-relative links outside the engine`, (t) => {
    const f = fixture(t);
    f.git('symbolic-ref', 'refs/remotes/origin/HEAD', 'refs/remotes/origin/trunk');
    const src = f.write(`${prefix}projects/demo/published/report.md`, `---
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
    symlinkSync(join(f.root, prefix, 'projects'), join(f.root, prefix, 'alias'), 'dir');
    const result = f.run('render-published.mjs', src.replace('/projects/', '/alias/'), out);
    success(result);
    const html = readFileSync(out, 'utf8');
    assert.match(html, /<h1>Progress &lt;review><\/h1>/);
    assert.ok(html.includes(`Audience: Readers &amp; writers. Authority: ${authority}.`));
    assert.match(html, /<h2>Changes<\/h2>/);
    assert.match(html, /<td>Ready<\/td>/);
    assert.match(html, /<figure class="fig"><div class="node base">Flow/);
    assert.ok(html.includes(`href="${web}/blob/trunk/${encodeURI(prefix)}projects/demo/notes/design.md#choice"`));
    assert.ok(html.includes('href="https://docs.example.test/"'));
    assert.match(result.stdout, /1 h2, 1 figures, 1 tables/);
  });
}

}

for (const prefix of ['', 'memory %20 space/hoffice/']) {
  test(`relative-link rewriting at ${prefix || 'root'} preserves escapes, anchors, external links, and parent segments`, (t) => {
    const f = fixture(t);
    const src = f.write(`${prefix}projects/demo/published/a.md`, 'Source');
    const actual = rewriteRelativeLinks('[parent](../notes/a.md#part) [design](../notes/design%20doc.md#part) [local](./b.md) [anchor](#here) [remote](https://docs.example.test/x)',
      src, { root: f.root, blobBase: `${web}/blob/main/` });
    const urlPrefix = prefix ? 'memory%20%2520%20space/hoffice/' : '';
    assert.equal(actual, `[parent](${web}/blob/main/${urlPrefix}projects/demo/notes/a.md#part) [design](${web}/blob/main/${urlPrefix}projects/demo/notes/design%20doc.md#part) [local](${web}/blob/main/${urlPrefix}projects/demo/published/b.md) [anchor](#here) [remote](https://docs.example.test/x)`);
  });
}

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

for (const prefix of ['', 'memory space/hoffice/']) {
test(`digest and discovery at ${prefix || 'root'} render rolling history and open-ref sources with relative links`, (t) => {
  const f = fixture(t);
  const instance = resolve(f.root, prefix);
  cpSync(join(engine, 'templates/instance'), instance, { recursive: true });
  const write = (path, text) => f.write(`${prefix}${path}`, text);
  write('repos/org--context.md', '| Origin | `https://code.example.test/org/context.git` |\n| Projects | `projects/demo/` |\n');
  mkdirSync(join(instance, 'projects/demo'), { recursive: true });
  const env = { ...process.env, HOFFICE_DIR: instance };
  const discovered = execFileSync(join(engine, 'scripts/hoffice-instances.sh'), { env, encoding: 'utf8' });
  assert.equal(discovered, `${instance}\n`);
  const project = execFileSync(join(engine, 'scripts/hoffice-project-for-repo.sh'), [f.root], { env, encoding: 'utf8' });
  assert.equal(project, `${instance}\tdemo\n`);
  write('digests/demo/DIGEST.md', '---\ntitle: Demo log\nrolling_days: 2\n---\n');
  write('digests/demo/2026-05-01-daily.md', digest('2026-05-01', 'Old status', 'Old summary'));
  write('digests/demo/2026-05-02-daily.md', digest('2026-05-02', 'Middle status', 'Middle summary'));
  f.git('add', '.');
  f.git('-c', 'user.name=Test', '-c', 'user.email=test@example.test', 'commit', '-m', 'test: baseline');
  f.git('switch', '-c', 'digest/demo/pending');
  write('digests/demo/2026-05-03-daily.md', digest('2026-05-03', 'Latest status', '[Decision](../../projects/demo/decisions/one.md#why)'));
  write('digests/demo/archive/2026-05-10-daily.md', digest('2026-05-10', 'Archived status', 'Archived summary'));
  f.git('add', '.');
  f.git('-c', 'user.name=Test', '-c', 'user.email=test@example.test', 'commit', '-m', 'test: pending digest');
  f.git('switch', 'main');
  const out = join(f.root, 'digest.html');
  const rendered = f.run('render-digest.mjs', 'demo', out, '--instance', instance, '--ref', 'digest/demo/pending', '--quiet', 'No changes <today>');
  success(rendered);
  const html = readFileSync(out, 'utf8');
  assert.match(html, /<h1>Demo log<\/h1>/);
  assert.match(html, /No changes &lt;today>/);
  assert.match(html, /Latest status/);
  assert.doesNotMatch(html, /Middle status|Old status|Old summary|Archived status|Archived summary/);
  assert.match(html, /Middle summary/);
  assert.match(html, /PR open/);
  assert.match(html, /<span class="chip">baseline<\/span>/);
  assert.ok(html.includes(`href="${web}/blob/digest/demo/pending/${prefix}digests/demo/2026-05-03-daily.md">source</a>`));
  assert.ok(html.includes(`href="${web}/blob/digest/demo/pending/${encodeURI(prefix)}projects/demo/decisions/one.md#why"`));
  assert.ok(html.indexOf('2026-05-03-daily') < html.indexOf('2026-05-02-daily'));
  assert.match(rendered.stdout, /2 digest\(s\), newest 2026-05-03-daily.md, quiet note/);
  assert.match(html, /Older digests:/);
  assert.ok(html.includes(`href="${web}/tree/main/${prefix}digests/demo"`));
  assert.ok(html.includes(`href="${web}/blob/main/${prefix}digests/demo/2026-05-02-daily.md">source</a>`));
  write('digests/demo/2026-05-04-daily.md', digest('2026-05-04', '#99', 'New summary'));
  const stopped = f.run('render-digest.mjs', 'demo', out, '--instance', instance);
  assert.equal(stopped.status, 1);
  assert.match(stopped.stderr, /render stopped: 2026-05-04-daily.md has 1 unlinked artifact/);
});
}

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

function dashboardFixture(t, prefix = '') {
  const f = fixture(t);
  f.git('remote', 'remove', 'origin'); // Rendering needs only the local registry.
  const instance = resolve(f.root, prefix);
  const write = (path, text) => f.write(`${prefix}${path}`, text);
  write('HOFFICE.md', '---\nname: Example registry\n---\n');
  const out = realpathSync(mkdtempSync(join(tmpdir(), 'hoffice-dashboard output-')));
  t.after(() => rmSync(out, { recursive: true, force: true }));
  const render = () => f.run('render-dashboard.mjs', '--instance', instance, out);
  const html = (path = 'index.html') => readFileSync(join(out, path), 'utf8');
  return { ...f, instance, out, write, render, html };
}

function filesUnder(root) {
  return Object.fromEntries(readdirSync(root, { recursive: true }).sort()
    .filter(path => !path.split('/').includes('.git') && statSync(join(root, path)).isFile())
    .map(path => [path, readFileSync(join(root, path), 'utf8')]));
}

function assertLocalHrefsWork(html, page) {
  const hrefs = [...html.matchAll(/href="([^"]+)"/g)].map(match => match[1].replaceAll('&amp;', '&'));
  assert.ok(hrefs.length > 0, `no links in ${page}`);
  for (const href of hrefs) {
    const url = new URL(href, pathToFileURL(page));
    assert.ok(['file:', 'https:', 'http:'].includes(url.protocol), `unsafe href: ${href}`);
    if (url.protocol === 'file:') assert.ok(statSync(fileURLToPath(url)).isFile(), `broken local href: ${href}`);
  }
}

for (const prefix of ['', 'memory space/hoffice/']) {
  test(`dashboard at ${prefix || 'root'} renders a multi-project registry with deterministic output and working local hrefs`, (t) => {
    const f = dashboardFixture(t, prefix);
    // Write in reverse order to catch filesystem-order-dependent output.
    f.write('projects/zeta/README.md', '# Zeta example\n\n| Field | Value |\n|---|---|\n| Owner | Second owner |\n');
    f.write('projects/alpha/README.md', `# Alpha example
| Field | Value |
|---|---|
| Owner | First owner |
| Repos | \`repos/shared.md\` |
| Documents | \`DOCS.md\` |
| Tracker | [Work queue](https://tracker.example.test/alpha) |
| Channels | [Discussion](https://chat.example.test/alpha) |
`);
    f.write('projects/alpha/STATE.md', `# Current state
Last reviewed: 2026-05-02 by Example author.
## Summary
Authored summary with [design](notes/design%20notes.md#choice).
## Open questions
Who reviews the draft?
## Next steps
- Review the draft.
- [x] Circulate the outline.
## Architecture
Architecture stays in the source.
`);
    f.write('projects/alpha/notes/design notes.md', '# Design\n\n## Choice\n');
    f.write('projects/alpha/DOCS.md', '# Registry\n');
    f.write('repos/shared.md', '# Shared repository\n\n| Field | Value |\n|---|---|\n| Origin | [Source](https://code.example.test/org/shared) |\n| Projects | `projects/alpha/`, `projects/zeta/` |\n');
    f.write('repos/alpha.md', '# Alpha repository\n\n| Field | Value |\n|---|---|\n| Projects | `projects/alpha/` |\n');
    f.write('repos/unrelated.md', '# Unrelated repository\n\n| Field | Value |\n|---|---|\n| Projects | `projects/alphabeta/` |\n');
    const before = filesUnder(f.instance);
    success(f.render());
    const index = f.html(), alpha = f.html('projects/alpha.html'), zeta = f.html('projects/zeta.html');
    assert.ok(index.indexOf('Alpha example') < index.indexOf('Zeta example'));
    assert.ok(index.includes('href="projects/alpha.html"'));
    assert.ok(index.includes('href="projects/zeta.html"'));
    assert.match(index, /2026-05-02/);
    assert.match(index, /Dates below are authored STATE review dates, not refresh times/);
    assert.ok(index.includes('href="https://tracker.example.test/alpha"'));
    assert.ok(index.includes('href="https://chat.example.test/alpha"'));
    assert.match(alpha, /First owner/);
    assert.match(alpha, /Authored summary/);
    assert.match(alpha, /Who reviews the draft\?/);
    assert.match(alpha, /Review the draft/);
    assert.ok(alpha.indexOf('Next steps') < alpha.indexOf('Authored summary'), 'next steps lead the project page');
    assert.match(alpha, /<li class="task"><input type="checkbox" disabled aria-label="Open"><div>Review the draft\.<\/div><\/li>/);
    assert.match(alpha, /<li class="task done"><input type="checkbox" disabled checked aria-label="Done"><div>Circulate the outline\.<\/div><\/li>/);
    assert.match(index, /1 open · 1 done/);
    assert.doesNotMatch(alpha, /Architecture stays in the source|Unrelated repository|Second owner/);
    assert.match(alpha, /Alpha repository/);
    assert.match(alpha, /Shared repository/);
    assert.match(zeta, /Shared repository/);
    assert.doesNotMatch(zeta, /Alpha repository|Unrelated repository|First owner/);
    // Instance Markdown links open rendered pages; those pages link back to the raw source.
    assert.ok(alpha.includes('href="../source/projects/alpha/notes/design%20notes.md.html#choice"'));
    assert.ok(alpha.includes('href="../source/repos/shared.md.html"'));
    const state = f.html('source/projects/alpha/STATE.md.html');
    assert.match(state, /<h2[^>]*>Architecture<\/h2>/);
    assert.match(state, /Architecture stays in the source/);
    assert.ok(state.includes('href="notes/design%20notes.md.html#choice"'));
    assert.ok(state.includes(`href="${pathToFileURL(join(f.instance, 'projects/alpha/STATE.md')).href}"`));
    assert.ok(state.includes('href="../../../projects/alpha.html"'), 'source page links back to its project');
    assertLocalHrefsWork(state, join(f.out, 'source/projects/alpha/STATE.md.html'));
    for (const [path, html] of [['index.html', index], ['projects/alpha.html', alpha], ['projects/zeta.html', zeta]]) {
      assert.match(html, /Registry only/);
      assert.match(html, /No remote sources were queried/);
      assertLocalHrefsWork(html, join(f.out, path));
    }
    const firstOutput = filesUnder(f.out);
    assert.deepEqual(Object.keys(firstOutput), ['index.html', 'projects/alpha.html', 'projects/zeta.html',
      'source/HOFFICE.md.html', 'source/projects/alpha/DOCS.md.html', 'source/projects/alpha/README.md.html', 'source/projects/alpha/STATE.md.html',
      'source/projects/alpha/notes/design notes.md.html', 'source/projects/zeta/README.md.html',
      'source/repos/alpha.md.html', 'source/repos/shared.md.html', 'source/repos/unrelated.md.html']);
    success(f.render());
    assert.deepEqual(filesUnder(f.out), firstOutput, 'unchanged inputs produce byte-identical pages');
    assert.deepEqual(filesUnder(f.instance), before, 'rendering does not change instance sources');
  });
}

test('dashboard tolerates absent optional project files and empty registries without inventing status', (t) => {
  const f = dashboardFixture(t);
  success(f.render());
  assert.match(f.html(), /No projects registered/);
  mkdirSync(join(f.instance, 'projects/bare'), { recursive: true });
  f.write('projects/minimal/README.md', '# Minimal example\n');
  f.write('projects/minimal/STATE.md', '# State\nLast reviewed: 2026-02-30\n');
  success(f.render());
  for (const slug of ['bare', 'minimal']) {
    const html = f.html(`projects/${slug}.html`);
    assert.match(html, /Registry fields unavailable/);
    assert.match(html, /No repository cards registered/);
    assert.match(html, /Authoritative documents unavailable/);
    assert.match(html, /Last reviewed: <span class="muted">Unavailable<\/span>/);
    assert.match(html, /<h2>Summary<\/h2><div class="prose"><p class="muted">Unavailable\.<\/p>/);
    assert.match(html, /<h2>Latest digests<\/h2><p><span class="muted">Unavailable<\/span>/);
    assert.doesNotMatch(html, /2026-02-30|href="[^"]*(?:DOCS|DIGEST)\.md/);
    assertLocalHrefsWork(html, join(f.out, `projects/${slug}.html`));
  }
  assert.match(f.html('projects/bare.html'), /<h1>bare<\/h1>/);
});

test('dashboard associates digests through config and selects the latest valid period_end, not filename', (t) => {
  const f = dashboardFixture(t);
  for (const slug of ['alpha', 'beta', 'daily']) f.write(`projects/${slug}/README.md`, `# ${slug}\n`);
  f.write('digests/daily/DIGEST.md', '---\ntitle: Shared activity\nprojects:\n  - name: alpha\n  - name: beta\n---\n');
  const latest = f.write('digests/daily/2026-01-01-daily.md', digest('2026-05-03T23:00:00Z', 'Status not summary', 'Newest valid summary'));
  f.write('digests/daily/2026-12-31-daily.md', digest('2026-05-03T01:00:00Z', 'Old status', 'Older same-day summary'));
  f.write('digests/daily/2026-12-30-daily.md', digest('2026-02-30', 'Invalid status', 'Invalid date summary'));
  f.write('digests/daily/2026-12-30-daily.md', digest('2026-11-31', 'Invalid status', 'Invalid date summary'));
  f.write('digests/daily/2026-12-28-daily.md', '# No frontmatter\n## Summary\nMissing metadata summary\n');
  f.write('digests/daily/archive/2026-12-31-daily.md', digest('2026-12-31', 'Archived', 'Archived summary'));
  f.write('digests/daily/README.md', digest('2026-12-31', 'Not an entry', 'Undated file summary'));
  f.write('digests/unconfigured/2026-12-31-daily.md', digest('2026-12-31', 'Unconfigured', 'Unconfigured summary'));
  f.write('digests/broken/DIGEST.md', '---\nprojects: [\n---\n');
  const result = f.render();
  success(result);
  assert.match(result.stderr, /skipped digest: invalid period_end/);
  assert.match(result.stderr, /skipped digest: missing frontmatter/);
  assert.match(result.stderr, /skipped digest configuration/);
  for (const slug of ['alpha', 'beta']) {
    const html = f.html(`projects/${slug}.html`);
    assert.match(html, /Shared activity \(2026-05-03\)/);
    assert.match(html, /Newest valid summary/);
    assert.ok(html.includes('href="../source/digests/daily/2026-01-01-daily.md.html"'));
    assert.ok(f.html('source/digests/daily/2026-01-01-daily.md.html').includes(`href="${pathToFileURL(latest).href}"`));
    assert.doesNotMatch(html, /Older same-day summary|Invalid date summary|Malformed date summary|Missing metadata summary|Archived summary|Undated file summary|Unconfigured summary|Status not summary/);
    assertLocalHrefsWork(html, join(f.out, `projects/${slug}.html`));
  }
  assert.doesNotMatch(f.html('projects/daily.html'), /Shared activity|Newest valid summary/);
});

test('dashboard shows only explicitly authoritative document rows', (t) => {
  const f = dashboardFixture(t);
  f.write('projects/alpha/README.md', '# Alpha\n');
  f.write('projects/alpha/DOCS.md', `# Documents
| Doc | Type | Link | Owner | Authority |
|---|---|---|---|---|
| Accepted design | TDD | [Design](https://docs.example.test/design#choice) | Example owner | authoritative: architecture |
| Accepted policy | spec | [Policy](https://docs.example.test/policy) | Policy owner | Authoritative: policy |
| Draft design | TDD | [Draft](https://docs.example.test/draft) | Draft owner | draft |
| Background note | research note | [Note](https://docs.example.test/note) | Note owner | informational |
| Retired spec | spec | [Old](https://docs.example.test/old) | Old owner | superseded |
| Unscoped authority | spec | [Unscoped](https://docs.example.test/unscoped) | Unknown | authoritative |
`);
  f.write('projects/beta/README.md', '# Beta\n');
  f.write('projects/beta/DOCS.md', '| Doc | Authority |\n|---|---|\n| Draft only | draft |\n');
  success(f.render());
  const html = f.html('projects/alpha.html');
  assert.match(html, /Accepted design/);
  assert.match(html, /Example owner/);
  assert.match(html, /authoritative: architecture/);
  assert.match(html, /Accepted policy/);
  assert.ok(html.includes('href="https://docs.example.test/design#choice"'));
  assert.doesNotMatch(html, /Draft design|Background note|Retired spec|Unscoped authority|docs\.example\.test\/(draft|note|old|unscoped)/);
  assert.match(f.html('projects/beta.html'), /No authoritative documents registered/);
});

test('dashboard escapes source content and drops unsafe or missing link targets without losing labels', (t) => {
  const f = dashboardFixture(t, 'memory space/hoffice/');
  f.write('projects/unsafe/README.md', `# Example <script>alert(1)</script> & "review"
| Field | Value |
|---|---|
| Owner | <img src=x onerror=alert(1)> |
| Tracker | [Unsafe tracker](javascript:alert%281%29) |
| Channels | [Safe channel](https://chat.example.test/?a=1&b=2) |
`);
  f.write('projects/unsafe/STATE.md', `# State
## Summary
<script>alert(2)</script>
[Unsafe script](javascript:alert%282%29) [Unsafe data](data:text/html,evil) [Unsafe file transfer](ftp://files.example.test/x)
[Missing local](notes/missing.md) ![Image label](https://images.example.test/x.png)
## Open questions
[Safe document](https://docs.example.test/?a=1&b=2)
`);
  f.write('projects/unsafe/DOCS.md', '| Doc | Link | Owner | Authority |\n|---|---|---|---|\n| <svg onload=alert(3)> | [Unsafe doc](javascript:alert%283%29) | A & B | authoritative: safety |\n');
  f.write('digests/activity/DIGEST.md', '---\ntitle: "Activity <img src=x> & review"\nprojects:\n  - name: unsafe\n---\n');
  f.write('digests/activity/2026-05-02-daily.md', digest('2026-05-02', 'Unused', '<img src=x onerror=alert(4)> [Unsafe digest](data:text/html,evil)'));
  success(f.render());
  const html = f.html('projects/unsafe.html');
  for (const page of [f.html(), html]) {
    assert.doesNotMatch(page, /<(?:script|img|svg)\b/i);
    assert.doesNotMatch(page, /href="(?:javascript|data|ftp):/i);
    assert.match(page, /Example &lt;script>alert\(1\)&lt;\/script> &amp; &quot;review&quot;/);
    assertLocalHrefsWork(page, join(f.out, page === html ? 'projects/unsafe.html' : 'index.html'));
  }
  assert.match(html, /&lt;img src=x onerror=alert\(1\)>/);
  assert.match(html, /&lt;script>alert\(2\)&lt;\/script>/);
  assert.match(html, /&lt;svg onload=alert\(3\)>/);
  assert.match(html, /Activity &lt;img src=x> &amp; review/);
  assert.match(html, /&lt;img src=x onerror=alert\(4\)>/);
  for (const label of ['Unsafe tracker', 'Unsafe script', 'Unsafe data', 'Unsafe file transfer', 'Missing local', 'Image label', 'Unsafe doc', 'Unsafe digest']) {
    assert.ok(html.includes(label), `lost label: ${label}`);
  }
  assert.doesNotMatch(html, /href="[^"]*notes\/missing\.md/);
  // Rendered source pages, including frontmatter properties, get the same escaping and link filtering.
  for (const path of Object.keys(filesUnder(join(f.out, 'source')))) {
    const page = f.html(`source/${path}`);
    assert.doesNotMatch(page, /<(?:script|img|svg)\b/i, path);
    assert.doesNotMatch(page, /href="(?:javascript|data|ftp):/i, path);
    assertLocalHrefsWork(page, join(f.out, 'source', path));
  }
  assert.match(f.html('source/digests/activity/DIGEST.md.html'), /Activity &lt;img src=x> &amp; review/);
  assert.ok(html.includes('href="https://docs.example.test/?a=1&amp;b=2"'));
  assert.ok(f.html().includes('href="https://chat.example.test/?a=1&amp;b=2"'));
});

test('dashboard rejects invalid invocation, unmarked roots and output paths that could overwrite instance sources', (t) => {
  const f = dashboardFixture(t);
  f.write('projects/alpha/README.md', '# Alpha\n');
  const before = filesUnder(f.instance);
  const usage = f.run('render-dashboard.mjs');
  assert.equal(usage.status, 2);
  assert.match(usage.stderr, /usage: render-dashboard\.mjs --instance/);
  const unmarked = f.write('unmarked/README.md', '# Not an instance\n');
  const missingMarker = f.run('render-dashboard.mjs', '--instance', resolve(unmarked, '..'), f.out);
  assert.equal(missingMarker.status, 1);
  assert.match(missingMarker.stderr, /instance root must contain HOFFICE\.md/);
  rmSync(resolve(unmarked, '..'), { recursive: true });
  symlinkSync(f.instance, join(f.out, 'instance-alias'), 'dir');
  for (const out of [f.instance, join(f.instance, 'generated'), join(f.out, 'instance-alias', 'generated')]) {
    const result = f.run('render-dashboard.mjs', '--instance', f.instance, out);
    assert.equal(result.status, 1, `unsafe output accepted: ${out}`);
    assert.match(result.stderr, /output directory must be outside the instance/);
  }
  assert.deepEqual(filesUnder(f.instance), before);
});

test('dashboard rejects ancestor output without overwriting instance files', (t) => {
  const f = dashboardFixture(t, 'projects/');
  f.write('projects/alpha/README.md', '# Alpha\n');
  f.write('alpha.html', 'SENTINEL');
  const before = filesUnder(f.instance);
  const result = f.run('render-dashboard.mjs', '--instance', f.instance, f.root);
  assert.equal(result.status, 1);
  assert.match(result.stderr, /output directory must be outside the instance/);
  assert.deepEqual(filesUnder(f.instance), before);
});

for (const destination of ['index.html', 'projects', 'projects/alpha.html', 'source']) {
  test(`dashboard rejects a symlink at output ${destination} before writing any pages`, (t) => {
    const f = dashboardFixture(t);
    f.write('projects/alpha/README.md', '# Alpha sentinel\n');
    f.write('projects/zeta/README.md', '# Zeta sentinel\n');
    const before = filesUnder(f.instance);
    const sentinel = destination === 'projects' ? join(f.instance, 'projects') : join(f.instance, 'HOFFICE.md');
    if (destination === 'projects/alpha.html') mkdirSync(join(f.out, 'projects'));
    symlinkSync(sentinel, join(f.out, destination), destination === 'projects' ? 'dir' : 'file');
    const result = f.render();
    assert.equal(result.status, 1, `output symlink accepted: ${destination}`);
    assert.match(result.stderr, /output destination must not be a symlink/);
    assert.deepEqual(filesUnder(f.instance), before, 'all instance sentinels must remain unchanged');
    assert.deepEqual(readdirSync(f.out).sort(), [destination === 'index.html' || destination === 'source' ? destination : 'projects']);
    if (destination === 'projects/alpha.html') {
      assert.deepEqual(readdirSync(join(f.out, 'projects')), ['alpha.html'], 'no other project pages written before rejection');
    }
  });
}

function variantFixture(t) {
  const f = dashboardFixture(t);
  f.write('projects/alpha/README.md', '# Alpha <one>\n\nAlpha lead.\n\n| Field | Value |\n|---|---|\n| Tracker | [Board](https://tracker.example.test/alpha) |\n');
  f.write('projects/alpha/STATE.md', '# Alpha state\n\nLast reviewed: 2026-05-01 by test.\n\n## Summary\n\nAlpha summary.\n\n## Open questions\n\n- Which <way>?\n\n## Next steps\n\n- [x] Ship the first part\n- Write the [design](notes/design.md)\n');
  f.write('projects/alpha/notes/design.md', '# Design note\n');
  f.write('projects/alpha/sessions/2026-05-02-kickoff.md', '# Kickoff\n');
  f.write('projects/beta/README.md', '# Beta\n');
  f.write('projects/beta/STATE.md', '# Beta state\n\n## Next steps\n\nNone agreed. [bad](file:///tmp/%2Fbad)\n');
  // Hostile directory names: project slugs and document kinds come straight from the filesystem.
  f.write('projects/q"<s>/README.md', '# Hostile\n');
  f.write('projects/q"<s>/STATE.md', '# State\n\n## Next steps\n\n- Step\n\n## Open questions\n\n- Q\n');
  f.write('projects/q"<s>/n"<k>/2026-05-03-x.md', '# X\n');
  return f;
}

test('a variant module restyles and replaces dashboard pages and adds its own pages', (t) => {
  const f = variantFixture(t);
  const variant = f.write('variant.mjs', `export const css = '.mine{}';
export const script = 'window.mine = 1;';
export function index(ctx) { return { title: 'Mine', crumbs: ['Mine'], body: ctx.projects.map(p => ctx.link(p.title, ctx.hrefTo('index.html', p.page)) + p.stepItems.length).join('') }; }
export function project(p, ctx) { const page = ctx.defaults.project(p, ctx); return { ...page, body: '<p id="custom"></p>' + page.body }; }
export function pages(ctx) { return [{ path: 'extra/all.html', title: 'All', crumbs: [ctx.indexCrumb('extra/all.html')], body: String(ctx.docs.length) }]; }
`);
  success(f.run('render-dashboard.mjs', '--instance', f.instance, '--variant', variant, f.out));
  const index = f.html();
  assert.match(index, /\.mine\{\}/);
  assert.match(index, /<script>window\.mine = 1;<\/script>/);
  assert.match(index, />Alpha &lt;one><\/a>2/);
  assert.match(f.html('projects/alpha.html'), /<p id="custom"><\/p><div class="head"><h1>Alpha &lt;one><\/h1>/);
  assert.match(f.html('extra/all.html'), /<a href="\.\.\/index\.html">Projects<\/a>/);
  for (const page of ['index.html', 'projects/alpha.html', 'extra/all.html']) assertLocalHrefsWork(f.html(page), join(f.out, page));

  for (const [body, error] of [
    [`export function pages() { return [{ path: '../escape.html', title: 'x', body: '' }]; }`, /must stay inside the output/],
    [`export function pages() { return [{ path: 'index.html', title: 'x', body: '' }]; }`, /two pages render to index\.html/],
  ]) {
    const out = join(f.out, 'bad');
    const bad = f.write('bad.mjs', body);
    const result = f.run('render-dashboard.mjs', '--instance', f.instance, '--variant', bad, out);
    assert.equal(result.status, 1);
    assert.match(result.stderr, error);
    assert.throws(() => statSync(out), /ENOENT/);
  }
});

test('render-prototypes renders every bundled variant with a manifest and working local links', (t) => {
  const f = variantFixture(t);
  const variants = join(engine, 'prototypes', 'dashboard');
  const result = f.run('render-prototypes.mjs', '--instance', f.instance, '--out', f.out, '--baseline', variants);
  success(result);
  const manifest = JSON.parse(readFileSync(join(f.out, 'prototypes.json'), 'utf8'));
  const modules = readdirSync(variants).filter(n => n.endsWith('.mjs') && !n.startsWith('_'));
  assert.equal(manifest.prototypes.length, modules.length + 1);
  assert.equal(manifest.prototypes[0].baseline, true);
  for (const p of manifest.prototypes) {
    assert.ok(p.title && p.entry === `${p.id}/index.html`, JSON.stringify(p));
    if (!p.baseline) assert.ok(p.approach && p.differences.length && p.features.length, `${p.id} needs approach, differences and features`);
    for (const page of ['index.html', 'projects/alpha.html', 'projects/beta.html', 'projects/q"<s>.html', 'source/projects/alpha/STATE.md.html']) {
      const html = readFileSync(join(f.out, p.id, page), 'utf8');
      assert.doesNotMatch(html, /<way>|<one>|q"<|n"<|<s>|<k>/, `${p.id}/${page} leaks unescaped source HTML`);
      assertLocalHrefsWork(html, join(f.out, p.id, page));
    }
  }
});

test('render-prototypes refuses a symlinked manifest before rendering anything', (t) => {
  const f = variantFixture(t);
  const victim = f.write('victim.txt', 'keep');
  symlinkSync(victim, join(f.out, 'prototypes.json'));
  const result = f.run('render-prototypes.mjs', '--instance', f.instance, '--out', f.out, '--baseline');
  assert.equal(result.status, 1);
  assert.match(result.stderr, /must not be a symlink/);
  assert.equal(readFileSync(victim, 'utf8'), 'keep');
  assert.throws(() => statSync(join(f.out, 'baseline')), /ENOENT/);
});
