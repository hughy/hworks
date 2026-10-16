// Annotation layer the recorder adds as an init script, so it loads with every page. recorder.cjs drives it through window.ann.
// window.__annClock = { base, cells, cellW, height } must be set first; the strip encodes draw time per frame.
(() => {
  if (window.top !== window) return;
  if (!document.body) return document.addEventListener("DOMContentLoaded", () => setup(), { once: true });
  setup();
})();

function setup() {
  if (window.ann) return;
  const css = `
  #ann-layer{--accent:#2457d6;--good:#05a660;--bad:#e5263d;--alt:#8a1022;--ink:#0a0b0d;
    position:fixed;inset:0;pointer-events:none;z-index:2147483000;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Helvetica Neue",sans-serif}
  #ann-layer *{box-sizing:border-box}
  .ann-caption{position:fixed;left:50%;bottom:14px;transform:translateX(-50%);max-width:min(1000px,90vw);background:rgba(10,11,13,.86);color:#fff;
    font-size:19px;line-height:1.3;font-weight:500;padding:10px 20px;border-radius:14px;text-align:center;transition:opacity .25s}
  .ann-caption.alt{background:var(--alt);font-weight:600}
  .ann-caption .label{display:block;font-size:11px;letter-spacing:.18em;font-weight:800;opacity:.75;margin-bottom:2px}
  .ann-card{position:fixed;left:50%;top:14px;transform:translate(-50%,-140%);background:var(--accent);color:#fff;padding:10px 22px 12px;border-radius:16px;
    display:flex;align-items:center;gap:14px;transition:transform .45s cubic-bezier(.2,1.4,.4,1)}
  .ann-card.in{transform:translate(-50%,0)}
  .ann-card .emo{font-size:38px;line-height:1}
  .ann-card .kick{font-size:12px;letter-spacing:.14em;font-weight:700;opacity:.85}
  .ann-card .title{font-size:24px;font-weight:700}
  .ann-ring{position:fixed;color:var(--accent);border:3px solid currentColor;border-radius:12px;animation:ann-pulse 1.1s ease-in-out infinite}
  .ann-ring.good{color:var(--good)}.ann-ring.bad{color:var(--bad)}
  @keyframes ann-pulse{0%,100%{outline:0 solid transparent}50%{outline:6px solid color-mix(in srgb,currentColor 18%,transparent)}}
  .ann-bubble{position:fixed;background:#fff;color:var(--ink);border:3px solid var(--ink);border-radius:16px;padding:10px 16px;font-size:18px;line-height:1.35;
    max-width:470px;transform:scale(.3);opacity:0;transition:transform .35s cubic-bezier(.2,1.5,.4,1),opacity .2s}
  .ann-bubble.in{transform:scale(1);opacity:1}
  .ann-bubble.good{border-color:var(--good)}.ann-bubble.bad{border-color:var(--bad)}.ann-bubble.accent{border-color:var(--accent)}
  .ann-bubble b{font-weight:800}.ann-bubble code{font-family:ui-monospace,Menlo,monospace;font-size:15px;font-weight:700;background:#f1f3f5;padding:1px 5px;border-radius:5px}
  .ann-arrow{position:fixed;inset:0;width:100vw;height:100vh;overflow:visible}
  .ann-arrow .shaft{stroke-dasharray:600;stroke-dashoffset:600;animation:ann-draw .45s ease-out forwards}
  @keyframes ann-draw{to{stroke-dashoffset:0}}
  .ann-stamp{position:fixed;font-weight:900;font-size:20px;letter-spacing:.04em;padding:3px 11px;border:3px solid currentColor;border-radius:10px;color:var(--good);
    background:rgba(255,255,255,.94);transform:translate(-50%,-50%) rotate(-9deg) scale(3);opacity:0;transition:transform .3s cubic-bezier(.3,1.6,.5,1),opacity .15s;white-space:nowrap}
  .ann-stamp.in{transform:translate(-50%,-50%) rotate(-9deg) scale(1);opacity:1}
  .ann-stamp.bad{color:var(--bad)}.ann-stamp.accent{color:var(--accent)}
  .ann-emo{position:fixed;font-size:34px;animation:ann-float 1.6s ease-out forwards}
  @keyframes ann-float{0%{transform:translate(0,0) scale(.4);opacity:0}15%{opacity:1;transform:translate(0,-10px) scale(1.1)}100%{transform:translate(var(--dx),-120px) scale(1);opacity:0}}
  .ann-cursor{position:fixed;width:26px;height:26px;left:0;top:0;opacity:0;transition:transform .6s cubic-bezier(.5,0,.2,1);z-index:2}
  .ann-cursor.on{opacity:1}
  .ann-cursor.click::after{content:"";position:absolute;left:-14px;top:-14px;width:28px;height:28px;border-radius:50%;border:3px solid var(--accent);animation:ann-click .4s ease-out}
  @keyframes ann-click{from{transform:scale(.3);opacity:1}to{transform:scale(1.6);opacity:0}}
  `;
  const style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);
  const layer = document.createElement("div");
  layer.id = "ann-layer";
  for (const [k, v] of Object.entries(window.__annTheme || {})) layer.style.setProperty(`--${k}`, v);
  document.body.appendChild(layer);

  const cursor = document.createElement("div");
  cursor.className = "ann-cursor";
  cursor.innerHTML = `<svg width="26" height="26" viewBox="0 0 26 26"><path d="M3 2 L3 21 L8 16.5 L11.5 24 L15 22.5 L11.5 15 L18 15 Z" fill="#0a0b0d" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>`;
  layer.appendChild(cursor);

  // Clock strip: a white and a black sentinel cell, then (cells - 2) bits of (Date.now() - base) / 10, redrawn every animation frame.
  const clk = window.__annClock;
  const strip = document.createElement("div");
  strip.style.cssText = `position:fixed;left:0;bottom:0;width:100vw;height:${clk.height}px;display:flex;z-index:3;background:#fff`;
  const cells = [];
  for (let i = 0; i < clk.cells; i++) {
    const c = document.createElement("div");
    c.style.cssText = `width:${clk.cellW}px;height:${clk.height}px`;
    strip.appendChild(c);
    cells.push(c);
  }
  layer.appendChild(strip);
  const bits = clk.cells - 2;
  const tick = () => {
    const v = Math.floor((Date.now() - clk.base) / 10);
    cells[0].style.background = "#fff";
    cells[1].style.background = "#000";
    for (let i = 0; i < bits; i++) cells[i + 2].style.background = Math.floor(v / 2 ** (bits - 1 - i)) % 2 ? "#000" : "#fff";
    requestAnimationFrame(tick);
  };
  tick();

  let cx = innerWidth - 140, cy = innerHeight - 80;
  cursor.style.transform = `translate(${cx}px,${cy}px)`;

  const rect = (sel) => {
    const el = typeof sel === "string" ? document.querySelector(sel) : sel;
    if (!el) throw new Error(`ann: no element for ${sel}`);
    return el.getBoundingClientRect();
  };
  const add = (cls, html = "") => {
    const el = document.createElement("div");
    el.className = cls;
    el.innerHTML = html;
    el.dataset.ann = "1";
    layer.appendChild(el);
    return el;
  };
  const pop = (el) => requestAnimationFrame(() => requestAnimationFrame(() => el.classList.add("in")));
  const color = (tone) => getComputedStyle(layer).getPropertyValue(`--${tone === "good" || tone === "bad" ? tone : tone === "accent" ? "accent" : "ink"}`);
  let caption, card;

  window.ann = {
    caption(text, { label = "", alt = false } = {}) {
      if (!caption) caption = add("ann-caption");
      caption.classList.toggle("alt", alt);
      caption.style.opacity = text ? "1" : "0";
      if (!text) return;
      caption.textContent = text;
      if (label) {
        const l = document.createElement("span");
        l.className = "label";
        l.textContent = label;
        caption.prepend(l);
      }
    },
    card(kick, title, emo = "") {
      if (card) card.remove();
      card = add("ann-card", `<span class="emo">${emo}</span><span><div class="kick">${kick}</div><div class="title">${title}</div></span>`);
      pop(card);
    },
    ring(sel, tone = "", pad = 6) {
      const r = rect(sel);
      const el = add(`ann-ring ${tone}`);
      Object.assign(el.style, { left: `${r.left - pad}px`, top: `${r.top - pad}px`, width: `${r.width + 2 * pad}px`, height: `${r.height + 2 * pad}px` });
    },
    // Bubble with its top-left at (x, y), plus a curved arrow from its nearest edge to the target. Pick (x, y) in free space.
    bubble(sel, html, { x, y, tone = "", arrow = true } = {}) {
      const r = rect(sel);
      const el = add(`ann-bubble ${tone}`, html);
      el.style.left = `${x}px`;
      el.style.top = `${y}px`;
      pop(el);
      if (!arrow) return;
      const b = { left: x, top: y, width: el.offsetWidth, height: el.offsetHeight };
      const tx = Math.max(r.left, Math.min(b.left + b.width / 2, r.right));
      const ty = Math.max(r.top, Math.min(b.top + b.height / 2, r.bottom));
      const sx = Math.max(b.left, Math.min(tx, b.left + b.width));
      const sy = Math.max(b.top, Math.min(ty, b.top + b.height));
      const ex = tx + Math.sign(sx - tx) * 8;
      const ey = ty + Math.sign(sy - ty) * 8;
      const mx = (sx + ex) / 2 + (ey - sy) * 0.25;
      const my = (sy + ey) / 2 - (ex - sx) * 0.25;
      const c = color(tone);
      const id = `ah${Math.random().toString(36).slice(2)}`;
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("class", "ann-arrow");
      svg.dataset.ann = "1";
      svg.innerHTML = `<defs><marker id="${id}" viewBox="0 0 10 10" markerWidth="4" markerHeight="4" refX="6" refY="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="${c}"/></marker></defs>
        <path class="shaft" d="M${sx},${sy} Q${mx},${my} ${ex},${ey}" fill="none" stroke="${c}" stroke-width="3.5" stroke-linecap="round" marker-end="url(#${id})"/>`;
      layer.insertBefore(svg, el);
    },
    stamp(sel, text, tone = "good", { dx = 0, dy = 0 } = {}) {
      const r = rect(sel);
      const el = add(`ann-stamp ${tone}`, text);
      el.style.left = `${r.left + r.width / 2 + dx}px`;
      el.style.top = `${r.top + r.height / 2 + dy}px`;
      pop(el);
    },
    burst(sel, emos) {
      const r = rect(sel);
      emos.forEach((e, i) =>
        setTimeout(() => {
          const el = add("ann-emo", e);
          el.style.left = `${r.left + r.width / 2 - 17 + (i - emos.length / 2) * 22}px`;
          el.style.top = `${r.top}px`;
          el.style.setProperty("--dx", `${(i - (emos.length - 1) / 2) * 30}px`);
          setTimeout(() => el.remove(), 1700);
        }, i * 90),
      );
    },
    // The cursor stays hidden until the first moveTo, so scenes that never click show no pointer.
    moveTo(sel) {
      const r = rect(sel);
      cursor.classList.add("on");
      cx = r.left + r.width / 2 - 4;
      cy = r.top + r.height / 2 - 2;
      cursor.style.transform = `translate(${cx}px,${cy}px)`;
    },
    click() {
      cursor.classList.remove("click");
      void cursor.offsetWidth;
      cursor.classList.add("click");
    },
    // Removes rings, bubbles, arrows, and stamps; keeps the caption and card.
    clear() {
      layer.querySelectorAll("[data-ann]").forEach((el) => el !== caption && el !== card && el.remove());
    },
    clearAll() {
      this.clear();
      card?.remove();
      card = undefined;
      this.caption("");
    },
  };
}
