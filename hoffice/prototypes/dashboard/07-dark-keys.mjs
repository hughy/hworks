import { stats, icon, ageLabel, ageClass, sharedCss, filterScript, keyNavScript } from './_shared.mjs';

export const meta = {
  id: 'dark-keys',
  title: 'Dark, dense, keyboard-first',
  approach: 'A dark theme with tighter rows for people who keep the dashboard open all day. The index is a dense list driven from the keyboard: / filters, j and k move, Enter opens. Long channel and tracker values move off the index to the project page.',
  differences: ['Dark palette tuned for contrast (WCAG AA text)', 'One-line rows, about twice the density of the current table', 'Keyboard navigation and a filter box', 'Channels and tracker dropped from the index to keep rows short'],
  features: ['Comfortable for long sessions and low light', 'Fast to operate without a mouse', 'Fixes the tall-row problem the current index has'],
};

export const css = sharedCss + `
  :root { color-scheme: dark; --fg: #e6e7ea; --muted: #9a9fa8; --faint: #6c717a; --line: #2a2d33; --soft: #1d1f24; --bg: #131418; --accent: #8b93ff; --accent-soft: #23264a; background: var(--bg); color: var(--fg); }
  body { font-size: 13px; }
  a { text-decoration-color: #4a4e57; }
  .top { background: rgba(19,20,24,.9); }
  .head .desc, .prose, .doc .prose { color: #cfd1d6; }
  .age.fresh { background: #12321e; color: #6fdc8c; }
  .age.aging { background: #3a2c0a; color: #f2c14e; }
  .age.stale { background: #3d1515; color: #ff8a80; }
  .icon { background: hsl(var(--h) 40% 22%); color: hsl(var(--h) 80% 78%); }
  .rows { border-top: 1px solid var(--line); }
  .row { display: grid; grid-template-columns: minmax(0, 2.2fr) 120px 120px 90px 90px minmax(0, 1.4fr); gap: 12px; align-items: center; padding: 7px 10px; border-bottom: 1px solid var(--line); white-space: nowrap; }
  .row:hover { background: var(--soft); }
  .row.hd { color: var(--faint); font-size: 11.5px; text-transform: uppercase; letter-spacing: .04em; }
  .row .name { display: flex; align-items: center; gap: 10px; overflow: hidden; text-overflow: ellipsis; }
  .row .name a { font-weight: 500; text-decoration: none; }
  .row .digest { overflow: hidden; text-overflow: ellipsis; color: var(--muted); }
  .row .num { font-variant-numeric: tabular-nums; color: var(--muted); }
  .next { background: var(--soft); border-color: var(--line); border-left-color: var(--accent); }
  li.task input { background: var(--bg); border-color: #555a64; }
  pre, code, .props, .note, .count { background: var(--soft); }
  .prose th { background: var(--soft); }
  table.list tbody tr:hover { background: var(--soft); }
  a.issue { background: var(--soft); }
  .banner-keys { color: var(--faint); font-size: 12px; }
  @media (max-width: 860px) { .row { grid-template-columns: minmax(0, 1fr) 100px; } .row > :nth-child(n+3) { display: none; } }
`;
export const script = filterScript + keyNavScript;

export function index(ctx) {
  const rows = ctx.projects.map(p => {
    const s = stats(p, ctx);
    return `<div class="row" data-nav data-search="${ctx.esc(`${p.title} ${p.slug} ${p.lead}`)}"><div class="name">${icon(p)}${ctx.link(p.title, ctx.hrefTo('index.html', p.page))}<span class="muted">${ctx.esc(p.slug)}</span></div>
<div>${ctx.stepSummary(p)}</div><div><span class="age ${ageClass(s.reviewAge)}">${ageLabel(s.reviewAge)}</span></div><div class="num">${s.questions} q</div><div class="num">${s.sessions14} / 14d</div>
<div class="digest">${p.digests.length ? ctx.fileLink(`${p.digests[0].title} · ${ctx.date(p.digests[0].end)}`, p.digests[0].source, 'index.html') : ctx.unavailable}</div></div>`;
  }).join('');
  return { title: 'Projects', crumbs: ['Projects'], body: `<div class="head"><h1>Projects<span class="count"><span data-count></span>/${ctx.projects.length}</span></h1></div>
<div class="toolbar"><input class="filter" data-filter placeholder="Filter projects" aria-label="Filter projects"><span class="banner-keys"><span class="kbd">/</span> filter · <span class="kbd">j</span> <span class="kbd">k</span> move · <span class="kbd">Enter</span> open</span></div>
<div class="rows"><div class="row hd"><div>Project</div><div>Next steps</div><div>STATE reviewed</div><div>Questions</div><div>Sessions</div><div>Latest digest</div></div>${rows}</div>` };
}
