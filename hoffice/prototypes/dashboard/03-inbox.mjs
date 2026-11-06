import { stats, icon, filterScript, sharedCss, tok } from './_shared.mjs';

export const meta = {
  id: 'inbox',
  title: 'Next-step inbox',
  approach: 'Pulls every next step from every STATE into one checklist on the home page, grouped by project, with filters for open and done and per project. It answers "what should I do next" across the portfolio without opening each project.',
  differences: ['Home page is a task list, not a project list', 'Open/done and project filters plus text search', 'Projects without itemized next steps called out with a link to fix them', 'A compact project rail summarises counts'],
  features: ['One place to plan the week', 'Search across all next steps (press /)', 'Exposes STATE files whose next steps are prose, nudging authors toward lists'],
};

export const css = sharedCss + `
  .wrap { display: grid; grid-template-columns: 220px minmax(0, 1fr); gap: 32px; align-items: start; }
  .rail { position: sticky; top: 68px; font-size: 13px; }
  .rail button { display: flex; align-items: center; gap: 8px; width: 100%; padding: 6px 8px; border: 0; border-radius: 6px; background: none; font: inherit; color: var(--fg); text-align: left; cursor: pointer; }
  .rail button:hover { background: var(--soft); }
  .rail button[aria-pressed="true"] { background: var(--accent-soft); color: var(--accent); }
  .rail button .n { margin-left: auto; color: var(--muted); font-size: 12px; }
  .group { margin: 0 0 28px; }
  .group h2 { display: flex; align-items: center; gap: 8px; margin: 0 0 6px; font-size: 14px; }
  .group h2 a { text-decoration: none; }
  ul.tasks li.task { padding: 9px 0; }
  .prose-only { padding: 10px 12px; border: 1px dashed var(--line); border-radius: 6px; color: var(--muted); font-size: 13px; }
  @media (max-width: 860px) { .wrap { grid-template-columns: 1fr; } .rail { position: static; } }
`;
export const script = filterScript;

export function index(ctx) {
  const from = 'index.html';
  let open = 0, done = 0;
  const groups = ctx.projects.map(p => {
    const s = stats(p, ctx);
    open += s.open; done += s.done;
    const items = p.stepItems.map(i => `<li class="task${i.checked ? ' done' : ''}" data-search="${ctx.esc(i.text)}" data-status="${i.checked ? 'done' : 'open'}" data-project="${tok(p.slug)}"><input type="checkbox" disabled${i.checked ? ' checked' : ''} aria-label="${i.checked ? 'Done' : 'Open'}"><div>${ctx.markdown(i.text, p.state, from, { inline: true })}</div></li>`).join('');
    const prose = !s.total && p.narrative['next steps']?.trim()
      ? `<div class="prose-only" data-search="${ctx.esc(p.narrative['next steps'])}" data-status="open" data-project="${tok(p.slug)}">Written as prose, not a list: ${ctx.markdown(p.narrative['next steps'].trim().split('\n')[0], p.state, from, { inline: true })} ${ctx.optionalLink('Open STATE', p.state, from)}</div>` : '';
    return `<section class="group" data-group><h2>${icon(p)}${ctx.link(p.title, ctx.hrefTo(from, p.page))}<span class="count">${s.open} open</span></h2>${items ? `<ul class="tasks">${items}</ul>` : prose || `<p class="muted" data-search="" data-status="none" data-project="${tok(p.slug)}">No next steps recorded.</p>`}</section>`;
  }).join('');
  const rail = ctx.projects.map(p => `<button data-facet="project=${tok(p.slug)}" aria-pressed="false">${icon(p)}<span>${ctx.esc(p.title)}</span><span class="n">${p.steps.total - p.steps.done}</span></button>`).join('');
  return { title: 'Next steps', crumbs: ['Next steps'], body: `<div class="head"><h1>Next steps<span class="count">${open} open</span></h1><p class="sub">${done} done across ${ctx.projects.length} projects, read from each project's STATE. Checkboxes are read-only; edit STATE to change them.</p></div>
<div class="toolbar"><input class="filter" data-filter placeholder="Filter next steps  ( / )" aria-label="Filter next steps"><button class="chip" data-facet="status=open" aria-pressed="false">Open</button><button class="chip" data-facet="status=done" aria-pressed="false">Done</button><span class="muted"><span data-count></span> shown</span></div>
<div class="wrap"><nav class="rail" aria-label="Projects">${rail}</nav><div>${groups}</div></div>` };
}
