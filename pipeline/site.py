"""`make site`: the design doc as one static page, in the style of Linear's design system.

Built only from what the repo already holds: storyboard.json (shots, reasons,
motion, lines), runs.jsonl (costs and latency), the final cut's report (which
motion each shot really used) and the Markdown documents. Colours, type and
radii are Linear's own tokens, read from linear.app's stylesheet on
2026-11-25. Output: outputs/site/index.html plus thumbnails in outputs/site/img/.
"""
from __future__ import annotations

import base64
import html
import json
import re
from pathlib import Path
from typing import Any

import markdown
from PIL import Image

from . import storyboard as sbmod
from .cache import StageCache
from .config import ROOT, Project
from .costs import summarise
from .engines import MODES, VIDEO_ENGINES

DOCS = [("design", "Audience and tests", "DESIGN.md"), ("experiments", "Experiments", "EXPERIMENTS.md"),
        ("failures", "Failures", "FAILURES.md"), ("costs", "Costs", "COSTS.md"), ("ethics", "Ethics", "ETHICS.md"),
        ("architecture", "Architecture", "ARCHITECTURE.md")]
MODE_LABEL = {"full_i2v": "Full motion", "flf_inbetween": "In-between", "masked_i2v": "Masked motion",
              "cinemagraph": "Cinemagraph", "parallax": "Parallax", "still_kenburns": "Ken Burns", "still": "Still"}


def _md(text: str) -> str:
    text = re.sub(r"\A#\s.*\n", "", text)  # the section supplies its own title
    return markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])


def _thumb(src: Path, out: Path, width: int = 360) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as img:
        img = img.convert("RGB")
        img.thumbnail((width, width * 2))
        img.save(out, quality=82)


def _shot_cards(project: Project, sb: dict[str, Any], site: Path, used: dict[str, Any]) -> str:
    keyframes = StageCache(project, "keyframes")
    cast = sbmod.characters(sb)
    cards = []
    for shot in sb["shots"]:
        sid, mode = shot["id"], shot["motion"]["mode"]
        img = ""
        kf = keyframes.current(sid)
        if kf:
            thumb = site / "img" / f"{sid}.jpg"
            _thumb(kf, thumb)  # embedded too, so index.html works as a single file
            data = base64.b64encode(thumb.read_bytes()).decode("ascii")
            img = f'<img src="data:image/jpeg;base64,{data}" alt="Keyframe {sid}" loading="lazy">'
        paid = MODES[mode]["paid"]
        engine = VIDEO_ENGINES.get(shot["motion"].get("engine") or sb["models"]["video"], {})
        cost = f"${engine.get('usd', {}).get(shot['motion'].get('clip_s', 5), 0):.2f}" if paid else "free"
        real = (used.get(sid) or {}).get("used")
        fell = (f'<span class="fell">in the last cut: {MODE_LABEL.get(real, real)}</span>'
                if real and real != mode else "")
        lines = "".join(f'<p class="line"><span>{html.escape(cast[l["speaker"]]["name"])}</span>'
                        f'{html.escape(l["en"])}</p>' for l in shot["lines"])
        cards.append(f"""
<article class="shot">
  <div class="frame">{img}</div>
  <div class="meta">
    <div class="row"><b>{sid}</b><span class="size">{html.escape(shot["size"])}</span>
      <span class="pill {"paid" if paid else "free"}">{MODE_LABEL[mode]}</span><span class="cost">{cost}</span></div>
    <p class="reason">{html.escape(shot["reason"])}</p>{lines}{fell}
  </div>
</article>""")
    return "".join(cards)


def _stats(project: Project, sb: dict[str, Any]) -> str:
    table = summarise(project)
    calls = sum(int(s["calls"]) for s in table.values())
    spent = sum(s["usd_list"] for k, s in table.items() if k in ("shots", "music"))
    paid = len(sbmod.paid_clips(sb))
    clip_cost = sum(VIDEO_ENGINES[s["motion"].get("engine") or sb["models"]["video"]]["usd"]
                    .get(s["motion"].get("clip_s", 5), 0) for s in sbmod.paid_clips(sb))
    tiles = [(f"{len(sb['shots'])}", "shots"), (f"{paid}", "paid clips planned"),
             (f"${clip_cost:.2f}", "motion per film"), (f"{calls}", "model calls logged"),
             (f"${spent:.3f}", "spent at WaveSpeed")]
    return "".join(f'<div class="stat"><b>{v}</b><span>{k}</span></div>' for v, k in tiles)


