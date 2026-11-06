import { attention, icon, ageLabel, ageClass, sharedCss } from './_shared.mjs';

export const meta = {
  id: 'attention',
  title: 'Attention queue',
  approach: 'Ranks projects by what needs a look instead of listing them alphabetically. Each row states its reasons (stale STATE, next steps not itemized, old digest, quiet sessions) so the reader knows why it is at the top.',
  differences: ['Projects sorted by an attention score, not by name', 'Every row lists the reasons behind its score', 'Freshness shown as coloured age badges', 'Project pages open with the same reasons as a banner'],
  features: ['Triage first: the first row is the next thing to fix', 'Explains every signal instead of showing a bare number', 'Same signals on the index and the project page'],
};

export const css = sharedCss + `
  .queue { list-style: none; margin: 0; padding: 0; border-top: 1px solid var(--line); }
  .queue > li { display: grid; grid-template-columns: 34px minmax(0, 1fr) auto; gap: 14px; align-items: start; padding: 14px 4px; border-bottom: 1px solid var(--line); }
  .queue .rank { font-size: 20px; font-weight: 600; color: var(--faint); text-align: right; line-height: 1.2; }
  .queue .title { display: flex; align-items: center; gap: 10px; font-weight: 500; }
  .queue .title a { text-decoration: none; }
  .queue .reasons { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
  .reason { padding: 1px 8px; border-radius: 10px; font-size: 12px; background: var(--soft); color: #3c3f45; }
  .reason.w3 { background: #fde8e8; color: #b42318; }
  .reason.w2 { background: #fdf3dc; color: #8a5a00; }
  .score { min-width: 44px; text-align: center; }
  .score b { display: block; font-size: 18px; }
  .score small { color: var(--muted); font-size: 11px; }
  .banner { margin: 0 0 24px; padding: 12px 14px; border: 1px solid #f3d3a5; border-radius: 8px; background: #fffaf0; font-size: 13px; }
  .banner.ok { border-color: #bfe3cb; background: #f3fbf5; }
  .banner .reasons { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
`;

const reasonChips = list => `<div class="reasons">${list.map(r => `<span class="reason w${r.weight}">${r.text}</span>`).join('')}</div>`;

export function index(ctx) {
  const ranked = ctx.projects.map(p => ({ p, a: attention(p, ctx) })).sort((x, y) => y.a.score - x.a.score || x.p.title.localeCompare(y.p.title));
  const rows = ranked.map(({ p, a }, n) => `<li><span class="rank">${n + 1}</span><div>
<div class="title">${icon(p)}${ctx.link(p.title, ctx.hrefTo('index.html', p.page))} <span class="age ${ageClass(a.stats.reviewAge)}">STATE ${ageLabel(a.stats.reviewAge)}</span></div>
${a.reasons.length ? reasonChips(a.reasons) : '<div class="reasons"><span class="reason">Nothing flagged</span></div>'}
</div><div class="score"><b>${a.score}</b><small>attention</small></div></li>`).join('');
  return { title: 'Attention queue', crumbs: ['Projects'], body: `<div class="head"><h1>What needs a look<span class="count">${ctx.projects.length}</span></h1>
<p class="sub">Ranked by stale STATE reviews, unitemized next steps, digest age, and session activity. Ages count from today.</p></div>
<ol class="queue">${rows}</ol>` };
}

export function project(p, ctx) {
  const a = attention(p, ctx);
  const banner = a.reasons.length
    ? `<div class="banner"><b>Needs attention</b> · score ${a.score}${reasonChips(a.reasons)}</div>`
    : '<div class="banner ok"><b>Nothing flagged.</b> STATE is fresh and next steps are itemized.</div>';
  const page = ctx.defaults.project(p, ctx);
  return { ...page, body: page.body.replace(ctx.remoteNote, banner) };
}
