import { stats, icon, tasks, ageLabel, ageClass, firstParagraph, sharedCss } from './_shared.mjs';

export const meta = {
  id: 'cards',
  title: 'Card grid with tabbed projects',
  approach: 'Replaces the wide table with one card per project that previews the work itself: progress, the first open next steps, and freshness. Project pages split into tabs so the first screen shows one topic at a time.',
  differences: ['Cards instead of a seven-column table', 'Top three open next steps visible without clicking in', 'Progress bar for itemized next steps', 'Project page sections become tabs (Next steps, Summary, Questions, Digests, Documents)'],
  features: ['Scannable at a glance on wide and narrow screens', 'Previews actual work, not just links to it', 'Tabs shorten long STATE pages; the URL hash keeps the selected tab'],
};

export const css = sharedCss + `
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }
  .card { display: flex; flex-direction: column; gap: 10px; padding: 16px; border: 1px solid var(--line); border-radius: 10px; background: var(--bg); transition: border-color .15s; }
  .card:hover { border-color: #c9cbd1; }
  .card header { display: flex; align-items: center; gap: 10px; }
  .card header a { font-weight: 600; text-decoration: none; }
  .card header small { display: block; color: var(--faint); font-size: 12px; }
  .card .lead { margin: 0; color: #3c3f45; font-size: 13px; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
  .bar { height: 6px; border-radius: 3px; background: var(--soft); overflow: hidden; }
  .bar span { display: block; height: 100%; background: var(--accent); }
  .card ul.tasks li.task { padding: 5px 0; font-size: 13px; }
  .card ul.tasks li.task div { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .card footer { display: flex; flex-wrap: wrap; gap: 6px; margin-top: auto; padding-top: 8px; border-top: 1px solid var(--line); font-size: 12px; color: var(--muted); }
  .tabs { display: flex; gap: 2px; margin: 0 0 20px; border-bottom: 1px solid var(--line); }
  .tabs a { padding: 8px 12px; margin-bottom: -1px; border-bottom: 2px solid transparent; color: var(--muted); text-decoration: none; font-size: 13px; }
  .tabs a[aria-selected="true"] { border-color: var(--accent); color: var(--fg); font-weight: 500; }
  .panel:not(.on) { display: none; }
`;

export function index(ctx) {
  const cards = ctx.projects.map(p => {
    const s = stats(p, ctx);
    const pct = s.total ? Math.round(s.done / s.total * 100) : 0;
    const preview = s.total ? `<ul class="tasks">${tasks(p, ctx, 'index.html', { limit: 3, openOnly: true })}</ul>${s.open > 3 ? `<small class="muted">+${s.open - 3} more</small>` : ''}`
      : `<p class="muted" style="margin:0;font-size:13px">${p.narrative['next steps']?.trim() ? 'Next steps are written as prose.' : 'No next steps.'}</p>`;
    return `<article class="card"><header>${icon(p)}<div>${ctx.link(p.title, ctx.hrefTo('index.html', p.page))}<small>${ctx.esc(p.slug)}</small></div></header>
<p class="lead">${firstParagraph(p, 'summary', ctx, 'index.html') || (p.lead ? ctx.markdown(p.lead, p.source, 'index.html', { inline: true }) : '')}</p>
${s.total ? `<div><div class="bar"><span style="width:${pct}%"></span></div><small class="muted">${s.open} open · ${s.done} done</small></div>` : ''}
${preview}
<footer><span class="age ${ageClass(s.reviewAge)}">STATE ${ageLabel(s.reviewAge)}</span><span class="chip">${s.questions} questions</span><span class="chip">${s.sessions} sessions</span>${s.digestEnd ? `<span class="chip">digest ${s.digestEnd}</span>` : ''}</footer></article>`;
  }).join('');
  return { title: 'Projects', crumbs: ['Projects'], body: `<div class="head"><h1>Projects<span class="count">${ctx.projects.length}</span></h1><p class="sub">Open next steps first; ages count from today.</p></div><div class="grid">${cards}</div>` };
}

const tabScript = `
(() => {
  const show = id => {
    const tabs = [...document.querySelectorAll('.tabs a')];
    if (!tabs.some(t => t.hash === '#' + id)) id = tabs[0]?.hash.slice(1);
    tabs.forEach(t => t.setAttribute('aria-selected', String(t.hash === '#' + id)));
    document.querySelectorAll('.panel').forEach(p => p.classList.toggle('on', p.id === id));
  };
  addEventListener('hashchange', () => show(location.hash.slice(1)));
  show(location.hash.slice(1));
})();`;
export const script = tabScript;

export function project(p, ctx) {
  const from = p.page, s = stats(p, ctx);
  const panels = [
    ['next', `Next steps${s.total ? ` (${s.open})` : ''}`, ctx.parts.nextSteps(p, from)],
    ['summary', 'Summary', ctx.parts.section(p, 'summary', 'Summary', from)],
    ['questions', `Questions (${s.questions})`, ctx.parts.section(p, 'open questions', 'Open questions', from)],
    ['digests', 'Digests', ctx.parts.digests(p, from)],
    ['documents', `Documents (${s.documents})`, `<section><h2>Documents</h2><ul>${p.files.filter(f => !f.readme).sort((a, b) => (b.date || '').localeCompare(a.date || '')).map(f => `<li>${ctx.link(f.title, ctx.hrefTo(from, f.page))} <small class="muted">${f.kind}${f.date ? ` · ${f.date}` : ''}</small></li>`).join('')}</ul></section>`],
  ];
  const body = `${ctx.parts.head(p, from)}
<nav class="tabs" role="tablist">${panels.map(([id, label]) => `<a href="#${id}" role="tab">${label}</a>`).join('')}</nav>
<div class="layout"><div>${panels.map(([id, , html]) => `<div class="panel" id="${id}">${html}</div>`).join('')}</div>
<aside>${ctx.parts.properties(p, from)}${ctx.parts.repositories(p, from)}${ctx.parts.documents(p, from)}${ctx.parts.sources(p, from)}</aside></div>`;
  return { title: p.title, crumbs: [ctx.indexCrumb(from), ctx.esc(p.title)], body };
}
