import { stats, icon, sharedCss } from './_shared.mjs';

export const meta = {
  id: 'heatmap',
  title: 'Health heatmap',
  approach: 'A matrix of projects against health signals (STATE age, digest age, open steps, done share, open questions, sessions in 14 days, decisions, authoritative documents) with conditional colour, a legend, and sortable columns. Project pages add a signal strip above the default layout.',
  differences: ['Numbers instead of links on the index', 'Cell colour encodes good, watch, and bad thresholds', 'Click a column header to sort', 'A 12-week activity sparkline per project'],
  features: ['Compares portfolio health in one glance', 'Thresholds are explicit in the legend, not implied', 'Sparklines show momentum, not just the latest date'],
};

export const css = sharedCss + `
  table.heat { width: 100%; border-collapse: separate; border-spacing: 3px; font-variant-numeric: tabular-nums; }
  table.heat th { padding: 6px 8px; font-size: 11.5px; font-weight: 500; color: var(--muted); text-align: center; vertical-align: bottom; cursor: pointer; user-select: none; }
  table.heat th:first-child { text-align: left; }
  table.heat th[aria-sort]::after { content: " ↓"; }
  table.heat th[aria-sort="ascending"]::after { content: " ↑"; }
  table.heat td { padding: 9px 8px; border-radius: 6px; text-align: center; background: var(--soft); }
  table.heat td.p { text-align: left; background: none; }
  table.heat td.p div { display: flex; align-items: center; gap: 8px; }
  table.heat td.p a { font-weight: 500; text-decoration: none; }
  table.heat td.good { background: #e3f4e8; color: #17602f; }
  table.heat td.watch { background: #fcf0d4; color: #7a4f00; }
  table.heat td.bad { background: #fbe1df; color: #a1251b; }
  table.heat td.none { color: var(--faint); }
  .legend { display: flex; gap: 14px; margin: 12px 0 0; font-size: 12px; color: var(--muted); }
  .legend i { display: inline-block; width: 12px; height: 12px; margin-right: 5px; border-radius: 3px; vertical-align: -2px; }
  .spark { display: inline-flex; align-items: flex-end; gap: 2px; height: 22px; }
  .spark span { width: 5px; border-radius: 1px; background: var(--accent); opacity: .85; }
  .spark span.z { height: 2px; background: var(--line); }
  .strip { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 8px; margin: 0 0 24px; }
  .strip div { padding: 10px 12px; border-radius: 8px; background: var(--soft); }
  .strip div.good { background: #e3f4e8; } .strip div.watch { background: #fcf0d4; } .strip div.bad { background: #fbe1df; }
  .strip b { display: block; font-size: 18px; } .strip small { color: var(--muted); font-size: 11.5px; }
`;

export const script = `
(() => {
  const table = document.querySelector('table.heat');
  if (!table) return;
  table.querySelectorAll('th').forEach((th, col) => th.addEventListener('click', () => {
    const asc = th.getAttribute('aria-sort') === 'descending';
    table.querySelectorAll('th').forEach(h => h.removeAttribute('aria-sort'));
    th.setAttribute('aria-sort', asc ? 'ascending' : 'descending');
    const body = table.tBodies[0];
    [...body.rows].sort((a, b) => {
      const x = a.cells[col].dataset.v, y = b.cells[col].dataset.v;
      const d = isNaN(x) || isNaN(y) ? String(x).localeCompare(y) : Number(x) - Number(y);
      return asc ? d : -d;
    }).forEach(r => body.append(r));
  }));
})();`;

// Each signal: label, value, thresholds as a function returning good, watch, or bad.
function signals(p, ctx) {
  const s = stats(p, ctx);
  const ageGrade = d => d === null ? 'bad' : d <= 7 ? 'good' : d <= 21 ? 'watch' : 'bad';
  return [
    ['STATE age (days)', s.reviewAge, ageGrade(s.reviewAge)],
    ['Digest age (days)', s.digestAge, ageGrade(s.digestAge)],
    ['Open steps', s.total ? s.open : null, !s.total ? 'bad' : s.open <= 5 ? 'good' : 'watch'],
    ['Done %', s.total ? Math.round(s.done / s.total * 100) : null, !s.total ? 'none' : s.done / s.total >= 0.5 ? 'good' : 'watch'],
    ['Open questions', s.questions, s.questions <= 3 ? 'good' : s.questions <= 8 ? 'watch' : 'bad'],
    ['Sessions, 14 days', s.sessions14, s.sessions14 >= 2 ? 'good' : s.sessions14 === 1 ? 'watch' : 'bad'],
    ['Decisions', s.decisions, s.decisions ? 'good' : 'watch'],
    ['Authoritative docs', s.authoritative, s.authoritative ? 'good' : 'watch'],
  ];
}

function spark(p, ctx) {
  const weeks = Array(12).fill(0);
  for (const f of p.files) { const a = ctx.age(f.date); if (f.date && !f.readme && a >= 0 && a < 84) weeks[11 - Math.floor(a / 7)]++; }
  const max = Math.max(1, ...weeks);
  return `<span class="spark" title="Dated documents per week, last 12 weeks: ${weeks.join(', ')}">${weeks.map(n => n ? `<span style="height:${Math.round(n / max * 22)}px"></span>` : '<span class="z"></span>').join('')}</span>`;
}

export function index(ctx) {
  const head = signals(ctx.projects[0] ?? { files: [], steps: {}, questions: [], digests: [], docs: [] }, ctx).map(([label]) => label);
  const rows = ctx.projects.map(p => `<tr><td class="p" data-v="${ctx.esc(p.title)}"><div>${icon(p)}${ctx.link(p.title, ctx.hrefTo('index.html', p.page))}</div></td>${signals(p, ctx).map(([, v, grade]) => `<td class="${v === null ? 'none' : grade}" data-v="${v ?? -1}">${v ?? '–'}</td>`).join('')}<td data-v="0">${spark(p, ctx)}</td></tr>`).join('');
  return { title: 'Health', crumbs: ['Health'], body: `<div class="head"><h1>Portfolio health<span class="count">${ctx.projects.length}</span></h1><p class="sub">Computed from the local instance. Ages count from today. Click a column to sort.</p></div>
<table class="heat"><thead><tr><th>Project</th>${head.map(h => `<th>${h}</th>`).join('')}<th>Activity, 12 weeks</th></tr></thead><tbody>${rows}</tbody></table>
<div class="legend"><span><i style="background:#e3f4e8"></i>good: age ≤ 7 days, ≤ 5 open steps, ≥ 2 sessions</span><span><i style="background:#fcf0d4"></i>watch: age ≤ 21 days</span><span><i style="background:#fbe1df"></i>bad: older, missing, or no sessions</span></div>` };
}

export function project(p, ctx) {
  const strip = `<div class="strip">${signals(p, ctx).map(([label, v, grade]) => `<div class="${v === null ? '' : grade}"><b>${v ?? '–'}</b><small>${label}</small></div>`).join('')}<div><b>${spark(p, ctx)}</b><small>Activity, 12 weeks</small></div></div>`;
  const page = ctx.defaults.project(p, ctx);
  return { ...page, body: page.body.replace(ctx.remoteNote, strip) };
}
