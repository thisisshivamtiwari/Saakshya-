"""Report generation tests on the synthetic sample investigation."""

import json
from pathlib import Path

from core.models import DISCLAIMER, Investigation
from reports.builder import write_reports
from reports.csv_report import write_csv
from reports.html_report import render_html
from reports.json_report import render_json
from reports.markdown_report import render_markdown
from tests.factories import make_sample_investigation


def test_json_round_trip():
    inv = make_sample_investigation()
    data = json.loads(render_json(inv))
    assert data["schema_version"] == "1.0"
    data.pop("schema_version")
    back = Investigation.model_validate(data)
    assert back.phone.e164 == inv.phone.e164
    assert len(back.findings) == len(inv.findings) and len(back.entities) == len(inv.entities)
    for key in ("investigation", "phone", "telecom", "entities", "names", "emails", "usernames", "social_profiles",
                "businesses", "locations", "documents", "associated_numbers", "timeline", "relationships",
                "contradictions", "sources", "queries", "confidence", "limitations"):
        assert key in data


def test_markdown_sections_and_labels():
    inv = make_sample_investigation()
    md = render_markdown(inv)
    assert md.lstrip().startswith(">") and DISCLAIMER in md[:600]
    for header in ("Executive summary", "Candidate identities", "Social profiles", "Businesses", "Timeline",
                   "Contradictions", "Confidence", "Source", "Limitations", "Documents"):
        assert header.lower() in md.lower(), header
    assert "CONFIRMED PUBLIC FACT" in md and "ANALYTICAL INFERENCE" in md
    an = inv.associated_numbers[0]
    assert an.e164 in md and an.masked in md
    assert "current address" not in md.lower().replace("no current address", "")
    assert "estimate" in md.lower()


def test_html_renders_and_escapes():
    inv = make_sample_investigation()
    html = render_html(inv)
    assert DISCLAIMER in html and "<svg" in html
    inv.sources[0].title = "<script>alert(1)</script>"
    inv.findings[0].evidence_text = "<img src=x onerror=alert(1)>"
    html = render_html(inv)
    assert "<script>alert(1)</script>" not in html and "<img src=x onerror" not in html
    assert "&lt;script&gt;" in html


def test_csv_and_builder(tmp_path: Path):
    inv = make_sample_investigation()
    files = write_csv(inv, tmp_path / "csv")
    for name in ("findings.csv", "sources.csv", "entities.csv", "queries.csv", "timeline.csv"):
        assert name in files and files[name].exists()
    rows = files["findings.csv"].read_text().splitlines()
    assert len(rows) == len(inv.findings) + 1
    paths = write_reports(inv, tmp_path / "out", ["json", "markdown", "html", "csv", "pdf"])
    assert (tmp_path / "out" / "report.json").exists() and (tmp_path / "out" / "report.md").exists()
    assert (tmp_path / "out" / "report.html").exists()
    assert (tmp_path / "out" / "manifest.json").exists()
    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text())
    assert "+919876543210" not in json.dumps(manifest.get("phone", "")) or "masked" in json.dumps(manifest)
    assert all(Path(p).exists() for p in paths.values())
