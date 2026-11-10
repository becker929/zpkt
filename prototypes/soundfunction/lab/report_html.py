#!/usr/bin/env python3
"""Render the runner's reports as one self-contained page.
    python3 lab/report_html.py lab/drive/reports/all.json out.html "Run title"
Design: a bench sheet for one producer's material. Dark-first like the research
pages; condensed industrial display face, Plex body, Plex Mono for data; every
measure drawn on a small scale against the corpus median so the eye reads
"where am I" before the number."""
import json, html, sys, math
from pathlib import Path
from datetime import datetime, timezone

CORPUS = json.load(open("corpus2/summary.json"))["all"]
E = lambda s: html.escape(str(s)) if s is not None else ""


def fmt(v, unit=""):
    if v is None or v == "": return "–"
    if isinstance(v, (int, float)):
        if isinstance(v, float) and not math.isfinite(v): return "–"
        s = f"{v:.0f}" if abs(v) >= 100 or float(v).is_integer() else (f"{v:.1f}" if abs(v) >= 10 else f"{v:.2f}")
        return s + (f"<span class=u>{E(unit)}</span>" if unit else "")
    return E(v)


def scale(value, ref, unit):
    """A small horizontal scale: reference at centre, value as a dot. Only for numbers with a reference."""
    if not isinstance(value, (int, float)) or not isinstance(ref, (int, float)) or ref == 0: return ""
    span = {"bpm": 30, "dB": 12, "ms": 200, "share": 0.4, "Hz": 30}.get(unit, abs(ref))
    x = 50 + 50 * max(-1, min(1, (value - ref) / span))
    return f'<span class="sc" title="reference at the centre; the span is ±{span} {E(unit)}"><i></i><b style="left:{x:.1f}%"></b></span>'


def rows_table(rows):
    out = ['<table class="m"><thead><tr><th>measure</th><th class="n">value</th><th class="n">reference</th><th>where you sit</th><th>note</th></tr></thead><tbody>']
    for r in rows:
        flag = " class=\"void\"" if str(r.get("note", "")).lower().startswith("not usable") else ""
        out.append(f'<tr{flag}><td>{E(r["label"])}</td><td class="n">{fmt(r.get("value"), r.get("unit", ""))}</td><td class="n">{fmt(r.get("ref"), r.get("unit", "")) if r.get("ref") is not None else ""}</td>'
                   f'<td>{scale(r.get("value"), r.get("ref"), r.get("unit", ""))}</td><td class="note">{E(r.get("note", ""))}</td></tr>')
    out.append("</tbody></table>"); return "".join(out)


def generic_table(t):
    head = "".join(f"<th{' class=n' if i else ''}>{E(c)}</th>" for i, c in enumerate(t["columns"]))
    body = "".join("<tr>" + "".join(f'<td class="{"n" if isinstance(v, (int, float)) else ""}">{fmt(v)}</td>' for v in row) + "</tr>" for row in t["rows"])
    return f'<table class="m"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def grid_svg(g):
    rows, cols = len(g), len(g[0]); mx = max(max(r) for r in g) or 1
    cw, ch, lw = 44, 30, 62; W, H = lw + cols * cw, rows * ch + 22
    cells = []
    for r in range(rows):
        for k in range(cols):
            a = 0.08 + 0.92 * g[r][k] / mx
            cells.append(f'<rect x="{lw + k * cw + 1}" y="{r * ch + 1}" width="{cw - 2}" height="{ch - 2}" rx="2" fill="var(--accent)" fill-opacity="{a:.3f}"/>')
    labels = "".join(f'<text x="{lw - 6}" y="{r * ch + ch / 2 + 4}" text-anchor="end" class="gl">{n}</text>' for r, n in enumerate(["sub", "low", "lo-mid", "mid", "high", "air"]))
    beats = "".join(f'<text x="{lw + k * cw + 4}" y="{H - 6}" class="gl">{k // 4 + 1}</text>' for k in range(0, cols, 4))
    return f'<svg viewBox="0 0 {W} {H}" class="grid" role="img" aria-label="attack grid, six bands by sixteen steps">{"".join(cells)}{labels}{beats}</svg>'


