import { stats, icon, sharedCss, tok } from './_shared.mjs';

export const meta = {
  id: 'workspace',
  title: 'Split-pane workspace',
  approach: 'A single-page app in the style of a mail client: a persistent left sidebar lists projects and each project\'s documents, and the right pane shows the selected project without a page load. The URL hash keeps the selection; j and k step through projects.',
  differences: ['One page with a persistent sidebar instead of separate pages', 'Document tree per project in the sidebar, grouped by kind', 'Hash routing, so the back button and links work', 'Keyboard: j/k for next and previous project'],
  features: ['No context switch between projects', 'Navigates the whole instance from one place', 'Still links out to the rendered source pages for full documents'],
};

export const replaceCss = false;
export const bodyClass = 'app';
export const css = sharedCss + `
  body.app { display: grid; grid-template-columns: 280px minmax(0, 1fr); height: 100vh; overflow: hidden; }
  body.app > nav.side { overflow-y: auto; border-right: 1px solid var(--line); background: #fbfbfc; font-size: 13px; }
  body.app > .pane { overflow-y: auto; }
  body.app > .pane > main { max-width: 1040px; }
  .side .brand { position: sticky; top: 0; padding: 12px 14px; border-bottom: 1px solid var(--line); background: #fbfbfc; font-weight: 600; }
  .side .brand small { display: block; font-weight: 400; color: var(--muted); }
  .side a.proj { display: flex; align-items: center; gap: 8px; padding: 6px 12px; margin: 2px 6px; border-radius: 6px; text-decoration: none; }
  .side a.proj:hover { background: var(--soft); }
  .side a.proj[aria-current="true"] { background: var(--accent-soft); color: var(--accent); font-weight: 500; }
  .side a.proj .n { margin-left: auto; font-size: 11px; color: var(--muted); }
  .side details { margin: 0 6px 0 36px; }
  .side summary { padding: 3px 4px; color: var(--muted); cursor: pointer; font-size: 12px; text-transform: capitalize; }
  .side details a { display: block; padding: 3px 6px; color: var(--muted); text-decoration: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
  .side details a:hover { color: var(--fg); }
  .side .tree { display: none; padding-bottom: 6px; }
  .side .tree.on { display: block; }
  .side .help { padding: 12px 14px; color: var(--faint); font-size: 12px; }
  .view:not(.on) { display: none; }
  @media (max-width: 860px) { body.app { grid-template-columns: 1fr; height: auto; overflow: visible; } body.app > nav.side, body.app > .pane { overflow: visible; } }
`;

export function shell({ body }) {
  return body;
}

export const script = `
(() => {
  const views = [...document.querySelectorAll('.view')];
  if (!views.length) return;
  const show = id => {
    if (!views.some(v => v.id === id)) id = views[0].id;
    views.forEach(v => v.classList.toggle('on', v.id === id));
    document.querySelectorAll('a.proj').forEach(a => a.setAttribute('aria-current', String(a.hash === '#' + id)));
    document.querySelectorAll('.tree').forEach(t => t.classList.toggle('on', t.dataset.for === id));
    document.querySelector('.pane').scrollTop = 0;
  };
  addEventListener('hashchange', () => show(location.hash.slice(1)));
  addEventListener('keydown', e => {
    if (e.target.matches('input, textarea') || !['j', 'k'].includes(e.key)) return;
    const i = views.findIndex(v => v.classList.contains('on'));
    location.hash = views[(i + (e.key === 'j' ? 1 : views.length - 1)) % views.length].id;
  });
  show(location.hash.slice(1));
})();`;

// Non-index pages keep the base layout inside the pane, with the sidebar linking back to the app.
function frame(ctx, from, side, main) {
  return `<nav class="side" aria-label="Projects"><div class="brand">Projects<small>${ctx.projects.length} projects · ${ctx.docs.length} documents</small></div>${side}<p class="help"><span class="kbd">j</span> <span class="kbd">k</span> next / previous project</p></nav>
<div class="pane"><main>${main}</main></div>`;
}

function sidebar(ctx, from, current) {
  return ctx.projects.map(p => {
    const groups = Object.create(null);
    for (const f of p.files.filter(f => !f.readme)) (groups[f.kind] ??= []).push(f);
    const target = from === 'index.html' ? `#${tok(p.slug)}` : `${ctx.hrefTo(from, 'index.html')}#${tok(p.slug)}`;
    return `<a class="proj" href="${ctx.esc(target)}" aria-current="${p.slug === current}">${icon(p)}<span>${ctx.esc(p.title)}</span><span class="n">${stats(p, ctx).open || ''}</span></a>
<div class="tree${p.slug === current ? ' on' : ''}" data-for="${tok(p.slug)}">${Object.entries(groups).map(([kind, files]) => `<details${kind === 'root' ? ' open' : ''}><summary>${kind === 'root' ? 'Core' : ctx.esc(kind)} (${files.length})</summary>${files.sort((a, b) => (b.date || '').localeCompare(a.date || '') || a.title.localeCompare(b.title)).map(f => `<a href="${ctx.esc(ctx.hrefTo(from, f.page))}" title="${ctx.esc(f.title)}">${ctx.esc(f.title)}</a>`).join('')}</details>`).join('')}</div>`;
  }).join('');
}

export function index(ctx) {
  const views = ctx.projects.map(p => `<div class="view" id="${tok(p.slug)}">${ctx.parts.projectBody(p, 'index.html').replace(ctx.remoteNote, '')}</div>`).join('');
  return { title: 'Projects', body: frame(ctx, 'index.html', sidebar(ctx, 'index.html'), views || '<p class="muted">No projects registered.</p>') };
}

export function project(p, ctx) {
  return { title: p.title, body: frame(ctx, p.page, sidebar(ctx, p.page, p.slug), `<p class="note">This workspace shows projects in ${ctx.link('one page', `${ctx.hrefTo(p.page, 'index.html')}#${tok(p.slug)}`)}.</p>${ctx.parts.projectBody(p, p.page)}`) };
}

export function doc(d, ctx) {
  const page = ctx.defaults.doc(d, ctx);
  return { title: page.title, body: frame(ctx, d.page, sidebar(ctx, d.page, d.owner), `<nav class="top" style="position:static;padding:0 0 12px;height:auto;border:0;background:none">${page.crumbs.join('<span class="sep">/</span>')}</nav>${page.body}`) };
}
