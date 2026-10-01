"""
HTML report rendered from ``reports/templates/report.html.j2`` (Jinja2,
autoescape ON, self-contained: inline CSS, no external assets).

The evidence graph is drawn as an inline SVG whose coordinates are computed
here with a simple layered layout (phone at the left, candidate entities in
the next column, their attributes further right).  Graphs with more than
``MAX_SVG_NODES`` nodes fall back to an edge table.  If ``inv.graph`` carries
a ``pyvis_html`` string (produced elsewhere, optional) it is embedded in an
``<iframe srcdoc>`` in addition - pyvis itself is never required here.
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

from core.models import Association, ConfidenceLabel, Investigation, utcnow
from reports.markdown_report import (
    ADDRESS_NOTE,
    ALT_NUMBER_NOTE,
    ESTIMATE_NOTE,
    FACT_LABEL,
    INFERENCE_LABEL,
    QUALITY_LEGEND,
    build_ascii_tree,
    entity_label,
    finding_label,
    fmt_dt,
    pct,
    profile_label,
    source_quality_counts,
)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
TEMPLATE_NAME = "report.html.j2"
MAX_SVG_NODES = 150

BADGE_CLASS: dict[str, str] = {
    ConfidenceLabel.FACT.value: "badge-fact",
    ConfidenceLabel.STRONG_MATCH.value: "badge-strong",
    ConfidenceLabel.POSSIBLE_MATCH.value: "badge-possible",
    ConfidenceLabel.WEAK_ASSOCIATION.value: "badge-weak",
    ConfidenceLabel.UNVERIFIED.value: "badge-unverified",
    ConfidenceLabel.CONTRADICTORY.value: "badge-contradictory",
}

NODE_FILL: dict[str, str] = {
    "phone": "#1f5f8b", "entity": "#7a3e9d", "name": "#2e7d32", "email": "#00838f", "username": "#5d4037",
    "business": "#ef6c00", "location": "#558b2f", "address": "#558b2f", "profile": "#3949ab", "document": "#6d4c41",
    "website": "#00695c", "other": "#616161",
}


# --------------------------------------------------------------------------- #
# Graph layout
# --------------------------------------------------------------------------- #


@dataclass
class _Node:
    id: str
    label: str
    kind: str
    percent: int | None = None
    x: float = 0.0
    y: float = 0.0
    layer: int = 0


@dataclass
class _Edge:
    source: str
    target: str
    relation: str
    association: str
    confidence: float = 0.5


@dataclass
class GraphLayout:
    nodes: list[_Node] = field(default_factory=list)
    edges: list[_Edge] = field(default_factory=list)
    width: int = 900
    height: int = 300


def _graph_elements(inv: Investigation) -> tuple[list[_Node], list[_Edge]]:
    """Nodes/edges from ``inv.graph`` (node-link) or, failing that, from relationships."""
    nodes: dict[str, _Node] = {}
    edges: list[_Edge] = []
    g = inv.graph if isinstance(inv.graph, dict) else {}
    raw_nodes = g.get("nodes") or []
    raw_edges = g.get("edges") or g.get("links") or []
    if raw_nodes and raw_edges:
        for n in raw_nodes:
            nid = str(n.get("id", ""))
            if not nid:
                continue
            kind = str(n.get("kind") or nid.partition(":")[0] if ":" in nid else n.get("kind") or "other")
            if nid.startswith("ent_"):
                kind = "entity"
            nodes[nid] = _Node(id=nid, label=str(n.get("label") or nid), kind=kind or "other",
                               percent=n.get("percent"))
        for e in raw_edges:
            src, dst = str(e.get("source", "")), str(e.get("target", ""))
            if src in nodes and dst in nodes:
                edges.append(_Edge(src, dst, str(e.get("relation", "")), str(e.get("association", "inferred")),
                                   float(e.get("confidence", 0.5) or 0.5)))
    else:
        phone_node = f"phone:{inv.phone.e164}"
        nodes[phone_node] = _Node(id=phone_node, label=inv.phone.e164, kind="phone")
        for ent in inv.entities:
            nodes[ent.entity_id] = _Node(id=ent.entity_id, label=ent.label or ent.entity_id, kind="entity",
                                         percent=ent.score.percent)
        for r in inv.relationships:
            for nid in (r.from_id, r.to_id):
                if nid not in nodes:
                    kind, _, rest = nid.partition(":")
                    nodes[nid] = _Node(id=nid, label=rest or nid, kind=kind if rest else "other")
            edges.append(_Edge(r.from_id, r.to_id, r.relation, r.association.value, r.confidence))
    # entity nodes get their percent from the model when missing
    for ent in inv.entities:
        if ent.entity_id in nodes and nodes[ent.entity_id].percent is None:
            nodes[ent.entity_id].percent = ent.score.percent
    return list(nodes.values()), edges


def layout_graph(inv: Investigation) -> GraphLayout | None:
    """Layered layout: BFS from the phone node assigns layers; nodes are spread vertically per layer."""
    nodes, edges = _graph_elements(inv)
    if not nodes or len(nodes) > MAX_SVG_NODES:
        return None
    by_id = {n.id: n for n in nodes}
    adjacency: dict[str, list[str]] = {}
    for e in edges:
        adjacency.setdefault(e.source, []).append(e.target)
        adjacency.setdefault(e.target, []).append(e.source)
    root = f"phone:{inv.phone.e164}"
    if root not in by_id:
        root = next((n.id for n in nodes if n.kind == "phone"), nodes[0].id)
    layer_of: dict[str, int] = {root: 0}
    queue: deque[str] = deque([root])
    while queue:
        cur = queue.popleft()
        for nxt in adjacency.get(cur, []):
            if nxt not in layer_of:
                layer_of[nxt] = layer_of[cur] + 1
                queue.append(nxt)
    max_layer = max(layer_of.values(), default=0)
    for n in nodes:  # disconnected nodes go to the last column
        n.layer = layer_of.get(n.id, max_layer + 1)
    max_layer = max(n.layer for n in nodes)

    col_w, row_h, node_w, margin = 280, 58, 210, 30
    per_layer: dict[int, list[_Node]] = {}
    for n in sorted(nodes, key=lambda n: (n.layer, -(n.percent or 0), n.label.lower())):
        per_layer.setdefault(n.layer, []).append(n)
    tallest = max(len(v) for v in per_layer.values())
    height = margin * 2 + tallest * row_h
    for layer, col in per_layer.items():
        block = len(col) * row_h
        top = (height - block) / 2
        for i, n in enumerate(col):
            n.x = margin + layer * col_w
            n.y = top + i * row_h + row_h / 2
    width = margin * 2 + max_layer * col_w + node_w
    return GraphLayout(nodes=nodes, edges=edges, width=int(width), height=int(height))


def render_graph_svg(inv: Investigation) -> Markup | None:
    """Inline SVG of the evidence graph (already escaped; safe to mark)."""
    lay = layout_graph(inv)
    if lay is None:
        return None
    node_w, node_h = 210, 40
    by_id = {n.id: n for n in lay.nodes}
    out: list[str] = [
        f'<svg class="evidence-graph" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {lay.width} {lay.height}" '
        f'width="{lay.width}" height="{lay.height}" role="img" aria-label="Evidence graph">',
        "<defs><marker id='arrow' viewBox='0 0 10 10' refX='10' refY='5' markerWidth='7' markerHeight='7' "
        "orient='auto-start-reverse'><path d='M0,0 L10,5 L0,10 z' fill='#777'/></marker></defs>",
    ]
    dash = {"direct": "", "indirect": "6,4", "inferred": "2,4"}
    for e in lay.edges:
        a, b = by_id[e.source], by_id[e.target]
        x1, y1 = a.x + node_w, a.y
        x2, y2 = b.x, b.y
        if b.layer <= a.layer:  # backward/same-layer edge: draw from the right edge back
            x1, x2 = a.x + node_w / 2, b.x + node_w / 2
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2 - 4
        out.append(
            f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" stroke="#888" stroke-width="1.4" '
            f'stroke-dasharray="{dash.get(e.association, "2,4")}" marker-end="url(#arrow)">'
            f"<title>{escape(e.relation)} ({escape(e.association)}, {pct(e.confidence)})</title></line>"
        )
        out.append(f'<text x="{mx:.0f}" y="{my:.0f}" class="edge-label" text-anchor="middle">'
                   f"{escape(e.relation.lower().replace('_', ' '))}</text>")
    for n in lay.nodes:
        fill = NODE_FILL.get(n.kind, NODE_FILL["other"])
        label = n.label if len(n.label) <= 30 else n.label[:27] + "..."
        sub = f" {n.percent}%" if n.percent is not None else ""
        out.append(
            f'<g class="node node-{escape(n.kind)}"><rect x="{n.x:.0f}" y="{n.y - node_h / 2:.0f}" width="{node_w}" '
            f'height="{node_h}" rx="6" fill="{fill}" opacity="0.92"><title>{escape(n.id)}</title></rect>'
            f'<text x="{n.x + 8:.0f}" y="{n.y - 3:.0f}" class="node-kind">{escape(n.kind.upper())}{escape(sub)}</text>'
            f'<text x="{n.x + 8:.0f}" y="{n.y + 13:.0f}" class="node-label">{escape(label)}</text></g>'
        )
    out.append("</svg>")
    return Markup("".join(out))


# --------------------------------------------------------------------------- #
# Context + render
# --------------------------------------------------------------------------- #


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(default=True, default_for_string=True),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["dt"] = fmt_dt
    env.filters["pct"] = pct
    env.filters["badge"] = lambda label: BADGE_CLASS.get(getattr(label, "value", str(label)), "badge-unverified")
    env.filters["yesno"] = lambda v: "yes" if v else "no"
    return env


def build_context(inv: Investigation) -> dict[str, Any]:
    """Everything the template needs, pre-computed in Python (keeps the template logic-free)."""
    top = inv.entity_by_id(inv.confidence.top_entity_id or "")
    entities = sorted(inv.entities, key=lambda e: -e.score.percent)
    findings_by_entity = {e.entity_id: [f for f in inv.findings if f.entity_id == e.entity_id] for e in entities}
    source_url = {s.source_id: s.url for s in inv.sources}
    pyvis_html = inv.graph.get("pyvis_html") if isinstance(inv.graph, dict) else None
    svg = render_graph_svg(inv)
    graph_edges = _graph_elements(inv)[1] if svg is None else []
    fact_count = sum(1 for f in inv.findings if finding_label(f) == FACT_LABEL)
    return {
        "inv": inv,
        "meta": inv.investigation,
        "phone": inv.phone,
        "summary": inv.summary,
        "confidence": inv.confidence,
        "entities": entities,
        "top_entity": top,
        "top_claim_label": entity_label(top) if top else INFERENCE_LABEL,
        "entity_label": entity_label,
        "finding_label": finding_label,
        "profile_label": profile_label,
        "findings_by_entity": findings_by_entity,
        "source_url": source_url,
        "FACT_LABEL": FACT_LABEL,
        "INFERENCE_LABEL": INFERENCE_LABEL,
        "ADDRESS_NOTE": ADDRESS_NOTE,
        "ALT_NUMBER_NOTE": ALT_NUMBER_NOTE,
        "ESTIMATE_NOTE": ESTIMATE_NOTE,
        "QUALITY_LEGEND": QUALITY_LEGEND,
        "quality_counts": source_quality_counts(inv.sources),
        "field_counts": Counter(f.field.value for f in inv.findings),
        "fact_count": fact_count,
        "inference_count": len(inv.findings) - fact_count,
        "graph_svg": svg,
        "graph_edges": graph_edges,
        "graph_ascii": build_ascii_tree(inv),
        "pyvis_html": pyvis_html if isinstance(pyvis_html, str) and pyvis_html.strip() else None,
        "timeline": sorted(inv.timeline, key=lambda t: (t.date is None, t.date or utcnow())),
        "generated_at": utcnow(),
        "Association": Association,
        "ConfidenceLabel": ConfidenceLabel,
    }


def render_html(inv: Investigation) -> str:
    """Render the self-contained HTML report."""
    template = _env().get_template(TEMPLATE_NAME)
    return template.render(**build_context(inv))


def write_html(inv: Investigation, path: Path | str) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(inv), encoding="utf-8")
    return out


__all__ = ["render_html", "write_html", "render_graph_svg", "layout_graph", "build_context", "MAX_SVG_NODES"]
