"""
Evidence graph (ARCHITECTURE section 5) - a thin wrapper around ``networkx.MultiDiGraph``.

Nodes carry ``{kind, label, quality?, confidence?}``; edges carry
``{relation, confidence, association, finding_ids, source_ids}``.  Node ids follow the
resolver's ``kind:value`` convention so the JSON export, the ASCII tree used in Markdown
reports and the optional pyvis view all describe the same objects.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

import networkx as nx

from core.models import Entity, FieldType, Finding, NormalizedPhone, Relationship, Source

from correlation._text import address_hash, display_domain, normalise_business, normalise_city, normalise_domain, normalise_email, normalise_name
from correlation.entity_resolver import _platform_and_user, node_id

_FIELD_RELATION: dict[FieldType, tuple[str, str]] = {
    FieldType.NAME: ("name", "HAS_NAME"), FieldType.ALIAS: ("name", "HAS_NAME"),
    FieldType.EMAIL: ("email", "HAS_EMAIL"), FieldType.USERNAME: ("username", "HAS_USERNAME"),
    FieldType.SOCIAL_PROFILE: ("profile", "HAS_PROFILE"), FieldType.BUSINESS: ("business", "RUNS_BUSINESS"),
    FieldType.ORGANIZATION: ("business", "RUNS_BUSINESS"), FieldType.WEBSITE: ("website", "HAS_WEBSITE"),
    FieldType.LOCATION: ("location", "LOCATED_IN"), FieldType.ADDRESS: ("address", "HAS_ADDRESS"),
    FieldType.JOB_TITLE: ("jobtitle", "HAS_JOB_TITLE"), FieldType.PHONE: ("phone", "CO_LISTED_WITH"),
}


def _plain(v: Any) -> Any:
    """Make attribute values JSON-serialisable."""
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    return v


class EvidenceGraph:
    """MultiDiGraph of phone -> entities -> attributes -> source documents."""

    def __init__(self, phone: NormalizedPhone) -> None:
        self.phone = phone
        self.G: nx.MultiDiGraph = nx.MultiDiGraph()
        self.add_phone(phone)

    # ---- nodes ---------------------------------------------------------- #
    def _node(self, nid: str, kind: str, label: str, **attrs: Any) -> str:
        if nid in self.G:
            cur = self.G.nodes[nid]
            if not cur.get("label") and label:
                cur["label"] = label
            for k, v in attrs.items():
                if v is not None and cur.get(k) in (None, ""):
                    cur[k] = _plain(v)
        else:
            self.G.add_node(nid, kind=kind, label=label, **{k: _plain(v) for k, v in attrs.items() if v is not None})
        return nid

    def add_phone(self, phone: NormalizedPhone) -> str:
        return self._node(node_id("phone", phone.e164), "phone", phone.e164)

    def add_entity(self, e: Entity) -> str:
        return self._node(
            node_id("ent", e.entity_id), e.kind.value, e.label,
            confidence=e.score.percent, confidence_label=e.score.label, association=e.association,
        )

    def add_source(self, s: Source) -> str:
        return self._node(node_id("doc", s.source_id), "source", display_domain(s.url) or s.url,
                          quality=s.quality, url=s.url, source_type=s.source_type)

    # ---- edges ---------------------------------------------------------- #
    def _edge(self, u: str, v: str, key: str, **attrs: Any) -> None:
        if self.G.has_edge(u, v, key):
            return
        self.G.add_edge(u, v, key=key, **{k: _plain(x) for k, x in attrs.items()})

    def add_finding(self, f: Finding, source: Source) -> None:
        """Owner (entity or phone) -> value node, and value node -> source document."""
        owner = node_id("ent", f.entity_id) if f.entity_id else node_id("phone", f.phone)
        if owner not in self.G:
            self._node(owner, "entity" if f.entity_id else "phone", f.entity_id or f.phone)
        doc = self.add_source(source)
        spec = _FIELD_RELATION.get(f.field)
        if spec is None:
            self._edge(owner, doc, f"MENTIONED_IN:{f.finding_id}", relation="MENTIONED_IN", confidence=f.confidence,
                       association=f.association, finding_ids=[f.finding_id], source_ids=[f.source_id])
            return
        kind, relation = spec
        value = f.value
        if kind == "name":
            vid = node_id("name", normalise_name(value))
        elif kind == "email":
            vid = node_id("email", normalise_email(f.normalized_value or value))
        elif kind in ("username", "profile"):
            platform, user = _platform_and_user(f, source)
            vid = node_id(kind, platform, user)
        elif kind == "business":
            vid = node_id("business", normalise_business(value))
        elif kind == "website":
            vid = node_id("website", normalise_domain(f.normalized_value or value))
        elif kind == "location":
            vid = node_id("location", normalise_city(str((f.metadata or {}).get("city") or f.normalized_value or value)))
        elif kind == "address":
            vid = node_id("address", address_hash(value))
        elif kind == "phone":
            vid = node_id("phone", value.replace(" ", ""))
        else:
            vid = node_id(kind, normalise_business(value))
        self._node(vid, kind, value, confidence=f.confidence)
        self._edge(owner, vid, f"{relation}:{f.finding_id}", relation=relation, confidence=f.confidence,
                   association=f.association, finding_ids=[f.finding_id], source_ids=[f.source_id])
        self._edge(vid, doc, f"MENTIONED_IN:{f.finding_id}", relation="MENTIONED_IN", confidence=f.confidence,
                   association=f.association, finding_ids=[f.finding_id], source_ids=[f.source_id])

    def add_relationship(self, r: Relationship) -> None:
        for nid in (r.from_id, r.to_id):
            if nid not in self.G:
                kind, _, rest = nid.partition(":")
                self._node(nid, kind, rest)
        self._edge(r.from_id, r.to_id, r.relationship_id, relation=r.relation, confidence=r.confidence,
                   association=r.association, finding_ids=list(r.finding_ids), source_ids=list(r.source_ids))

    # ---- builders ------------------------------------------------------- #
    @classmethod
    def from_investigation_parts(
        cls,
        phone: NormalizedPhone,
        entities: list[Entity],
        relationships: list[Relationship],
        findings: list[Finding],
        sources: list[Source],
    ) -> "EvidenceGraph":
        g = cls(phone)
        src_by_id = {s.source_id: s for s in sources}
        for e in entities:
            g.add_entity(e)
        for r in relationships:
            g.add_relationship(r)
        # enrich document nodes that relationships referenced by id only
        referenced = {r.to_id for r in relationships if r.to_id.startswith("doc:")}
        for sid, s in src_by_id.items():
            if node_id("doc", sid) in referenced:
                g.add_source(s)
        # findings that no entity claimed still hang off the phone node
        for f in findings:
            if not f.entity_id and f.source_id in src_by_id and f.field in _FIELD_RELATION:
                g.add_finding(f, src_by_id[f.source_id])
        return g

    # ---- exports -------------------------------------------------------- #
    def to_node_link(self) -> dict[str, Any]:
        return nx.node_link_data(self.G, edges="edges")

    def stats(self) -> dict[str, Any]:
        kinds: dict[str, int] = {}
        for _, d in self.G.nodes(data=True):
            kinds[d.get("kind", "?")] = kinds.get(d.get("kind", "?"), 0) + 1
        rels: dict[str, int] = {}
        for _, _, d in self.G.edges(data=True):
            rels[d.get("relation", "?")] = rels.get(d.get("relation", "?"), 0) + 1
        return {
            "nodes": self.G.number_of_nodes(),
            "edges": self.G.number_of_edges(),
            "node_kinds": dict(sorted(kinds.items())),
            "relations": dict(sorted(rels.items())),
        }

    def to_ascii_tree(self) -> str:
        """``PHONE`` -> entities -> attributes tree for Markdown reports."""
        phone_node = node_id("phone", self.phone.e164)
        lines = [f"PHONE {self.phone.e164}"]
        ents = sorted(
            (v for _, v in self.G.out_edges(phone_node) if v.startswith("ent:")),
            key=lambda v: (-(self.G.nodes[v].get("confidence") or 0), self.G.nodes[v].get("label", "")),
        )
        for i, ent in enumerate(ents):
            last_ent = i == len(ents) - 1
            d = self.G.nodes[ent]
            conf = d.get("confidence")
            head = f"{d.get('kind', 'entity').upper()} {d.get('label', ent)}"
            if conf is not None:
                head += f" [{d.get('confidence_label', '')} {conf}%]".replace("[ ", "[")
            lines.append(f"{'└── ' if last_ent else '├── '}{head}")
            prefix = "    " if last_ent else "│   "
            children: list[tuple[str, str]] = []
            for _, v, ed in self.G.out_edges(ent, data=True):
                if v.startswith("doc:"):
                    continue
                label = self.G.nodes[v].get("label", v)
                assoc = ed.get("association", "")
                n_src = len(ed.get("source_ids", []) or [])
                children.append((ed.get("relation", ""), f"{ed.get('relation', '')} {label} ({assoc}, {n_src} source{'s' if n_src != 1 else ''})"))
            children.sort()
            docs = sorted(self.G.nodes[v].get("label", v) for _, v in self.G.out_edges(ent) if v.startswith("doc:"))
            if docs:
                children.append(("~", f"MENTIONED_IN {', '.join(docs)}"))
            for j, (_, text) in enumerate(children):
                branch = "└── " if j == len(children) - 1 else "├── "
                lines.append(f"{prefix}{branch}{text}")
        return "\n".join(lines)

    def to_pyvis_html(self) -> Optional[str]:
        """Interactive HTML via pyvis when installed; ``None`` otherwise (never raises)."""
        try:
            from pyvis.network import Network  # type: ignore[import-not-found]
        except Exception:
            return None
        try:
            net = Network(height="700px", width="100%", directed=True, notebook=False, cdn_resources="in_line")
            colors = {"phone": "#d62728", "person": "#1f77b4", "business": "#2ca02c", "organization": "#2ca02c",
                      "unknown": "#7f7f7f", "source": "#bcbd22"}
            for nid, d in self.G.nodes(data=True):
                kind = d.get("kind", "")
                net.add_node(nid, label=d.get("label", nid), title=f"{kind}: {d.get('label', '')}",
                             color=colors.get(kind, "#ff7f0e"), shape="box" if kind == "source" else "dot")
            for u, v, d in self.G.edges(data=True):
                net.add_edge(u, v, title=f"{d.get('relation', '')} ({d.get('association', '')})", label=d.get("relation", ""))
            return net.generate_html()
        except Exception:
            return None


__all__ = ["EvidenceGraph"]
