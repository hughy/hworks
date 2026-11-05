#!/usr/bin/env node
import { readFileSync, writeFileSync, readdirSync, existsSync, realpathSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { join, basename, relative } from 'node:path';
import { loadMarked, repoInfo, parseFrontmatter, rewriteRelativeLinks, esc, page } from './lib/render-common.mjs';

const LOG_SECTIONS = [
  'Background',
  'Summary',
  'Decisions and commitments',
  'Discussion',
  'Documents',
  'Code',
  'Tracker activity',
  'Open questions',
];
const LINT_SECTIONS = new Set(['Current status', ...LOG_SECTIONS]);
const FILE_RE = /^\d{4}-\d{2}-\d{2}-(daily|weekly)(-\d{4})?\.md$/;
const EMPTY_RE = /^(none|n\/a|nothing (material|to report))\.?$/i;

function parseArgs(argv) {
  const opts = { refs: [], positional: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--ref') opts.refs.push(argv[++i]);
    else if (a === '--quiet') opts.quiet = argv[++i];
    else if (a === '--check') opts.check = argv[++i];
    else if (a === '--instance') opts.instance = argv[++i];
    else if (a === '--config') opts.config = argv[++i];
    else opts.positional.push(a);
  }
  return opts;
}

function sections(body) {
  const out = new Map();
  let name = null;
  body.split('\n').forEach((line, i) => {
    const h = line.match(/^## (.+?)\s*$/);
    if (h) {
      name = h[1];
      out.set(name, { lines: [], start: i + 1 });
    } else if (name) {
      out.get(name).lines.push(line);
    }
  });
  for (const v of out.values()) v.text = v.lines.join('\n').trim();
  return out;
}

const isEmpty = (text) => !text || EMPTY_RE.test(text.replace(/<!--[\s\S]*?-->/g, '').trim());

function linkChecks(config) {
  const patterns = config?.link_patterns === undefined ? [
    { kind: 'PR or issue number', pattern: '(?<![\\w/&])#\\d+\\b' },
    { kind: 'bare URL', pattern: 'https?://[^\\s)>\\]]*[^\\s)>\\].,;:!?]' },
  ] : config.link_patterns;
  if (!Array.isArray(patterns)) throw new Error('link_patterns must be a YAML or JSON list of {kind, pattern}');
  return patterns.map((entry) => {
    if (!entry || typeof entry.kind !== 'string' || !entry.kind || typeof entry.pattern !== 'string' || !entry.pattern) {
      throw new Error('each link_patterns entry needs a nonempty kind and pattern');
    }
    return [entry.kind, new RegExp(entry.pattern, 'g')];
  });
}

function lintText(text, firstLine, checks) {
  const findings = [];
  let inComment = false;
  text.split('\n').forEach((line, i) => {
    if (inComment || line.includes('<!--')) {
      inComment = !line.includes('-->');
      return;
    }
    const stripped = line.replace(/\[[^\]]*\]\([^)]*\)/g, ' ').replace(/<a\s[^>]*>.*?<\/a>/g, ' ');
    for (const [kind, re] of checks) {
      for (const m of stripped.matchAll(re)) {
        findings.push({ line: firstLine + i, kind, token: m[0] });
      }
    }
  });
  return findings;
}

function lintDigest(text, config) {
  const { body } = parseFrontmatter(text);
  const offset = text.split('\n').length - body.split('\n').length;
  const checks = linkChecks(config);
  const findings = [];
  for (const [name, s] of sections(body)) {
    if (!LINT_SECTIONS.has(name)) continue;
    findings.push(...lintText(s.lines.join('\n'), offset + s.start + 1, checks));
  }
  return findings;
}

function report(file, findings) {
  for (const f of findings) console.error(`${file}:${f.line}: unlinked ${f.kind}: ${f.token}`);
}

const opts = parseArgs(process.argv.slice(2));

if (opts.check) {
  const config = opts.config ? parseFrontmatter(readFileSync(opts.config, 'utf8')).fm : null;
  const findings = lintDigest(readFileSync(opts.check, 'utf8'), config);
  report(opts.check, findings);
  console.log(`${opts.check}: ${findings.length} unlinked artifact(s)`);
  process.exit(findings.length ? 1 : 0);
}

const [project, out] = opts.positional;
if (!project || !out || !opts.instance) {
  console.error('usage: render-digest.mjs <digest> <out.html> --instance <root> [--ref <ref>]... [--quiet "<note>"]');
  console.error('       render-digest.mjs --check <digest.md> [--config <DIGEST.md>]');
  process.exit(2);
}

