import { hue, icon, filterScript, sharedCss, tok } from './_shared.mjs';

export const meta = {
  id: 'library',
  title: 'Knowledge library',
  approach: 'Makes the instance\'s documents the primary object. The home page is a searchable, faceted library of every rendered Markdown file (sessions, decisions, notes, published, digests), newest first. Project pages put the project\'s documents, grouped by kind, beside its STATE.',
  differences: ['Home page lists all documents, not projects', 'Facets by kind and by project, plus title and path search', 'Project page adds a grouped document index', 'Excerpts come from each document\'s first paragraph'],
  features: ['Finds a past decision or session in seconds', 'Shows how much knowledge each project has accumulated', 'Turns the source pages from a side effect into a feature'],
};

export const css = sharedCss + `
  .lib { list-style: none; margin: 0; padding: 0; border-top: 1px solid var(--line); }
  .lib li { display: grid; grid-template-columns: 96px minmax(0, 1fr) 160px; gap: 14px; padding: 10px 4px; border-bottom: 1px solid var(--line); }
  .lib time { color: var(--muted); font-size: 12.5px; font-variant-numeric: tabular-nums; }
  .lib a.t { font-weight: 500; text-decoration: none; }
  .lib a.t:hover { text-decoration: underline; }
  .lib .path { display: block; color: var(--faint); font: 11.5px ui-monospace, Menlo, monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .lib .proj { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); }
  .facets { display: grid; grid-template-columns: auto 1fr; gap: 8px 12px; align-items: center; margin: 0 0 18px; font-size: 12px; color: var(--muted); }
  .facets div { display: flex; flex-wrap: wrap; gap: 6px; }
  .kinds h3 { margin: 18px 0 6px; text-transform: capitalize; }
  .kinds ul { margin: 0; padding-left: 18px; }
  .kinds li { margin: 3px 0; }
  @media (max-width: 860px) { .lib li { grid-template-columns: 80px minmax(0, 1fr); } .lib .proj { display: none; } }
`;
export const script = filterScript;

export function index(ctx) {
  const docs = ctx.docs.filter(d => !d.readme).sort((a, b) => (b.date || '0').localeCompare(a.date || '0') || a.rel.localeCompare(b.rel));
  const kinds = [...new Set(docs.map(d => d.kind))].sort();
  const items = docs.map(d => {
    const p = ctx.projects.find(x => x.slug === d.owner);
    return `<li data-search="${ctx.esc(`${d.title} ${d.rel}`)}" data-kind="${tok(d.kind)}" data-project="${tok(d.owner ?? 'none')}"><time>${d.date || '—'}</time><div>${ctx.link(d.title, ctx.hrefTo('index.html', d.page), 't')}<span class="path">${ctx.esc(d.rel)}</span></div><div class="proj">${p ? `${icon(p)}${ctx.esc(p.title)}` : '<span>Instance</span>'}</div></li>`;
  }).join('');
  return { title: 'Library', crumbs: ['Library'], body: `<div class="head"><h1>Library<span class="count"><span data-count></span> of ${docs.length}</span></h1><p class="sub">Every Markdown document in the instance, rendered. READMEs omitted.</p></div>
<div class="toolbar"><input class="filter" data-filter placeholder="Search titles and paths  ( / )" aria-label="Search documents"></div>
<div class="facets"><span>Kind</span><div>${kinds.map(k => `<button class="chip" data-facet="kind=${tok(k)}" aria-pressed="false">${ctx.esc(k)} (${docs.filter(d => d.kind === k).length})</button>`).join('')}</div>
<span>Project</span><div>${ctx.projects.map(p => `<button class="chip" data-facet="project=${tok(p.slug)}" aria-pressed="false" style="--h:${hue(p.slug)}">${ctx.esc(p.title)} (${p.files.filter(f => !f.readme).length})</button>`).join('')}</div></div>
<ol class="lib">${items}</ol>` };
}

export function project(p, ctx) {
  const from = p.page;
  const groups = Object.create(null);
  for (const f of p.files.filter(f => !f.readme)) (groups[f.kind] ??= []).push(f);
  const order = ['root', 'decisions', 'sessions', 'notes', 'published'];
  const kinds = Object.keys(groups).sort((a, b) => (order.indexOf(a) + 99) % 99 - (order.indexOf(b) + 99) % 99 || a.localeCompare(b));
  const index = `<section class="kinds"><h2>Documents<span class="count">${p.files.filter(f => !f.readme).length}</span></h2>${kinds.map(k => `<h3>${k === 'root' ? 'Core' : ctx.esc(k)} · ${groups[k].length}</h3><ul>${groups[k].sort((a, b) => (b.date || '').localeCompare(a.date || '') || a.title.localeCompare(b.title)).map(f => `<li>${ctx.link(f.title, ctx.hrefTo(from, f.page))}${f.date ? ` <small class="muted">${f.date}</small>` : ''}</li>`).join('')}</ul>`).join('')}</section>`;
  const body = `${ctx.parts.head(p, from)}
<div class="layout"><div>${ctx.parts.nextSteps(p, from)}${ctx.parts.section(p, 'summary', 'Summary', from)}${ctx.parts.section(p, 'open questions', 'Open questions', from)}</div>
<aside>${index}${ctx.parts.properties(p, from)}${ctx.parts.repositories(p, from)}</aside></div>`;
  return { title: p.title, crumbs: [ctx.indexCrumb(from), ctx.esc(p.title)], body };
}
