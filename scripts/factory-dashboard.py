#!/usr/bin/env python3
"""Render factory-metrics JSON as self-contained ASCII HTML with CSS-only details.

Usage: factory-dashboard.py METRICS.json [--tiles FILE]... [--prose FILE] [-o OUT.html]
Default prose: factory-dashboard-prose.json beside this script. Default output: stdout.
Extension JSON schema:
 {"series": {"name": {"YYYY-MM-DD": number|[number,...]|null}},
  "tiles": [{"key": "id", "band": "Cost", "title": "Label", "home": "owner",
    "about": "Definition", "kind": "bars|stacked bars|lines|table|empty",
    "series": ["name", ...], "names": ["stack label", ...],
    "kpi": {"series": "name", "how": "sum|last|mean", "format": "$|%|h|",
            "better": "up|down|none"},
    "key_metric": "optional target text",
    "score_row": {"category": "Cost", "title": "Row", "series": "name",
                  "how": "sum|last|mean", "format": "$|%|h|", "better": "up|down|none"},
    "rows": [["column", "column"], ["value", 1]]}]}
Band must be an existing band. Series align to metrics dates; missing dates are null.
Optional table rows include their header; otherwise dates and series become columns.
Strings are escaped; markup is never accepted.
All-null series render dim empty tiles. An extension with a generic key replaces
that tile, e.g. cloud. Score rows append to their category. No private sources.
"""
import argparse
import json
import statistics as st
import html
import math
from pathlib import Path
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

ACC, INK, GREY, LIGHT, PAPER = "#b3261e", "#222", "#8a8a8a", "#cfcfcf", "#fffff8"
esc = lambda s: html.escape(str(s))


def roll(vals, k=7, fn=lambda xs: sum(xs) / len(xs)):
    out = []
    for i in range(len(vals)):
        w = [v for v in vals[max(0, i - k + 1): i + 1] if v is not None]
        out.append(fn(w) if w else None)
    return out


rsum = lambda v: roll(v, 7, sum)


def ratio(a, b, minb=1e-9):
    return [x / y if (x is not None and y and y >= minb) else None for x, y in zip(a, b)]


def fmt(v, kind=""):
    if v is None:
        return "-"
    if kind == "$":
        return "$0" if v == 0 else (f"${v:,.0f}" if abs(v) >= 100 else f"${v:,.2f}")
    if kind == "%":
        return f"{v:.0%}"
    if kind == "h":
        return f"{v:.0f} h" if v == 0 or v >= 20 else f"{v:.1f} h"
    if isinstance(v, float):
        return f"{v:,.1f}" if abs(v) < 100 else f"{v:,.0f}"
    return f"{v:,}"


def daylabel(d):
    return date.fromisoformat(d).strftime("%b %-d")


# ---------- sparkline ----------
def spark(vals, w=120, h=20, kind="", bars=False, sample_dates=None):
    sample_dates = sample_dates or dates
    pts = [(i, v) for i, v in enumerate(vals) if v is not None]
    if not pts:
        return ""
    lo = min(0, min(v for _, v in pts))
    hi = max(v for _, v in pts) or 1
    x = lambda i: 2 + i * (w - 6) / max(1, len(vals) - 1)
    y = lambda v: h - 2 - (v - lo) * (h - 5) / (hi - lo or 1)
    s = [f'<svg class="spark" width="{w}" height="{h}" viewBox="0 0 {w} {h}">']
    if bars:
        bw = max(1.2, (w - 6) / len(vals) * 0.6)
        for i, v in pts:
            s.append(f'<rect x="{x(i)-bw/2:.1f}" y="{y(v):.1f}" width="{bw:.1f}" height="{h-2-y(v):.1f}" fill="{GREY}"><title>{daylabel(sample_dates[i])}: {fmt(v, kind)}</title></rect>')
    else:
        d = " ".join(f"{'M' if j == 0 else 'L'}{x(i):.1f},{y(v):.1f}" for j, (i, v) in enumerate(pts))
        s.append(f'<path d="{d}" fill="none" stroke="{GREY}" stroke-width="1"/>')
    imax = max(pts, key=lambda p: p[1])
    s.append(f'<circle cx="{x(imax[0]):.1f}" cy="{y(imax[1]):.1f}" r="1.6" fill="{INK}"><title>max {daylabel(sample_dates[imax[0]])}: {fmt(imax[1], kind)}</title></circle>')
    li, lv = pts[-1]
    s.append(f'<circle cx="{x(li):.1f}" cy="{y(lv):.1f}" r="2" fill="{ACC}"><title>{daylabel(sample_dates[li])}: {fmt(lv, kind)}</title></circle>')
    s.append("</svg>")
    return "".join(s)