DIAGRAM = """<svg viewBox="0 0 700 470" class="diagram" role="img" aria-label="Pipeline: story to film">
<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
<path d="M0,0L10,5L0,10z" class="ah"/></marker></defs>
<g class="n"><rect x="250" y="4" width="200" height="40" rx="8"/><text x="350" y="29">story.md</text></g>
<path d="M350 44V64"/>
<g class="n"><rect x="225" y="66" width="250" height="44" rx="8"/><text x="350" y="86">script</text>
<text class="s" x="350" y="101">Gemini Flash chain, validates and repairs</text></g>
<path d="M350 110V130"/>
<g class="n k"><rect x="200" y="132" width="300" height="46" rx="8"/><text x="350" y="153">storyboard.json</text>
<text class="s" x="350" y="168">the contract every stage reads</text></g>
<path d="M260 178L90 226"/><path d="M320 178L265 226"/><path d="M380 178L435 226"/><path d="M440 178L610 226"/>
<g class="n f"><rect x="10" y="228" width="160" height="66" rx="8"/><text x="90" y="250">keyframes</text>
<text class="s" x="90" y="266">FLUX.2 klein</text><text class="s" x="90" y="281">references first</text></g>
<g class="n f"><rect x="185" y="228" width="160" height="66" rx="8"/><text x="265" y="250">narration</text>
<text class="s" x="265" y="266">Gemini TTS, bare line</text><text class="s" x="265" y="281">listen-back, re-takes</text></g>
<g class="n p"><rect x="355" y="228" width="160" height="66" rx="8"/><text x="435" y="250">music</text>
<text class="s" x="435" y="266">ACE-Step 1.5</text><text class="s" x="435" y="281">3 candidates</text></g>
<g class="n p"><rect x="530" y="228" width="160" height="66" rx="8"/><text x="610" y="250">shots</text>
<text class="s" x="610" y="266">Wan 2.2, at most 7 paid</text><text class="s" x="610" y="281">masks, depth maps</text></g>
<path d="M90 294L300 352"/><path d="M265 294L325 352"/><path d="M435 294L375 352"/><path d="M610 294L400 352"/>
<g class="n l"><rect x="150" y="354" width="400" height="58" rx="8"/><text x="350" y="376">assemble, on the laptop</text>
<text class="s" x="350" y="393">RIFE, parallax, loops, Ken Burns, captions, ducking, -14 LUFS</text></g>
<path d="M350 412V430"/>
<g class="n"><rect x="170" y="432" width="360" height="34" rx="8"/><text x="350" y="454">final film, 9:16 and 16:9</text></g>
</svg>"""

