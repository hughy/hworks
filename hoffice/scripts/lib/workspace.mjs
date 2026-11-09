import { readFileSync } from 'node:fs';
import { parseFrontmatter, esc as escapeHtml } from './render-common.mjs';

// Derived signals for one project, all from the local instance.
function stats(project, ctx) {
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

const ageLabel = days => days === null || days === undefined ? 'never' : days <= 0 ? 'today' : days === 1 ? '1 day ago' : `${days} days ago`;
const ageClass = days => days === null || days === undefined ? 'unknown' : days <= 7 ? 'fresh' : days <= 21 ? 'aging' : 'stale';

// Reasons a project needs a look, heaviest first. The score orders the attention queue.
function attention(project, ctx) {
  const s = stats(project, ctx);
  const reasons = (ctx.roster?.roles ?? []).filter(r => r.project === project.slug && !r.live)
    .map(r => ({ weight: 3, text: `Session stale: ${r.name}` }));
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
function hue(slug) {
  let h = 0;
  for (const c of slug) h = (h * 31 + c.charCodeAt(0)) % 360;
  return h;
}
// A token safe in ids, classes, URL fragments, and space-separated data attributes.
const tok = value => String(value).replace(/[^A-Za-z0-9-]/g, ch => `_${ch.codePointAt(0).toString(16)}_`);

const kinds = Object.assign(Object.create(null), { sessions: 'Session', decisions: 'Decision', digests: 'Digest', published: 'Published', notes: 'Note' });
const kindName = (kind, ctx) => kinds[kind] ?? ctx.esc(kind);

function weekOf(day) {
  const d = new Date(day + 'T00:00:00Z');
  d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
  return d.toISOString().slice(0, 10);
}
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const short = day => `${MONTHS[Number(day.slice(5, 7)) - 1]} ${Number(day.slice(8, 10))}`;

// Front matter through the engine's own YAML reader; a note without valid front matter keeps its whole text as body.
function frontMatter(text) {
  text = text.replace(/\r\n?/g, '\n');
  try {
    const { fm, body } = parseFrontmatter(text);
    return { fm: fm && typeof fm === 'object' ? fm : {}, body };
  } catch {
    return { fm: {}, body: text.replace(/^---\n[\s\S]*?\n---\n?/, '') };
  }
}

function sections(body) {
  const out = Object.create(null);
  const parts = body.split(/^## +(.+)$/m);
  out[''] = parts[0].replace(/^# .*$/m, '').trim();
  for (let i = 1; i < parts.length; i += 2) out[parts[i].trim().toLowerCase()] = parts[i + 1].trim();
  return out;
}

const firstPara = text => (text ?? '').split(/\n\s*\n/).find(p => p.trim() && !/^\s*[-*] |^\s*\d+\. /.test(p))?.trim() ?? '';
const topBullets = (text, n) => (text ?? '').split('\n').filter(l => /^[-*] /.test(l)).slice(0, n);
const list = v => (Array.isArray(v) ? v : v === undefined || v === null || v === '' ? [] : [v]).filter(x => typeof x === 'string' || typeof x === 'number').map(String);

const SUMMARY = ['goal', 'decision', 'summary', 'context', 'what changed', 'highlights'];
const FINDINGS = ['what was learned', 'findings', 'consequences', 'outcome', 'next', 'what was done'];

// All dated, non-README documents as events, newest first. Built once per render and shared by every page.
const built = new WeakMap();
function events(ctx) {
  if (!built.has(ctx)) built.set(ctx, build(ctx));
  return built.get(ctx);
}
function build(ctx) {
  return ctx.docs.filter(d => d.date && !d.readme).map(doc => {
    let text = '';
    try { text = readFileSync(doc.source, 'utf8'); } catch { /* missing file: title-only event */ }
    const { fm, body } = frontMatter(text);
    const sec = sections(body);
    const summaryKey = SUMMARY.find(k => sec[k]);
    const findingsKey = FINDINGS.find(k => k !== summaryKey && topBullets(sec[k], 1).length);
    const findings = findingsKey ? topBullets(sec[findingsKey], 3) : [];
    return {
      doc, date: doc.date, kind: doc.kind, owner: doc.owner, title: doc.title,
      project: ctx.projects.find(p => p.slug === doc.owner),
      status: typeof fm.status === 'string' ? fm.status : '',
      prs: list(fm.prs), tickets: list(fm.tickets), tags: list(fm.tags),
      summary: firstPara(summaryKey ? sec[summaryKey] : sec['']), summaryLabel: summaryKey ?? '',
      findings, findingsLabel: findingsKey ?? '', findingsMore: findingsKey ? topBullets(sec[findingsKey], 99).length - findings.length : 0,
      done: topBullets(sec['what was done'], 99).length,
    };
  }).sort((a, b) => b.date.localeCompare(a.date) || a.doc.rel.localeCompare(b.doc.rel));
}

const projectEvents = (p, ctx, all) => all.filter(e => e.owner === p.slug ||
  (e.kind === 'digests' && p.digests.some(g => e.doc.source.startsWith(g.source.slice(0, g.source.lastIndexOf('/') + 1)))));

// Small badges for the facts a row carries: decision status, PRs, tickets.
function badges(e, ctx) {
  const out = [];
  if (e.status) out.push(`<span class="st st-${tok(e.status)}">${ctx.esc(e.status)}</span>`);
  if (e.prs.length) out.push(`<span class="meta-n" title="Pull requests">${e.prs.length} PR${e.prs.length === 1 ? '' : 's'}</span>`);
  if (e.tickets.length) out.push(`<span class="meta-n" title="Tickets">${e.tickets.length} ticket${e.tickets.length === 1 ? '' : 's'}</span>`);
  return out.join('');
}

// The folded body of an event: summary, findings, links, tags. Empty string when there is nothing to fold.
function detail(e, ctx, from) {
  const md = (text, opts) => ctx.markdown(text, e.doc.source, from, opts);
  const parts = [];
  if (e.summary) parts.push(`<div class="d-sum">${e.summaryLabel ? `<b>${ctx.esc(cap(e.summaryLabel))}.</b> ` : ''}${md(e.summary, { inline: true })}</div>`);
  if (e.findings.length) parts.push(`<div class="d-find"><b>${ctx.esc(cap(e.findingsLabel))}</b>${md(e.findings.join('\n'))}${e.findingsMore ? `<p class="muted">+${e.findingsMore} more in the full note</p>` : ''}</div>`);
  const links = e.prs.slice(0, 6).map(u => `<li>${linkOut(u, ctx)}</li>`).join('');
  if (links) parts.push(`<div class="d-links"><b>Pull requests</b><ul>${links}</ul></div>`);
  if (e.tags.length) parts.push(`<p class="d-tags">${e.tags.map(t => `<span>${ctx.esc(t)}</span>`).join('')}</p>`);
  if (!parts.length) return '';
  return parts.join('') + `<p class="d-open">${ctx.link('Open the full note →', ctx.hrefTo(from, e.doc.page))}</p>`;
}
const cap = s => s.charAt(0).toUpperCase() + s.slice(1);
function linkOut(u, ctx) {
  const m = u.match(/^https?:\/\/[^/]+\/([^/]+\/[^/]+)\/pull\/(\d+)/);
  return m ? `<a href="${ctx.esc(u)}">${ctx.esc(m[1])}#${m[2]}</a>` : ctx.esc(u);
}

// Counts of events per week for the last n weeks, oldest first, ending at the render date's week.
function weekly(list, now, n = 12) {
  const end = weekOf(now.toISOString().slice(0, 10));
  const keys = Array.from({ length: n }, (_, i) => {
    const d = new Date(end + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() - 7 * (n - 1 - i)); return d.toISOString().slice(0, 10);
  });
  const counts = Object.fromEntries(keys.map(k => [k, 0]));
  for (const e of list) { const w = weekOf(e.date); if (w in counts) counts[w]++; }
  return keys.map(k => [k, counts[k]]);
}

function spark(series) {
  const max = Math.max(1, ...series.map(([, n]) => n));
  return `<span class="spark" role="img" aria-label="Events per week, last ${series.length} weeks: ${series.map(([, n]) => n).join(', ')}">${series.map(([w, n]) => `<span title="Week of ${w}: ${n}" style="height:${n ? Math.max(3, Math.round(n / max * 20)) : 2}px"${n ? '' : ' class="z"'}></span>`).join('')}</span>`;
}

const foldButtons = `<span class="fold-ctl"><button type="button" data-fold="open">Expand all</button><button type="button" data-fold="close">Collapse all</button></span>`;

function foldDigests(items) {
  const digests = items.filter(e => e.kind === 'digests');
  if (digests.length < 2) return items;
  const out = [];
  for (const e of items) {
    if (e.kind !== 'digests') out.push(e);
    else if (e === digests[0]) out.push({ group: true, kind: 'digests', date: e.date, items: digests,
      prs: digests.flatMap(d => d.prs), tickets: digests.flatMap(d => d.tickets) });
  }
  return out;
}
const groupTitle = g => `${g.items.length} daily digests`;
function groupBody(g, ctx, from) {
  return `<ul class="g-list">${g.items.map(e => `<li><time datetime="${e.date}">${short(e.date)}</time>${ctx.link(e.title, ctx.hrefTo(from, e.doc.page))}<span class="meta-n">${badges(e, ctx)}</span></li>`).join('')}</ul>`;
}
const HOME = '_home';
const viewId = slug => `v-${slug === null ? HOME : tok(slug)}`;
const viewHref = (ctx, from, slug) => `${from === 'index.html' ? '' : ctx.esc(ctx.hrefTo(from, 'index.html'))}#${viewId(slug)}`;
const icon = p => `<span class="icon" style="--h:${hue(p.slug)}" aria-hidden="true">${escapeHtml([...p.title][0]?.toUpperCase() ?? '?')}</span>`;
const level = s => s >= 5 ? 'hi' : s >= 2 ? 'mid' : 'lo';

function tree(p, ctx, from) {
  const groups = Object.create(null);
  for (const f of p.files.filter(f => !f.readme)) (groups[f.kind] ??= []).push(f);
  return Object.entries(groups).map(([kind, files]) => `<details class="tk"${kind === 'root' ? ' open' : ''}><summary>${kind === 'root' ? 'Core' : ctx.esc(kind)} <small>${files.length}</small></summary>${files
    .sort((a, b) => (b.date || '').localeCompare(a.date || '') || a.title.localeCompare(b.title))
    .map(f => `<a class="doc" href="${ctx.esc(ctx.hrefTo(from, f.page))}" data-doc="${ctx.esc(f.rel)}" title="${ctx.esc(f.title)}" data-search="${ctx.esc(`${f.title} ${p.title}`)}">${f.date ? `<time>${short(f.date)}</time>` : ''}${ctx.esc(f.title)}</a>`).join('')}</details>`).join('');
}

export function workspace(ctx, from, current = null) {
  const rows = ranked(ctx);
  const onIndex = from === 'index.html';
  const navLink = (slug, inner) => `<a class="sv" href="${viewHref(ctx, from, slug)}" aria-current="${slug === current}">${inner}</a>`;
  const nav = `<nav class="ws-nav" aria-label="Projects"><div class="ws-brand">Projects<small>${ctx.projects.length} projects · ${ctx.docs.length} documents</small></div>
<input class="ws-filter" data-ws-filter placeholder="Filter projects and documents  ( / )" aria-label="Filter projects and documents">
${navLink(null, `<span class="icon ws-home" aria-hidden="true">◎</span><span class="ws-t"><span>Overview</span><small>${rows.filter(r => r.a.reasons.length).length} need a look</small></span>`)}
${rows.map(({ p, a }) => `<div class="ws-p" data-p="${ctx.esc(p.title)}">${navLink(p.slug, `${icon(p)}<span class="ws-t"><span>${ctx.esc(p.title)}</span><small>${ageLabel(a.stats.activityAge)}${a.stats.total ? ` · ${a.stats.open} open` : ''}</small></span><span class="ws-dot ${level(a.score)}" title="${ctx.esc(a.reasons.map(r => r.text).join('; ') || 'Healthy')}"></span>`)}
<div class="ws-tree${p.slug === current ? ' on' : ''}" data-for="${viewId(p.slug)}">${tree(p, ctx, from)}</div></div>`).join('')}
<noscript><p>Project pages</p>${ctx.projects.map(p => `<p>${ctx.link(p.title, ctx.hrefTo(from, p.page))}</p>`).join('')}</noscript>
<p class="ws-help"><span class="kbd">j</span> <span class="kbd">k</span> project · <span class="kbd">/</span> filter · Escape clear</p></nav>`;
  const views = onIndex
    ? `<section class="view" id="${viewId(null)}">${home(ctx)(from)}</section>${ctx.projects.map(p => `<section class="view" id="${viewId(p.slug)}" hidden>${pane(ctx)(p, from)}</section>`).join('')}`
    : `<section class="view" id="${viewId(current)}">${pane(ctx)(ctx.projects.find(p => p.slug === current), from)}</section>`;
  return `<div class="ws">${nav}<div class="ws-pane">${views}</div></div>`;
}
const ranked = ctx => ctx.projects.map(p => ({ p, a: attention(p, ctx) }))
  .sort((x, y) => y.a.reasons.length - x.a.reasons.length || y.a.score - x.a.score || x.p.title.localeCompare(y.p.title));

const wsScript = `
(() => {
  const views = [...document.querySelectorAll('.view')];
  const links = [...document.querySelectorAll('a.sv')];
  if (!views.length) return;
  const show = hash => {
    const el = hash ? document.getElementById(hash) : null;
    const view = el?.classList.contains('view') ? el : el?.closest('.view') ?? views[0];
    views.forEach(v => { v.hidden = v !== view; });
    links.forEach(a => a.setAttribute('aria-current', String(a.hash === '#' + view.id)));
    document.querySelectorAll('.ws-tree').forEach(t => t.classList.toggle('on', t.dataset.for === view.id));
    if (!el || el === view) scrollTo(0, 0);
    else { for (let d = el.parentElement?.closest('details'); d; d = d.parentElement?.closest('details')) d.open = true; if (el.tagName === 'DETAILS') el.open = true; requestAnimationFrame(() => el.scrollIntoView({ block: 'start' })); }
  };
  const current = () => { try { return decodeURIComponent(location.hash.slice(1)); } catch { return ''; } };
  if (views.length > 1) {
    addEventListener('hashchange', () => show(current()));
    show(current());
    addEventListener('load', () => { const el = document.getElementById(current()); if (el?.classList.contains('view')) scrollTo(0, 0); });
  }
  const box = document.querySelector('[data-ws-filter]');
  box?.addEventListener('input', () => {
    const q = box.value.toLowerCase().trim();
    document.querySelectorAll('.ws-p').forEach(p => {
      let any = false;
      p.querySelectorAll('a.doc').forEach(a => { const ok = !q || a.dataset.search.toLowerCase().includes(q); a.hidden = !ok; any ||= ok && !!q; });
      p.querySelectorAll('details.tk').forEach(d => { const hit = !!q && !!d.querySelector('a.doc:not([hidden])'); if (q) d.open = hit; d.hidden = !!q && !hit; });
      const nameHit = !q || p.dataset.p.toLowerCase().includes(q);
      p.hidden = !nameHit && !any;
      p.querySelector('.ws-tree')?.classList.toggle('search', !!q && any);
    });
  });
  addEventListener('keydown', e => {
    if (/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName ?? '') || e.metaKey || e.ctrlKey || e.altKey) {
      if (e.key === 'Escape' && document.activeElement === box) { box.value = ''; box.dispatchEvent(new Event('input')); box.blur(); }
      return;
    }
    if (e.key === '/' && box) { e.preventDefault(); box.focus(); return; }
    if (!['j', 'k'].includes(e.key)) return;
    const visibleLinks = links.filter(a => !a.closest('[hidden]'));
    const i = Math.max(0, visibleLinks.findIndex(a => a.getAttribute('aria-current') === 'true'));
    location.href = visibleLinks[(i + (e.key === 'j' ? 1 : visibleLinks.length - 1)) % visibleLinks.length].href;
  });
})();
`;

const wsCss = `
  main:has(.ws) { max-width: none; padding: 0; }
  .ws { display: grid; grid-template-columns: var(--ws-w, 280px) minmax(0, 1fr); min-height: calc(100vh - 45px); }
  .ws-nav { position: sticky; top: 45px; align-self: start; height: calc(100vh - 45px); overflow-y: auto; padding: 0 8px 16px; border-right: 1px solid var(--line); background: var(--ws-bg, #fbfbfc); font-size: 13px; box-sizing: border-box; }
  .ws-pane { min-width: 0; padding: 28px 36px 96px; box-sizing: border-box; max-width: var(--ws-pane, 1120px); }
  .ws-brand { position: sticky; top: 0; z-index: 1; margin: 0 -8px 8px; padding: 12px 16px; border-bottom: 1px solid var(--line); background: var(--ws-bg, #fbfbfc); font-weight: 600; }
  .ws-brand small { display: block; font-weight: 400; color: var(--muted); font-size: 11.5px; }
  .ws-filter { width: 100%; box-sizing: border-box; margin: 0 0 8px; padding: 6px 9px; border: 1px solid var(--line); border-radius: 6px; font: inherit; font-size: 12.5px; background: var(--bg); color: var(--fg); }
  a.sv { display: flex; align-items: center; gap: 10px; padding: 7px 8px; border-radius: 8px; text-decoration: none; color: var(--fg); }
  a.sv:hover { background: var(--soft); }
  a.sv[aria-current="true"] { background: var(--accent-soft); box-shadow: inset 2px 0 0 var(--accent); }
  .ws-t { display: flex; flex-direction: column; min-width: 0; flex: 1; }
  .ws-t > span { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ws-t small { color: var(--muted); font-size: 11.5px; }
  .ws-home { --h: 235; }
  .ws-dot { flex: none; width: 8px; height: 8px; border-radius: 50%; background: #3fb36b; }
  .ws-dot.mid { background: #e0a526; } .ws-dot.hi { background: #e0533d; }
  .ws-tree { display: none; margin: 0 0 6px 30px; }
  .ws-tree.on, .ws-tree.search { display: block; }
  .ws-tree details > summary { padding: 3px 4px; color: var(--muted); font-size: 12px; text-transform: capitalize; }
  .ws-tree details > summary small { color: var(--faint, var(--muted)); }
  .ws-tree a.doc { max-width: 100%; box-sizing: border-box; display: flex; gap: 6px; padding: 3px 6px; color: var(--muted); text-decoration: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; border-radius: 4px; }
  .ws-tree a.doc time { flex: none; color: var(--faint, var(--muted)); font-variant-numeric: tabular-nums; min-width: 40px; }
  .ws-tree a.doc:hover { color: var(--fg); background: var(--soft); }
  .ws-help { margin: 16px 8px 0; color: var(--faint, var(--muted)); font-size: 11.5px; }
    .ws-pane code { overflow-wrap: anywhere; }
  @media (max-width: 860px) { .ws { grid-template-columns: minmax(0, 1fr); } .ws-nav { position: static; height: auto; max-height: 50vh; border-right: 0; border-bottom: 1px solid var(--line); } .ws-pane { padding: 20px 16px 64px; } }
`;

// First sentence of a STATE section as plain-ish inline HTML, for folded previews.
function preview(text, p, ctx, from, max = 180) {
  const para = (text ?? '').split(/\n\s*\n/).find(x => x.trim() && !/^\s*(\||```)/.test(x))?.replace(/^\s*[-*]\s+/, '').replace(/\s+/g, ' ').trim() ?? '';
  let first = para.split(/(?<=[.!?])\s+/)[0] ?? '';
  if (first.length > max) first = first.slice(0, max).replace(/\s+\S*$/, '') + '…';
  return first ? ctx.markdown(first, p.state, from, { inline: true }) : '';
}

// STATE sections other than next steps and open questions, in file order.
const stateSections = p => Object.keys(p.narrative).filter(k => !['next steps', 'open questions'].includes(k) && p.narrative[k]?.trim());
const title = k => k.charAt(0).toUpperCase() + k.slice(1);

// Next steps as a checklist with done items folded; prose next steps render as prose.
function steps(p, ctx, from) {
  const open = p.stepItems.filter(i => !i.checked), done = p.stepItems.filter(i => i.checked);
  if (!p.stepItems.length) return p.narrative['next steps']?.trim() ? `<div class="prose">${ctx.markdown(p.narrative['next steps'], p.state, from)}</div>` : '<p class="muted">No next steps recorded.</p>';
  const li = i => `<li class="task${i.checked ? ' done' : ''}"><input type="checkbox" disabled${i.checked ? ' checked' : ''} aria-label="${i.checked ? 'Done' : 'Open'}"><div>${ctx.markdown(i.text, p.state, from, { inline: true })}</div></li>`;
  return `<ul class="tasks">${open.map(li).join('')}</ul>${done.length ? `<details class="done-fold"><summary>${done.length} done</summary><ul class="tasks">${done.map(li).join('')}</ul></details>` : ''}`;
}

// Short label for a project's next steps: "3 open of 5", or "not itemized" when STATE writes them as prose.
const stepLabel = p => p.stepItems.length ? `${p.stepItems.filter(i => !i.checked).length} open of ${p.stepItems.length}` : p.narrative['next steps']?.trim() ? 'not itemized' : 'none';
// The first open step, or the first sentence of prose next steps.
function nextStep(p, ctx, from) {
  if (p.stepItems.length) {
    const item = p.stepItems.find(i => !i.checked);
    return item ? ctx.markdown(item.text, p.state, from, { inline: true }) : '';
  }
  return preview(p.narrative['next steps'], p, ctx, from, 200);
}

function questions(p, ctx, from) {
  const text = p.narrative['open questions']?.trim();
  return text ? `<div class="prose">${ctx.markdown(text, p.state, from)}</div>` : '<p class="muted">None recorded.</p>';
}

// One event as a folded row: date, kind, title; the summary, findings and links fold underneath.
function evRow(e, ctx, from) {
  const body = detail(e, ctx, from);
  const head = `<time datetime="${e.date}">${short(e.date)}</time><span class="kind ${tok(e.kind)}">${kindName(e.kind, ctx)}</span><span class="ev-t">${ctx.esc(e.title)}</span><span class="b">${badges(e, ctx)}</span>`;
  return body ? `<details class="ev fold"><summary>${head}</summary><div class="ev-body">${body}</div></details>`
    : `<div class="ev"><a class="ev-flat" href="${ctx.esc(ctx.hrefTo(from, e.doc.page))}">${head}</a></div>`;
}
// Daily digests fold together so they do not crowd out other recent notes.
function recent(p, ctx, from, n = 6) {
  const list = projectEvents(p, ctx, events(ctx));
  const items = foldDigests(list).slice(0, n);
  return { list, html: items.map(it => it.items ? `<details class="ev fold"><summary><time>${short(it.items[0].date)}</time><span class="kind digests">Digest</span><span class="ev-t">${groupTitle(it)}</span></summary><div class="ev-body">${groupBody(it, ctx, from)}</div></details>` : evRow(it, ctx, from)).join('') };
}
const evCss = `
  .ev { border-bottom: 1px solid var(--line); }
  .ev > summary, .ev-flat { display: flex; align-items: baseline; gap: 10px; padding: 8px 4px; cursor: pointer; color: var(--fg); text-decoration: none; list-style: none; }
  .ev > summary::-webkit-details-marker { display: none; }
  .ev > summary::before { content: '▸'; color: var(--muted); font-size: 10px; width: 8px; transition: transform .15s; }
  .ev[open] > summary::before { transform: rotate(90deg); }
  .ev-flat::before { content: ''; width: 8px; }
  .ev time { flex: none; width: 46px; color: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; }
  .ev .kind { flex: none; font-size: 11px; padding: 1px 7px; border-radius: 999px; background: var(--soft); color: var(--muted); }
  .ev .kind.decisions { background: #fdf0d8; color: #8a5a00; } .ev .kind.sessions { background: #e3f0ff; color: #1d5fa8; } .ev .kind.digests { background: #ece9fb; color: #5843b5; } .ev .kind.published { background: #e2f5ea; color: #217346; }
  .ev-t { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ev[open] .ev-t { white-space: normal; }
  .ev .b { flex: none; display: flex; gap: 4px; }
  .ev .b > span { font-size: 11px; color: var(--muted); border: 1px solid var(--line); border-radius: 999px; padding: 0 6px; }
  .ev-body { padding: 2px 8px 12px 68px; font-size: 13.5px; color: var(--fg); }
  .ev-body ul { margin: 4px 0; padding-left: 18px; } .ev-body p { margin: 4px 0; }
  .ev-body b { font-weight: 600; } .d-tags span { font-size: 11px; background: var(--soft); border-radius: 4px; padding: 1px 6px; margin-right: 4px; }
  ul.tasks { list-style: none; padding: 0; margin: 0; } li.task { display: flex; gap: 8px; padding: 5px 0; align-items: flex-start; } li.task input { margin-top: 4px; } li.task.done { color: var(--muted); } li.task > div > p { margin: 0; }
  details.done-fold > summary { color: var(--muted); font-size: 12.5px; padding: 4px 0; cursor: pointer; }
  @media (max-width: 860px) { .ev .b, .ev .kind { display: none; } .ev-body { padding-left: 12px; } }
`;

// Expand/collapse-all for the visible view only (the sidebar's trees stay as they are); everything opens for print.
const wsFold = `
(() => {
  document.querySelectorAll('[data-fold]').forEach(b => b.addEventListener('click', () => {
    b.closest('.view')?.querySelectorAll('details').forEach(d => { d.open = b.dataset.fold === 'open'; });
  }));
  const all = () => document.querySelectorAll('.ws-pane details');
  addEventListener('beforeprint', () => all().forEach(d => { d.dataset.wasOpen = d.open; d.open = true; }));
  addEventListener('afterprint', () => all().forEach(d => { d.open = d.dataset.wasOpen === 'true'; }));
})();
`;
const refinedCss = wsCss + evCss + `
  .ph { display: flex; gap: 14px; align-items: center; margin-bottom: 14px; } .ph .icon { width: 40px; height: 40px; font-size: 18px; border-radius: 10px; }
  .ph h1 { margin: 0; font-size: 24px; } .ph .sub { margin: 2px 0 0; color: var(--muted); font-size: 13px; }
  .lead { margin: 0 0 16px; font-size: 15px; color: var(--fg); max-width: 72ch; }
  .strip { display: flex; flex-wrap: wrap; gap: 0; border: 1px solid var(--line); border-radius: 10px; margin: 0 0 18px; }
  .strip > div { padding: 10px 16px; border-right: 1px solid var(--line); } .strip > div:last-child { border-right: 0; margin-left: auto; }
  .strip b { display: block; font-size: 18px; font-weight: 600; } .strip small { color: var(--muted); font-size: 11.5px; }
  .strip .stale b { color: #c0392b; } .strip .aging b { color: #b7791f; }
  .spark { display: inline-flex; align-items: flex-end; gap: 2px; height: 22px; } .spark span { width: 6px; background: var(--accent); border-radius: 1px; opacity: .8; } .spark span.z { background: var(--line); }
  .look { border-left: 3px solid #e0a526; background: #fffaf0; padding: 8px 14px; border-radius: 0 8px 8px 0; margin: 0 0 18px; font-size: 13.5px; }
  .look ul { margin: 4px 0 0; padding-left: 18px; }
  .cols { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr); gap: 28px; }
  h2.sh { font-size: 13px; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); margin: 22px 0 8px; display: flex; justify-content: space-between; align-items: baseline; }
  h2.sh a { text-transform: none; letter-spacing: 0; font-weight: 400; }
  details.sec { border-bottom: 1px solid var(--line); } details.sec > summary { padding: 10px 4px; cursor: pointer; list-style: none; }
  details.sec > summary::-webkit-details-marker { display: none; }
  details.sec > summary b { display: block; font-weight: 600; } details.sec > summary span { color: var(--muted); font-size: 13px; }
  details.sec[open] > summary span { display: none; } details.sec .prose { padding: 0 4px 12px; }
  .fold-ctl { float: right; } .fold-ctl button { font: inherit; font-size: 12px; border: 1px solid var(--line); background: var(--bg); border-radius: 6px; padding: 3px 9px; margin-left: 4px; cursor: pointer; }
  table.rank { width: 100%; border-collapse: collapse; font-size: 13.5px; } table.rank td, table.rank th { padding: 9px 8px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; } table.rank th { color: var(--muted); font-weight: 500; font-size: 12px; }
  table.rank .r { color: var(--muted); font-size: 12.5px; }
  @media (max-width: 1000px) { .cols { grid-template-columns: minmax(0, 1fr); } .strip > div:last-child { margin-left: 0; } }
`;


function strip(p, ctx, list) {
  const s = attention(p, ctx).stats;
  return `<div class="strip">
<div>${s.total ? `<b>${s.open}<small> / ${s.total}</small></b>` : '<b>–</b>'}<small>${s.total ? 'open steps' : `steps ${stepLabel(p)}`}</small></div>
<div><b>${s.questions}</b><small>open questions</small></div>
<div><b>${s.sessions14}</b><small>sessions, 14 days</small></div>
<div class="${ageClass(s.reviewAge)}"><b>${ageLabel(s.reviewAge)}</b><small>STATE reviewed</small></div>
<div class="${ageClass(s.digestAge)}"><b>${ageLabel(s.digestAge)}</b><small>latest digest</small></div>
<div>${spark(weekly(list, ctx.now))}<small style="display:block">notes per week, 12 weeks</small></div></div>`;
}

function sessions(ctx, from, project = null) {
  if (!ctx.roster) return '';
  const roles = ctx.roster.roles.filter(r => project === null || r.project === project);
  return `<h2 class="sh">Sessions</h2><p class="muted">Roster generated ${ageLabel(ctx.age(ctx.date(ctx.roster.generatedAt)))}</p>
<table class="rank"><thead><tr><th>Name</th><th>Project</th><th>Status</th><th>Last beat</th><th>Open items</th><th>Generation</th><th>Link</th></tr></thead><tbody>${roles.map(r => {
    const p = ctx.projects.find(p => p.slug === r.project);
    let url;
    try { url = new URL(r.link); } catch { /* invalid links stay plain text */ }
    const scheme = url?.protocol.slice(0, -1);
    // An allowlist may enable session handlers, never executable page content.
    const safe = ctx.roster.linkSchemes.includes(scheme) && !['javascript', 'data', 'vbscript'].includes(scheme);
    return `<tr><td>${ctx.esc(r.name)}</td><td>${p ? `<a href="${viewHref(ctx, from, p.slug)}">${ctx.esc(p.title)}</a>` : r.project === null ? 'All projects' : `${ctx.esc(r.project)} (unknown)`}</td><td>${r.live ? 'live' : 'stale'}</td><td>${ageLabel(ctx.age(ctx.date(r.beat)))}</td><td>${r.openItems}</td><td>${r.generation}</td><td>${r.link === null ? ctx.unavailable : safe ? ctx.link(r.link, url.href) : ctx.esc(r.link)}</td></tr>`;
  }).join('')}</tbody></table>`;
}

function pane(ctx) {
  return (p, from) => {
    const a = attention(p, ctx), r = recent(p, ctx, from, 6);
    return `<div class="ph">${icon(p)}<div><h1>${ctx.esc(p.title)}</h1><p class="sub">${ctx.esc(p.slug)} · ${ctx.optionalLink('Full STATE', p.state, from)} · ${ctx.link('Project page', ctx.hrefTo(from, p.page))}</p></div></div>
${p.lead ? `<p class="lead">${ctx.markdown(p.lead, p.source, from, { inline: true })}</p>` : ''}
${strip(p, ctx, r.list)}${sessions(ctx, from, p.slug)}
${a.reasons.length ? `<div class="look"><b>Needs a look</b><ul>${a.reasons.map(x => `<li>${ctx.esc(x.text)}</li>`).join('')}</ul></div>` : ''}
<div class="cols"><div><h2 class="sh">Next steps</h2>${steps(p, ctx, from)}
<details class="sec"><summary><b>Open questions (${p.questions.length})</b><span>${p.questions.length ? 'Unresolved items from STATE' : 'None recorded'}</span></summary>${questions(p, ctx, from)}</details></div>
<div><h2 class="sh">Recent activity <span>${r.list.length} note${r.list.length === 1 ? '' : 's'}</span></h2>${r.html || '<p class="muted">No dated notes.</p>'}</div></div>
<h2 class="sh">State ${foldButtons}</h2>
${stateSections(p).map(k => `<details class="sec fold"><summary><b>${ctx.esc(title(k))}</b><span>${preview(p.narrative[k], p, ctx, from)}</span></summary><div class="prose">${ctx.markdown(p.narrative[k], p.state, from)}</div></details>`).join('')}
<details class="sec"><summary><b>Properties and sources</b><span>Repositories, links, and authoritative documents</span></summary>${ctx.properties(p, from)}${ctx.repositories(p, from)}${ctx.documents(p, from)}${ctx.sources(p, from)}</details>`;
  };
}

function home(ctx) {
  return from => {
    const rows = ranked(ctx);
    return `<h1>Overview</h1><p class="muted">Projects ranked by what needs a look. Select one on the left or here.</p>
<table class="rank"><thead><tr><th>Project</th><th>Needs a look</th><th>Next open step</th><th>Last activity</th></tr></thead><tbody>${rows.map(({ p, a }) => {
      return `<tr><td style="width:170px"><a href="${viewHref(ctx, from, p.slug)}">${ctx.esc(p.title)}</a></td><td class="r" style="width:210px">${a.reasons.slice(0, 2).map(x => ctx.esc(x.text)).join('<br>') || 'Nothing'}</td><td>${nextStep(p, ctx, from) || '<span class="muted">None</span>'}</td><td class="r" style="white-space:nowrap">${ageLabel(a.stats.activityAge)}</td></tr>`;
    }).join('')}</tbody></table>${rows.length ? '' : '<p class="muted">No projects registered.</p>'}${sessions(ctx, from)}`;
  };
}


export const workspaceCss = refinedCss + `
  [hidden] { display: none !important; }
  .icon { background: hsl(var(--h, 235) 70% 95%); color: hsl(var(--h, 235) 55% 42%); }
  .ws-pane { overflow-wrap: anywhere; }
  .ws-pane .doc { max-width: 100%; }
  .ws-pane section, .ph > div, li.task > div { min-width: 0; }
  .ws-pane .prose { overflow-x: auto; }
  .kbd { padding: 0 4px; border: 1px solid var(--line); border-radius: 4px; }
  @media (max-width: 600px) {
    table.rank { table-layout: fixed; font-size: 12px; }
    table.rank td, table.rank th { padding: 8px 4px; width: auto !important; white-space: normal !important; }
  }
`;
export const workspaceScript = wsScript + wsFold;