# ---------- daily chart with range frame ----------
def chart(series, w=360, h=120, ymax=None, kind="", notes=(), R=58, yfmt=None, xt="weeks"):
    """series: dict(vals, style: bar|stack|line|dash|dots, label, color, colors, names)."""
    L, T, B = 34, 10, 18
    iw, ih = w - L - R, h - T - B
    allv = []
    for s in series:
        for v in s["vals"]:
            if v is None:
                continue
            if s.get("style") == "stack":
                allv.append(sum(v))
            elif isinstance(v, list):
                allv.extend(v)
            else:
                allv.append(v)
    hi = ymax or (max(allv) if allv else 1) or 1
    x = lambda i: L + i * iw / max(1, N - 1)
    y = lambda v: T + ih - min(v, hi) * ih / hi
    yf = yfmt or (lambda v: fmt(v, kind))
    out = [f'<svg class="chart" viewBox="0 0 {w} {h}" preserveAspectRatio="xMinYMin meet">']
    lo_v, hi_v = (min(allv) if allv else 0), min(max(allv) if allv else 0, hi)
    out.append(f'<line x1="{L-5}" x2="{L-5}" y1="{y(hi_v):.1f}" y2="{y(max(0, lo_v)):.1f}" stroke="{INK}" stroke-width="0.6"/>')
    lo_v = 0
    tv = sorted({0, hi_v})
    if len(tv) == 2 and y(tv[0]) - y(tv[1]) < 10:
        tv = [tv[1]]
    for v in tv:
        out.append(f'<text x="{L-8}" y="{y(v)+3:.1f}" class="tick" text-anchor="end">{esc(yf(v))}</text>')
    lastx = -99
    for i, d in enumerate(dates):
        dd = date.fromisoformat(d)
        want = (i in (0, N - 1)) if xt == "ends" else (dd.weekday() == 0 or i == N - 1)
        if want and x(i) - lastx > 30:
            lastx = x(i)
            out.append(f'<line x1="{x(i):.1f}" x2="{x(i):.1f}" y1="{T+ih+2}" y2="{T+ih+4}" stroke="{INK}" stroke-width="0.6"/>')
            out.append(f'<text x="{x(i):.1f}" y="{T+ih+13}" class="tick" text-anchor="middle">{dd.strftime("%b %-d")}</text>')
    bw = max(1.5, iw / N * 0.6)
    for s in series:
        col, vals, sty = s.get("color", GREY), s["vals"], s.get("style", "line")
        if sty == "bar":
            for i, v in enumerate(vals):
                if v:
                    out.append(f'<rect x="{x(i)-bw/2:.1f}" y="{y(v):.1f}" width="{bw:.1f}" height="{T+ih-y(v):.1f}" fill="{col}"><title>{daylabel(dates[i])}: {fmt(v, kind)}</title></rect>')
        elif sty == "stack":
            for i, v in enumerate(vals):
                base = 0
                tip = ", ".join(f"{n} {fmt(p, kind)}" for n, p in zip(s["names"], v) if p)
                for p, c in zip(v, s["colors"]):
                    if p:
                        out.append(f'<rect x="{x(i)-bw/2:.1f}" y="{y(base+p):.1f}" width="{bw:.1f}" height="{y(base)-y(base+p):.1f}" fill="{c}"><title>{daylabel(dates[i])}: {esc(tip)}</title></rect>')
                        base += p
        elif sty == "dots":
            for i, v in enumerate(vals):
                for p in (v or []):
                    out.append(f'<circle cx="{x(i):.1f}" cy="{y(p):.1f}" r="1.3" fill="{col}" fill-opacity="0.5"><title>{daylabel(dates[i])}: {fmt(p, kind)}</title></circle>')
        else:
            pts = [(i, v) for i, v in enumerate(vals) if v is not None]
            if pts:
                d = " ".join(f"{'M' if j == 0 else 'L'}{x(i):.1f},{y(v):.1f}" for j, (i, v) in enumerate(pts))
                dash = ' stroke-dasharray="3,2"' if sty == "dash" else ""
                out.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="{s.get("width", 1.3)}"{dash}/>')
                for i, v in pts:
                    out.append(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="3" fill="transparent"><title>{daylabel(dates[i])}: {fmt(v, kind)}</title></circle>')
        if s.get("label"):
            pts = [(i, v) for i, v in enumerate(vals) if v is not None and not isinstance(v, list)]
            if pts:
                i, v = pts[-1]
                out.append(f'<text x="{x(i)+4:.1f}" y="{y(v)+3+s.get("dy", 0):.1f}" class="lab" fill="{col}">{esc(s["label"])}</text>')
    for (d, v, txt) in notes:
        i = dates.index(d)
        out.append(f'<line x1="{x(i):.1f}" x2="{x(i):.1f}" y1="{y(v):.1f}" y2="{T-2}" stroke="{ACC}" stroke-width="0.6"/>')
        anchor, dx = ("end", -3) if x(i) > L + iw * 0.5 else ("start", 3)
        out.append(f'<text x="{x(i)+dx:.1f}" y="{T+4}" class="ann" fill="{ACC}" text-anchor="{anchor}">{esc(txt)}</text>')
    out.append("</svg>")
    return "".join(out)


# ---------- horizontal bars (window totals) ----------
def hbars(items, kind="", w=360, lw=130, unit=""):
    """items: (label, [(value, color, name)...])"""
    rows = [(lab, parts if isinstance(parts, list) else [(parts, GREY, "")]) for lab, parts in items]
    mx = max((sum(p[0] for p in parts) for _, parts in rows), default=1) or 1
    bh, gap = 11, 6
    h = len(rows) * (bh + gap) + 4
    iw = w - lw - 60
    out = [f'<svg class="chart" viewBox="0 0 {w} {h}" preserveAspectRatio="xMinYMin meet">']
    for k, (lab, parts) in enumerate(rows):
        yy = 2 + k * (bh + gap)
        out.append(f'<text x="{lw-6}" y="{yy+bh-2}" class="tick r" text-anchor="end">{esc(lab)}</text>')
        x0 = lw
        for v, c, nm in parts:
            ww = v * iw / mx
            if ww > 0:
                out.append(f'<rect x="{x0:.1f}" y="{yy}" width="{ww:.1f}" height="{bh}" fill="{c}"><title>{esc(lab)}{": " + esc(nm) if nm else ""} {fmt(v, kind)}{unit}</title></rect>')
            x0 += ww
        out.append(f'<text x="{x0+4:.1f}" y="{yy+bh-2}" class="tick">{fmt(sum(p[0] for p in parts), kind)}{unit}</text>')
    out.append("</svg>")
    return "".join(out)


def hrange(items, w=360, lw=150, kind="$"):
    """items: (label, median, p90, n). Dot at median, line to p90."""
    mx = max((i[2] for i in items), default=1) or 1
    bh = 15
    h = len(items) * bh + 20
    iw = w - lw - 40
    x = lambda v: lw + v * iw / mx
    out = [f'<svg class="chart" viewBox="0 0 {w} {h}" preserveAspectRatio="xMinYMin meet">']
    for k, (lab, md, p9, n) in enumerate(items):
        yy = 8 + k * bh
        out.append(f'<text x="{lw-6}" y="{yy+3}" class="tick r" text-anchor="end">{esc(lab)} ({n})</text>')
        out.append(f'<line x1="{x(md):.1f}" x2="{x(p9):.1f}" y1="{yy}" y2="{yy}" stroke="{LIGHT}" stroke-width="1.5"/>')
        out.append(f'<circle cx="{x(md):.1f}" cy="{yy}" r="3" fill="{INK}"><title>{esc(lab)}: median {fmt(md, kind)}, p90 {fmt(p9, kind)}, {n} PRs</title></circle>')
        out.append(f'<text x="{x(p9)+5:.1f}" y="{yy+3}" class="tick">{fmt(md, kind)}</text>')
    yb = 8 + len(items) * bh
    out.append(f'<line x1="{lw}" x2="{x(mx):.1f}" y1="{yb-4}" y2="{yb-4}" stroke="{INK}" stroke-width="0.6"/>')
    out.append(f'<text x="{lw}" y="{yb+7}" class="tick">$0</text><text x="{x(mx):.1f}" y="{yb+7}" class="tick" text-anchor="end">{fmt(mx, kind)}</text>')
    out.append("</svg>")
    return "".join(out)


# ---------- tiles ----------
def tag(home):
    return "".join(f'<span class="tag t-{esc(h.replace("+", "").strip())}">{esc(h.strip())}</span>' for h in home.split("+"))


def tip(text):
    return f'<span class="i" tabindex="0">i<span class="tip">{esc(text)}</span></span>'


def last7(v):
    return [a for a in v[-7:] if a is not None]


def prior7(v):
    return [a for a in v[-14:-7] if a is not None]


def summ(v, how):
    xs, ps = last7(v), prior7(v)
    if how == "sum":
        return (sum(ps) if ps else None), (sum(xs) if xs else None)
    if how == "last":
        return (ps[-1] if ps else None), (xs[-1] if xs else None)
    return (sum(ps) / len(ps) if ps else None), (sum(xs) / len(xs) if xs else None)


def change(b, a, better):
    if a is None or not b:
        return ""
    r = a / b - 1
    cls = "" if abs(r) < 0.1 or better == "none" else ("good" if (r > 0) == (better == "up") else "bad")
    return f'<span class="chg {cls}">{r:+.0%}</span>'


def kpi(v, how, kind="", better="none"):
    b, a = summ(v, how)
    return (f'<div class="kpi"><span class="pv">prior 7d {fmt(b, kind)}</span>'
            f'<span class="lv">{fmt(a, kind)}</span>{change(b, a, better)}</div>')


KEY = {}


def tile(title, body, tipkey, home, k="", cls=""):
    key = KEY.get(title)
    badge = f'<span class="keyb">key metric: {esc(key)}</span>' if key else ""
    return (f'<div class="tile {cls}{" key" if key else ""}"><div class="th"><span class="tt">{esc(title)}</span>{tag(home)}</div>{badge}'
            f'{k}<div class="body">{body}</div><details class="about"><summary aria-label="How it is measured" title="How it is measured"></summary><p>{esc(P[tipkey])}</p></details></div>')


def empty(title, tipkey, home):
    return tile(title, '<div class="none">no collector yet</div>', tipkey, home, cls="dim")


def band(name, tiles):
    return f'<section><h2>{esc(name)}</h2><div class="grid">{"".join(tiles)}</div></section>'


CSS = f"""
*{{box-sizing:border-box}}
body{{margin:0;background:{PAPER};color:{INK};font:13px/1.4 "Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;font-variant-numeric:tabular-nums}}
header{{display:flex;align-items:baseline;gap:16px;padding:14px 22px 6px;border-bottom:1px solid #e4e0d4}}
header h1{{font-weight:400;font-size:22px;margin:0}}
header .sub{{color:#666;font-size:12px;flex:1}}
main{{padding:4px 22px 30px;max-width:1600px}}
section h2{{font-weight:400;font-style:italic;font-size:15px;margin:18px 0 8px;color:#444}}
.grid{{display:grid;align-items:start;grid-auto-flow:row dense;grid-template-columns:repeat(auto-fill,minmax(440px,1fr));gap:12px}}
.tile{{background:#fff;border:1px solid #e8e4d8;padding:9px 11px 8px;min-width:0}}
.tile.w2{{grid-column:span 2}} .tile.full{{grid-column:1/-1}} .tile.key{{border-top:2px solid {ACC}}}
.keyb{{font:10.5px -apple-system,system-ui,sans-serif;color:{ACC};letter-spacing:.02em}}
details.about{{margin-top:4px}} details.about summary{{font-size:12px;color:#aaa;cursor:pointer;width:14px}} details.about summary:hover{{color:#555}} details.about p{{margin:4px 0 0;font-size:12px;color:#444;max-width:620px}}
.tbl td{{white-space:nowrap}} .sc tr.grp td{{font-style:italic;color:#888;padding-top:8px;border-bottom:none}} .sc tr.krow td{{font-weight:600}} .sc tr.krow td:first-child{{border-left:2px solid {ACC};padding-left:6px}} .sc .tg{{color:{ACC};font:10.5px -apple-system,system-ui,sans-serif}}
.tile.dim{{background:transparent;border-style:dashed}}
.th{{display:flex;align-items:center;gap:6px}}
.tt{{flex:1;font-size:13.5px}}
.tag{{font:10px/1 -apple-system,system-ui,sans-serif;letter-spacing:.04em;color:#777;border:1px solid #ddd;padding:2px 4px}}
.i{{position:relative;display:inline-block;width:15px;height:15px;border:1px solid #bbb;border-radius:50%;font:italic 10px/13px Georgia,serif;text-align:center;color:#888;cursor:help}}
.i .tip{{display:none;position:absolute;right:-4px;top:19px;width:300px;background:#fff;border:1px solid #ccc;padding:8px 10px;z-index:9;color:#333;font:normal 12px/1.45 "Iowan Old Style",Georgia,serif;text-align:left}}
.i:hover .tip,.i:focus .tip{{display:block}}
.kpi{{display:flex;align-items:baseline;gap:8px;margin:3px 0 2px}}
.kpi .pv{{color:#888;font-size:11.5px}}
.kpi .lv{{font-size:19px}}
.chg{{font-size:11.5px;color:#888}} .good{{color:#2e6b2e}} .bad{{color:{ACC}}}
.sub,.foot{{color:#777;font-size:11.5px;margin-top:2px}}
svg.chart{{width:100%;height:auto;display:block;margin-top:4px}}
svg text{{font-family:-apple-system,system-ui,sans-serif}}
.tick{{font-size:8.5px;fill:#666}} .lab{{font-size:9px}} .ann{{font-size:8.5px}}
.sms{{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:4px 12px}}
.smt{{font-size:11.5px;color:#555}}
.lg{{display:flex;flex-wrap:wrap;gap:10px;font-size:11px;color:#666;margin-top:2px}}
.lg i{{display:inline-block;width:8px;height:8px;margin-right:4px}}
.none{{color:#999;font-style:italic;padding:22px 0;text-align:center}}
table.tbl{{border-collapse:collapse;width:100%;font-size:12.5px}}
.tbl th{{font-weight:400;color:#888;text-align:right;font-size:11px;padding:2px 6px;border-bottom:1px solid #ddd}}
.tbl th:first-child{{text-align:left}}
.tbl td{{padding:2px 6px;border-bottom:1px solid #f0ede4}}
table.tbl:not(.sc) td{{text-align:right}} table.tbl:not(.sc) td:first-child{{text-align:left}}
.num{{text-align:right}}
table.mx{{border-collapse:collapse;margin:8px 0;font-size:12.5px}}
.mx th{{font-weight:400;color:#666;padding:4px 8px;text-align:left;font-size:11.5px}}
.mx td{{width:90px;text-align:center;font-size:20px;padding:8px}}
.mx td.ok{{background:#f1efe6}} .mx td.no{{color:{ACC}}}
details{{margin:18px 0 0;border-top:1px solid #e4e0d4;padding-top:8px;max-width:980px}}
summary{{cursor:pointer;font-style:italic;color:#444;font-size:14px}}
details li{{margin:3px 0}}
details table td{{padding:4px 8px;border-bottom:1px solid #eee;vertical-align:top}}
@media (max-width:800px){{.tile.w2{{grid-column:span 1}}}}
"""

BANDS = ['Output', 'Cost', 'Human touches and friction', 'Review and quality', 'Churn', 'Factory health and improvement']


def rolling_ratio(a, b, minimum=1):
    return ratio(rsum(a), rsum(b), minimum)


def nullable_sum(xs):
    return sum(xs) if xs and all(x is not None for x in xs) else None


def derive(metrics):
    series = {k: [d.get(k) for d in D] for k in {k for d in D for k in d} - {'date'}}
    col = lambda k: series.get(k, [None] * N)
    series['cpp_all'] = rolling_ratio(col('spend'), col('merged'), 10)
    series['cpp_prod'] = rolling_ratio(col('spend_product'), col('merged'), 10)
    series['ops_pr'] = rolling_ratio(col('ops'), col('merged'), 10)
    for key, num, den in [('cw_share', 'cw', 'spend'), ('long_share', 'longc', 'spend'), ('coverage', 'linked', 'spend'), ('factory_share', 'spend_factory', 'spend'), ('schema', 'fr_inschema', 'fr_rows'), ('cr', 'churn21', 'added')]:
        series[key] = rolling_ratio(col(num), col(den))
    series['escaped'] = [None if d.get('friction') is None else d['friction'].get('operator', 0) + d['friction'].get('ci', 0) for d in D]
    series['fr_all'] = [None if d.get('friction') is None else sum(d['friction'].values()) for d in D]
    for key, src in [('escaped_pr', 'escaped'), ('fr_pr', 'fr_all')]:
        series[key] = rolling_ratio(series[src], col('merged'), 10)
    series['subfail'] = [nullable_sum([d.get('subagent_fail'), d.get('babysitter_fail')]) for d in D]
    series['corr_pr'] = rolling_ratio([nullable_sum([d.get('sig_correction'), d.get('sig_abort')]) for d in D], col('merged'), 10)
    for key, fields in [('landed_stack', ['pr_landed', 'pr_fixed', 'pr_holding']), ('tasks_stack', ['tasks_landed', 'tasks_fixed', 'tasks_nopr', 'tasks_holding']), ('sub_stack', ['subagent_fail', 'babysitter_fail'])]:
        series[key] = [[d[k] for k in fields] if all(d.get(k) is not None for k in fields) else None for d in D]
    series['touch_stack'] = []
    for d in D:
        fields = ['sig_correction', 'sig_abort', 'sig_approval', 'sig_status-check', 'ops']
        series['touch_stack'].append([d['sig_correction'], d['sig_abort'], d['sig_approval'] + d['sig_status-check'], max(0, d['ops'] - sum(d[k] for k in fields[:4]))] if all(d.get(k) is not None for k in fields) else None)
    for key, src, minimum in [('attr7', 'pr_cost', 5), ('htm7', 'htm', 5)]:
        series[key] = []
        for i in range(N):
            xs = [x for d in D[max(0, i-6):i+1] for x in (d.get(src) or []) if x is not None]
            series[key].append(st.median(xs) if len(xs) >= minimum else None)
    series['oq_rev'], series['oq_judged'] = [], []
    for i in range(N):
        window = D[max(0, i-13):i+1]
        r = nullable_sum([d.get('oq_reversed') for d in window])
        k = nullable_sum([d.get('oq_kept') for d in window])
        t = nullable_sum([d.get('oq') for d in window])
        series['oq_rev'].append(r / (r+k) if r is not None and k is not None and r+k >= 3 else None)
        series['oq_judged'].append((r+k) / t if r is not None and k is not None and t and t >= 10 else None)
    for catcher in ('self', 'test', 'reviewer', 'operator', 'ci'):
        series['fr_' + catcher] = [d['friction'].get(catcher, 0) if d.get('friction') is not None else None for d in D]
    return series


def generic_tiles(metrics):
    specs = []
    def add(key, title, bandname, fields=(), kind='lines', how='last', form='', better='none', target='', names=(), wide=False, rows=None):
        specs.append(dict(key=key, title=title, band=bandname, home='hworks', about=P.get(key, ''), kind=kind, series=list(fields),
                          format=form, kpi=dict(series=fields[0], how=how, format=form, better=better) if fields else {},
                          key_metric=target, names=list(names), wide=wide, rows=rows))
    has_tasks = any(d.get('tasks_done') is not None for d in D)
    add('tasks', 'Tasks completed per day', 'Output', ['tasks_stack'], 'stacked bars', 'sum', better='up', target='higher is better' if has_tasks else '', names=['landed', 'PR fixed', 'no PR', 'holding'])
    specs[-1]['kpi']['series'] = 'tasks_done'
    ppt = metrics['tables'].get('prs_per_task', [])
    if ppt:
        specs[-1]['foot'] = f'PRs per task: mean {st.mean(ppt):.2f}, max {max(ppt)}, over {len(ppt)} tasks'
    add('merged', 'PRs merged per day', 'Output', ['merged'], 'bars', 'sum', better='up', target='higher is better' if not has_tasks else '')
    add('opened', 'PRs opened per day', 'Output', ['opened'], 'bars', 'sum', better='up')
    add('landed', 'Landed PRs, by merge day', 'Output', ['landed_stack'], 'stacked bars', names=['landed', 'fixed within 7d', 'in 7d window'])
    specs[-1]['kpi'] = dict(series='pr_fixed', how='sum', better='down')
    add('queue', 'Queue and work in progress', 'Output', ['queue', 'wip', 'open_prs'])
    specs[-1]['kpi'] = dict(series='open_prs', how='last', better='down')
    specs[-1]['foot'] = f'median open-PR age {fmt(D[-1].get("open_age"))} days'
    add('abandoned', 'Closed unmerged', 'Output', ['abandoned'], 'bars', 'sum', better='down')
    abandoned_spend = nullable_sum([d.get('abandoned_spend') for d in D])
    specs[-1]['foot'] = f'Direct cost of these PRs: {fmt(abandoned_spend, "$")} over the period'
    add('cpp', 'Cost per merged PR', 'Cost', ['cpp_all', 'cpp_prod', 'attr7'], kind='cost lines', form='$', better='down', target='lower is better', wide=True)
    add('cw', 'Cache-write share of spend', 'Cost', ['cw_share'], form='%', better='down')
    add('longc', 'Long-context share of spend', 'Cost', ['long_share'], form='%', better='down')
    add('spend', 'Spend per day by where the session ran', 'Cost', ['spend_product', 'spend_factory', 'spend_home', 'spend_auto'], 'small bars', 'sum', '$', wide=True)
    specs[-1]['kpi']['series'] = 'spend'
    add('coverage', 'Spend linked to a PR', 'Cost', ['coverage'], form='%', better='up')
    add('factory', 'Factory share of spend', 'Cost', ['factory_share'], form='%')
    repo = metrics['tables'].get('repo_cost', {})
    add('repo_cost', 'Direct cost per PR, by repo', 'Cost', kind='range', rows=[(k.rsplit('/', 1)[-1], v['median'], v['p90'], v['n']) for k, v in repo.items()])
    report = metrics['tables'].get('token_report', {})
    for key, title, section, label in [('rewrites', 'Cache rewrites by cause', 'cache writes', 'cause'), ('loops', 'Review-loop spend by round', 'loop rounds', 'round')]:
        add(key, title, 'Cost', kind='hbars', rows=[(('round ' if label == 'round' else '') + str(r[label]), r['cost']) for r in report.get(section, [])], form='$')
    add('cloud', 'Cloud agent spend', 'Cost', ['cloud'], 'empty')
    add('revcost', 'Cost per dispatched review', 'Cost', ['revcost'], 'empty')
    add('ops_pr', 'Operator messages per merged PR', 'Human touches and friction', ['ops_pr'], better='down', target='lower is better')
    add('touches', 'Operator touches per day, by type', 'Human touches and friction', ['touch_stack'], 'stacked bars', names=['corrections', 'aborts', 'approvals and status checks', 'other'], wide=True)
    specs[-1]['kpi'] = dict(series='corr_pr', how='last', better='down')
    specs[-1]['overlay'] = 'human_reviews'
    add('fr_pr', 'Friction per merged PR', 'Human touches and friction', ['fr_pr'], better='down')
    add('catcher', 'Friction by who caught it', 'Human touches and friction', ['fr_self', 'fr_test', 'fr_reviewer', 'fr_operator', 'fr_ci'], 'small bars', wide=True)
    specs[-1]['kpi'] = {}
    add('decisions', 'Agent decisions: reversed and judged', 'Human touches and friction', ['oq_rev', 'oq_judged'], form='%', better='down')
    add('htm', 'Hours to merge', 'Human touches and friction', ['htm7'], kind='merge lines', form='h', better='down')
    add('timesplit', 'Main-session time by who held the turn', 'Human touches and friction', kind='hbars', rows=[({'tool': 'tools', 'human': 'operator'}.get(k, k), v/3600) for k, v in metrics['tables'].get('time', {}).items()], form='h')
    add('escaped', 'Escaped defects per merged PR', 'Review and quality', ['escaped_pr'], better='down', target='guardrail, keep low')
    add('funnel', 'Review-loop rounds', 'Review and quality', kind='hbars', rows=[('round ' + str(r['round']), [(r['rounds_with_blocker'], INK, 'blocked'), (r['runs'] - r['rounds_with_blocker'], LIGHT, 'clean')]) for r in report.get('loop rounds', [])])
    models = defaultdict(lambda: [0, 0])
    for r in report.get('roles', []):
        models[r['model']][0] += r.get('first_round_clean', 0)
        models[r['model']][1] += r.get('first_rounds', 0)
    add('firstclean', 'First review clean, by coder model', 'Review and quality', kind='hbars', rows=[(f'{m.rsplit("/", 1)[-1]} ({b})', [(a/b, INK, 'clean')]) for m, (a, b) in models.items() if b >= 10], form='%')
    weeks = defaultdict(lambda: [0, 0])
    tz = ZoneInfo(metrics['tz'])
    for p in metrics['tables'].get('prs', []):
        if p.get('mergedAt'):
            dd = datetime.fromisoformat(p['mergedAt'].replace('Z', '+00:00')).astimezone(tz).date()
            if not metrics['start'] <= dd.isoformat() <= metrics['end']:
                continue
            week = (dd - timedelta(days=dd.weekday())).isoformat()
            weeks[week][0] += 1
            # Outcome definitions remain owned by kaizen-prs via collector table.
            weeks[week][1] += bool(p.get('no_rework'))
    add('rework', 'Merged with no rework, by week', 'Review and quality', kind='hbars', rows=[(f'week of {daylabel(w)} ({a})', [(b/a, INK, 'no rework')]) for w, (a, b) in sorted(weeks.items()) if a >= 5], form='%')
    add('hdispatch', 'Review dispatcher verdicts against outcome', 'Review and quality', kind='empty')
    add('churn_chart', 'Lines rewritten within 21 days, share of added', 'Churn', ['cr'], form='%', better='down', target='guardrail, keep low')
    rows = [['repo', 'lines added', 'churn21', 'moved', 'revisit', 'weekly']]
    for name, r in metrics['tables'].get('churn', {}).items():
        t = r['totals']; rows.append([Path(name).name, fmt(t['added']), f"{t['churn21_ratio']:.1%}" if t['churn21_ratio'] is not None else '-', f"{t['moved_ratio']:.1%}" if t['moved_ratio'] is not None else '-', fmt(t['revisit_share'], '%'), name])
    add('churn_tbl', 'Churn by repo', 'Churn', kind='table', rows=rows if len(rows) > 1 else [], wide=True)
    specs[-1]['weekly'] = []
    for name, result in metrics['tables'].get('churn', {}).items():
        weekly = defaultdict(lambda: [0, 0])
        for row in result.get('daily', []):
            dd = date.fromisoformat(row['date'])
            week = (dd - timedelta(days=dd.weekday())).isoformat()
            weekly[week][0] += row['added']
            weekly[week][1] += row['churn21']
        weeks = [(w, b/a) for w, (a, b) in sorted(weekly.items()) if a >= 200]
        specs[-1]['weekly'].append((name, [v for _, v in weeks], [w for w, _ in weeks]))
    add('failures', 'Subagent failures per day', 'Factory health and improvement', ['sub_stack'], 'stacked bars', 'sum', better='down', target='guardrail, keep low', names=['other roles', 'pr-babysitter'])
    specs[-1]['kpi']['series'] = 'subfail'
    specs[-1]['notes'] = [(d['date'], nullable_sum([d.get('subagent_fail'), d.get('babysitter_fail')]) or 0, f"{daylabel(d['date'])}: {d['runs_never_started']:,} runs never started") for d in D if d.get('runs_never_started')]
    for key, title, field in [('guards', 'Guard blocks per day', 'guard'), ('automations', 'Automation runs per day', 'automations'), ('commits', 'Factory commits per day', 'factory_commits'), ('effective', 'Days to an effective fix', 'effective'), ('schema', 'Friction rows in schema', 'schema')]:
        add(key, title, 'Factory health and improvement', [field], 'bars' if key in ('guards', 'commits') else 'lines', 'sum' if key in ('guards', 'commits') else 'last', '%' if key == 'schema' else '')
    state_colors = {'implemented': INK, 'effective': INK, 'open': ACC, 'awaiting-user': GREY, 'dropped': LIGHT, 'findings': GREY, 'pending': LIGHT, 'unproven': GREY}
    add('kaizen', 'Kaizen and hansei findings per run', 'Factory health and improvement', kind='hbars', rows=[(f"{r['skill']} {daylabel(r['date'])}", [(v, state_colors.get(k, GREY), k) for k, v in r['counts'].items()]) for r in sorted(metrics['tables'].get('findings', []), key=lambda r: (r['skill'] != 'kaizen', r['date']))])
    labels = {'spend': ['product repos', 'factory repos', 'home tabs', 'automations'], 'catcher': ['self', 'test', 'reviewer', 'operator', 'ci'], 'decisions': ['reversed', 'judged'], 'queue': ['tasks not started', 'in progress', 'open PRs']}
    palettes = {'tasks': [INK, ACC, LIGHT, GREY], 'landed': [INK, ACC, LIGHT], 'touches': [ACC, '#e08a7f', GREY, LIGHT], 'failures': [GREY, ACC], 'decisions': [ACC, GREY], 'queue': [GREY, INK, ACC], 'catcher': [GREY, GREY, GREY, ACC, GREY], 'ops_pr': [ACC], 'spend': [GREY], 'guards': [GREY], 'commits': [GREY], 'abandoned': [GREY]}
    for spec in specs:
        spec['labels'] = labels.get(spec['key'], [])
        if spec['key'] in palettes:
            spec['colors'] = palettes[spec['key']]
        if spec['key'] in ('cw', 'longc', 'coverage', 'factory', 'decisions', 'schema'):
            spec['ymax'] = 1
        if spec['key'] in ('funnel', 'loops', 'timesplit'):
            spec['lw'] = 70
        elif spec['key'] in ('rework', 'rewrites'):
            spec['lw'] = 150
        elif spec['key'] == 'firstclean':
            spec['lw'] = 170
        elif spec['key'] == 'kaizen':
            spec['lw'] = 100
            spec['legend'] = [(k, state_colors[k]) for k in state_colors if any(k in r['counts'] for r in metrics['tables'].get('findings', []))]
    findings_tile = next(s for s in specs if s['key'] == 'kaizen')
    specs.remove(findings_tile)
    specs.insert(next(i for i, s in enumerate(specs) if s['key'] == 'effective'), findings_tile)
    return specs


def score_row(title, values, how='last', form='', better='none', target=''):
    b, a = summ(values, how)
    return (f'<tr class="{"krow" if target else ""}"><td>{esc(title)}</td><td>{spark(values, kind=form, bars=how == "sum")}</td>'
            f'<td class="num">{fmt(b, form)}</td><td class="num"><b>{fmt(a, form)}</b></td>'
            f'<td class="num">{change(b, a, better)}</td><td class="tg">{esc(target)}</td></tr>')


def render_tile(spec, series):
    key, title, kind = spec['key'], spec['title'], spec['kind']
    P[key] = spec.get('about', '')
    if spec.get('key_metric'):
        KEY[title] = spec['key_metric']
    fields = spec.get('series', [])
    vals = [series.get(k, [None] * N) for k in fields]
    if kind == 'empty' or (vals and all(v is None for field in vals for v in field)) or (not vals and not spec.get('rows')):
        return empty(title, key, spec['home'])
    conf = spec.get('kpi', {})
    form = spec.get('format', conf.get('format', ''))
    kval = kpi(series.get(conf.get('series'), [None] * N), conf.get('how', 'last'), form, conf.get('better', 'none')) if conf else ''
    prefixes = {'cpp': 'all spend, ', 'landed': 'fixed within 7 days, ', 'queue': 'open PRs, ', 'touches': 'corrections and aborts per merged PR, ', 'decisions': 'reversed, '}
    kval = kval.replace('prior 7d', prefixes.get(key, '') + 'prior 7d')
    if key == 'cpp':
        kval += kpi(series['attr7'], 'last', '$', 'down').replace('prior 7d', 'direct, median, prior 7d')
    colors = spec.get('colors', [INK, ACC, GREY, LIGHT, '#e08a7f'])
    if kind == 'table':
        rows = spec.get('rows') or [['date', *fields], *[[dd, *[fmt(v[i]) for v in vals]] for i, dd in enumerate(dates)]]
        body = '<table class="tbl">' + ''.join('<tr>' + ''.join(f'<{"th" if i == 0 else "td"}>{esc(c)}</{"th" if i == 0 else "td"}>' for c in row) + '</tr>' for i, row in enumerate(rows)) + '</table>'
    elif kind == 'range':
        body = hrange(sorted(spec['rows'], key=lambda row: -row[1]), w=380, lw=165)
    elif kind == 'hbars':
        body = hbars(spec['rows'], form, lw=spec.get('lw', 130))
    elif kind == 'small bars':
        maximum = 300 if key == 'spend' else max((x for field in vals for x in field if x is not None), default=1)
        panels = []
        for i, (label, values) in enumerate(zip(spec.get('labels') or fields, vals)):
            plot = chart([dict(vals=values, style='bar', color=colors[i % len(colors)])], w=180, h=70, R=14, kind=form, xt='ends', ymax=maximum)
            panels.append(f'<div class="sm"><div class="smt">{esc(label)}</div>{plot}</div>')
        body = '<div class="sms">' + ''.join(panels) + '</div>'
    elif kind == 'stacked bars':
        stack = vals[0] if len(vals) == 1 and any(isinstance(v, list) for v in vals[0] if v is not None) else [list(v) if all(x is not None for x in v) else None for v in zip(*vals)]
        count = max((len(v) for v in stack if v is not None), default=len(fields))
        names = spec.get('names') or fields
        names = names if len(names) == count else [str(i+1) for i in range(count)]
        stack = [v if v is not None else [0] * count for v in stack]
        styles = [dict(vals=stack, style='stack', colors=[colors[i % len(colors)] for i in range(count)], names=names)]
        if spec.get('overlay'):
            styles.append(dict(vals=roll(series.get(spec['overlay'], [None] * N)), color=INK, label='PR reviews by others'))
        body = chart(styles, kind=form, w=740 if spec.get('wide') else 360, h=150 if spec.get('wide') else 120, R=120 if spec.get('overlay') else 58, notes=spec.get('notes', []))
        body += '<div class="lg">' + ''.join(f'<span><i style="background:{colors[i % len(colors)]}"></i>{esc(name)}</span>' for i, name in enumerate(names))
        if spec.get('overlay'):
            body += f'<span><i style="background:{INK}"></i>reviews by others, 7d mean</span>'
        body += '</div>'
    else:
        styles = [dict(vals=v, style='bar' if kind == 'bars' else 'line', color=colors[i % len(colors)], label=(spec.get('labels') or fields)[i] if kind == 'lines' and len(vals) > 1 and key != 'queue' else '') for i, v in enumerate(vals)]
        if kind in ('cost lines', 'merge lines'):
            samples = series.get('pr_cost' if kind == 'cost lines' else 'htm', [None] * N)
            styles.insert(0, dict(vals=samples, style='dots', color=GREY))
        if kind == 'merge lines':
            styles[-1]['label'] = '7d median'
        if key in ('ops_pr', 'fr_pr', 'escaped'):
            styles[0]['label'] = '7d'
        if kind == 'cost lines':
            for style, name, color in zip(styles[1:], ('all spend', 'product repos', 'direct'), (INK, INK, ACC)):
                style['label'], style['color'] = name, color
            styles[2]['style'] = 'dash'
        body = chart(styles, kind=form, w=740 if spec.get('wide') else 360, h=170 if spec.get('wide') else 120, ymax=40 if kind == 'cost lines' else 72 if kind == 'merge lines' else spec.get('ymax'), R=74 if kind == 'cost lines' else 14 if key == 'queue' else 64 if key == 'decisions' else 58, yfmt=(lambda v: f'${v:.0f}') if kind == 'cost lines' else None)
        if key == 'abandoned':
            body = chart([dict(vals=vals[0], style='bar', color=GREY)], h=80)
        elif kind == 'bars':
            body = chart([dict(vals=vals[0], style='bar', color=colors[0] if key in ('guards', 'commits') else LIGHT), dict(vals=roll(vals[0]), color=INK, label='7d mean')], kind=form)
    if key == 'churn_tbl' and spec.get('weekly'):
        for name, values, week_dates in spec['weekly']:
            body = body.replace('<td>' + esc(name) + '</td>', '<td>' + (spark(values, w=70, h=16, sample_dates=week_dates) if len(values) > 1 else '') + '</td>')
    if spec.get('legend'):
        body += '<div class="lg">' + ''.join(f'<span><i style="background:{c}"></i>{esc(n)}</span>' for n, c in spec['legend']) + '</div>'
    if key == 'queue' and spec.get('labels'):
        body += '<div class="lg">' + ''.join(f'<span><i style="background:{c}"></i>{esc(n)}</span>' for n, c in zip(spec['labels'], colors)) + '</div>'
    if key == 'ops_pr':
        body += '<div class="foot">Includes the first prompt.</div>'
    if spec.get('foot'):
        body += f'<div class="foot">{esc(spec["foot"])}</div>'
    return tile(title, body, key, spec['home'], kval, 'w2' if spec.get('wide') else '')


def extension(path, series):
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict) or not isinstance(data.get('series'), dict) or not isinstance(data.get('tiles'), list):
        raise ValueError('extension needs series object and tiles list')
    for name, values in data['series'].items():
        if not isinstance(values, dict):
            raise ValueError('extension series must be keyed by date')
        for dd, value in values.items():
            date.fromisoformat(dd)
            xs = value if isinstance(value, list) else [value]
            if any(x is not None and (not isinstance(x, (int, float)) or not math.isfinite(x) or x < 0) for x in xs):
                raise ValueError('series values must be finite nonnegative numbers or null')
        series[name] = [values.get(d) for d in dates]
    for tile_spec in data['tiles']:
        if any(not isinstance(tile_spec.get(k), str) for k in ('key', 'band', 'title', 'home', 'about', 'kind')):
            raise ValueError('tile needs string key, band, title, home, about and kind')
        if tile_spec['band'] not in BANDS or tile_spec['kind'] not in ('bars', 'stacked bars', 'lines', 'table', 'empty'):
            raise ValueError('unknown extension band or kind')
        if not isinstance(tile_spec.get('series', []), list) or any(k not in series for k in tile_spec.get('series', [])):
            raise ValueError('unknown extension series')
        if tile_spec['kind'] == 'table' and not isinstance(tile_spec.get('rows', []), list):
            raise ValueError('table rows must be a list')
    return data['tiles']


