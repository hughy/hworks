#!/usr/bin/env node
import { readFileSync, readdirSync, statSync, lstatSync, mkdirSync, writeFileSync, realpathSync } from 'node:fs';
import { dirname, resolve, relative, isAbsolute, join } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { loadMarked, parseFrontmatter, esc, page } from './lib/render-common.mjs';

const args = process.argv.slice(2);
if (args.length !== 3 || args[0] !== '--instance') {
  console.error('usage: render-dashboard.mjs --instance <instance-root> <output-directory>');
  process.exit(2);
}
const marked = await loadMarked();
const unavailable = '<span class="muted">Unavailable</span>';
const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;
const link = (label, url) => `<a href="${esc(url)}">${esc(label)}</a>`;
const fileLink = (label, path) => link(label, pathToFileURL(path).href);
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
  const result = {};
  let name;
  for (const token of marked.lexer(text)) {
    if (token.type === 'heading' && token.depth <= 2) name = token.depth === 2 ? token.text.toLowerCase() : undefined;
    else if (name) result[name] = (result[name] ?? '') + token.raw;
  }
  return result;
}
try {
  const instance = realpathSync(resolve(args[1]));
  if (!exists(join(instance, 'HOFFICE.md'))) throw new Error('instance root must contain HOFFICE.md');
  const out = resolve(args[2]);
  // Check resolved ancestors so output symlinks cannot overwrite instance sources.
  let ancestor = out;
  while (true) {
    try { ancestor = realpathSync(ancestor); break; }
    catch (error) { if (error.code !== 'ENOENT') throw error; ancestor = dirname(ancestor); }
  }
  const inside = relative(instance, ancestor);
  if (!inside || (inside !== '..' && !inside.startsWith('../') && !isAbsolute(inside))) throw new Error('output directory must be outside the instance');
  function href(raw, source) {
    try {
      const url = new URL(raw, pathToFileURL(source));
      if (!['http:', 'https:', 'file:'].includes(url.protocol)) return '';
      if (url.protocol === 'file:' && !exists(fileURLToPath(url))) return '';
      return url.href;
    } catch { return ''; }
  }
  function markdown(text, source, inline = false) {
    const renderer = new marked.Renderer();
    renderer.html = ({ text }) => esc(text);
    renderer.image = ({ text }) => esc(text);
    renderer.link = function ({ href: raw, tokens }) {
      const url = href(raw, source);
      const label = this.parser.parseInline(tokens);
      return url ? `<a href="${esc(url)}">${label}</a>` : label;
    };
    renderer.codespan = ({ text }) => {
      const path = resolve(text.startsWith('repos/') || text.startsWith('projects/') ? instance : dirname(source), text);
      return exists(path) ? fileLink(text, path) : `<code>${esc(text)}</code>`;
    };
    return inline ? marked.parseInline(text, { renderer }) : marked.parse(text, { renderer });
  }
  const optionalLink = (label, path) => exists(path) ? fileLink(label, path) : unavailable;
  const renderFields = (values, source) => Object.entries(values).length
    ? `<table><thead><tr><th>Field</th><th>Value</th></tr></thead><tbody>${Object.entries(values).map(([key, value]) => `<tr><th scope="row">${esc(key)}</th><td>${value ? markdown(value, source, true) : unavailable}</td></tr>`).join('')}</tbody></table>`
    : '<p>Registry fields unavailable.</p>';
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
      if (entries.length) digests.push({ title: typeof fm.title === 'string' ? fm.title : name, projects: fm.projects, ...entries[0] });
    } catch (error) { console.error(`${dir}: skipped digest configuration: ${error.message}`); }
  }
  const projects = directories(join(instance, 'projects')).map(slug => {
    const dir = join(instance, 'projects', slug), source = join(dir, 'README.md'), text = read(source);
    const state = join(dir, 'STATE.md'), stateText = read(state);
    return { slug, dir, source, state, title: text.match(/^# (.+)$/m)?.[1] ?? slug, values: fields(text), narrative: sections(stateText),
      reviewed: date(stateText.match(/^Last reviewed:\s*(\S+)/m)?.[1]), digests: digests.filter(d => d.projects.some(p => p && p.name === slug)) };
  });
  // Preflight every destination before writing, including the intermediate directory.
  for (const path of [join(out, 'projects'), join(out, 'index.html'), ...projects.map(p => join(out, 'projects', `${p.slug}.html`))]) {
    try {
      if (lstatSync(path).isSymbolicLink()) throw new Error(`output destination must not be a symlink: ${path}`);
    } catch (error) { if (error.code !== 'ENOENT') throw error; }
  }
  mkdirSync(join(out, 'projects'), { recursive: true });
  const digestLinks = project => project.digests.length ? project.digests.map(d => fileLink(`${d.title} (${date(d.end)})`, d.source)).join('<br>') : unavailable;
  const remoteNote = '<p class="muted">Registry only. Remote health, milestones, issue counts, PR counts, factory state, weekly goals and briefings are unavailable in this phase. No remote sources were queried.</p>';
  for (const project of projects) {
    const { slug, dir, source, state, values, narrative, reviewed } = project;
    const docsSource = join(dir, 'DOCS.md');
    const docRows = tables(read(docsSource)).filter(row => 'doc' in row && 'authority' in row);
    const docs = docRows.filter(row => /^authoritative\s*:/i.test(row.authority ?? ''));
    const cards = repos.filter(repo => [...(repo.values.projects ?? '').matchAll(/`?projects\/([^/`\s,]+)\/?`?/g)].some(m => m[1] === slug));
    const body = `${remoteNote}<h2>Registry</h2>${renderFields(values, source)}
<h2>Repository cards</h2>${cards.length ? `<ul>${cards.map(repo => `<li>${fileLink(repo.title, repo.source)}${repo.values.origin ? `: ${markdown(repo.values.origin, repo.source, true)}` : ''}</li>`).join('')}</ul>` : '<p>No repository cards registered.</p>'}
<h2>STATE narrative</h2><p>Last reviewed: ${reviewed ? esc(reviewed) : unavailable}. ${optionalLink('Full STATE', state)}</p>
${['summary', 'open questions', 'next steps'].map(section => `<h3>${esc(section)}</h3>${narrative[section]?.trim() ? markdown(narrative[section], state) : '<p>Unavailable.</p>'}`).join('')}
<h2>Authoritative documents</h2><p>${optionalLink('Full document registry', docsSource)}</p>
${docs.length ? `<table><thead><tr><th>Document</th><th>Link</th><th>Owner</th><th>Authority</th></tr></thead><tbody>${docs.map(doc => `<tr>${['doc', 'link', 'owner', 'authority'].map(key => `<td>${doc[key] ? markdown(doc[key], docsSource, true) : unavailable}</td>`).join('')}</tr>`).join('')}</tbody></table>` : `<p>${docRows.length ? 'No authoritative documents registered.' : 'Authoritative documents unavailable.'}</p>`}
<h2>Latest digests</h2><p>${digestLinks(project)}</p>${project.digests.map(d => d.summary ? `<h3>${esc(d.title)}</h3>${markdown(d.summary, d.source)}` : '').join('')}`;
    writeFileSync(join(out, 'projects', `${slug}.html`), page({ title: project.title, meta: `${fileLink('All projects', join(out, 'index.html'))} | ${esc(slug)} | ${optionalLink('Project brief', source)}`, body }));
  }
  const rows = projects.map(project => `<tr><th scope="row">${link(project.title, `projects/${encodeURIComponent(project.slug)}.html`)}<br><small>${esc(project.slug)}</small></th><td>${project.reviewed || unavailable}</td><td>${project.values.tracker ? markdown(project.values.tracker, project.source, true) : unavailable}</td><td>${project.values.channels ? markdown(project.values.channels, project.source, true) : unavailable}</td><td>${optionalLink('STATE', project.state)}</td><td>${digestLinks(project)}</td></tr>`).join('');
  writeFileSync(join(out, 'index.html'), page({ title: 'Project dashboard', meta: 'Source: local instance registry. Dates below are authored STATE review dates, not refresh times.', body: `${remoteNote}<table><thead><tr><th>Project</th><th>STATE reviewed</th><th>Tracker</th><th>Channels</th><th>State</th><th>Latest digest</th></tr></thead><tbody>${rows}</tbody></table>${projects.length ? '' : '<p>No projects registered.</p>'}` }));
  console.log(`${pathToFileURL(join(out, 'index.html')).href}: ${projects.length} projects`);
} catch (error) { console.error(`render-dashboard: ${error.message}`); process.exitCode = 1; }