def render_report(rep):
    it = rep.get("item", {}); parts = [f'<article class="rep" id="{E(it.get("title", ""))}">']
    parts.append(f'<div class="eyebrow">{E(it.get("kind", ""))} · {E(", ".join(it.get("files", [])))}</div>')
    parts.append(f'<h2>{E(it.get("title", "untitled"))}</h2>')
    parts.append(f'<p class="headline">{E(rep.get("headline", ""))}</p>')
    if rep.get("rows"): parts.append(rows_table(rep["rows"]))
    for sec in rep.get("sections", []):
        parts.append(f'<h3>{E(sec["title"])}</h3>')
        if sec.get("text"): parts.append(f'<p class="lede">{E(sec["text"])}</p>')
        if sec.get("rows"): parts.append(rows_table(sec["rows"]))
        if sec.get("table"): parts.append(generic_table(sec["table"]))
        if sec.get("grid"): parts.append(grid_svg(sec["grid"]))
    rn = rep.get("runner", {})
    parts.append(f'<p class="foot">measured in {rn.get("seconds", "?")} s on {E(rn.get("when", ""))}</p></article>')
    return "".join(parts)


def compare_table(reports):
    """Tracks and references side by side on the measures that matter, corpus median last."""
    cols = [("tempo", "tempo", "bpm"), ("pump_depth_db", "pump, mix", "dB"), ("pump_return_ms", "return", "ms"), ("kick_off_share", "bars no kick", "share"),
            ("kick_decay20", "kick falls 20 dB", "ms"), ("kick_ring", "kick at next beat", "dB"), ("kick_sub", "kick sub share", ""), ("kick_bright", "kick brightness", "Hz"), ("kick_pitch_hz", "kick lands", "Hz")]
    rows = []
    for r in reports:
        it = r.get("item", {}); raw = r.get("raw") or {}
        if it.get("kind") not in ("track", "reference") or not raw: continue
        k = raw.get("kicks") or {}
        vals = dict(tempo=raw.get("tempo"), pump_depth_db=raw.get("pump_depth_db"), pump_return_ms=raw.get("pump_return_ms"), kick_off_share=raw.get("kick_off_share"),
                    kick_decay20=k.get("decay20_ms"), kick_ring=k.get("level_at_next_beat_db"), kick_sub=k.get("band_sub_share"), kick_bright=k.get("spectral_centroid_hz"), kick_pitch_hz=raw.get("kick_pitch_hz"))
        rows.append((it.get("kind"), it.get("title"), vals))
    if not rows: return ""
    corpus = dict(tempo=CORPUS["tempo_median"], pump_depth_db=CORPUS["pump_depth_median"], pump_return_ms=CORPUS["pump_return_median"], kick_off_share=CORPUS["kick_off_share_median"],
                  kick_decay20=None, kick_ring=None, kick_sub=0.47, kick_bright=2127, kick_pitch_hz=55.7)
    head = "<th>item</th>" + "".join(f'<th class="n">{E(lab)}</th>' for _, lab, _ in cols)
    body = ""
    for kind, title, vals in sorted(rows, key=lambda x: (x[0] != "reference", x[1])):
        body += f'<tr class="{kind}"><td><span class="tag">{E(kind)}</span> <a href="#{E(title)}">{E(title)}</a></td>' + "".join(f'<td class="n">{fmt(vals.get(key), unit)}</td>' for key, _, unit in cols) + "</tr>"
    body += '<tr class="corpus"><td><span class="tag">corpus</span> median of 218 tracks</td>' + "".join(f'<td class="n">{fmt(corpus.get(key), unit)}</td>' for key, _, unit in cols) + "</tr>"
    return f'<h3>Side by side</h3><p class="lede">Your tracks, your references and the corpus on the same eight numbers. Kick numbers come from the kicks found by position in the separated drums; corpus kick numbers from part three.</p><div class="tw"><table class="m cmp"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def embedding_section():
    """The embedding figure inline (data URI) plus each owner item's nearest corpus neighbours and z-scores."""
    import base64, os
    ej = Path("lab/drive/reports/embedding.json"); png = Path("out/plots/embedding.png")
    if not ej.exists() or not png.exists(): return ""
    E = json.load(open(ej)); names = E["names"]
    b64 = base64.b64encode(png.read_bytes()).decode()
    parts = [f'<h3>Where your tracks sit</h3><p class="lede">Every corpus excerpt and every item here as one point: {len(E["features"])} measures per track, standardised on the corpus, reduced to two axes ({E["explained"][0]:.0%} and {E["explained"][1]:.0%} of the spread). Distances below are in the full 14-measure space, in corpus standard deviations.</p>',
             f'<img class="embed" src="data:image/png;base64,{b64}" alt="Scatter of 215 corpus tracks in grey with the references in orange and the owner\'s tracks in teal, on two axes built from fourteen per-track measures.">']
    rows = []
    for it in E["items"]:
        if it["kind"] == "corpus": continue
        z = it.get("z", {}); far = sorted(z.items(), key=lambda kv: -abs(kv[1]))[:3]
        rows.append([f'{it["kind"]}: {it["label"]}', ", ".join(f'{n["label"]} ({n["distance"]})' for n in it.get("nearest", [])), ", ".join(f'{names[f]} {v:+.1f}' for f, v in far)])
    parts.append(generic_table(dict(columns=["item", "nearest corpus tracks (distance)", "what sets it apart (z-scores)"], rows=rows)))
    return "".join(parts)


