#!/usr/bin/env python3
"""
Indian Phone Number OSINT Research Engine - command line interface.

Examples
--------
    python main.py investigate --phone "+919876543210"
    python main.py investigate --phone "+919876543210" --deep --output reports/
    python main.py investigate --phone "+919876543210" --providers brave,serpapi --no-social --json
    python main.py investigate --phone "+919876543210" --offline          # synthetic demo, no network
    python main.py normalize "(98)76543210"
    python main.py providers
    python main.py plan --phone "+919876543210" --deep                    # show queries without running them
    python main.py history
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from config.settings import get_settings
from core.logging import configure_logging
from core.models import DISCLAIMER, Depth, InvestigationConfig, ProgressEvent, StageStatus, mask_phone
from core.normalize import normalize_indian_number

app = typer.Typer(add_completion=False, help="Lawful public-source OSINT research for Indian phone numbers.",
                  no_args_is_help=True)
console = Console()

_STATUS_ICON = {
    StageStatus.PENDING: "·", StageStatus.RUNNING: "…", StageStatus.DONE: "✓",
    StageStatus.SKIPPED: "–", StageStatus.FAILED: "✗",
}


def _progress(event: ProgressEvent) -> None:
    icon = _STATUS_ICON.get(event.status, "·")
    if event.status == StageStatus.RUNNING:
        return
    counts = " ".join(f"{k}={v}" for k, v in event.counts.items())
    console.print(f"  {icon} [bold]{event.stage.value:16}[/bold] {event.message} [dim]{counts}[/dim]")


@app.command()
def investigate(
    phone: str = typer.Option(..., "--phone", "-p", help="Indian phone number in any common format"),
    output: str = typer.Option("output", "--output", "-o", help="Output directory (a sub-folder per investigation)"),
    depth: str = typer.Option("standard", "--depth", help="quick | standard | deep"),
    deep: bool = typer.Option(False, "--deep", help="Shortcut for --depth deep"),
    quick: bool = typer.Option(False, "--quick", help="Shortcut for --depth quick"),
    max_depth: Optional[int] = typer.Option(None, "--max-depth", help="Lead-expansion recursion depth"),
    max_queries: Optional[int] = typer.Option(None, "--max-queries", help="Global search-query budget"),
    providers: Optional[str] = typer.Option(None, "--providers", help="Comma-separated provider names to use"),
    json_only: bool = typer.Option(False, "--json", help="Write only the JSON report"),
    csv: bool = typer.Option(False, "--csv", help="Also write CSV exports (default on unless --json)"),
    pdf: bool = typer.Option(False, "--pdf", help="Also write a PDF (requires weasyprint)"),
    no_social: bool = typer.Option(False, "--no-social"),
    no_documents: bool = typer.Option(False, "--no-documents"),
    no_business: bool = typer.Option(False, "--no-business"),
    no_registries: bool = typer.Option(False, "--no-registries"),
    no_classifieds: bool = typer.Option(False, "--no-classifieds"),
    no_fetch: bool = typer.Option(False, "--no-fetch", help="Do not fetch pages; rely on search snippets only"),
    username_enum: bool = typer.Option(False, "--username-enum", help="Enable public-profile username checks"),
    cities: Optional[str] = typer.Option(None, "--cities", help="Comma-separated city hints for India-oriented queries"),
    offline: bool = typer.Option(False, "--offline", help="Use the synthetic fixture only (demo / tests, no network)"),
    fixture: Optional[str] = typer.Option(None, "--fixture", help="Custom fixture JSON for --offline"),
    case_ref: str = typer.Option("", "--case", help="Case reference stored in the report metadata"),
    authorization: str = typer.Option("", "--authorization", help="Who authorised this investigation and why"),
    no_persist: bool = typer.Option(False, "--no-persist", help="Do not write the SQLite evidence store / snapshots"),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Run a full investigation and write reports."""
    configure_logging(log_level)
    d = Depth.DEEP if deep else Depth.QUICK if quick else Depth(depth.lower())
    formats = ["json"] if json_only else ["json", "markdown", "html", "csv"]
    if csv and "csv" not in formats:
        formats.append("csv")
    if pdf:
        formats.append("pdf")
    overrides: dict = dict(
        enable_social=not no_social, enable_documents=not no_documents, enable_business=not no_business,
        enable_registries=not no_registries, enable_classifieds=not no_classifieds, enable_page_fetch=not no_fetch,
        output_dir=output, formats=formats, offline=offline, fixture_path=fixture, case_reference=case_ref,
        authorization_note=authorization, cities=[c.strip() for c in cities.split(",")] if cities else [],
    )
    if username_enum:
        overrides["enable_username_enum"] = True
    if max_depth is not None:
        overrides["max_depth"] = max_depth
    if max_queries is not None:
        overrides["max_queries"] = max_queries
    if providers:
        overrides["providers"] = [p.strip() for p in providers.split(",") if p.strip()]
    config = InvestigationConfig.for_depth(phone, d, **overrides)

    console.print(Panel.fit(f"[bold]SAAKSHYA · Indian Phone OSINT Research Engine[/bold]\n{mask_phone(phone)} · depth={d.value}"
                            + (" · OFFLINE FIXTURE" if offline else ""), border_style="cyan"))
    from core.engine import InvestigationEngine

    engine = InvestigationEngine(get_settings(), progress=_progress, persist=not no_persist)
    inv = engine.run_sync(config)
    _print_summary(inv, engine.last_paths)


