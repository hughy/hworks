// Helpers shared by the dashboard variants. Files starting with _ are not variants.

// Derived signals for one project, all from the local instance.
export function stats(project, ctx) {
  const dated = project.files.filter(f => f.date && !f.readme);
  const recent = days => dated.filter(f => ctx.age(f.date) <= days);
  const digestEnd = project.digests.map(d => ctx.date(d.end)).sort().at(-1) ?? '';
  const lastActivity = [...dated.map(f => f.date), digestEnd, project.reviewed].filter(Boolean).sort().at(-1) ?? '';
  return {
    open: project.steps.total - project.steps.done, done: project.steps.done, total: project.steps.total,
    questions: project.questions.length,
    sessions: dated.filter(f => f.kind === 'sessions').length,
    sessions14: recent(14).filter(f => f.kind === 'sessions').length,
    decisions: dated.filter(f => f.kind === 'decisions').length,
    documents: project.files.length,
    authoritative: project.docs.length,
    digestEnd, digestAge: ctx.age(digestEnd),
    lastActivity, activityAge: ctx.age(lastActivity),
    reviewAge: project.reviewedAge,
  };
}

export const ageLabel = days => days === null || days === undefined ? 'never' : days <= 0 ? 'today' : days === 1 ? '1 day ago' : `${days} days ago`;
export const ageClass = days => days === null || days === undefined ? 'unknown' : days <= 7 ? 'fresh' : days <= 21 ? 'aging' : 'stale';

// Reasons a project needs a look, heaviest first. The score orders the attention queue.
export function attention(project, ctx) {
  const s = stats(project, ctx);
  const reasons = [];
  if (s.reviewAge === null) reasons.push({ weight: 3, text: 'STATE has no review date' });
  else if (s.reviewAge > 21) reasons.push({ weight: 3, text: `STATE reviewed ${s.reviewAge} days ago` });
  else if (s.reviewAge > 7) reasons.push({ weight: 1, text: `STATE reviewed ${s.reviewAge} days ago` });
  if (!s.total) reasons.push({ weight: 2, text: project.narrative['next steps']?.trim() ? 'Next steps are not a list' : 'No next steps' });
  if (s.questions >= 5) reasons.push({ weight: 1, text: `${s.questions} open questions` });
  if (!project.digests.length) reasons.push({ weight: 1, text: 'No digest covers it' });
  else if (s.digestAge > 7) reasons.push({ weight: 1, text: `Latest digest ${s.digestAge} days old` });
  if (s.sessions14 === 0) reasons.push({ weight: 1, text: 'No sessions in 14 days' });
  return { score: reasons.reduce((n, r) => n + r.weight, 0), reasons: reasons.sort((a, b) => b.weight - a.weight), stats: s };
}

// A stable hue per project so every view colours it the same way.
export function hue(slug) {
  let h = 0;
  for (const c of slug) h = (h * 31 + c.charCodeAt(0)) % 360;
  return h;
}
export const icon = project => `<span class="icon" style="--h:${hue(project.slug)}" aria-hidden="true">${[...project.title][0]?.toUpperCase() ?? '?'}</span>`;

// Next-step items as read-only checkboxes, rendered inline for compact views.
export function tasks(project, ctx, from, { limit = Infinity, openOnly = false } = {}) {
  const items = project.stepItems.filter(i => !openOnly || !i.checked).slice(0, limit);
  return items.map(i => `<li class="task${i.checked ? ' done' : ''}"><input type="checkbox" disabled${i.checked ? ' checked' : ''} aria-label="${i.checked ? 'Done' : 'Open'}"><div>${ctx.markdown(i.text, project.state, from, { inline: true })}</div></li>`).join('');
}

// The first paragraph of a STATE section, for summaries that link to the full text.
export function firstParagraph(project, name, ctx, from) {
  const text = (project.narrative[name] ?? '').trim().split(/\n\s*\n/)[0] ?? '';
  return text ? ctx.markdown(text, project.state, from, { inline: true }) : '';
}

