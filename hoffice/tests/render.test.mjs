import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync, symlinkSync, cpSync, realpathSync, readdirSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { execFileSync, spawnSync } from 'node:child_process';
import { parseFrontmatter, rewriteRelativeLinks } from '../scripts/lib/render-common.mjs';
import { renderDashboard } from '../scripts/lib/dashboard.mjs';

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
  const render = (...args) => f.run('render-dashboard.mjs', '--instance', instance, out, ...args);
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
    assert.ok(index.indexOf('Zeta example') < index.indexOf('Alpha example'), 'more reasons rank first');
    assert.ok(index.includes('href="projects/alpha.html"'));
    assert.ok(index.includes('href="projects/zeta.html"'));
    assert.match(alpha, /STATE reviewed/);
    assert.match(index, /Projects ranked by what needs a look/);
    assert.doesNotMatch(index, /<h2 class="sh">Sessions<\/h2>/);
    assert.ok(index.includes('href="https://tracker.example.test/alpha"'));
    assert.ok(index.includes('href="https://chat.example.test/alpha"'));
    assert.match(alpha, /First owner/);
    assert.match(alpha, /Authored summary/);
    assert.match(alpha, /Who reviews the draft\?/);
    assert.match(alpha, /Review the draft/);
    assert.ok(alpha.indexOf('Next steps') < alpha.indexOf('Authored summary'), 'next steps lead the project page');
    assert.match(alpha, /<li class="task"><input type="checkbox" disabled aria-label="Open"><div>Review the draft\.<\/div><\/li>/);
    assert.match(alpha, /<li class="task done"><input type="checkbox" disabled checked aria-label="Done"><div>Circulate the outline\.<\/div><\/li>/);
    assert.match(index, /1 open/);
    assert.match(alpha, /<summary>1 done<\/summary>/);
    assert.doesNotMatch(alpha, /Unrelated repository|Second owner/);
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
      assert.match(html, /class="ws"/);
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