def _print_summary(inv, paths: dict) -> None:  # type: ignore[no-untyped-def]
    console.print()
    console.print(Panel(DISCLAIMER, title="Notice", border_style="yellow"))
    if not inv.phone.ok:
        console.print("[red]Invalid or non-Indian number:[/red] " + "; ".join(inv.phone.warnings))
        raise typer.Exit(code=2)
    s = inv.summary
    t = Table(title="Executive summary", box=box.SIMPLE, show_header=False)
    t.add_column("k", style="bold")
    t.add_column("v")
    t.add_row("Candidate identity", s.candidate_identity or "—")
    t.add_row("Confidence", f"{s.confidence_percent}% ({s.confidence_label.value}) — analytical estimate")
    t.add_row("Possible location", s.possible_location or "—")
    t.add_row("Candidates / contradictions", f"{s.candidate_count} / {s.contradiction_count}")
    t.add_row("Public businesses", str(s.public_businesses))
    t.add_row("Public emails / usernames", f"{s.public_emails} / {s.public_usernames}")
    t.add_row("Public profiles / documents", f"{s.public_profiles} / {s.public_documents}")
    t.add_row("Associated public numbers", str(s.associated_public_numbers))
    t.add_row("Sources / queries", f"{s.sources_consulted} / {s.queries_executed}")
    console.print(t)
    if s.headline:
        console.print(f"[dim]{s.headline}[/dim]")
    if inv.entities:
        et = Table(title="Candidate entities", box=box.SIMPLE)
        for col in ("Label", "Kind", "Score", "Label", "Sources", "Why linked"):
            et.add_column(col)
        for e in inv.entities[:6]:
            et.add_row(e.label, e.kind.value, f"{e.score.percent}%", e.score.label.value,
                       str(e.independent_source_count), "; ".join(e.why_linked[:2])[:120])
        console.print(et)
    if inv.contradictions:
        console.print("[yellow]Contradictions:[/yellow]")
        for c in inv.contradictions:
            console.print(f"  • [{c.severity}] {c.kind.value}: {c.description}")
    if paths:
        console.print("\n[green]Reports:[/green]")
        for k, p in paths.items():
            console.print(f"  {k:10} {p}")


@app.command()
def normalize(number: str = typer.Argument(..., help="Number in any format")) -> None:
    """Show how a number is normalised and which search variants are generated."""
    r = normalize_indian_number(number)
    console.print_json(r.model_dump_json(indent=2))