CSS = """
:root{--bg:#08090a;--panel:#0f1011;--l2:#141516;--l3:#191a1b;--t1:#f7f8f8;--t2:#d0d6e0;--t3:#8a8f98;--t4:#62666d;
--b1:#ffffff0d;--b2:#ffffff14;--b3:#23252a;--accent:#7170ff;--accent-h:#828fff;--tint:#18182f;--green:#27a644;
--orange:#fc7840;--blue:#4ea7fc;--yellow:#f0bf00;--font:"Inter Variable","Inter","SF Pro Display",-apple-system,"Segoe UI",sans-serif;
--mono:ui-monospace,"SF Mono",Menlo,monospace;color-scheme:dark}
@media (prefers-color-scheme:light){:root{--bg:#fff;--panel:#f8f8f8;--l2:#f4f4f4;--l3:#f0f0f0;--t1:#282a30;--t2:#3c4149;
--t3:#6f6e77;--t4:#86848d;--b1:#0000000d;--b2:#00000014;--b3:#e9e8ea;--accent:#5e6ad2;--accent-h:#4f5bc4;--tint:#f1f1ff;color-scheme:light}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--t2);font:400 15px/1.6 var(--font);letter-spacing:-.011em;
font-feature-settings:"cv01","ss03";-webkit-font-smoothing:antialiased}
a{color:var(--accent);text-decoration:none}a:hover{color:var(--accent-h)}
.layout{display:grid;grid-template-columns:232px minmax(0,1fr);max-width:1180px;margin:0 auto}
nav{position:sticky;top:0;align-self:start;padding:28px 16px;min-height:480px;border-right:1px solid var(--b1);display:flex;flex-direction:column;gap:2px}
nav .brand{font-weight:590;color:var(--t1);font-size:14px;padding:0 10px 18px}
nav a{color:var(--t3);font-size:13px;font-weight:510;padding:6px 10px;border-radius:6px;transition:background .15s,color .15s}
nav a:hover{background:var(--l2);color:var(--t1)}
main{padding:56px 48px 96px;min-width:0}
section{max-width:820px;margin:0 0 72px;scroll-margin-top:24px}
.hero{position:relative}
.hero::before{content:"";position:absolute;inset:-120px -80px auto;height:320px;pointer-events:none;
background:radial-gradient(60% 60% at 30% 30%,color-mix(in srgb,var(--accent) 22%,transparent),transparent 70%);filter:blur(10px)}
.eyebrow{font:510 12px/1 var(--mono);color:var(--t3);text-transform:uppercase;letter-spacing:.06em}
h1{position:relative;font-size:44px;line-height:1.05;letter-spacing:-.022em;font-weight:590;color:var(--t1);margin:14px 0 14px}
h2{font-size:22px;letter-spacing:-.012em;font-weight:590;color:var(--t1);margin:0 0 6px}
h3{font-size:15px;font-weight:590;color:var(--t1);margin:28px 0 6px}
.lead{position:relative;font-size:17px;color:var(--t3);max-width:640px;margin:0}
.sub{color:var(--t3);font-size:14px;margin:0 0 22px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1px;background:var(--b2);border:1px solid var(--b2);
border-radius:12px;overflow:hidden;margin-top:36px}
.stat{background:var(--panel);padding:16px 18px;display:flex;flex-direction:column;gap:2px}
.stat b{font-size:22px;font-weight:590;color:var(--t1);letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.stat span{font-size:12.5px;color:var(--t3)}
.audience{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin-top:20px}
.audience div{border:1px solid var(--b2);border-radius:12px;padding:14px 16px;background:var(--panel)}
.audience small{display:block;font:510 11px/1 var(--mono);text-transform:uppercase;letter-spacing:.06em;color:var(--t4);margin-bottom:8px}
.audience p{margin:0;color:var(--t2);font-size:14px}
.diagram{width:100%;height:auto;display:block;border:1px solid var(--b2);border-radius:12px;background:var(--panel);padding:16px}
.diagram path{fill:none;stroke:var(--t4);stroke-width:1.2;marker-end:url(#ar)}.diagram .ah{fill:var(--t4);stroke:none}
.diagram rect{fill:var(--l2);stroke:var(--b3)}.diagram text{fill:var(--t1);font:590 12.5px var(--font);text-anchor:middle}
.diagram text.s{fill:var(--t3);font-weight:400;font-size:10.5px}
.diagram .k rect{fill:var(--tint);stroke:var(--accent)}.diagram .p rect{stroke:var(--orange)}
.diagram .f rect{stroke:var(--blue)}.diagram .l rect{stroke:var(--green)}
.legend{display:flex;flex-wrap:wrap;gap:16px;font-size:12.5px;color:var(--t3);margin-top:12px}
.legend i{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:6px;vertical-align:1px}
.shots{display:grid;gap:12px}
.shot{display:grid;grid-template-columns:96px minmax(0,1fr);gap:16px;border:1px solid var(--b2);border-radius:12px;
padding:12px;background:var(--panel);transition:border-color .15s}
.shot:hover{border-color:var(--b3)}
.frame{aspect-ratio:9/16;border-radius:8px;overflow:hidden;background:var(--l3)}
.frame img{width:100%;height:100%;object-fit:cover;display:block}
.row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.row b{color:var(--t1);font-weight:590;font-family:var(--mono);font-size:13px}
.size{color:var(--t4);font-size:12.5px}.cost{margin-left:auto;font:510 12.5px var(--mono);color:var(--t3);font-variant-numeric:tabular-nums}
.pill{font-size:11.5px;font-weight:510;padding:2px 8px;border-radius:9999px;border:1px solid var(--b2)}
.pill.paid{color:var(--orange);background:color-mix(in srgb,var(--orange) 10%,transparent)}
.pill.free{color:var(--green);background:color-mix(in srgb,var(--green) 10%,transparent)}
.reason{margin:8px 0 6px;color:var(--t2);font-size:14px}
.line{margin:4px 0 0;font-size:13.5px;color:var(--t3)}.line span{font-weight:510;color:var(--t2);margin-right:6px}
.fell{display:inline-block;margin-top:8px;font-size:12px;color:var(--yellow)}
.doc table{width:100%;border-collapse:collapse;font-size:13.5px;margin:14px 0;display:block;overflow-x:auto}
.doc th{text-align:left;font-weight:510;color:var(--t3);border-bottom:1px solid var(--b3);padding:8px 10px;white-space:nowrap}
.doc td{border-bottom:1px solid var(--b1);padding:8px 10px;vertical-align:top}
.doc code{font:13px var(--mono);background:var(--l2);border:1px solid var(--b1);border-radius:4px;padding:1px 5px;color:var(--t1)}
.doc pre{background:var(--panel);border:1px solid var(--b2);border-radius:8px;padding:14px;overflow:auto}
.doc pre code{background:none;border:0;padding:0}
.doc h2{font-size:17px;margin:34px 0 8px}.doc ul{padding-left:20px}.doc li{margin:4px 0}
.doc strong{color:var(--t1);font-weight:590}.doc blockquote{margin:12px 0;padding:2px 16px;border-left:2px solid var(--accent);color:var(--t3)}
footer{color:var(--t4);font-size:12.5px;border-top:1px solid var(--b1);padding-top:20px;max-width:820px}
@media (max-width:900px){.layout{grid-template-columns:1fr}
nav{position:sticky;height:auto;flex-direction:row;flex-wrap:wrap;gap:4px;padding:12px 16px;border-right:0;border-bottom:1px solid var(--b1);
background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(12px);z-index:5;min-height:0}
.scroll{overflow-x:auto;border-radius:12px}.scroll .diagram{min-width:620px}
nav .brand{width:100%;padding:0 10px 6px}main{padding:36px 16px 72px}h1{font-size:34px}}
@media (min-width:1600px){.layout{max-width:1440px}section{max-width:960px}.shots{grid-template-columns:1fr 1fr}}
"""


