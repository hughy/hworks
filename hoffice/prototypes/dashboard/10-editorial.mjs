import { stats, tasks, firstParagraph, ageLabel } from './_shared.mjs';

export const meta = {
  id: 'editorial',
  title: 'Editorial briefing',
  approach: 'Reads like a weekly report: one serif column, each project a short article with its lead, open next steps, the first paragraph of its summary, and a count of open questions. Project pages become long-form documents with a sticky table of contents built from every STATE heading, and both print cleanly.',
  differences: ['Narrative single column instead of a table and sidebar', 'Serif type, wider line height, 68-character measure', 'Full STATE rendered on the project page with a generated table of contents', 'Print stylesheet: one project per page, links shown as text'],
  features: ['Good for reading before a sync or sharing as a PDF', 'Shows every STATE section, not just three', 'Calm, low-chrome reading experience'],
};

export const css = `
  .ed { --serif: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif; }
  body { background: #fbfaf7; }
  .top { background: rgba(251,250,247,.92); }
  main { max-width: 760px; }
  main:has(.doc-layout) { max-width: 1000px; }
  .ed h1 { font: 600 34px/1.15 var(--serif); letter-spacing: -0.01em; }
  .ed .kicker { margin: 0 0 6px; font-size: 12px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
  .ed .dek { margin: 10px 0 32px; font: italic 18px/1.5 var(--serif); color: #4a4d53; }
  .ed article { padding: 28px 0; border-top: 1px solid #e4e1d8; }
  .ed article h2 { margin: 0 0 4px; font: 600 24px/1.25 var(--serif); }
  .ed article h2 a { text-decoration: none; }
  .ed article .by { margin: 0 0 12px; font-size: 12px; color: var(--muted); }
  .ed article p, .ed article li { font: 17px/1.6 var(--serif); color: #24262a; }
  .ed article h3 { margin: 18px 0 4px; font-size: 12px; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); }
  .ed ul.tasks li.task { border: 0; padding: 4px 0; }
  .ed .doc-layout { display: grid; grid-template-columns: 200px minmax(0, 1fr); gap: 40px; align-items: start; }
  .ed .toc { position: sticky; top: 68px; font-size: 12.5px; }
  .ed .toc a { display: block; padding: 3px 0; color: var(--muted); text-decoration: none; }
  .ed .toc a:hover { color: var(--fg); }
  .ed .long .prose { font: 17px/1.65 var(--serif); }
  .ed .long .prose h2 { margin: 36px 0 8px; font: 600 22px/1.3 var(--serif); }
  .ed .long .prose h3 { font: 600 18px/1.3 var(--serif); color: var(--fg); }
  @media (max-width: 860px) { .ed .doc-layout { grid-template-columns: 1fr; } .ed .toc { position: static; } }
  @media print {
    .top, .toc { display: none; }
    body { background: #fff; }
    .ed article { break-after: page; border: 0; }
    a { color: inherit; text-decoration: none; }
  }
`;
export const bodyClass = 'ed';

export function index(ctx) {
  const from = 'index.html';
  const latest = ctx.docs.map(d => d.date).filter(Boolean).sort().at(-1) ?? '';
  const articles = ctx.projects.map(p => {
    const s = stats(p, ctx);
    const summary = firstParagraph(p, 'summary', ctx, from);
    const next = s.total ? `<ul class="tasks">${tasks(p, ctx, from, { openOnly: true })}</ul>` : (p.narrative['next steps']?.trim() ? `<p>${ctx.markdown(p.narrative['next steps'].trim(), p.state, from, { inline: true })}</p>` : '<p class="muted">None recorded.</p>');
    return `<article><h2>${ctx.link(p.title, ctx.hrefTo(from, p.page))}</h2>
<p class="by">STATE reviewed ${ageLabel(s.reviewAge)} · ${s.questions} open questions · ${s.sessions14} sessions in 14 days</p>
${p.lead ? `<p>${ctx.markdown(p.lead, p.source, from, { inline: true })}</p>` : ''}
${summary ? `<h3>Where it stands</h3><p>${summary}</p>` : ''}
<h3>Next</h3>${next}</article>`;
  }).join('');
  return { title: 'Briefing', crumbs: ['Briefing'], body: `<p class="kicker">Project briefing${latest ? ` · latest activity ${latest}` : ''}</p><h1>The state of ${ctx.projects.length} projects</h1>
<p class="dek">What each project is, where it stands, and what comes next, from the authored STATE files.</p>${articles}` };
}

export function project(p, ctx) {
  const from = p.page;
  const toc = Object.keys(p.narrative).map(name => `<a href="#${encodeURIComponent(name.replace(/\s+/g, '-'))}">${ctx.esc(name[0].toUpperCase() + name.slice(1))}</a>`).join('');
  const sections = Object.entries(p.narrative).map(([name, text]) => `<h2 id="${ctx.esc(name.replace(/\s+/g, '-'))}">${ctx.esc(name[0].toUpperCase() + name.slice(1))}</h2>${ctx.markdown(text, p.state, from, { tasks: name === 'next steps' })}`).join('');
  const body = `<p class="kicker">${ctx.esc(p.slug)} · reviewed ${p.reviewed || 'never'}</p><h1>${ctx.esc(p.title)}</h1>
${p.lead ? `<p class="dek">${ctx.markdown(p.lead, p.source, from, { inline: true })}</p>` : ''}
<div class="doc-layout"><nav class="toc" aria-label="Sections">${toc}<a href="${ctx.esc(ctx.fileHref(p.state, from))}">Source STATE →</a></nav><div class="long"><div class="prose">${sections || '<p class="muted">STATE unavailable.</p>'}</div>${ctx.parts.digests(p, from)}</div></div>`;
  return { title: p.title, crumbs: [ctx.indexCrumb(from), ctx.esc(p.title)], body };
}
