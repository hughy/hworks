import { hue, icon, filterScript, sharedCss, tok } from './_shared.mjs';

export const meta = {
  id: 'timeline',
  title: 'Activity timeline',
  approach: 'Treats the instance as a stream of dated events (sessions, decisions, digests, published notes) and shows them newest first, grouped by week, with project and kind filters. Project pages pair the summary with that project\'s own timeline.',
  differences: ['Home page is a chronological feed instead of a registry', 'Week grouping with event counts', 'Project colour dots and kind badges on every event', 'Filters by project and by kind, plus search'],
  features: ['Answers "what happened lately" in one scroll', 'Makes quiet projects visible by their absence', 'Every event links to its rendered source page'],
};

export const css = sharedCss + `
  .week { margin: 0 0 26px; }
  .week h2 { position: sticky; top: 44px; z-index: 0; margin: 0; padding: 8px 0; background: var(--bg); font-size: 12px; font-weight: 600; color: var(--muted); letter-spacing: .03em; text-transform: uppercase; }
  .events { list-style: none; margin: 0; padding: 0 0 0 16px; border-left: 2px solid var(--line); }
  .events li { position: relative; display: grid; grid-template-columns: 86px minmax(0, 1fr); gap: 12px; padding: 7px 0; font-size: 13.5px; }
  .events li::before { content: ""; position: absolute; left: -22px; top: 13px; width: 10px; height: 10px; border-radius: 50%; background: hsl(var(--h) 60% 52%); box-shadow: 0 0 0 3px var(--bg); }
  .events time { color: var(--muted); font-variant-numeric: tabular-nums; }
  .events a { text-decoration: none; font-weight: 500; }
  .events a:hover { text-decoration: underline; }
  .events small { display: block; margin-top: 2px; color: var(--muted); font-size: 12px; }
  .kind { display: inline-block; margin-right: 6px; padding: 0 6px; border-radius: 4px; font-size: 11px; line-height: 17px; background: var(--soft); color: var(--muted); }
  .kind.decisions { background: #efeafd; color: #5b3cc4; }
  .kind.digests { background: #e6f3fb; color: #1d6a96; }
  .kind.published { background: #e7f6ec; color: #1f7a3d; }
`;
export const script = filterScript;

const kinds = Object.assign(Object.create(null), { sessions: 'Session', decisions: 'Decision', digests: 'Digest', published: 'Published', notes: 'Note' });

function weekOf(day) {
  const d = new Date(day + 'T00:00:00Z');
  d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
  return d.toISOString().slice(0, 10);
}

function feed(ctx, from, events) {
  const weeks = new Map();
  for (const e of events) {
    const w = weekOf(e.date);
    if (!weeks.has(w)) weeks.set(w, []);
    weeks.get(w).push(e);
  }
  return [...weeks].map(([w, list]) => `<section class="week" data-group><h2>Week of ${w} · ${list.length}</h2><ol class="events">${list.map(e => {
    const p = ctx.projects.find(x => x.slug === e.owner);
    return `<li style="--h:${hue(e.owner ?? e.kind)}" data-search="${ctx.esc(`${e.title} ${p?.title ?? ''}`)}" data-kind="${tok(e.kind)}" data-project="${tok(e.owner ?? 'none')}"><time>${e.date}</time><div><span class="kind ${tok(e.kind)}">${kinds[e.kind] ?? ctx.esc(e.kind)}</span>${ctx.link(e.title, ctx.hrefTo(from, e.page))}<small>${p ? ctx.esc(p.title) : ctx.esc(e.rel.split('/').slice(0, 2).join('/'))}</small></div></li>`;
  }).join('')}</ol></section>`).join('');
}

const events = docs => docs.filter(d => d.date && !d.readme).sort((a, b) => b.date.localeCompare(a.date) || a.rel.localeCompare(b.rel));

export function index(ctx) {
  const list = events(ctx.docs);
  const present = [...new Set(list.map(e => e.kind))];
  const toolbar = `<div class="toolbar"><input class="filter" data-filter placeholder="Filter events  ( / )" aria-label="Filter events">
${present.map(k => `<button class="chip" data-facet="kind=${tok(k)}" aria-pressed="false">${kinds[k] ?? ctx.esc(k)}</button>`).join('')}
<span class="muted">·</span>${ctx.projects.map(p => `<button class="chip" data-facet="project=${tok(p.slug)}" aria-pressed="false" style="--h:${hue(p.slug)}">${ctx.esc(p.title)}</button>`).join('')}
<span class="muted"><span data-count></span> shown</span></div>`;
  return { title: 'Activity', crumbs: ['Activity'], body: `<div class="head"><h1>Activity<span class="count">${list.length}</span></h1><p class="sub">Dated instance documents, newest first. Dates come from file names.</p></div>${toolbar}${feed(ctx, 'index.html', list)}` };
}

export function project(p, ctx) {
  const from = p.page;
  const list = events(p.files.concat(ctx.docs.filter(d => d.kind === 'digests' && p.digests.some(g => d.source.startsWith(g.source.slice(0, g.source.lastIndexOf('/') + 1))))));
  const body = `${ctx.parts.head(p, from)}
<div class="layout"><div>${ctx.parts.nextSteps(p, from)}<section style="margin-top:28px"><h2>Timeline<span class="count">${list.length}</span></h2>${feed(ctx, from, list)}</section></div>
<aside><section><h3>Project</h3><p style="display:flex;gap:8px;align-items:center;margin:0">${icon(p)}${ctx.esc(p.slug)}</p></section>${ctx.parts.properties(p, from)}${ctx.parts.repositories(p, from)}${ctx.parts.sources(p, from)}</aside></div>`;
  return { title: p.title, crumbs: [ctx.indexCrumb(from), ctx.esc(p.title)], body };
}
