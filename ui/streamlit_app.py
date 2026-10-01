"""
Streamlit GUI for the Indian Phone OSINT Research Engine.

Run with:  python main.py ui      or      streamlit run ui/streamlit_app.py
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from config.settings import get_settings  # noqa: E402
from core.models import (  # noqa: E402
    DISCLAIMER,
    Association,
    ConfidenceLabel,
    Depth,
    Investigation,
    InvestigationConfig,
    ProgressEvent,
    Stage,
    StageStatus,
    mask_phone,
)
from core.normalize import normalize_indian_number  # noqa: E402

st.set_page_config(page_title="Saakshya · Indian Phone OSINT", page_icon="📞", layout="wide")

STAGE_LABELS = [
    (Stage.NORMALIZE, "Number normalized"), (Stage.TELECOM, "Telecom intelligence"),
    (Stage.SEARCH, "Search engine discovery"), (Stage.DOCUMENTS, "Public documents"),
    (Stage.SOCIAL, "Social discovery"), (Stage.BUSINESS, "Business discovery"),
    (Stage.REGISTRIES, "Public registries"), (Stage.CLASSIFIEDS, "Classifieds / marketplaces"),
    (Stage.PAGE_FETCH, "Page fetch (robots.txt-aware)"), (Stage.LEAD_EXPANSION, "Lead expansion"),
    (Stage.CORRELATION, "Entity resolution"), (Stage.SCORING, "Evidence analysis"), (Stage.REPORT, "Reports"),
]
ICON = {StageStatus.PENDING: "⬜", StageStatus.RUNNING: "⏳", StageStatus.DONE: "✅",
        StageStatus.SKIPPED: "➖", StageStatus.FAILED: "❌"}


def _label_badge(label: ConfidenceLabel) -> str:
    colours = {ConfidenceLabel.FACT: "green", ConfidenceLabel.STRONG_MATCH: "blue",
               ConfidenceLabel.POSSIBLE_MATCH: "orange", ConfidenceLabel.WEAK_ASSOCIATION: "gray",
               ConfidenceLabel.UNVERIFIED: "gray", ConfidenceLabel.CONTRADICTORY: "red"}
    return f":{colours.get(label, 'gray')}[**{label.value}**]"


def _fact_or_inference(label: ConfidenceLabel, association: Association) -> str:
    return "CONFIRMED PUBLIC FACT" if (label == ConfidenceLabel.FACT and association == Association.DIRECT) \
        else "ANALYTICAL INFERENCE"


# --------------------------------------------------------------------------- #
# Sidebar / input
# --------------------------------------------------------------------------- #
st.title("📞 Saakshya · Indian Phone OSINT Research Engine")
st.caption("Lawful public-source research · evidence, provenance, entity resolution, confidence scoring")
st.warning(DISCLAIMER)

with st.sidebar:
    st.header("Investigation")
    phone_in = st.text_input("Phone number", value="", placeholder="+91 98765 43210")
    depth = st.radio("Depth", ["quick", "standard", "deep"], index=1, horizontal=True)
    offline = st.checkbox("Offline demo (synthetic fixture, no network)", value=False)
    st.subheader("Stages")
    en_social = st.checkbox("Social discovery", True)
    en_docs = st.checkbox("Public documents", True)
    en_biz = st.checkbox("Business discovery", True)
    en_reg = st.checkbox("Public registries", True)
    en_cls = st.checkbox("Classifieds", True)
    en_fetch = st.checkbox("Fetch pages (robots.txt-aware)", True)
    en_user = st.checkbox("Username public-profile checks (opt-in)", False)
    cities = st.text_input("City hints (comma-separated)", "")
    case_ref = st.text_input("Case reference", "")
    authorization = st.text_area("Authorization note (who authorised this and why)", "", height=70)
    st.subheader("Providers")
    try:
        from core.registry import ProviderRegistry

        reg = ProviderRegistry(get_settings())
        for info in reg.infos():
            st.write(f"{'🟢' if info.state.value == 'available' else '⚪'} `{info.name}` "
                     f"({info.category}{', PAID' if info.paid else ''}) {info.reason}")
    except Exception as exc:  # pragma: no cover
        st.write(f"provider list unavailable: {exc}")
    start = st.button("START INVESTIGATION", type="primary", use_container_width=True)

if "progress" not in st.session_state:
    st.session_state.progress = {}
if "result" not in st.session_state:
    st.session_state.result = None
if "paths" not in st.session_state:
    st.session_state.paths = {}


def _run(config: InvestigationConfig) -> None:
    from core.engine import InvestigationEngine

    progress: dict = {}

    def cb(e: ProgressEvent) -> None:
        progress[e.stage] = (e.status, e.message)

    engine = InvestigationEngine(get_settings(), progress=cb)
    st.session_state.progress = progress
    inv = engine.run_sync(config)
    st.session_state.result = inv
    st.session_state.paths = engine.last_paths


if start:
    norm = normalize_indian_number(phone_in)
    if not norm.ok:
        st.error("Invalid or non-Indian number: " + "; ".join(norm.warnings))
    else:
        cfg = InvestigationConfig.for_depth(
            phone_in, Depth(depth), enable_social=en_social, enable_documents=en_docs, enable_business=en_biz,
            enable_registries=en_reg, enable_classifieds=en_cls, enable_page_fetch=en_fetch,
            enable_username_enum=en_user, cities=[c.strip() for c in cities.split(",") if c.strip()],
            offline=offline, case_reference=case_ref, authorization_note=authorization,
            formats=["json", "markdown", "html", "csv"],
        )
        st.session_state.result = None
        with st.status(f"Investigating {mask_phone(norm.e164)} …", expanded=True) as status:
            t = threading.Thread(target=_run, args=(cfg,))
            t.start()
            placeholder = st.empty()
            import time

            while t.is_alive():
                lines = []
                for stage, label in STAGE_LABELS:
                    stt, msg = st.session_state.progress.get(stage, (StageStatus.PENDING, ""))
                    lines.append(f"{ICON[stt]} {label} — {msg}")
                placeholder.markdown("\n\n".join(lines))
                time.sleep(0.5)
            t.join()
            lines = []
            for stage, label in STAGE_LABELS:
                stt, msg = st.session_state.progress.get(stage, (StageStatus.PENDING, ""))
                lines.append(f"{ICON[stt]} {label} — {msg}")
            placeholder.markdown("\n\n".join(lines))
            status.update(label="Investigation complete", state="complete")

inv: Investigation | None = st.session_state.result
if inv is None:
    st.info("Enter an Indian phone number you are authorised to investigate and press START INVESTIGATION. "
            "Tick *Offline demo* to try the engine on a fully synthetic scenario without any API keys.")
    st.stop()

# --------------------------------------------------------------------------- #
# Executive summary
# --------------------------------------------------------------------------- #
s = inv.summary
st.header("Executive summary")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Candidate identity", s.candidate_identity or "—")
c2.metric("Confidence (analytical estimate)", f"{s.confidence_percent}%", s.confidence_label.value)
c3.metric("Possible location", s.possible_location or "—")
c4.metric("Candidates / contradictions", f"{s.candidate_count} / {s.contradiction_count}")
c5, c6, c7, c8 = st.columns(4)
c5.metric("Public businesses", s.public_businesses)
c6.metric("Public emails / usernames", f"{s.public_emails} / {s.public_usernames}")
c7.metric("Public profiles / documents", f"{s.public_profiles} / {s.public_documents}")
c8.metric("Associated public numbers", s.associated_public_numbers)
st.write(s.headline)
if st.session_state.paths:
    st.success("Reports written: " + ", ".join(f"`{p}`" for p in st.session_state.paths.values()))

tabs = st.tabs(["Identity", "Businesses", "Social profiles", "Emails & usernames", "Locations", "Documents",
                "Alternate public numbers", "Timeline", "Evidence graph", "Contradictions", "Telecom",
                "Sources", "Queries", "Findings", "Limitations", "JSON"])

with tabs[0]:
    st.subheader("Candidate identities")
    for e in inv.entities:
        with st.expander(f"{e.label or '(unnamed)'} · {e.kind.value} · {e.score.percent}% · {e.score.label.value}",
                         expanded=e is inv.entities[0]):
            st.markdown(f"{_label_badge(e.score.label)} · association: **{e.association.value}** · "
                        f"{_fact_or_inference(e.score.label, e.association)} · independent sources: "
                        f"{e.independent_source_count}")
            st.markdown("**Why linked**")
            for w in e.why_linked:
                st.markdown(f"- {w}")
            st.markdown("**Score ledger** (analytical estimate, not factual certainty)")
            st.table([{"rule": c.rule, "points": c.points, "reason": c.reason} for c in e.score.components])
            cols = st.columns(3)
            cols[0].write({"names": e.names, "emails": e.emails, "usernames": e.usernames})
            cols[1].write({"businesses": e.businesses, "websites": e.websites, "job_titles": e.job_titles})
            cols[2].write({"locations": e.locations, "addresses": e.addresses,
                           "associated_numbers": e.associated_numbers})
    if not inv.entities:
        st.info("No candidate identity could be established from public sources.")

with tabs[1]:
    st.table([{"name": b.name, "owner (if publicly stated)": b.owner, "category": b.category, "address": b.address,
               "city": b.city, "website": b.website, "email": b.email,
               "other public numbers": ", ".join(b.other_numbers), "sources": len(b.source_ids)}
              for b in inv.businesses] or [{"info": "none"}])
    if inv.listings:
        st.subheader("Classified / marketplace listings")
        st.table([{"title": l.title, "seller": l.seller_name, "category": l.category, "location": l.location,
                   "date": str(l.published_at or "")[:10], "url": l.url} for l in inv.listings])

with tabs[2]:
    st.table([{"platform": p.platform, "username": p.username, "display name": p.display_name,
               "profile": p.profile_url, "source": p.source_url, "number displayed": p.number_displayed,
               "association": p.association.value, "confidence": round(p.confidence, 2),
               "matching text": p.matching_text[:160]} for p in inv.social_profiles] or [{"info": "none"}])

with tabs[3]:
    st.write({"emails": inv.emails, "usernames": inv.usernames, "names": inv.names})

with tabs[4]:
    st.caption("Addresses are reported separately with their source dates. No current address is asserted.")
    st.table([{"address": a.raw, "city": a.city, "state": a.state, "pincode": a.pincode,
               "classification": a.classification.value, "source date": str(a.published_at or "unknown")[:10],
               "entity": a.entity_id or ""} for a in inv.addresses] or [{"info": "none"}])
    st.table([{"location": l.label, "sources": l.source_count, "entity": l.entity_id or ""}
              for l in inv.locations] or [{"info": "none"}])

with tabs[5]:
    st.table([{"title": d.title, "type": d.doc_type, "author": d.author, "organization": d.organization,
               "date": str(d.published_at or "")[:10], "fetched": d.fetched, "phones": ", ".join(d.phones),
               "emails": ", ".join(d.emails), "names": ", ".join(d.names), "url": d.url}
              for d in inv.documents] or [{"info": "none"}])

with tabs[6]:
    st.caption("Only numbers publicly co-listed with the same entity/page. Nothing is generated, guessed or tested.")
    st.table([{"number": a.e164, "masked": a.masked, "relation": a.relation, "reason": a.reason,
               "source": a.source_url, "confidence": a.confidence, "discovered": str(a.discovered_at)[:10]}
              for a in inv.associated_numbers] or [{"info": "none"}])

with tabs[7]:
    st.table([{"date": str(t.date)[:10] if t.date else "unknown", "precision": t.precision.value,
               "event": t.description, "source": t.source_url} for t in inv.timeline] or [{"info": "none"}])

with tabs[8]:
    ascii_tree = inv.graph.get("ascii") if isinstance(inv.graph, dict) else None
    if ascii_tree:
        st.code(ascii_tree)
    try:
        from correlation.graph import EvidenceGraph

        g = EvidenceGraph.from_investigation_parts(inv.phone, inv.entities, inv.relationships, inv.findings,
                                                   inv.sources)
        html = g.to_pyvis_html()
        if html:
            import streamlit.components.v1 as components

            components.html(html, height=600, scrolling=True)
        else:
            st.caption("Install pyvis for an interactive graph; showing relationships table.")
            st.table([{"from": r.from_id, "relation": r.relation, "to": r.to_id, "confidence": r.confidence,
                       "association": r.association.value} for r in inv.relationships[:200]])
    except Exception as exc:  # pragma: no cover
        st.write(f"graph unavailable: {exc}")

with tabs[9]:
    for c in inv.contradictions:
        st.error(f"[{c.severity}] {c.kind.value}: {c.description}\n\n_Hint: {c.resolution_hint}_")
    if not inv.contradictions:
        st.success("No contradictions detected among public sources.")

with tabs[10]:
    st.table([{"provider": t.provider, "field": t.field, "value": t.value, "confidence": t.confidence,
               "note": t.note} for t in inv.telecom] or [{"info": "none"}])

with tabs[11]:
    st.table([{"title": sr.title[:80], "url": sr.url, "type": sr.source_type.value, "quality": sr.quality.value,
               "published": str(sr.published_at or "")[:10], "fetched": sr.fetched,
               "referenced by": len(sr.referenced_by), "excerpt": sr.excerpt[:140]} for sr in inv.sources])

with tabs[12]:
    st.table([{"provider": q.provider, "query": q.query, "stage": q.stage.value, "results": q.results_count,
               "new": q.new_results_count, "gain": round(q.information_gain, 2), "cached": q.cached,
               "error": q.error or ""} for q in inv.queries])

with tabs[13]:
    st.table([{"field": f.field.value, "value": f.value, "association": f.association.value,
               "number displayed": f.number_displayed, "confidence": round(f.confidence, 2),
               "quality": f.source_quality.value, "source": f.source_url, "evidence": f.evidence_text[:160]}
              for f in inv.findings])

with tabs[14]:
    for lim in inv.limitations:
        st.markdown(f"- {lim}")

with tabs[15]:
    st.download_button("Download JSON", inv.to_json(), file_name="report.json", mime="application/json")
    st.json(inv.model_dump(mode="json"), expanded=False)