def render(metrics, prose, paths=()):
    global D, N, dates, P
    D = metrics['days']; N = len(D); dates = [d['date'] for d in D]; P = dict(prose)
    if not N or dates != sorted(set(dates)):
        raise ValueError('metrics needs unique chronological days')
    for d in dates:
        date.fromisoformat(d)
    KEY.clear()
    series = derive(metrics)
    specs = generic_tiles(metrics)
    for path in paths:
        for spec in extension(path, series):
            specs = [s for s in specs if s['key'] != spec['key']]
            specs.append(spec)
    groups = defaultdict(list)
    output = ('Tasks completed', 'tasks_done') if any(d.get('tasks_done') is not None for d in D) else ('PRs merged', 'merged')
    curated = [
        ('Output', output[0], output[1], 'sum', '', 'up', 'optimize: higher'),
        ('Output', 'PRs merged', 'merged', 'sum', '', 'up', ''),
        ('Output', 'Open PRs', 'open_prs', 'last', '', 'down', ''),
        ('Cost', 'Cost per merged PR, all spend', 'cpp_all', 'last', '$', 'down', 'optimize: lower'),
        ('Cost', 'Cost per merged PR, direct (median)', 'attr7', 'last', '$', 'down', ''),
        ('Cost', 'Spend', 'spend', 'sum', '$', 'none', ''),
        ('Cost', 'Cache-write share of spend', 'cw_share', 'last', '%', 'down', ''),
        ('Human touches', 'Operator messages per merged PR', 'ops_pr', 'last', '', 'down', 'optimize: lower'),
        ('Human touches', 'Corrections and aborts per merged PR', 'corr_pr', 'last', '', 'down', ''),
        ('Human touches', 'Hours to merge', 'htm7', 'last', 'h', 'down', ''),
        ('Quality', 'Escaped defects per merged PR', 'escaped_pr', 'last', '', 'down', 'guardrail'),
        ('Quality', 'PRs fixed within 7 days', 'pr_fixed', 'sum', '', 'down', ''),
        ('Churn', 'Lines rewritten within 21 days', 'cr', 'last', '%', 'down', 'guardrail'),
        ('Factory health', 'Subagent failures', 'subfail', 'sum', '', 'down', 'guardrail'),
        ('Factory health', 'Automation runs failed', 'auto_fail', 'last', '%', 'down', ''),
        ('Factory health', 'Spend linked to a PR', 'coverage', 'last', '%', 'up', ''),
    ]
    if output[1] == 'merged':
        curated.pop(1)
    for category, title, field, how, form, better, target in curated:
        values = series.get(field, [None] * N)
        if any(v is not None for v in values):
            groups[category].append(score_row(title, values, how, form, better, target))
    for spec in specs:
        conf = spec.get('score_row')
        if not conf:
            continue
        values = series.get(conf.get('series'), [None] * N)
        if any(isinstance(v, list) for v in values if v is not None):
            continue
        if any(v is not None for v in values):
            groups[conf.get('category', spec['band'])].append(score_row(conf.get('title', spec['title']), values, conf.get('how', 'last'), conf.get('format', ''), conf.get('better', 'none')))
    score = ''.join(f'<tr class="grp"><td colspan="6">{esc(category)}</td></tr>' + ''.join(rows) for category, rows in groups.items())
    P['score'] = prose.get('score', '')
    score = tile('Last 7 days against the 7 days before', f'<table class="tbl sc"><tr><th></th><th>{daylabel(dates[0])} to {daylabel(dates[-1])}</th><th>prior 7d</th><th>last 7d</th><th>change</th><th></th></tr>{score}</table>', 'score', 'hworks', cls='full')
    bands = [band('Scorecard', [score])]
    for bandname in BANDS:
        bands.append(band(bandname, [render_tile(s, series) for s in specs if s['band'] == bandname]))
    notes = ''.join(f'<li>{esc(n)}</li>' for n in prose.get('notes', []))
    coverage = metrics.get('coverage', {})
    missing = coverage.get('missing_prs', [])
    hosts = coverage.get('unavailable_pr_hosts', [])
    coverage_note = (f'<div class="foot">PR coverage: {len(missing)} PRs missing' + (f'; unavailable hosts: {esc(", ".join(hosts))}' if hosts else '') + '. PR series cover only PRs read.</div>') if missing or hosts else ''
    doc = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
           f'<title>hworks factory metrics</title><style>{CSS}</style></head><body>'
           f'<header><h1>hworks factory metrics</h1><span class="sub">{esc(prose.get("subtitle", ""))}</span>'
           f'<span class="sub" style="flex:0;white-space:nowrap">generated {esc(metrics.get("generated", "")[:10])}</span></header><main>{coverage_note}{"".join(bands)}'
           f'<details><summary>{esc(prose.get("notes_title", "About the data"))}</summary><ul>{notes}</ul></details></main></body></html>')
    return doc.encode('ascii', 'xmlcharrefreplace').decode('ascii')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('metrics')
    parser.add_argument('--tiles', action='append', default=[])
    parser.add_argument('--prose', default=str(Path(__file__).with_name('factory-dashboard-prose.json')))
    parser.add_argument('-o', default='-')
    args = parser.parse_args()
    try:
        result = render(json.loads(Path(args.metrics).read_text()), json.loads(Path(args.prose).read_text()), args.tiles)
        if args.o == '-':
            print(result)
        else:
            Path(args.o).write_text(result, encoding='ascii')
    except (OSError, ValueError, KeyError, TypeError) as e:
        parser.error(str(e))


if __name__ == '__main__':
    main()