// Elements with data-search filter on a text box with data-filter; buttons with data-facet="key=value"
// narrow to elements whose data-<key> attribute contains the value. Press / to focus the box.
export const filterScript = `
(() => {
  const box = document.querySelector('[data-filter]');
  const items = [...document.querySelectorAll('[data-search]')];
  const facets = {};
  const apply = () => {
    const q = (box?.value ?? '').toLowerCase().trim();
    let shown = 0;
    for (const el of items) {
      const ok = (!q || el.dataset.search.toLowerCase().includes(q)) &&
        Object.entries(facets).every(([k, v]) => !v || (el.dataset[k] ?? '').split(' ').includes(v));
      el.hidden = !ok; if (ok) shown++;
    }
    document.querySelectorAll('[data-count]').forEach(el => { el.textContent = shown; });
    document.querySelectorAll('[data-group]').forEach(g => { g.hidden = !g.querySelector('[data-search]:not([hidden])'); });
  };
  box?.addEventListener('input', apply);
  document.querySelectorAll('[data-facet]').forEach(btn => btn.addEventListener('click', () => {
    const [k, v] = btn.dataset.facet.split('=');
    facets[k] = facets[k] === v ? '' : v;
    document.querySelectorAll(\`[data-facet^="\${k}="]\`).forEach(b => b.setAttribute('aria-pressed', String(b.dataset.facet === \`\${k}=\${facets[k]}\`)));
    apply();
  }));
  addEventListener('keydown', e => { if (e.key === '/' && document.activeElement !== box && box) { e.preventDefault(); box.focus(); } });
  apply();
})();`;

// j and k move through [data-nav] rows, Enter opens the row's first link.
export const keyNavScript = `
(() => {
  const rows = () => [...document.querySelectorAll('[data-nav]')].filter(r => !r.hidden);
  let i = -1;
  const mark = () => rows().forEach((r, n) => r.classList.toggle('cursor', n === i));
  addEventListener('keydown', e => {
    if (e.target.matches('input, textarea')) { if (e.key === 'Escape') e.target.blur(); return; }
    const list = rows();
    if (e.key === 'j') { i = Math.min(list.length - 1, i + 1); mark(); list[i]?.scrollIntoView({ block: 'nearest' }); }
    if (e.key === 'k') { i = Math.max(0, i - 1); mark(); list[i]?.scrollIntoView({ block: 'nearest' }); }
    if (e.key === 'Enter' && list[i]) list[i].querySelector('a')?.click();
  });
})();`;

// Tokens and pieces several variants reuse on top of the base sheet.
export const sharedCss = `
  .icon { background: hsl(var(--h, 235) 70% 95%); color: hsl(var(--h, 235) 55% 42%); }
  .age { display: inline-block; padding: 0 6px; border-radius: 4px; font-size: 12px; line-height: 19px; white-space: nowrap; }
  .age.fresh { background: #e7f6ec; color: #1f7a3d; }
  .age.aging { background: #fdf3dc; color: #8a5a00; }
  .age.stale { background: #fde8e8; color: #b42318; }
  .age.unknown { background: var(--soft); color: var(--muted); }
  .chip { display: inline-block; padding: 0 8px; border: 1px solid var(--line); border-radius: 10px; font-size: 12px; line-height: 20px; color: var(--muted); background: var(--bg); white-space: nowrap; }
  button.chip { cursor: pointer; font: inherit; font-size: 12px; }
  button.chip[aria-pressed="true"] { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
  input.filter { width: 100%; max-width: 360px; padding: 7px 10px; border: 1px solid var(--line); border-radius: 6px; font: inherit; background: var(--bg); color: var(--fg); }
  input.filter:focus { outline: 2px solid var(--accent-soft); border-color: var(--accent); }
  .toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 0 0 16px; }
  .kbd { padding: 0 5px; border: 1px solid var(--line); border-bottom-width: 2px; border-radius: 4px; font: 11px ui-monospace, Menlo, monospace; color: var(--muted); }
  [hidden] { display: none !important; }
  .cursor { outline: 2px solid var(--accent); outline-offset: -2px; }
`;