def page(reports, title):
    when = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    body = "".join(render_report(r) for r in reports)
    toc = "".join(f'<li><a href="#{E(r.get("item", {}).get("title", ""))}">{E(r.get("item", {}).get("title", ""))}</a><span>{E(r.get("item", {}).get("kind", ""))}</span></li>' for r in reports)
    return f'''<title>{E(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{{--bg:#f6f5f1;--panel:#ecebe5;--ink:#181b20;--dim:#5b6470;--line:#d6d5cd;--accent:#177e88;--warm:#a85f1c;--void:#8a2b2b;--sans:"IBM Plex Sans",system-ui,sans-serif;--mono:"IBM Plex Mono",ui-monospace,Menlo,monospace;--disp:"Barlow Condensed","Arial Narrow",sans-serif}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#0e1116;--panel:#151a22;--ink:#e6e9ef;--dim:#9aa4b5;--line:#262d39;--accent:#22a7b3;--warm:#cf7f2a;--void:#e06060}}}}
:root[data-theme="dark"]{{--bg:#0e1116;--panel:#151a22;--ink:#e6e9ef;--dim:#9aa4b5;--line:#262d39;--accent:#22a7b3;--warm:#cf7f2a;--void:#e06060}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 var(--sans)}}
.wrap{{max-width:900px;margin:0 auto;padding:2.2rem 1.25rem 4rem}}
header .kicker{{font:600 .72rem/1 var(--mono);letter-spacing:.16em;text-transform:uppercase;color:var(--accent)}}
h1{{font:600 clamp(2rem,5vw,3rem)/1 var(--disp);letter-spacing:.01em;text-transform:uppercase;margin:.5rem 0 .4rem;text-wrap:balance}}
header p{{color:var(--dim);margin:0;max-width:65ch}}
.toc{{list-style:none;padding:0;margin:1.4rem 0 0;display:flex;flex-wrap:wrap;gap:.5rem}} .toc li{{display:flex;gap:.5rem;align-items:baseline;background:var(--panel);border:1px solid var(--line);border-radius:4px;padding:.35rem .6rem}} .toc a{{color:var(--ink);text-decoration:none;font-weight:500}} .toc span{{font:500 .68rem var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--dim)}}
.rep{{margin-top:3rem;padding-top:1.6rem;border-top:2px solid var(--ink)}}
.eyebrow{{font:500 .7rem/1 var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--dim)}}
h2{{font:600 2rem/1.05 var(--disp);text-transform:uppercase;margin:.35rem 0 .6rem;text-wrap:balance}}
.headline{{font-size:1.15rem;font-weight:500;margin:0 0 1.2rem;max-width:65ch}}
h3{{font:600 1.2rem/1.1 var(--disp);text-transform:uppercase;letter-spacing:.02em;margin:2rem 0 .5rem}}
.lede{{color:var(--dim);margin:0 0 .7rem;max-width:70ch}}
table.m{{width:100%;border-collapse:collapse;font-size:.88rem}} table.m th{{text-align:left;font:500 .68rem/1.2 var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--dim);padding:.35rem .5rem;border-bottom:1px solid var(--line)}}
table.m td{{padding:.42rem .5rem;border-bottom:1px solid var(--line);vertical-align:top}} table.m .n,table.m th.n{{text-align:right;font-family:var(--mono);font-variant-numeric:tabular-nums;white-space:nowrap}}
.u{{color:var(--dim);margin-left:.25em;font-size:.8em}} td.note{{color:var(--dim);font-size:.8rem;max-width:34ch}}
tr.void td{{color:var(--dim)}} tr.void td.note{{color:var(--void)}} tr.void .n{{text-decoration:line-through;text-decoration-color:var(--void)}}
.sc{{position:relative;display:inline-block;width:110px;height:14px;vertical-align:middle}} .sc i{{position:absolute;left:0;right:0;top:6px;height:2px;background:var(--line)}} .sc i::after{{content:"";position:absolute;left:50%;top:-4px;width:1px;height:10px;background:var(--dim)}} .sc b{{position:absolute;top:2px;width:10px;height:10px;margin-left:-5px;border-radius:50%;background:var(--accent);border:2px solid var(--bg)}}
img.embed{{width:100%;height:auto;display:block;border-radius:4px;border:1px solid var(--line);margin:.4rem 0 1rem}}
svg.grid{{width:100%;height:auto;display:block;background:var(--panel);border:1px solid var(--line);border-radius:4px;margin:.4rem 0}} .gl{{font:11px var(--mono);fill:var(--dim)}}
.foot{{font:.72rem var(--mono);color:var(--dim);margin-top:1.2rem}}
.tw{{overflow-x:auto}} .tag{{font:500 .62rem var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--dim);margin-right:.3rem}} table.cmp tr.reference td:first-child .tag{{color:var(--warm)}} table.cmp tr.track td:first-child .tag{{color:var(--accent)}} table.cmp tr.corpus td{{border-top:2px solid var(--line);color:var(--dim)}} table.cmp a{{color:var(--ink);text-decoration:none;border-bottom:1px dotted var(--dim)}}
@media (max-width:640px){{td.note{{display:none}} table.m th:last-child{{display:none}}}}
</style>
<div class="wrap">
<header><div class="kicker">The lab · bench sheet</div><h1>{E(title)}</h1><p>{len(reports)} item{"s" if len(reports) != 1 else ""} measured against the 218-track corpus. Reference column: your own references once you upload some, the corpus median until then. A scale shows where you sit; the tick is the reference.</p>
<ul class="toc">{toc}</ul></header>
{compare_table(reports)}
{embedding_section()}
{body}
<p class="foot">Made {when}. Numbers that the method cannot support for this file are struck through and say why.</p>
</div>'''


if __name__ == "__main__":
    reports = json.load(open(sys.argv[1])); out = sys.argv[2]; title = sys.argv[3] if len(sys.argv) > 3 else "Lab run"
    open(out, "w").write(page(reports, title)); print("wrote", out, len(reports), "reports")