const repo = repoInfo(opts.instance);
const dir = join(realpathSync(opts.instance), 'digests', project);
const digestPath = relative(repo.root, dir);
const configPath = join(dir, 'DIGEST.md');
if (!existsSync(configPath)) throw new Error(`missing ${configPath}`);
const config = parseFrontmatter(readFileSync(configPath, 'utf8')).fm;
const rollingDays = Number(config.rolling_days || 14);

const digests = new Map();
for (const name of existsSync(dir) ? readdirSync(dir) : []) {
  if (FILE_RE.test(name)) {
    digests.set(name, { text: readFileSync(join(dir, name), 'utf8'), url: `${repo.blobBase}${digestPath}/${name}` });
  }
}
const git = (...args) => execFileSync('git', args, { cwd: repo.root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
for (const ref of opts.refs) {
  const branch = ref.replace(/^origin\//, '');
  let paths;
  try {
    paths = git('ls-tree', '-r', '--name-only', ref, `${digestPath}/`).split('\n').filter(Boolean);
  } catch {
    console.error(`warning: skipped unreadable ref ${ref}`);
    continue;
  }
  for (const path of paths) {
    const name = basename(path);
    if (path !== `${digestPath}/${name}` || !FILE_RE.test(name) || digests.has(name)) continue;
    digests.set(name, { text: git('show', `${ref}:${path}`), url: `${repo.webBase}/blob/${branch}/${path}`, branch });
  }
}

const shown = [...digests.entries()]
  .map(([name, d]) => ({
    name, ...d,
    ...parseFrontmatter(rewriteRelativeLinks(d.text, join(dir, name), {
      ...repo, blobBase: d.branch ? `${repo.webBase}/blob/${d.branch}/` : repo.blobBase,
    })),
  }))
  .sort((a, b) => (b.fm.period_end || b.name).localeCompare(a.fm.period_end || a.name))
  .slice(0, rollingDays);
if (!shown.length) throw new Error(`no digests in digests/${project}/ or the given refs`);

const newest = shown[0];
const newestFindings = lintDigest(newest.text, config);
if (newestFindings.length) {
  report(newest.name, newestFindings);
  console.error(`render stopped: ${newest.name} has ${newestFindings.length} unlinked artifact(s)`);
  process.exit(1);
}
for (const d of shown.slice(1)) report(d.name, lintDigest(d.text, config));

const marked = await loadMarked();
const md = (s) => marked.parse(s);
const day = (iso) => (iso || '').slice(0, 10);
const parts = [];

if (opts.quiet) parts.push(`<p class="quiet">${esc(opts.quiet)}</p>`);

const status = sections(newest.body).get('Current status');
parts.push('<h2>Current status</h2>');
parts.push(status && !isEmpty(status.text) ? md(status.text) : '<p class="muted">No status section in the newest digest.</p>');

parts.push('<h2>Daily log</h2>');
for (const d of shown) {
  const secs = sections(d.body);
  const pending = d.branch ? ' <span class="chip">PR open</span>' : '';
  const base = d.fm.baseline === 'true' ? ' <span class="chip">baseline</span>' : '';
  parts.push(
    `<h3 id="${esc(d.name.replace(/\.md$/, ''))}">${esc(day(d.fm.period_end) || d.name)}${base}${pending}</h3>`,
    `<p class="meta">Window ${esc(d.fm.period_start)} to ${esc(d.fm.period_end)}. <a href="${esc(d.url)}">source</a>.</p>`,
  );
  for (const name of LOG_SECTIONS) {
    const s = secs.get(name);
    if (!s || isEmpty(s.text)) continue;
    parts.push(`<h4>${esc(name)}</h4>`, md(s.text.replace(/^### /gm, '##### ')));
  }
}

if (digests.size > shown.length) {
  parts.push(`<p class="muted">Older digests: <a href="${esc(`${repo.treeBase}${digestPath}`)}">digests/${esc(project)}/ source</a>.</p>`);
}

const title = config.title || `${project} digest`;
const extraCss = `
    h4 { margin: 18px 0 6px; font-size: 17px; font-weight: 700; }
    h5 { margin: 12px 0 4px; font-size: 15px; font-weight: 700; color: #5b616e; }
    .quiet { padding: 10px 14px; border-left: 3px solid #315c85; background: #f3f4f5; }
`;
const html = page({
  title,
  meta: `Updated ${esc(newest.fm.period_end)}. Covers ${shown.length} digest(s), ${esc(day(shown.at(-1).fm.period_start))} to ${esc(day(newest.fm.period_end))}. Working digest; code and the linked documents are authoritative.`,
  body: parts.join('\n'),
  extraCss,
});
writeFileSync(out, html);
console.log(`${out}: ${html.length} bytes, ${shown.length} digest(s), newest ${newest.name}${opts.quiet ? ', quiet note' : ''}`);
