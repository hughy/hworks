import { stats, icon, ageLabel, ageClass, sharedCss } from './_shared.mjs';

export const meta = {
  id: 'board',
  title: 'Board',
  approach: 'Lays the portfolio out as a board: one column per project, each holding cards for open next steps, open questions, and done items. Project pages use the same board shape across Next steps, Open questions, and Recent sessions.',
  differences: ['Columns per project with horizontal scroll', 'Questions appear as their own card type beside steps', 'Done items collapse to the bottom of each column', 'Project page is a three-column board instead of a document'],
  features: ['Compares workload across projects side by side', 'Shows blockers (questions) next to the work they block', 'Familiar issue-tracker board layout without needing a tracker'],
};

export const css = sharedCss + `
  main { max-width: none; }
  .board { display: grid; grid-auto-flow: column; grid-auto-columns: minmax(280px, 1fr); gap: 14px; overflow-x: auto; padding-bottom: 12px; align-items: start; }
  .col { padding: 10px; border-radius: 10px; background: var(--soft); }
  .col > h2 { display: flex; align-items: center; gap: 8px; margin: 2px 4px 10px; font-size: 13px; }
  .col > h2 a { text-decoration: none; }
  .col > h2 .count { margin-left: auto; background: var(--bg); }
  .col .meta { margin: -4px 4px 10px; }
  .tile { margin: 0 0 8px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--bg); font-size: 13px; line-height: 1.45; }
  .tile .kind { display: block; margin-bottom: 4px; font-size: 11px; font-weight: 600; letter-spacing: .03em; text-transform: uppercase; color: var(--accent); }
  .tile.question .kind { color: #8a5a00; }
  .tile.session .kind { color: var(--muted); }
  .tile .text { display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden; }
  details.done summary { cursor: pointer; margin: 6px 4px; font-size: 12px; color: var(--muted); }
  details.done .tile { opacity: .65; text-decoration: line-through; }
  .empty { margin: 4px; font-size: 12px; color: var(--muted); }
`;

const tile = (kind, cls, html) => `<div class="tile ${cls}"><span class="kind">${kind}</span><div class="text">${html}</div></div>`;

function column(title, head, tiles, done = '') {
  return `<section class="col"><h2>${title}</h2>${head}${tiles || '<p class="empty">Nothing here.</p>'}${done}</section>`;
}

export function index(ctx) {
  const from = 'index.html';
  const cols = ctx.projects.map(p => {
    const s = stats(p, ctx);
    const md = text => ctx.markdown(text, p.state, from, { inline: true });
    const open = p.stepItems.filter(i => !i.checked).map(i => tile('Next step', 'step', md(i.text))).join('');
    const prose = !s.total && p.narrative['next steps']?.trim() ? tile('Next steps (prose)', 'step', md(p.narrative['next steps'].trim().split('\n')[0])) : '';
    const questions = p.questions.map(q => tile('Question', 'question', md(q.text))).join('');
    const done = p.stepItems.filter(i => i.checked);
    return column(`${icon(p)}${ctx.link(p.title, ctx.hrefTo(from, p.page))}<span class="count">${s.open + s.questions}</span>`,
      `<div class="meta"><span class="age ${ageClass(s.reviewAge)}">STATE ${ageLabel(s.reviewAge)}</span></div>`,
      open + prose + questions,
      done.length ? `<details class="done"><summary>${done.length} done</summary>${done.map(i => tile('Done', 'step', md(i.text))).join('')}</details>` : '');
  }).join('');
  return { title: 'Board', crumbs: ['Board'], body: `<div class="head"><h1>Board<span class="count">${ctx.projects.length} projects</span></h1><p class="sub">Open next steps, then open questions, per project. Read from STATE; edit STATE to move a card.</p></div><div class="board">${cols}</div>` };
}

export function project(p, ctx) {
  const from = p.page;
  const md = text => ctx.markdown(text, p.state, from, { inline: true });
  const sessions = p.files.filter(f => f.kind === 'sessions' && f.date && !f.readme).sort((a, b) => b.date.localeCompare(a.date)).slice(0, 12);
  const prose = !p.steps.total && p.narrative['next steps']?.trim() ? tile('Next steps (prose)', 'step', md(p.narrative['next steps'].trim())) : '';
  const body = `${ctx.parts.head(p, from)}
<div class="board">
${column(`Next steps<span class="count">${p.steps.total - p.steps.done}</span>`, '', p.stepItems.filter(i => !i.checked).map(i => tile('Next step', 'step', md(i.text))).join('') + prose)}
${column(`Open questions<span class="count">${p.questions.length}</span>`, '', p.questions.map(q => tile('Question', 'question', md(q.text))).join(''))}
${column(`Recent sessions<span class="count">${sessions.length}</span>`, '', sessions.map(f => tile(f.date, 'session', ctx.link(f.title, ctx.hrefTo(from, f.page)))).join(''))}
</div>
<div class="layout" style="margin-top:32px"><div>${ctx.parts.section(p, 'summary', 'Summary', from)}${ctx.parts.digests(p, from)}</div><aside>${ctx.parts.properties(p, from)}${ctx.parts.repositories(p, from)}${ctx.parts.sources(p, from)}</aside></div>`;
  return { title: p.title, crumbs: [ctx.indexCrumb(from), ctx.esc(p.title)], body };
}
