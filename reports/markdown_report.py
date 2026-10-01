"""
Markdown report (spec section 30) plus the small set of labelling helpers
shared by every report format.

Section order follows ``docs/ARCHITECTURE.md`` section 7: disclaimer banner
first, then metadata, input number, normalisation, telecom, executive
summary, candidate identities, names, emails, usernames, social profiles,
businesses, addresses/locations, public alternate numbers, documents,
timeline, evidence graph, contradictions, confidence scores, source quality,
full source list, queries used, limitations and timestamp.

Labelling rule (invariant 4): a claim is a **CONFIRMED PUBLIC FACT** only
when its confidence label is ``FACT`` *and* its association is ``DIRECT``.
Everything else is an **ANALYTICAL INFERENCE**.  Findings carry no
``ConfidenceLabel`` of their own, so they are treated as FACT-grade only when
the subject number is literally displayed by an A/B-quality source with a
DIRECT association (the definition of ``ConfidenceLabel.FACT``).
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Iterable, Optional

from core.models import (
    Association,
    ConfidenceLabel,
    Entity,
    Finding,
    Investigation,
    SocialProfile,
    Source,
    SourceQuality,
    utcnow,
)

FACT_LABEL = "CONFIRMED PUBLIC FACT"
INFERENCE_LABEL = "ANALYTICAL INFERENCE"

SECTION_TITLES: list[str] = [
    "Investigation metadata",
    "Input number",
    "Normalisation",
    "Telecom",
    "Executive summary",
    "Candidate identities",
    "Names",
    "Emails",
    "Usernames",
    "Social profiles",
    "Businesses",
    "Addresses & Locations",
    "Public alternate numbers",
    "Documents",
    "Timeline",
    "Evidence graph",
    "Contradictions",
    "Confidence scores",
    "Source quality",
    "Full source list",
    "Search queries used",
    "Limitations",
    "Timestamp",
]

QUALITY_LEGEND: dict[str, str] = {
    "A": "official / public primary source (government registry, company's own site)",
    "B": "reputable secondary source (news, established professional network)",
    "C": "established directory (business directories, maps listings)",
    "D": "user-generated public source (forums, classifieds, social posts)",
    "E": "unknown / unreliable",
}

ADDRESS_NOTE = (
    "Addresses are reported separately with their source dates; no current address is asserted."
)
ALT_NUMBER_NOTE = "Only publicly co-listed numbers are listed; nothing was generated or tested."
ESTIMATE_NOTE = "Percentages are analytical estimates derived from public-source evidence, not factual certainty."


# --------------------------------------------------------------------------- #
# Shared labelling helpers (imported by html/csv reports)
# --------------------------------------------------------------------------- #


def claim_label(label: ConfidenceLabel | None, association: Association | None) -> str:
    """FACT + DIRECT -> CONFIRMED PUBLIC FACT; anything else -> ANALYTICAL INFERENCE."""
    if label == ConfidenceLabel.FACT and association == Association.DIRECT:
        return FACT_LABEL
    return INFERENCE_LABEL


def finding_is_fact(f: Finding) -> bool:
    """A finding is FACT-grade when the number is literally shown by an A/B source with DIRECT association."""
    return (
        f.association == Association.DIRECT
        and f.number_displayed
        and f.source_quality in (SourceQuality.A, SourceQuality.B)
    )


def finding_label(f: Finding) -> str:
    return FACT_LABEL if finding_is_fact(f) else INFERENCE_LABEL


def entity_label(e: Entity) -> str:
    return claim_label(e.score.label, e.association)


def profile_label(p: SocialProfile) -> str:
    """Profiles never carry a ConfidenceLabel; only a DIRECT, number-displaying profile can be FACT-grade."""
    if p.association == Association.DIRECT and p.number_displayed:
        return FACT_LABEL
    return INFERENCE_LABEL


def fmt_dt(value: Optional[datetime], precision: str | None = None) -> str:
    """ISO-ish date rendering honouring the declared precision."""
    if value is None:
        return "-"
    if precision == "year":
        return value.strftime("%Y")
    if precision == "month":
        return value.strftime("%Y-%m")
    if precision == "day":
        return value.strftime("%Y-%m-%d")
    return value.isoformat(timespec="seconds")


def _ids(ids: list[str], limit: int = 6) -> str:
    """Compact finding-id list: first ``limit`` ids plus a count (full ids live in the JSON/CSV exports)."""
    if not ids:
        return "-"
    if len(ids) <= limit:
        return ", ".join(ids)
    return ", ".join(ids[:limit]) + f" … (+{len(ids) - limit} more)"


def pct(value: float) -> str:
    return f"{int(round(value * 100))}%"


# --------------------------------------------------------------------------- #
# ASCII evidence tree
# --------------------------------------------------------------------------- #


def _node_label(inv: Investigation, node_id: str) -> str:
    """Human label for a graph node id (``ent_x`` -> entity label; ``email:x`` -> ``EMAIL x``)."""
    ent = inv.entity_by_id(node_id)
    if ent is not None:
        return f"{ent.kind.value.upper()} {ent.label or node_id} ({ent.score.percent}% {ent.score.label.value})"
    for node in inv.graph.get("nodes", []) if isinstance(inv.graph, dict) else []:
        if node.get("id") == node_id and node.get("label"):
            kind = str(node.get("kind", "")).upper()
            return f"{kind} {node['label']}".strip()
    if ":" in node_id:
        kind, _, rest = node_id.partition(":")
        return f"{kind.upper()} {rest}"
    return node_id


def build_ascii_tree(inv: Investigation, max_depth: int = 4) -> str:
    """
    Render ``PHONE ├── ENTITY ├── NAME ...`` from ``inv.relationships`` (falling
    back to entities' attribute lists when no relationships exist).
    """
    phone_node = f"phone:{inv.phone.e164}"
    children: dict[str, list[tuple[str, str, str]]] = {}
    for r in inv.relationships:
        children.setdefault(r.from_id, []).append((r.to_id, r.relation, r.association.value))

    if not children:
        # fallback: synthesise from entities
        for e in inv.entities:
            children.setdefault(phone_node, []).append((e.entity_id, "CANDIDATE_IDENTITY", e.association.value))
            for name in e.names:
                children.setdefault(e.entity_id, []).append((f"name:{name}", "HAS_NAME", e.association.value))
            for email in e.emails:
                children.setdefault(e.entity_id, []).append((f"email:{email}", "HAS_EMAIL", e.association.value))
            for u in e.usernames:
                children.setdefault(e.entity_id, []).append((f"username:{u}", "HAS_USERNAME", e.association.value))
            for b in e.businesses:
                children.setdefault(e.entity_id, []).append((f"business:{b}", "RUNS_BUSINESS", e.association.value))
            for loc in e.locations:
                children.setdefault(e.entity_id, []).append((f"location:{loc}", "LOCATED_IN", e.association.value))

    lines: list[str] = [f"PHONE {inv.phone.e164}"]
    seen: set[str] = {phone_node}

    def walk(node: str, prefix: str, depth: int) -> None:
        kids = children.get(node, [])
        for i, (child, relation, assoc) in enumerate(kids):
            last = i == len(kids) - 1
            branch = "└── " if last else "├── "
            marker = "" if child not in seen else " (see above)"
            lines.append(f"{prefix}{branch}{_node_label(inv, child)} [{relation}, {assoc}]{marker}")
            if child in seen or depth >= max_depth:
                continue
            seen.add(child)
            walk(child, prefix + ("    " if last else "│   "), depth + 1)

    walk(phone_node, "", 1)
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Markdown helpers
# --------------------------------------------------------------------------- #


def _esc(text: object) -> str:
    """Escape pipe characters and newlines so values sit inside a table cell."""
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def _table(headers: list[str], rows: Iterable[Iterable[object]]) -> str:
    rows = list(rows)
    if not rows:
        return "_None found._\n"
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(" --- " for _ in headers) + "|"]
    for row in rows:
        out.append("| " + " | ".join(_esc(c) for c in row) + " |")
    return "\n".join(out) + "\n"


def _bullets(items: Iterable[object]) -> str:
    items = list(items)
    if not items:
        return "_None found._\n"
    return "\n".join(f"- {_esc(i)}" for i in items) + "\n"


def _h(title: str, level: int = 2) -> str:
    return f"\n{'#' * level} {title}\n\n"


def _source_ref(inv: Investigation, source_id: str) -> str:
    src = inv.source_by_id(source_id)
    return src.url if src else source_id


# --------------------------------------------------------------------------- #
# Renderer
# --------------------------------------------------------------------------- #


def render_markdown(inv: Investigation) -> str:
    """Render the full Markdown report."""
    meta = inv.investigation
    p = inv.phone
    parts: list[str] = []

    # 0. disclaimer banner FIRST -------------------------------------------- #
    parts.append(f"> **DISCLAIMER:** {meta.disclaimer}\n")
    parts.append(f"\n# Public-source research report for {p.e164}\n\n")
    parts.append(
        "**Legend.** Every claim in this report is labelled either "
        f"**{FACT_LABEL}** (the subject number is literally displayed by an A/B-quality public source "
        "with a DIRECT association, or an entity carries the FACT label with a DIRECT association) or "
        f"**{INFERENCE_LABEL}** (everything else: INDIRECT/INFERRED associations, STRONG/POSSIBLE/WEAK matches, "
        "unverified or contradictory evidence). Association strength is one of DIRECT (number shown on the "
        "page), INDIRECT (number on a page connected to the entity) or INFERRED (correlation only).\n"
    )

    # 1. metadata ------------------------------------------------------------ #
    parts.append(_h("Investigation metadata"))
    parts.append(_table(
        ["Field", "Value"],
        [
            ("Investigation id", meta.investigation_id),
            ("Engine version", meta.engine_version),
            ("Started", fmt_dt(meta.started_at)),
            ("Finished", fmt_dt(meta.finished_at)),
            ("Depth", meta.depth.value),
            ("Case reference", meta.case_reference or "-"),
            ("Authorization note", meta.authorization_note or "-"),
        ],
    ))
    parts.append("\n**Providers**\n\n")
    parts.append(_table(
        ["Provider", "Category", "State", "Paid", "Reason"],
        [(pi.name, pi.category, pi.state.value, "yes" if pi.paid else "no", pi.reason or "-") for pi in meta.providers],
    ))
    if meta.stages:
        parts.append("\n**Stages**\n\n")
        parts.append(_table(
            ["Stage", "Status", "Counts", "Message"],
            [(s.stage.value, s.status.value, ", ".join(f"{k}={v}" for k, v in s.counts.items()) or "-",
              s.message or "-") for s in meta.stages],
        ))

    # 2. input number -------------------------------------------------------- #
    parts.append(_h("Input number"))
    parts.append(f"- Raw input: `{_esc(p.raw)}`\n- Subject (E.164): **{p.e164}**\n- Masked: `{p.masked}`\n")

    # 3. normalisation ------------------------------------------------------- #
    parts.append(_h("Normalisation"))
    parts.append(_table(
        ["Field", "Value"],
        [
            ("Raw", p.raw), ("E.164", p.e164), ("National", p.national), ("International", p.international),
            ("Subscriber", p.subscriber), ("Kind", p.kind.value),
            ("Valid", "yes" if p.is_valid else "no"), ("Possible", "yes" if p.is_possible else "no"),
            ("Indian", "yes" if p.is_indian else "no"),
            ("MNP note", " ".join(p.notes) if p.notes else
             "Mobile Number Portability: prefix indicates original allocation only."),
            ("Warnings", "; ".join(p.warnings) or "-"),
        ],
    ))
    parts.append("\n**Search variants**\n\n" + _bullets(p.variants))

    # 4. telecom ------------------------------------------------------------- #
    parts.append(_h("Telecom"))
    parts.append(
        f"_{INFERENCE_LABEL}: numbering-plan data describes original allocation, not the current subscriber._\n\n"
    )
    parts.append(_table(
        ["Provider", "Field", "Value", "Confidence", "Note"],
        [(t.provider, t.field, t.value, pct(t.confidence), t.note or "-") for t in inv.telecom],
    ))

    # 5. executive summary --------------------------------------------------- #
    s = inv.summary
    parts.append(_h("Executive summary"))
    top = inv.entity_by_id(inv.confidence.top_entity_id or "")
    top_label = entity_label(top) if top else INFERENCE_LABEL
    parts.append("```\n")
    parts.append(f"Candidate Identity        : {s.candidate_identity or '-'} ({s.candidate_kind.value}) [{top_label}]\n")
    parts.append(f"Confidence                : {s.confidence_percent}% {s.confidence_label.value} (analytical estimate)\n")
    parts.append(f"Possible Location         : {s.possible_location or '-'}\n")
    parts.append(f"Public Businesses         : {s.public_businesses}\n")
    parts.append(f"Public Emails             : {s.public_emails}\n")
    parts.append(f"Public Usernames          : {s.public_usernames}\n")
    parts.append(f"Public Profiles           : {s.public_profiles}\n")
    parts.append(f"Public Documents          : {s.public_documents}\n")
    parts.append(f"Associated Public Numbers : {s.associated_public_numbers}\n")
    parts.append(f"Candidates / Contradictions: {s.candidate_count} / {s.contradiction_count}\n")
    parts.append(f"Sources / Queries         : {s.sources_consulted} / {s.queries_executed}\n")
    parts.append("```\n")
    if s.headline:
        parts.append(f"\n{s.headline}\n")

    # 6. candidate identities ----------------------------------------------- #
    parts.append(_h("Candidate identities"))
    if not inv.entities:
        parts.append("_No candidate identity could be resolved from public sources._\n")
    for e in sorted(inv.entities, key=lambda x: -x.score.percent):
        parts.append(_h(f"{e.label or e.entity_id} ({e.kind.value})", 3))
        parts.append(
            f"**{entity_label(e)}** | Confidence: `{e.score.label.value}` **{e.score.percent}%** "
            f"(analytical estimate) | Association: `{e.association.value}` | "
            f"Independent sources: {e.independent_source_count} | "
            f"First/last seen: {fmt_dt(e.first_seen, 'day')} / {fmt_dt(e.last_seen, 'day')}\n\n"
        )
        parts.append("**WHY LINKED**\n\n" + _bullets(e.why_linked))
        parts.append("\n**Score ledger**\n\n")
        parts.append(_table(
            ["Rule", "Points", "Reason", "Findings"],
            [(c.rule, f"{c.points:+d}", c.reason, _ids(c.finding_ids)) for c in e.score.components]
            + [("**Total**", f"{e.score.total_points:+d}", f"{e.score.percent}% - {e.score.note}", "")],
        ))
        parts.append("\n")
        for title, values in (
            ("Names", e.names), ("Emails", e.emails), ("Usernames", e.usernames), ("Businesses", e.businesses),
            ("Websites", e.websites), ("Job titles", e.job_titles), ("Locations", e.locations),
            ("Addresses (with source dates below)", e.addresses),
            ("Associated public numbers", e.associated_numbers),
        ):
            if values:
                parts.append(f"- **{title}:** {', '.join(_esc(v) for v in values)}\n")
        parts.append("- **Sources:** " + ", ".join(_source_ref(inv, sid) for sid in e.source_ids) + "\n")
        ent_findings = [f for f in inv.findings if f.entity_id == e.entity_id]
        if ent_findings:
            parts.append("\n**Findings**\n\n")
            parts.append(_table(
                ["Label", "Field", "Value", "Association", "Number shown", "Quality", "Published", "Evidence", "Source"],
                [(finding_label(f), f.field.value, f.value, f.association.value,
                  "yes" if f.number_displayed else "no", f.source_quality.value,
                  fmt_dt(f.published_at, f.date_precision.value), f.evidence_text, f.source_url)
                 for f in ent_findings],
            ))

    # 7-9. names / emails / usernames ---------------------------------------- #
    def _by_field(field: str) -> list[tuple[object, ...]]:
        rows = []
        for f in inv.findings:
            if f.field.value == field:
                rows.append((finding_label(f), f.value, f.association.value, f.source_quality.value,
                             fmt_dt(f.published_at, f.date_precision.value), f.source_url))
        return rows

    parts.append(_h("Names"))
    parts.append(_bullets(inv.names))
    parts.append("\n" + _table(["Label", "Name", "Association", "Quality", "Published", "Source"], _by_field("name")))
    parts.append(_h("Emails"))
    parts.append(_bullets(inv.emails))
    parts.append("\n" + _table(["Label", "Email", "Association", "Quality", "Published", "Source"], _by_field("email")))
    parts.append(_h("Usernames"))
    parts.append(_bullets(inv.usernames))
    parts.append("\n" + _table(["Label", "Username", "Association", "Quality", "Published", "Source"],
                               _by_field("username")))

    # 10. social profiles ---------------------------------------------------- #
    parts.append(_h("Social profiles"))
    parts.append(_table(
        ["Label", "Platform", "Username", "Display name", "Profile URL", "Source URL", "Number displayed?",
         "Association", "Confidence", "Matching text"],
        [(profile_label(sp), sp.platform, sp.username, sp.display_name, sp.profile_url, sp.source_url,
          "yes" if sp.number_displayed else "no", sp.association.value, pct(sp.confidence), sp.matching_text)
         for sp in inv.social_profiles],
    ))

    # 11. businesses --------------------------------------------------------- #
    parts.append(_h("Businesses"))
    parts.append(_table(
        ["Name", "Owner (if publicly stated)", "Category", "Address", "City", "Website", "Email",
         "Co-listed numbers", "Sources"],
        [(b.name, b.owner or "-", b.category or "-", b.address or "-", b.city or "-", b.website or "-",
          b.email or "-", ", ".join(b.other_numbers) or "-",
          ", ".join(_source_ref(inv, sid) for sid in b.source_ids) or "-") for b in inv.businesses],
    ))
    if inv.listings:
        parts.append("\n**Classified / marketplace listings**\n\n")
        parts.append(_table(
            ["Title", "Seller name", "Category", "Location", "Published", "URL"],
            [(lst.title, lst.seller_name or "-", lst.category or "-", lst.location or "-",
              fmt_dt(lst.published_at, "day"), lst.url) for lst in inv.listings],
        ))

    # 12. addresses & locations ---------------------------------------------- #
    parts.append(_h("Addresses & Locations"))
    parts.append(f"_{ADDRESS_NOTE}_\n\n")
    parts.append(_table(
        ["Address", "City", "State", "PIN", "Classification", "Why", "Source date", "Source", "Entity"],
        [(a.raw, a.city or "-", a.state or "-", a.pincode or "-", a.classification.value,
          a.classification_reason or "-", fmt_dt(a.published_at, a.date_precision.value),
          _source_ref(inv, a.source_id), a.entity_id or "-") for a in inv.addresses],
    ))
    parts.append("\n**Locations (city / state level)**\n\n")
    parts.append(_table(
        ["Location", "City", "State", "Country", "Sources", "Entity"],
        [(loc.label or f"{loc.city}, {loc.state}", loc.city, loc.state, loc.country, loc.source_count,
          loc.entity_id or "-") for loc in inv.locations],
    ))

    # 13. public alternate numbers ------------------------------------------- #
    parts.append(_h("Public alternate numbers"))
    parts.append(f"_{ALT_NUMBER_NOTE}_\n\n")
    parts.append(_table(
        ["Masked", "E.164", "Relation", "Reason", "Source URL", "Confidence", "Discovered", "Published", "Entity"],
        [(n.masked, n.e164, n.relation, n.reason, n.source_url or _source_ref(inv, n.source_id),
          pct(n.confidence), fmt_dt(n.discovered_at, "day"), fmt_dt(n.published_at, "day"), n.entity_id or "-")
         for n in inv.associated_numbers],
    ))

    # 14. documents ---------------------------------------------------------- #
    parts.append(_h("Documents"))
    parts.append(_table(
        ["Title", "Type", "Organisation", "Author", "Published", "Phones", "Emails", "Names", "Fetched", "URL"],
        [(d.title or "-", d.doc_type or "-", d.organization or "-", d.author or "-",
          fmt_dt(d.published_at, d.date_precision.value), ", ".join(d.phones) or "-", ", ".join(d.emails) or "-",
          ", ".join(d.names) or "-", "yes" if d.fetched else "no", d.url) for d in inv.documents],
    ))

    # 15. timeline ----------------------------------------------------------- #
    parts.append(_h("Timeline"))
    parts.append(_table(
        ["Date", "Precision", "Description", "Kind", "Source"],
        [(fmt_dt(t.date, t.precision.value), t.precision.value, t.description, t.kind,
          t.source_url or _source_ref(inv, t.source_id))
         for t in sorted(inv.timeline, key=lambda t: (t.date is None, t.date or utcnow()))],
    ))

    # 16. evidence graph ----------------------------------------------------- #
    parts.append(_h("Evidence graph"))
    parts.append("```\n" + build_ascii_tree(inv) + "\n```\n")

    # 17. contradictions ----------------------------------------------------- #
    parts.append(_h("Contradictions"))
    parts.append(_table(
        ["Kind", "Severity", "Description", "Entities", "Findings", "Resolution hint"],
        [(c.kind.value, c.severity, c.description, ", ".join(c.entity_ids) or "-",
          _ids(c.finding_ids), c.resolution_hint or "-") for c in inv.contradictions],
    ))

    # 18. confidence scores -------------------------------------------------- #
    conf = inv.confidence
    parts.append(_h("Confidence scores"))
    parts.append(f"_{ESTIMATE_NOTE}_ {conf.note}\n\n")
    parts.append("**Rules**\n\n")
    parts.append(_table(["Rule", "Points"], [(k, f"{v:+d}") for k, v in conf.rules.items()]))
    parts.append("\n**Per entity**\n\n")
    parts.append(_table(
        ["Entity", "Percent", "Label", "Claim label"],
        [(f"{(inv.entity_by_id(eid).label if inv.entity_by_id(eid) else eid)} ({eid})", f"{v}%",
          inv.entity_by_id(eid).score.label.value if inv.entity_by_id(eid) else "-",
          entity_label(inv.entity_by_id(eid)) if inv.entity_by_id(eid) else INFERENCE_LABEL)
         for eid, v in conf.per_entity.items()],
    ))

    # 19. source quality ----------------------------------------------------- #
    parts.append(_h("Source quality"))
    counts = Counter(src.quality.value for src in inv.sources)
    parts.append(_table(
        ["Grade", "Meaning", "Sources"],
        [(g, meaning, counts.get(g, 0)) for g, meaning in QUALITY_LEGEND.items()],
    ))

    # 20. full source list --------------------------------------------------- #
    parts.append(_h("Full source list"))
    for i, src in enumerate(inv.sources, 1):
        parts.append(
            f"{i}. **{_esc(src.title) or '(untitled)'}** - <{src.url}>  \n"
            f"   type: `{src.source_type.value}` | quality: **{src.quality.value}** | provider: {src.provider or '-'} | "
            f"retrieved: {fmt_dt(src.retrieved_at)} | published: {fmt_dt(src.published_at, src.date_precision.value)} | "
            f"referenced by: {len(src.referenced_by)} | fetched: {'yes' if src.fetched else 'no (provider snippet)'}\n"
        )
    if not inv.sources:
        parts.append("_None._\n")

    # 21. queries ------------------------------------------------------------ #
    parts.append(_h("Search queries used"))
    parts.append(_table(
        ["Provider", "Query", "Stage", "Purpose", "Results", "New", "Information gain", "Cached", "Error"],
        [(q.provider, f"`{_esc(q.query)}`", q.stage.value, q.purpose or "-", q.results_count, q.new_results_count,
          f"{q.information_gain:.2f}", "yes" if q.cached else "no", q.error or "-") for q in inv.queries],
    ))

    # 22. limitations -------------------------------------------------------- #
    parts.append(_h("Limitations"))
    parts.append(_bullets(inv.limitations))

    # 23. timestamp ---------------------------------------------------------- #
    parts.append(_h("Timestamp"))
    parts.append(
        f"Report generated {fmt_dt(utcnow())} by engine {meta.engine_version} "
        f"for investigation `{meta.investigation_id}` (finished {fmt_dt(meta.finished_at)}).\n\n"
        f"> {meta.disclaimer}\n"
    )

    return "".join(parts)


def source_quality_counts(sources: Iterable[Source]) -> dict[str, int]:
    """Count sources per quality grade (A-E), all grades present."""
    c = Counter(s.quality.value for s in sources)
    return {g: c.get(g, 0) for g in QUALITY_LEGEND}


__all__ = [
    "FACT_LABEL", "INFERENCE_LABEL", "SECTION_TITLES", "QUALITY_LEGEND", "ADDRESS_NOTE", "ALT_NUMBER_NOTE",
    "ESTIMATE_NOTE", "claim_label", "finding_is_fact", "finding_label", "entity_label", "profile_label",
    "fmt_dt", "pct", "build_ascii_tree", "render_markdown", "source_quality_counts",
]
