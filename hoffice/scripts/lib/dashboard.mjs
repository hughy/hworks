// Instance model, safe Markdown pages, and dashboard output preflight.
import { readFileSync, readdirSync, statSync, lstatSync, mkdirSync, writeFileSync, realpathSync } from 'node:fs';
import { dirname, resolve, relative, isAbsolute, join, basename } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { loadMarked, parseFrontmatter, esc } from './render-common.mjs';
import { workspace, workspaceCss, workspaceScript } from './workspace.mjs';

const marked = await loadMarked();
const unavailable = '<span class="muted">Unavailable</span>';
const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;
const issueId = /^[A-Z][A-Z0-9]+-\d+$/;
function read(path) {
  try { return readFileSync(path, 'utf8').replace(/\r\n/g, '\n'); }
  catch (error) { if (error.code === 'ENOENT') return ''; throw error; }
}
function directories(path) {
  try { return readdirSync(path, { withFileTypes: true }).filter(e => e.isDirectory()).map(e => e.name).sort(compare); }
  catch (error) { if (error.code === 'ENOENT') return []; throw error; }
}
function exists(path) {
  try { return statSync(path).isFile(); }
  catch (error) { if (['ENOENT', 'ENOTDIR'].includes(error.code)) return false; throw error; }
}
// Every regular Markdown file in the instance, skipping dot directories and symlinks.
function markdownFiles(root) {
  const result = [];
  const walk = dir => {
    for (const entry of readdirSync(dir, { withFileTypes: true }).sort((a, b) => compare(a.name, b.name))) {
      if (entry.name.startsWith('.') || entry.name === 'node_modules') continue;
      const path = join(dir, entry.name);
      if (entry.isDirectory()) walk(path);
      else if (entry.isFile() && entry.name.endsWith('.md')) result.push(path);
    }
  };
  walk(root);
  return result;
}
function date(value) {
  const text = typeof value === 'string' ? value : '';
  const day = text.slice(0, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(day) && Number.isFinite(Date.parse(text)) &&
    new Date(day).toISOString().slice(0, 10) === day ? day : '';
}
function tables(text) {
  return marked.lexer(text).filter(t => t.type === 'table').flatMap(t =>
    t.rows.map(row => Object.fromEntries(t.header.map((cell, i) => [cell.text.toLowerCase(), row[i]?.text ?? '']))));
}
function fields(text) {
  return Object.fromEntries(tables(text).filter(row => row.field).map(row => [row.field.toLowerCase(), row.value]));
}
function sections(text) {
  const result = Object.create(null);
  let name;
  for (const token of marked.lexer(text)) {
    if (token.type === 'heading' && token.depth <= 2) name = token.depth === 2 ? token.text.toLowerCase() : undefined;
    else if (name) result[name] = (result[name] ?? '') + token.raw;
  }
  return result;
}
// The first paragraph after the title, used as the project description.
function lead(text) {
  const tokens = marked.lexer(text);
  const start = tokens.findIndex(t => t.type === 'heading' && t.depth === 1);
  const next = tokens.slice(start + 1).find(t => t.type !== 'space');
  return next?.type === 'paragraph' ? next.raw.trim() : '';
}
function steps(text) {
  const items = marked.lexer(text ?? '').filter(t => t.type === 'list').flatMap(t => t.items);
  return { total: items.length, done: items.filter(i => i.checked).length };
}

const baseCss = `
  :root { color-scheme: light; --fg: #1b1c1f; --muted: #6b6f76; --faint: #9a9ea6; --line: #e8e8ec; --soft: #f6f6f8; --bg: #fff; --accent: #5e6ad2; --accent-soft: #f1f2fc;
    font-family: -apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', system-ui, sans-serif; color: var(--fg); background: var(--bg); }
  body { margin: 0; font-size: 14px; line-height: 1.55; -webkit-font-smoothing: antialiased; }
  a { color: inherit; text-decoration: underline; text-decoration-color: #c9cbd1; text-underline-offset: 2px; }
  a:hover { text-decoration-color: currentColor; }
  code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12.5px; padding: 1px 4px; border-radius: 4px; background: var(--soft); }
  pre { padding: 12px 14px; border: 1px solid var(--line); border-radius: 6px; background: var(--soft); overflow-x: auto; }
  pre code { padding: 0; background: none; }
  .muted { color: var(--muted); }
  .top { position: sticky; top: 0; z-index: 1; display: flex; align-items: center; gap: 8px; height: 44px; padding: 0 24px; border-bottom: 1px solid var(--line); background: rgba(255,255,255,.92); backdrop-filter: blur(6px); font-size: 13px; color: var(--muted); }
  .top a { text-decoration: none; color: var(--muted); }
  .top a:hover { color: var(--fg); }
  .top .here { color: var(--fg); font-weight: 500; }
  .top .sep { color: var(--faint); }
  main { max-width: 1120px; margin: 0 auto; padding: 32px 24px 96px; }
  h1 { margin: 0; font-size: 22px; font-weight: 600; letter-spacing: -0.01em; line-height: 1.3; }
  h2 { margin: 0 0 10px; font-size: 13px; font-weight: 600; }
  h3 { margin: 0 0 8px; font-size: 12px; font-weight: 500; color: var(--muted); }
  .head { margin-bottom: 20px; }
  .head .sub { margin: 6px 0 0; color: var(--muted); font-size: 13px; }
  .head .desc { margin: 12px 0 0; max-width: 720px; color: #3c3f45; }
  .note { margin: 0 0 24px; padding: 8px 12px; border-radius: 6px; background: var(--soft); color: var(--muted); font-size: 12.5px; }
  a.issue { display: inline-block; padding: 0 5px; border: 1px solid var(--line); border-radius: 4px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11.5px; line-height: 18px; text-decoration: none; color: var(--muted); background: var(--bg); }
  a.issue:hover { border-color: var(--accent); color: var(--accent); }
  .icon { flex: none; display: inline-grid; place-items: center; width: 22px; height: 22px; border-radius: 5px; background: var(--accent-soft); color: var(--accent); font-size: 11px; font-weight: 600; }
  .prose > :first-child { margin-top: 0; }
  .prose p { margin: 8px 0; }
  .prose ul, .prose ol { padding-left: 20px; }
  .prose li { margin: 4px 0; }
  .prose table { border-collapse: collapse; margin: 12px 0; font-size: 13px; }
  .prose th, .prose td { padding: 6px 10px; border: 1px solid var(--line); text-align: left; vertical-align: top; }
  .prose th { background: var(--soft); font-weight: 500; }
  .doc { max-width: 760px; }
  .doc .prose h1 { margin: 0 0 16px; }
  .doc .prose h2 { margin: 28px 0 8px; font-size: 17px; }
  .doc .prose h3 { margin: 22px 0 6px; font-size: 14px; color: var(--fg); font-weight: 600; }
  .doc .prose h4 { margin: 18px 0 6px; font-size: 13px; }
  .doc .prose { font-size: 14.5px; line-height: 1.65; }
  .props { display: grid; grid-template-columns: max-content 1fr; gap: 4px 16px; margin: 0 0 24px; padding: 12px 14px; border: 1px solid var(--line); border-radius: 6px; font-size: 12.5px; }
  .props dt { color: var(--muted); }
  .props dd { margin: 0; overflow-wrap: anywhere; }
  @media (max-width: 860px) {
    .top { padding: 0 16px; }
  }
`;

function htmlPage({ title, crumbs = [], body, interactive = false }) {
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)}</title>
<style>${baseCss}${workspaceCss}</style>
</head>
<body>
<nav class="top">${crumbs.join('<span class="sep">/</span>') || 'Projects'}</nav>
<main>${body}</main>
${interactive ? `<script>${workspaceScript}</script>` : ''}
</body>
</html>
`;
}

const DAY = 86400000;
const withinPath = (parent, child) => {
  const path = relative(parent, child);
  return !path || (path !== '..' && !path.startsWith('../') && !isAbsolute(path));
};

export function renderDashboard({ instance: instanceArg, out: outArg, now = new Date() }) {
  const instance = realpathSync(resolve(instanceArg));
  if (!exists(join(instance, 'HOFFICE.md'))) throw new Error('instance root must contain HOFFICE.md');
  const out = resolve(outArg);
  // Check resolved ancestors so output symlinks cannot overwrite instance sources.
  let ancestor = out;
  while (true) {
    try { realpathSync(ancestor); break; }
    catch (error) { if (error.code !== 'ENOENT') throw error; ancestor = dirname(ancestor); }
  }
  const resolvedOut = resolve(realpathSync(ancestor), relative(ancestor, out));
  if (withinPath(instance, resolvedOut) || withinPath(resolvedOut, instance)) throw new Error('output directory must be outside the instance and must not contain it');

  // Each instance Markdown file gets a readable page at source/<instance path>.html.
  const docPages = new Map(markdownFiles(instance).map(path => [path, `source/${relative(instance, path)}.html`]));
  // Pages are addressed by output-relative paths; links between them stay relative.
  const hrefTo = (from, to, hash = '') => relative(dirname(join(out, from)), join(out, to)).split('/').map(encodeURIComponent).join('/') + hash;
  const fileHref = (path, from, hash = '') => docPages.has(path) ? hrefTo(from, docPages.get(path), hash) : pathToFileURL(path).href + hash;
  const link = (label, url, cls = '') => `<a href="${esc(url)}"${cls ? ` class="${cls}"` : ''}>${esc(label)}</a>`;
  const fileLink = (label, path, from) => link(label, fileHref(path, from));
  const optionalLink = (label, path, from) => exists(path) ? fileLink(label, path, from) : unavailable;
  function href(raw, source, from) {
    let url;
    try { url = new URL(raw, pathToFileURL(source)); } catch { return ''; }
    if (!['http:', 'https:', 'file:'].includes(url.protocol)) return '';
    if (url.protocol !== 'file:') return url.href;
    let path;
    try { path = fileURLToPath(url); } catch { return ''; }
    return exists(path) ? fileHref(path, from, url.hash) : '';
  }
  function markdown(text, source, from, { inline = false, anchors = false } = {}) {
    const renderer = new marked.Renderer();
    if (anchors) {
      // GitHub-style heading ids, so links like notes/design.md#choice land on the heading.
      const used = new Set();
      renderer.heading = function ({ tokens, depth }) {
        const html = this.parser.parseInline(tokens);
        // Slug the visible text, so a link's destination never becomes part of the id.
        const plain = html.replace(/<[^>]*>/g, '').replace(/&#(x[0-9a-f]+|[0-9]+);/gi, (_, ref) => {
          const n = ref[0].toLowerCase() === 'x' ? parseInt(ref.slice(1), 16) : Number(ref);
          return n > 0 && n <= 0x10ffff ? String.fromCodePoint(n) : '';
        }).replace(/&(?:amp|lt|gt|quot|apos);/g, '');
        const base = plain.toLowerCase().replace(/[^\p{L}\p{N}\s_-]/gu, '').trim().replace(/\s/g, '-');
        let id = base;
        for (let n = 1; used.has(id); n++) id = `${base}-${n}`;
        used.add(id);
        return `<h${depth} id="${esc(id)}">${html}</h${depth}>\n`;
      };
    }
    renderer.html = ({ text }) => esc(text);
    renderer.image = ({ text }) => esc(text);
    renderer.link = function ({ href: raw, tokens }) {
      const url = href(raw, source, from);
      const label = this.parser.parseInline(tokens);
      const cls = issueId.test(tokens.map(t => t.raw).join('')) ? ' class="issue"' : '';
      return url ? `<a href="${esc(url)}"${cls}>${label}</a>` : label;
    };
    renderer.codespan = ({ text }) => {
      const path = resolve(text.startsWith('repos/') || text.startsWith('projects/') ? instance : dirname(source), text);
      return exists(path) ? `<a href="${esc(fileHref(path, from))}"><code>${esc(text)}</code></a>` : `<code>${esc(text)}</code>`;
    };
    return inline ? marked.parseInline(text, { renderer }) : marked.parse(text, { renderer });
  }
  const indexCrumb = from => link('Projects', hrefTo(from, 'index.html'));

  const repoDir = join(instance, 'repos');
  let repoFiles = [];
  try { repoFiles = readdirSync(repoDir).filter(n => n.endsWith('.md')).sort(compare); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  const repos = repoFiles.map(name => {
    const source = join(repoDir, name), text = read(source);
    return { source, title: text.match(/^# (.+)$/m)?.[1] ?? name, values: fields(text) };
  });
  const digests = [];
  for (const name of directories(join(instance, 'digests'))) {
    const dir = join(instance, 'digests', name);
    try {
      const { fm } = parseFrontmatter(read(join(dir, 'DIGEST.md')));
      if (!Array.isArray(fm.projects)) throw new Error('projects must be a list');
      const entries = [];
      for (const filename of readdirSync(dir).filter(n => /^\d{4}-\d{2}-\d{2}.*\.md$/.test(n)).sort(compare)) {
        const source = join(dir, filename);
        try {
          const { fm: entry, body } = parseFrontmatter(read(source));
          if (!date(entry.period_end)) throw new Error('invalid period_end');
          entries.push({ source, end: entry.period_end, summary: sections(body).summary ?? '' });
        } catch (error) { console.error(`${source}: skipped digest: ${error.message}`); }
      }
      entries.sort((a, b) => Date.parse(b.end) - Date.parse(a.end) || compare(b.source, a.source));
      if (entries.length) digests.push({ title: typeof fm.title === 'string' ? fm.title : name, projects: fm.projects, ...entries[0], history: entries });
    } catch (error) { console.error(`${dir}: skipped digest configuration: ${error.message}`); }
  }
  // Every rendered source document, with the kind (its first directory), date, and title for the workspace tree.
  const docs = [...docPages].map(([source, page]) => {
    const rel = relative(instance, source);
    const owner = rel.match(/^projects\/([^/]+)\//)?.[1];
    const local = owner ? rel.slice(`projects/${owner}/`.length) : rel;
    const text = read(source).replace(/^---\n[\s\S]*?\n---\n?/, '');
    return { source, page, rel, owner, local, kind: local.includes('/') ? local.split('/')[0] : 'root', readme: basename(source) === 'README.md',
      date: date(basename(source).slice(0, 10)), title: text.match(/^# (.+)$/m)?.[1] ?? basename(source, '.md') };
  });
  const age = day => day ? Math.floor((Date.parse(now.toISOString().slice(0, 10)) - Date.parse(day)) / DAY) : null;
  const projects = directories(join(instance, 'projects')).map(slug => {
    const dir = join(instance, 'projects', slug), source = join(dir, 'README.md'), text = read(source);
    const state = join(dir, 'STATE.md'), stateText = read(state);
    const narrative = sections(stateText);
    const docsSource = join(dir, 'DOCS.md');
    const docRows = tables(read(docsSource)).filter(row => 'doc' in row && 'authority' in row);
    const listItems = name => marked.lexer(narrative[name] ?? '').filter(t => t.type === 'list').flatMap(t => t.items);
    const reviewed = date(stateText.match(/^Last reviewed:\s*(\S+)/m)?.[1]);
    return { slug, dir, source, state, title: text.match(/^# (.+)$/m)?.[1] ?? slug, lead: lead(text), values: fields(text), narrative,
      steps: steps(narrative['next steps']), page: `projects/${slug}.html`,
      reviewed, reviewedAge: age(reviewed), digests: digests.filter(d => d.projects.some(p => p && p.name === slug)),
      docsSource, docRows, docs: docRows.filter(row => /^authoritative\s*:/i.test(row.authority ?? '')),
      cards: repos.filter(repo => [...(repo.values.projects ?? '').matchAll(/`?projects\/([^/`\s,]+)\/?`?/g)].some(m => m[1] === slug)),
      stepItems: listItems('next steps').map(item => ({ text: item.text, checked: !!item.checked })),
      questions: listItems('open questions').map(item => ({ text: item.text })),
      files: docs.filter(d => d.owner === slug) };
  });

  const render = {
    properties(project, from) {
      const entries = Object.entries(project.values);
      return `<section><h3>Properties</h3>${entries.length
        ? `<dl>${entries.map(([key, value]) => `<dt>${esc(key)}</dt><dd>${value ? markdown(value, project.source, from, { inline: true }) : unavailable}</dd>`).join('')}</dl>`
        : '<p class="muted">Registry fields unavailable.</p>'}</section>`;
    },
    repositories(project, from) {
      const { cards } = project;
      return `<section><h3>Repositories</h3>${cards.length ? `<ul>${cards.map(repo => `<li>${fileLink(repo.title, repo.source, from)}${repo.values.origin ? `<small>${markdown(repo.values.origin, repo.source, from, { inline: true })}</small>` : ''}</li>`).join('')}</ul>` : '<p class="muted">No repository cards registered.</p>'}</section>`;
    },
    documents(project, from) {
      const { docs: list, docRows, docsSource } = project;
      return `<section><h3>Authoritative documents</h3>${list.length ? `<ul>${list.map(doc => `<li>${doc.doc ? markdown(doc.doc, docsSource, from, { inline: true }) : unavailable}${doc.link ? ` · ${markdown(doc.link, docsSource, from, { inline: true })}` : ''}<small>${doc.owner ? markdown(doc.owner, docsSource, from, { inline: true }) : unavailable} · ${markdown(doc.authority, docsSource, from, { inline: true })}</small></li>`).join('')}</ul>` : `<p class="muted">${docRows.length ? 'No authoritative documents registered.' : 'Authoritative documents unavailable.'}</p>`}</section>`;
    },
    sources(project, from) {
      return `<section><h3>Sources</h3><ul><li>${optionalLink('Project brief', project.source, from)}</li><li>${optionalLink('STATE', project.state, from)}</li><li>${exists(project.docsSource) ? fileLink('Full document registry', project.docsSource, from) : '<span class="muted">Document registry unavailable</span>'}</li></ul></section>`;
    },
    docBody(doc, from) {
      let text = read(doc.source), props = '';
      const front = text.match(/^---\n[\s\S]*?\n---\n?/);
      if (front) {
        try {
          const { fm, body } = parseFrontmatter(text);
          props = `<dl class="props">${Object.entries(fm).map(([key, value]) => `<dt>${esc(key)}</dt><dd>${esc(typeof value === 'string' ? value : JSON.stringify(value))}</dd>`).join('')}</dl>`;
          text = body;
        } catch { props = `<pre><code>${esc(front[0])}</code></pre>`; text = text.slice(front[0].length); }
      }
      return { props, html: markdown(text, doc.source, from, { anchors: true }), title: text.match(/^# (.+)$/m)?.[1] ?? basename(doc.source) };
    },
  };

  const ctx = { instance, now, projects, docs, esc, date, age, unavailable,
    link, fileLink, optionalLink, hrefTo, markdown, ...render };
  const pages = new Map();
  const destinations = new Set();
  const add = (destination, page) => {
    const key = destination.toLowerCase();
    if (destinations.has(key)) throw new Error(`two pages render to ${destination}`);
    destinations.add(key);
    pages.set(destination, htmlPage(page));
  };
  for (const project of projects) add(project.page, {
    title: project.title, body: workspace(ctx, project.page, project.slug), interactive: true,
  });
  for (const doc of docs) {
    const { props, html, title } = render.docBody(doc, doc.page);
    const project = projects.find(p => p.slug === doc.owner);
    add(doc.page, { title,
      crumbs: [indexCrumb(doc.page), ...(project ? [link(project.title, hrefTo(doc.page, project.page))] : []), esc(doc.rel)],
      body: `<div class="doc">${props}<div class="prose">${html}</div>
<p class="note">Rendered from ${link(doc.rel, pathToFileURL(doc.source).href)}. Edit the source; this page is overwritten on the next render.</p></div>`,
    });
  }
  add('index.html', { title: 'Projects', body: workspace(ctx, 'index.html'), interactive: true });

  // Preflight every destination and its intermediate directories before writing anything.
  const checked = new Set();
  for (const destination of pages.keys()) {
    const parts = destination.split('/');
    for (let i = 1; i <= parts.length; i++) {
      const path = join(out, ...parts.slice(0, i));
      if (checked.has(path)) continue;
      checked.add(path);
      try {
        if (lstatSync(path).isSymbolicLink()) throw new Error(`output destination must not be a symlink: ${path}`);
      } catch (error) { if (error.code !== 'ENOENT') throw error; }
    }
  }
  for (const [destination, html] of pages) {
    mkdirSync(dirname(join(out, destination)), { recursive: true });
    writeFileSync(join(out, destination), html);
  }
  return { index: join(out, 'index.html'), projects: projects.length, sourcePages: docPages.size, pages: pages.size };
}