def run(project: Project) -> Path:
    sb = sbmod.load_valid(project)
    site = project.outputs / "site"
    site.mkdir(parents=True, exist_ok=True)
    report_path = project.outputs / "final" / "heritage_short.report.json"
    used = json.loads(report_path.read_text("utf-8")).get("sources", {}) if report_path.exists() else {}
    docs = []
    for anchor, title, name in DOCS:
        path = ROOT / name
        if path.exists():
            docs.append((anchor, title, _md(path.read_text("utf-8"))))
    nav = "".join(f'<a href="#{a}">{t}</a>' for a, t in
                  [("overview", "Overview"), ("pipeline", "Pipeline"), ("shots", "Shots")] + [(a, t) for a, t, _ in docs])
    aud = sb["audience"]
    body = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(sb["title"])}: design doc</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400..700&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body><div class="layout">
<nav><div class="brand">10x video gen</div>{nav}</nav>
<main>
<section id="overview" class="hero"><div class="eyebrow">Heritage short · design doc</div>
<h1>{html.escape(sb["title"])}</h1><p class="lead">{html.escape(sb["logline"])}</p>
<div class="stats">{_stats(project, sb)}</div>
<div class="audience"><div><small>Who</small><p>{html.escape(aud["who"])}</p></div>
<div><small>Where</small><p>{html.escape(aud["where"])}</p></div><div><small>Feel</small><p>{html.escape(aud["feel"])}</p></div></div></section>
<section id="pipeline"><h2>Pipeline</h2><p class="sub">One command, six stages, one contract. Every output is cached by a hash of its inputs.</p>
<div class="scroll">{DIAGRAM}</div><div class="legend"><span><i style="background:var(--accent)"></i>contract</span><span><i style="background:var(--blue)"></i>free tier API</span>
<span><i style="background:var(--orange)"></i>paid API</span><span><i style="background:var(--green)"></i>local</span></div></section>
<section id="shots"><h2>Shots</h2><p class="sub">Each shot states why it exists and how it moves. Paid motion only where a person acts.</p>
<div class="shots">{_shot_cards(project, sb, site, used)}</div></section>
{"".join(f'<section id="{a}" class="doc"><h2>{t}</h2>{h}</section>' for a, t, h in docs)}
<footer>Built by <code>make site</code> from storyboard.json, runs.jsonl and the repo's documents. Colours and type follow Linear's design system.</footer>
</main></div></body></html>"""
    out = site / "index.html"
    out.write_text(body, "utf-8")
    print(f"  site: {out.relative_to(project.root)}")
    return out
