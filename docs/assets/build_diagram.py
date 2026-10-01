#!/usr/bin/env python3
"""
Builds the Saakshya pipeline diagram as script-free SVG.

    python docs/assets/build_diagram.py

Outputs (next to this file):
  saakshya-pipeline.svg        follows the viewer's colour scheme; when opened directly it is interactive:
                               hover / focus a stage for details, and use the Day / Night / Auto switch
  saakshya-pipeline-light.svg  forced day palette   (used by the README <picture> for GitHub light theme)
  saakshya-pipeline-dark.svg   forced night palette (used by the README <picture> for GitHub dark theme)

No JavaScript is used: theme switching relies on CSS :target, details on :hover / :focus, motion on CSS + SMIL.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

W, H = 1200, 660
NODE_W, NODE_H, GAP, LEFT = 168, 64, 22, 41
ROW1_Y, ROW2_Y = 132, 252

LIGHT = {
    "bg": "#FBF8F3", "panel": "#FFFFFF", "ink": "#1F2430", "muted": "#5B6474", "line": "#D9D2C5",
    "accent": "#C2410C", "accent-soft": "#FDE7D8", "teal": "#0F766E", "teal-soft": "#D8F1EE",
    "warn": "#9F1239", "warn-soft": "#FCE4EA", "node": "#FFFFFF", "node-hover": "#FFF4EC",
}
DARK = {
    "bg": "#12151C", "panel": "#1A1F2A", "ink": "#EEF1F6", "muted": "#9AA5B8", "line": "#313A4B",
    "accent": "#FB923C", "accent-soft": "#3A2516", "teal": "#5EEAD4", "teal-soft": "#12332F",
    "warn": "#FDA4AF", "warn-soft": "#3B1620", "node": "#1F2532", "node-hover": "#2A2118",
}

# (label, sub-label, detail title, detail line 1, detail line 2)
STAGES = [
    ("Normalise", "any Indian format", "1 · Normalise the number",
     "Accepts +91 98765 43210, 09876543210, (98)76543210 and more, validates with libphonenumber,",
     "classifies mobile / landline / toll-free / 140-series, and generates the search variants."),
    ("Telecom intel", "numbering facts only", "2 · Telecom intelligence",
     "Country, type, formats, time zone and the ORIGINAL allocation, always labelled as such:",
     "number portability means a prefix never proves the current carrier, region or person."),
    ("Exact search", "quoted variants", "3 · Exact-match discovery",
     "Runs quoted variants through documented search APIs (Brave, SerpAPI, Serper, Tavily).",
     "Each query is scored by information gain; branches that repeat known URLs are stopped."),
    ("Documents", "pdf · xls · doc", "4 · Public documents",
     "filetype: queries surface tenders, brochures, notices and directories. Files are fetched within",
     "robots.txt, size and type limits, then parsed in-process for names, e-mails and dates."),
    ("Social", "public pages only", "5 · Social and profile references",
     "site: queries find public pages that display the number. Wording stays honest:",
     "\"the number appears on a page associated with username X\", never \"belongs to\"."),
    ("Business", "listings and sites", "6 · Business discovery",
     "Directories, company sites and place listings: business name, stated owner, address,",
     "website, e-mail and any other number publicly listed on the same page."),
    ("Registries", "courts · tenders", "7 · Public registries",
     "Government, court, tender and company-record pages reached through search and",
     "documented APIs only. No form submission, no CAPTCHA solving, no logins."),
    ("Classifieds", "listings over time", "8 · Classifieds and marketplaces",
     "Old adverts are often the only trace of a previous holder of a number.",
     "Title, seller, category, place and date are recorded. Sellers are never contacted."),
    ("Page fetch", "robots.txt aware", "9 · Full-text evidence",
     "The most promising surfaced pages are fetched (never crawled) so every finding carries",
     "our own excerpt, a content hash and a retrieval time that an investigator can re-verify."),
    ("Lead expansion", "bounded recursion", "10 · Follow the leads",
     "Names, e-mails, usernames, businesses and domains become ranked leads. Only the relevant",
     "ones are searched, and expansion stops when new information dries up."),
    ("Entity resolution", "never merge blindly", "11 · Resolve entities, keep contradictions",
     "Sources merge only on strong keys (e-mail, username, website) or matching names.",
     "Two different names stay two candidates, with the conflict written down."),
    ("Score and report", "show your working", "12 · Transparent scoring and reports",
     "A visible point ledger (+40 exact match, -30 conflicting name ...) explains every score.",
     "Output: HTML, Markdown, JSON, CSV, a timeline and an evidence graph."),
]


def css_vars(p: dict[str, str]) -> str:
    return "".join(f"--{k}:{v};" for k, v in p.items())


def node_xy(i: int) -> tuple[int, int]:
    if i < 6:
        return LEFT + i * (NODE_W + GAP), ROW1_Y
    return LEFT + (11 - i) * (NODE_W + GAP), ROW2_Y  # second row runs right-to-left (serpentine)


def build(mode: str) -> str:
    """mode: 'auto' (media query + interactive switch), 'light' or 'dark' (forced palette)."""
    if mode == "dark":
        theme = f"svg{{{css_vars(DARK)}}}"
    elif mode == "light":
        theme = f"svg{{{css_vars(LIGHT)}}}"
    else:
        theme = (
            f"svg{{{css_vars(LIGHT)}}}"
            f"@media (prefers-color-scheme: dark){{svg{{{css_vars(DARK)}}}}}"
            f"svg:has(#night:target){{{css_vars(DARK)}}}"
            f"svg:has(#day:target){{{css_vars(LIGHT)}}}"
        )
    style = f"""
    {theme}
    text{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;fill:var(--ink)}}
    .bg{{fill:var(--bg)}} .panel{{fill:var(--panel);stroke:var(--line)}}
    .title{{font-size:34px;font-weight:700;letter-spacing:-0.5px}}
    .deva{{font-size:20px;fill:var(--accent);font-weight:600}}
    .tag{{font-size:15px;fill:var(--muted)}}
    .rail{{fill:none;stroke:var(--line);stroke-width:3}}
    .flow{{fill:none;stroke:var(--accent);stroke-width:3;stroke-linecap:round;stroke-dasharray:2 16;
          animation:flow 1.6s linear infinite}}
    @keyframes flow{{to{{stroke-dashoffset:-36}}}}
    .pulse{{fill:var(--accent)}}
    .node rect.box{{fill:var(--node);stroke:var(--line);stroke-width:1.5;transition:all .15s}}
    .node{{cursor:pointer;outline:none}}
    .node:hover rect.box,.node:focus rect.box{{fill:var(--node-hover);stroke:var(--accent);stroke-width:2.5}}
    .num{{font-size:11px;font-weight:700;fill:var(--accent)}}
    .label{{font-size:15px;font-weight:650}}
    .sub{{font-size:11.5px;fill:var(--muted)}}
    .tip{{opacity:0;pointer-events:none;transition:opacity .15s}}
    .node:hover .tip,.node:focus .tip{{opacity:1}}
    svg:has(.node:hover) .hint,svg:has(.node:focus) .hint{{opacity:0}}
    .hint{{transition:opacity .15s}}
    .tip-title{{font-size:18px;font-weight:700;fill:var(--accent)}}
    .tip-line{{font-size:14.5px;fill:var(--ink)}}
    .hint-title{{font-size:18px;font-weight:700}}
    .hint-line{{font-size:14.5px;fill:var(--muted)}}
    .chip rect{{stroke-width:1.2}} .chip text{{font-size:12.5px;font-weight:600}}
    .c-teal rect{{fill:var(--teal-soft);stroke:var(--teal)}} .c-teal text{{fill:var(--teal)}}
    .c-acc rect{{fill:var(--accent-soft);stroke:var(--accent)}} .c-acc text{{fill:var(--accent)}}
    .c-warn rect{{fill:var(--warn-soft);stroke:var(--warn)}} .c-warn text{{fill:var(--warn)}}
    .cap{{font-size:12px;font-weight:700;letter-spacing:1.2px;fill:var(--muted)}}
    .switch rect{{fill:var(--panel);stroke:var(--line)}} .switch text{{font-size:12.5px;font-weight:600;fill:var(--muted)}}
    .switch a:hover text{{fill:var(--accent)}}
    .phone{{font-size:15px;font-weight:700;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;fill:var(--accent)}}
    @media (prefers-reduced-motion: reduce){{.flow{{animation:none}} .pulse{{display:none}}}}
    """
    y1, y2 = ROW1_Y + NODE_H // 2, ROW2_Y + NODE_H // 2
    x_first, x_last = LEFT + 10, LEFT + 5 * (NODE_W + GAP) + NODE_W - 10
    turn = W - 22
    rail = (f"M {x_first} {y1} H {x_last} C {turn} {y1}, {turn} {y2}, {x_last} {y2} H {x_first}")

    out: list[str] = []
    a = out.append
    a(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
      f'aria-labelledby="t d">')
    a('<title id="t">Saakshya investigation pipeline</title>')
    a('<desc id="d">Twelve stages from a normalised Indian phone number to an evidence-backed report: normalise, '
      'telecom intelligence, exact search, documents, social, business, registries, classifieds, page fetch, lead '
      'expansion, entity resolution, scoring and report.</desc>')
    a(f"<style>{style}</style>")
    a(f'<rect class="bg" width="{W}" height="{H}" rx="18"/>')
    if mode == "auto":  # :target anchors for the script-free theme switch
        a('<g id="day"/><g id="night"/><g id="auto"/>')

    # header
    a('<text class="title" x="41" y="58">Saakshya <tspan class="deva" dx="6">साक्ष्य · evidence</tspan></text>')
    a('<text class="tag" x="41" y="86">One Indian phone number in. Every public association out, each with its '
      'source, its date and its doubt.</text>')
    a(f'<text class="phone" x="{W - 41}" y="86" text-anchor="end">+91 98765 43210</text>')
    if mode == "auto":
        sx = W - 41 - 222
        a(f'<g class="switch"><rect x="{sx}" y="34" width="222" height="30" rx="15"/>')
        for j, (label, target) in enumerate((("☀ Day", "day"), ("☾ Night", "night"), ("Auto", "auto"))):
            a(f'<a href="#{target}"><text x="{sx + 37 + j * 74}" y="54" text-anchor="middle">{label}</text></a>')
        a('</g>')

    # rail + animated flow
    a(f'<path class="rail" d="{rail}"/><path class="flow" d="{rail}"/>')
    a(f'<circle class="pulse" r="6"><animateMotion dur="9s" repeatCount="indefinite" path="{rail}"/></circle>')

    # detail panel
    py = 352
    a(f'<rect class="panel" x="41" y="{py}" width="{W - 82}" height="118" rx="14"/>')
    a(f'<g class="hint"><text class="hint-title" x="65" y="{py + 38}">What happens at each stage?</text>'
      f'<text class="hint-line" x="65" y="{py + 66}">Open this SVG on its own and hover or tab through the twelve '
      f'stages. Nothing here is a black box:</text>'
      f'<text class="hint-line" x="65" y="{py + 90}">every finding keeps its URL, excerpt, date, source grade and '
      f'the reason it was linked.</text></g>')

    # nodes (tips live inside each node so :hover reveals them in the panel)
    for i, (label, sub, tt, l1, l2) in enumerate(STAGES):
        x, y = node_xy(i)
        a(f'<g class="node" tabindex="0"><rect class="box" x="{x}" y="{y}" width="{NODE_W}" height="{NODE_H}" rx="12"/>'
          f'<text class="num" x="{x + 14}" y="{y + 20}">{i + 1:02d}</text>'
          f'<text class="label" x="{x + 14}" y="{y + 39}">{escape(label)}</text>'
          f'<text class="sub" x="{x + 14}" y="{y + 55}">{escape(sub)}</text>'
          f'<g class="tip"><text class="tip-title" x="65" y="{py + 38}">{escape(tt)}</text>'
          f'<text class="tip-line" x="65" y="{py + 66}">{escape(l1)}</text>'
          f'<text class="tip-line" x="65" y="{py + 90}">{escape(l2)}</text></g></g>')

    # chips
    def chips(y: int, caption: str, items: list[tuple[str, str]], x0: int = 41) -> None:
        a(f'<text class="cap" x="{x0}" y="{y - 12}">{escape(caption)}</text>')
        x = x0
        for text, cls in items:
            w = int(len(text) * 7.4) + 26
            a(f'<g class="chip {cls}"><rect x="{x}" y="{y}" width="{w}" height="28" rx="14"/>'
              f'<text x="{x + w / 2:.0f}" y="{y + 18.5}" text-anchor="middle">{escape(text)}</text></g>')
            x += w + 10

    chips(512, "EVERY CLAIM IS GRADED", [
        ("DIRECT", "c-teal"), ("INDIRECT", "c-teal"), ("INFERRED", "c-teal"),
        ("FACT", "c-acc"), ("STRONG MATCH", "c-acc"), ("POSSIBLE", "c-acc"), ("WEAK", "c-acc"),
        ("UNVERIFIED", "c-acc"), ("CONTRADICTORY", "c-acc"), ("Source grade A to E", "c-teal")])
    chips(590, "NEVER, BY DESIGN", [
        ("no breach data", "c-warn"), ("no logins", "c-warn"), ("no private APIs", "c-warn"),
        ("no OTP probes", "c-warn"), ("no subscriber data", "c-warn"), ("no tracking", "c-warn"),
        ("no guessed numbers", "c-warn"), ("no scraping", "c-warn")])
    a("</svg>")
    return "\n".join(out)


def main() -> None:
    here = Path(__file__).resolve().parent
    for mode, name in (("auto", "saakshya-pipeline.svg"), ("light", "saakshya-pipeline-light.svg"),
                       ("dark", "saakshya-pipeline-dark.svg")):
        (here / name).write_text(build(mode), encoding="utf-8")
        print("wrote", here / name)


if __name__ == "__main__":
    main()