@app.command()
def providers() -> None:
    """List providers and whether they are configured (keys are never shown)."""
    from core.registry import ProviderRegistry

    reg = ProviderRegistry(get_settings())
    t = Table(title="Providers", box=box.SIMPLE)
    for col in ("Category", "Name", "State", "Paid", "Reason / docs"):
        t.add_column(col)
    for i in reg.infos():
        colour = {"available": "green", "missing_key": "yellow", "not_installed": "red"}.get(i.state.value, "white")
        t.add_row(i.category, i.name, f"[{colour}]{i.state.value}[/{colour}]",
                  "PAID OPTIONAL" if i.paid else "free", i.reason or i.docs_url)
    console.print(t)
    import asyncio

    asyncio.run(reg.aclose())


@app.command()
def plan(
    phone: str = typer.Option(..., "--phone", "-p"),
    depth: str = typer.Option("standard", "--depth"),
    deep: bool = typer.Option(False, "--deep"),
    quick: bool = typer.Option(False, "--quick"),
    cities: Optional[str] = typer.Option(None, "--cities"),
) -> None:
    """Dry run: print the staged query plan without executing anything."""
    from core.strategy import QueryPlanner

    d = Depth.DEEP if deep else Depth.QUICK if quick else Depth(depth.lower())
    ph = normalize_indian_number(phone)
    if not ph.ok:
        console.print("[red]" + "; ".join(ph.warnings) + "[/red]")
        raise typer.Exit(code=2)
    cfg = InvestigationConfig.for_depth(phone, d, cities=[c.strip() for c in cities.split(",")] if cities else [])
    plan_ = QueryPlanner(cfg, ph).preview()
    t = Table(title=f"Query plan ({d.value}) — {len(plan_)} queries", box=box.SIMPLE)
    for col in ("#", "Stage", "Branch", "Priority", "Query"):
        t.add_column(col)
    for i, q in enumerate(plan_, 1):
        t.add_row(str(i), q.stage.value, q.branch, f"{q.priority:.2f}", q.query)
    console.print(t)


@app.command()
def history(limit: int = typer.Option(20, "--limit")) -> None:
    """List previous investigations stored in the local evidence store."""
    from storage.evidence_store import EvidenceStore

    settings = get_settings()
    if not settings.evidence_db_path.exists():
        console.print("No investigations stored yet.")
        return
    store = EvidenceStore(settings.evidence_db_path)
    rows = store.list(limit=limit)
    store.close()
    t = Table(title="Investigations", box=box.SIMPLE)
    for col in ("ID", "Phone", "Depth", "Started", "Top candidate", "Score"):
        t.add_column(col)
    for r in rows:
        t.add_row(str(r.get("investigation_id")), str(r.get("phone_masked")), str(r.get("depth")),
                  str(r.get("started_at"))[:19], str(r.get("top_candidate") or "—"), str(r.get("top_percent") or ""))
    console.print(t)


@app.command()
def export(investigation_id: str = typer.Argument(...), output: str = typer.Option("output", "--output", "-o"),
           formats: str = typer.Option("json,markdown,html,csv", "--formats")) -> None:
    """Re-generate reports for a stored investigation."""
    from reports.builder import write_reports
    from storage.evidence_store import EvidenceStore

    store = EvidenceStore(get_settings().evidence_db_path)
    inv = store.load(investigation_id)
    store.close()
    if inv is None:
        console.print("[red]Unknown investigation id[/red]")
        raise typer.Exit(code=1)
    paths = write_reports(inv, Path(output) / investigation_id, [f.strip() for f in formats.split(",")])
    console.print_json(json.dumps({k: str(v) for k, v in paths.items()}))


@app.command()
def ui(port: int = typer.Option(8501, "--port")) -> None:
    """Launch the Streamlit GUI."""
    import subprocess
    import sys

    subprocess.run([sys.executable, "-m", "streamlit", "run", str(Path(__file__).parent / "ui" / "streamlit_app.py"),
                    "--server.port", str(port)], check=False)


if __name__ == "__main__":
    app()
