// Browser helpers for prototype pages. Inline this file in a <script> at the end of <body>; each part does
// nothing when its markup is absent. Values are matched as space-separated tokens, so keep them free of spaces.
//
// Filter: an <input data-filter> filters elements with data-search="<text>" by substring. Buttons with
// data-facet="key=value" toggle a facet that keeps elements whose data-<key> lists the value; pressed buttons
// get aria-pressed="true". Elements with data-count show the visible count; a data-group container hides
// when none of its data-search elements is visible. Press / to focus the box.
// Keyboard: j and k move a .cursor through rendered [data-nav] rows, skipping hidden groups and tab panels; Enter opens
// the selected row's first link while it is visible. Keys typed in form fields and with modifiers are left alone.
// Tabs: links in .tabs show the .panel whose id matches their hash (the panel gets .on); the URL hash keeps it.
(() => {
  const box = document.querySelector('[data-filter]');
  const items = [...document.querySelectorAll('[data-search]')];
  const facets = {};
  const apply = () => {
    const q = (box?.value ?? '').toLowerCase().trim();
    let shown = 0;
    for (const el of items) {
      const ok = (!q || el.dataset.search.toLowerCase().includes(q)) &&
        Object.entries(facets).every(([k, v]) => !v || (el.getAttribute(`data-${k}`) ?? '').split(' ').includes(v));
      el.hidden = !ok; if (ok) shown++;
    }
    document.querySelectorAll('[data-count]').forEach(el => { el.textContent = shown; });
    document.querySelectorAll('[data-group]').forEach(g => { g.hidden = !g.querySelector('[data-search]:not([hidden])'); });
  };
  box?.addEventListener('input', apply);
  document.querySelectorAll('[data-facet]').forEach(btn => btn.addEventListener('click', () => {
    const [k, v] = btn.dataset.facet.split('=');
    facets[k] = facets[k] === v ? '' : v;
    document.querySelectorAll(`[data-facet^="${k}="]`).forEach(b => b.setAttribute('aria-pressed', String(b.dataset.facet === `${k}=${facets[k]}`)));
    apply();
  }));
  const typing = e => e.ctrlKey || e.metaKey || e.altKey || e.target.closest?.('input, textarea, select, [contenteditable]:not([contenteditable="false"])');
  addEventListener('keydown', e => { if (e.key === '/' && box && !typing(e)) { e.preventDefault(); box.focus(); } });
  apply();
})();

(() => {
  const rows = () => [...document.querySelectorAll('[data-nav]')].filter(r => r.getClientRects().length);
  let cur = null;
  const move = next => {
    cur = next ?? cur;
    document.querySelectorAll('[data-nav]').forEach(r => r.classList.toggle('cursor', r === cur));
    cur?.scrollIntoView({ block: 'nearest' });
  };
  addEventListener('keydown', e => {
    if (e.target.closest?.('input, textarea, select, [contenteditable]:not([contenteditable="false"])')) { if (e.key === 'Escape') e.target.blur(); return; }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const list = rows(), i = list.indexOf(cur);
    if (e.key === 'j') move(list[Math.min(list.length - 1, i + 1)]);
    if (e.key === 'k') move(list[Math.max(0, i - 1)]);
    if (e.key === 'Enter' && i >= 0) cur.querySelector('a')?.click();
  });
})();

(() => {
  const show = id => {
    const tabs = [...document.querySelectorAll('.tabs a')];
    if (!tabs.some(t => t.hash === '#' + id)) id = tabs[0]?.hash.slice(1);
    tabs.forEach(t => t.setAttribute('aria-selected', String(t.hash === '#' + id)));
    document.querySelectorAll('.panel').forEach(p => p.classList.toggle('on', p.id === id));
  };
  addEventListener('hashchange', () => show(location.hash.slice(1)));
  show(location.hash.slice(1));
})();