test('dashboard roster lists every role on Overview and only project roles beside project health', (t) => {
  const f = dashboardFixture(t);
  for (const slug of ['alpha', 'beta']) f.write(`projects/${slug}/README.md`, `# ${slug}\n`);
  success(f.render());
  const baseline = f.html();
  assert.ok(baseline.indexOf('data-p="alpha"') < baseline.indexOf('data-p="beta"'));
  const roster = {
    generatedAt: '2026-05-03T18:00:00Z',
    roles: [
      { id: 'chief', name: 'Chief <staff>', project: null, live: true, beat: '2026-05-02T17:58:00Z', link: 'https://example.test/s/1?a=1&b=2', generation: 2, openItems: 3 },
      { id: 'lead-a', name: 'Alpha lead', project: 'alpha', live: true, beat: '2026-05-03T18:00:00Z', link: 'session://example/alpha', generation: 4, openItems: 5 },
      { id: 'lead-b', name: 'Beta lead', project: 'beta', live: false, beat: null, link: 'javascript:alert("unsafe")', generation: 0, openItems: 0 },
      { id: 'unknown', name: 'Unknown lead', project: 'missing<project>', live: false, beat: null, link: null, generation: 0, openItems: 0 },
    ],
  };
  const path = f.write('roster.json', JSON.stringify(roster));
  success(f.render('--roster', path));
  const overview = f.html().split('<section class="view" id="v-alpha"')[0];
  for (const name of ['Chief &lt;staff>', 'Alpha lead', 'Beta lead', 'Unknown lead']) assert.ok(overview.includes(`<td>${name}</td>`));
  assert.ok(overview.indexOf('Session stale: Beta lead') < overview.indexOf('<h2 class="sh">Sessions</h2>'));
  assert.match(overview, /<td>missing&lt;project> \(unknown\)<\/td>/);
  assert.match(overview, /href="#v-alpha">alpha<\/a>/);
  assert.match(overview, /href="https:\/\/example.test\/s\/1\?a=1&amp;b=2"/);
  assert.doesNotMatch(overview, /href="(?:javascript|session):/);
  assert.match(overview, /javascript:alert\(&quot;unsafe&quot;\)/);
  assert.match(overview, /<td>stale<\/td><td>never<\/td><td>0<\/td><td>0<\/td>/);
  assert.match(f.html('projects/beta.html'), /ws-dot hi" title="Session stale: Beta lead;/);
  assert.ok(f.html().indexOf('data-p="beta"') < f.html().indexOf('data-p="alpha"'), 'stale role raises attention ranking');
  for (const [slug, own, other] of [['alpha', 'Alpha lead', 'Beta lead'], ['beta', 'Beta lead', 'Alpha lead']]) {
    const page = f.html(`projects/${slug}.html`);
    assert.match(page, new RegExp(`<td>${own}</td>`));
    assert.ok(page.indexOf('<h2 class="sh">Sessions</h2>') < page.indexOf('<h2 class="sh">Next steps</h2>'));
    assert.ok(!page.includes(`<td>${other}</td>`));
    assert.doesNotMatch(page, /<td>Chief &lt;staff>|<td>Unknown lead/);
    assert.match(page, new RegExp(`href="../index.html#v-${slug}">${slug}</a>`));
  }
  renderDashboard({ instance: f.instance, out: f.out, roster: path, now: new Date('2026-05-04T00:00:00Z') });
  assert.match(f.html(), /Roster generated 1 day ago/);
  assert.match(f.html(), /<td>live<\/td><td>2 days ago<\/td><td>3<\/td><td>2<\/td>/);
  assert.match(f.html('projects/alpha.html'), /<td>live<\/td><td>1 day ago<\/td><td>5<\/td><td>4<\/td>/);
  roster.linkSchemes = ['HTTPS', 'session', 'javascript'];
  f.write('roster.json', JSON.stringify(roster));
  success(f.render('--roster', path));
  assert.match(f.html(), /href="session:\/\/example\/alpha"/);
  assert.match(f.html(), /href="https:\/\/example.test/);
  assert.doesNotMatch(f.html(), /href="javascript:/);
});

test('dashboard rejects malformed rosters with exit 1 and no output writes', (t) => {
  const f = dashboardFixture(t);
  f.write('projects/alpha/README.md', '# Alpha\n');
  const valid = { generatedAt: '2026-05-03T18:00:00Z', roles: [
    { id: 'lead', name: 'Lead', project: 'alpha', live: true, beat: null, link: null, generation: 0, openItems: 0 },
  ] };
  const sentinel = join(f.out, 'index.html');
  writeFileSync(sentinel, 'SENTINEL');
  const before = filesUnder(f.out);
  const cases = [
    ['{', /JSON/], ['null', /expected an object/],
    [JSON.stringify({ ...valid, generatedAt: '2026-02-30' }), /generatedAt/],
    [JSON.stringify({ ...valid, roles: {} }), /roles must be a list/],
    [JSON.stringify({ ...valid, linkSchemes: 'https' }), /linkSchemes/],
    [JSON.stringify({ ...valid, linkSchemes: ['https:'] }), /linkSchemes/],
    ...Object.entries({ id: '', name: null, project: 3, live: 'false', beat: 'invalid', link: {}, generation: -1, openItems: 1.5 })
      .map(([field, value]) => [JSON.stringify({ ...valid, roles: [{ ...valid.roles[0], [field]: value }] }), /roles\[0\]/]),
  ];
  for (const [text, error] of cases) {
    const path = f.write('roster.json', text);
    const failed = f.render('--roster', path);
    assert.equal(failed.status, 1, failed.stderr);
    assert.match(failed.stderr, /render-dashboard: invalid roster/);
    assert.match(failed.stderr, error);
    assert.equal(failed.stdout, '');
    assert.deepEqual(filesUnder(f.out), before);
  }
  const missing = f.render('--roster', join(f.root, 'missing.json'));
  assert.equal(missing.status, 1);
  assert.match(missing.stderr, /invalid roster.*ENOENT/);
  assert.deepEqual(filesUnder(f.out), before);
  const path = f.write('roster.json', JSON.stringify({ ...valid, roles: [] }));
  success(f.render('--roster', path));
  assert.match(f.html(), /<h2 class="sh">Sessions<\/h2>/);
  assert.match(f.html(), /Roster generated/);
});

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
    assert.match(html, /STATE has no review date/);
    assert.match(html, /No next steps recorded/);
    assert.match(html, /No dated notes/);
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
  renderDashboard({ instance: f.instance, out: f.out, now: new Date('2026-05-04T00:00:00Z') });
  for (const slug of ['alpha', 'beta']) {
    const html = f.html(`projects/${slug}.html`);
    assert.match(html, /daily digests/);
    assert.match(html, /<b>1 day ago<\/b><small>latest digest<\/small>/);
    assert.match(f.html('source/digests/daily/2026-01-01-daily.md.html'), /Newest valid summary/);
    assert.ok(html.includes('href="../source/digests/daily/2026-01-01-daily.md.html"'));
    assert.ok(f.html('source/digests/daily/2026-01-01-daily.md.html').includes(`href="${pathToFileURL(latest).href}"`));
    assert.doesNotMatch(html, /Unconfigured summary|Status not summary/);
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
    assert.doesNotMatch(page.replace(/<script>[\s\S]*?<\/script>/g, ''), /<(?:script|img|svg)\b/i);
    assert.doesNotMatch(page, /href="(?:javascript|data|ftp):/i);
    assert.match(page, /Example &lt;script>alert\(1\)&lt;\/script> &amp; &quot;review&quot;/);
    assertLocalHrefsWork(page, join(f.out, page === html ? 'projects/unsafe.html' : 'index.html'));
  }
  assert.match(html, /&lt;img src=x onerror=alert\(1\)>/);
  assert.match(html, /&lt;script>alert\(2\)&lt;\/script>/);
  assert.match(html, /&lt;svg onload=alert\(3\)>/);
  assert.match(f.html('source/digests/activity/DIGEST.md.html'), /Activity &lt;img src=x> &amp; review/);
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

function workspaceFixture(t) {
  const f = dashboardFixture(t);
  f.write('projects/alpha/README.md', '# Alpha <one>\n\nAlpha lead.\n\n| Field | Value |\n|---|---|\n| Tracker | [Board](https://tracker.example.test/alpha) |\n');
  f.write('projects/alpha/STATE.md', '# Alpha state\n\nLast reviewed: 2026-05-01 by test.\n\n## Summary\n\nAlpha summary.\n\n## Open questions\n\n- Which <way>?\n\n## Next steps\n\n- [x] Ship the first part\n- Write the [design](notes/design.md#the-choice)\n');
  f.write('projects/alpha/notes/design.md', '# Design note\n\n## The choice\n\n## The choice\n\n## The choice-1\n\n## See [the plan](https://plan.example.test/x)\n');
  f.write('projects/alpha/sessions/2026-05-02-kickoff.md', '# Kickoff\n');
  // Hostile front matter must stay safe when rendered as event detail.
  f.write('projects/alpha/decisions/2026-05-04-pick.md', '---\nstatus: pro<s>posed\ntags: [a<k>, "c,d"]\nprs:\n  - javascript:alert(1)\n  - "https://git.example.test/o/r/pull/7"\n---\n\n# Pick <one>\n\n## Decision\n\nUse <way> here.\n\n## Consequences\n\n- First <s>\n- Second\n- Third\n- Fourth\n');
  f.write('projects/beta/README.md', '# Beta\n');
  f.write('projects/beta/STATE.md', '# Beta state\n\n## Next steps\n\nNone agreed. [bad](file:///tmp/%2Fbad)\n');
  // Hostile directory names: project slugs and document kinds come straight from the filesystem.
  f.write('projects/q"<s>/README.md', '# Hostile\n');
  f.write('projects/q"<s>/STATE.md', '# State\n\n## Next steps\n\n- Step\n\n## Open questions\n\n- Q\n');
  f.write('projects/q"<s>/n"<k>/2026-05-03-x.md', '# X\n');
  // Kinds that collide with Object.prototype names, and slugs a lossy token encoding would merge.
  for (const kind of ['constructor', '__proto__', 'toString']) f.write(`projects/alpha/${kind}/note.md`, '# Note\n');
  for (const slug of ['x.y', 'x_2e_y', 'home']) f.write(`projects/${slug}/README.md`, `# ${slug}\n`);
  // The project named home must not collide with the Overview view.
  f.write('projects/home/sessions/2026-05-04-note.md', '# Note in home\n');
  f.write('projects/home/STATE.md', '# State\n## Next steps\n- [x] Finished already\n');
  return f;
}

test('workspace renders unique views, folded events and safe source headings for hostile paths', (t) => {
  const f = workspaceFixture(t);
  f.write('projects/alpha/notes/entities.md', '# Entities\n## Caf&#233; &#x41;\n## Café A\n## See [the plan](https://plan.example.test/x)\n');
  f.write('projects/alpha/sessions/2026-05-05-crlf.md', '---\r\ntags: [crlf]\r\n---\r\n# CRLF\r\n## Goal\r\nNormalized session.\r\n');
  f.write('projects/alpha/sessions/2026-05-06-fallback.md', '---\nprs: [\n---\n# Fallback\n## Goal\nFallback session.\n');
  success(f.render());
  const index = f.html();
  const overview = index.match(/id="v-_home">([\s\S]*?)<\/section>/)[1];
  assert.match(overview, /Write the/);
  assert.match(overview, /None agreed\./);
  assert.doesNotMatch(overview, /Finished already/);
  assert.match(index, /Normalized session\./);
  assert.match(index, /Fallback session\./);
  assert.match(index, /<section class="view" id="v-_home">/);
  assert.match(index, /<section class="view" id="v-home" hidden>/);
  // Prose next steps have no open count, and a single note reads as singular.
  assert.doesNotMatch(index.match(/href="#v-beta"[\s\S]*?<\/a>/)[0], /open/);
  assert.match(index.match(/href="#v-alpha"[\s\S]*?<\/a>/)[0], /1 open/);
  assert.match(index.match(/id="v-home"[\s\S]*?<\/section>/)[0], />1 note</);
  assert.match(index, /<noscript>[\s\S]*href="projects\/home\.html"/);
  assert.match(index, /<b>Decision\.<\/b> Use &lt;way> here\./);
  assert.match(index, /\+1 more in the full note/);
  assert.match(index, /<a href="https:\/\/git\.example\.test\/o\/r\/pull\/7">o\/r#7<\/a>/);
  assert.match(index, /<p class="d-tags"><span>a&lt;k><\/span><span>c,d<\/span><\/p>/);
  assert.match(f.html('projects/alpha.html'), /href="\.\.\/index\.html#v-beta"/);
  assert.match(f.html('source/projects/alpha/notes/design.md.html'), /<h2 id="the-choice">The choice<\/h2>\n<h2 id="the-choice-1">The choice<\/h2>\n<h2 id="the-choice-1-1">The choice-1<\/h2>\n<h2 id="see-the-plan">/);
  assert.match(f.html('source/projects/alpha/notes/entities.md.html'), /id="café-a"/);
  assert.match(f.html('source/projects/alpha/notes/entities.md.html'), /id="café-a-1"/);
  for (const [path, html] of Object.entries(filesUnder(f.out))) {
    const ids = [...html.matchAll(/ id="([^"]+)"/g)].map(m => m[1]);
    assert.equal(new Set(ids).size, ids.length, `duplicate ids in ${path}`);
    assert.doesNotMatch(html, /<way>|<one>|q"<|n"<|<s>|<k>/, path);
    assertLocalHrefsWork(html, join(f.out, path));
  }
});

test('dashboard preflights nested source symlinks before any writes', (t) => {
  const f = dashboardFixture(t);
  f.write('projects/alpha/README.md', '# Alpha\n');
  mkdirSync(join(f.out, 'source/projects/alpha'), { recursive: true });
  symlinkSync(join(f.instance, 'HOFFICE.md'), join(f.out, 'source/projects/alpha/README.md.html'));
  const result = f.render();
  assert.equal(result.status, 1);
  assert.match(result.stderr, /output destination must not be a symlink/);
  assert.deepEqual(readdirSync(f.out), ['source']);
  assert.equal(readFileSync(join(f.instance, 'HOFFICE.md'), 'utf8'), '---\nname: Example registry\n---\n');
});

test('dashboard refuses case-folded page collisions before writing', (t) => {
  const f = dashboardFixture(t);
  f.write('projects/alpha/README.md', '# Alpha\n');
  f.write('projects/ALPHA/README.md', '# Upper alpha\n');
  if (readdirSync(join(f.instance, 'projects')).length !== 2) {
    t.skip('case-insensitive filesystem cannot hold colliding input names');
    return;
  }
  const result = f.render();
  assert.equal(result.status, 1);
  assert.match(result.stderr, /two pages render to/);
  assert.deepEqual(readdirSync(f.out), []);
});
