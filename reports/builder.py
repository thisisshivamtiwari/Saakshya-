"""
Report builder: writes every requested format into an output directory.

``write_reports`` never raises because one format failed - each writer is
isolated, failures are logged, and the caller receives the paths that *did*
get written.  ``write_reports_verbose`` additionally returns the error map.

Layout of ``output_dir``::

    report.json      report.md      report.html      report.pdf (optional)
    csv/findings.csv csv/sources.csv csv/entities.csv csv/queries.csv csv/timeline.csv
    csv/associated_numbers.csv csv/contradictions.csv
    manifest.json    (paths, generated_at, engine_version, masked phone)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from core.logging import get_logger
from core.models import Investigation, mask_phone, utcnow
from reports.csv_report import write_csv
from reports.html_report import render_html
from reports.json_report import write_json
from reports.markdown_report import render_markdown
from reports.pdf_report import weasyprint_available, write_pdf

log = get_logger(__name__)

FORMAT_ALIASES: dict[str, str] = {
    "json": "json", "md": "markdown", "markdown": "markdown", "html": "html", "htm": "html", "csv": "csv",
    "pdf": "pdf",
}
FILE_NAMES: dict[str, str] = {"json": "report.json", "markdown": "report.md", "html": "report.html", "pdf": "report.pdf"}
DEFAULT_FORMATS: list[str] = ["json", "markdown", "html", "csv"]


def _normalise_formats(formats: list[str] | None) -> list[str]:
    wanted: list[str] = []
    for f in formats or DEFAULT_FORMATS:
        key = FORMAT_ALIASES.get(f.lower().strip())
        if key is None:
            log.warning("Unknown report format ignored", format=f)
            continue
        if key not in wanted:
            wanted.append(key)
    return wanted


def write_reports_verbose(
    inv: Investigation, output_dir: Path | str, formats: list[str] | None = None
) -> tuple[dict[str, Path], dict[str, str]]:
    """
    Write the requested formats; return ``(paths, errors)``.

    ``paths`` keys: ``json``, ``markdown``, ``html``, ``pdf`` (only when
    written), one key per CSV file name (``findings.csv`` ...) plus ``csv_dir``,
    and ``manifest``.  ``errors`` maps a format name to the failure message.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    wanted = _normalise_formats(formats)
    paths: dict[str, Path] = {}
    errors: dict[str, str] = {}
    html_text: str | None = None

    def attempt(name: str, fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - isolate per-format failures
            errors[name] = f"{type(exc).__name__}: {exc}"
            log.error("Report format failed", format=name, error=str(exc), exc_info=True)

    if "json" in wanted:
        attempt("json", lambda: paths.__setitem__("json", write_json(inv, out_dir / FILE_NAMES["json"])))

    if "markdown" in wanted:
        def _md() -> None:
            p = out_dir / FILE_NAMES["markdown"]
            p.write_text(render_markdown(inv), encoding="utf-8")
            paths["markdown"] = p
        attempt("markdown", _md)

    if "html" in wanted or "pdf" in wanted:
        def _html() -> None:
            nonlocal html_text
            html_text = render_html(inv)
            if "html" in wanted:
                p = out_dir / FILE_NAMES["html"]
                p.write_text(html_text, encoding="utf-8")
                paths["html"] = p
        attempt("html", _html)

    if "csv" in wanted:
        def _csv() -> None:
            csv_dir = out_dir / "csv"
            written = write_csv(inv, csv_dir)
            paths["csv_dir"] = csv_dir
            paths.update(written)
        attempt("csv", _csv)

    if "pdf" in wanted:
        if html_text is None:
            errors["pdf"] = "HTML rendering failed; PDF skipped"
        elif not weasyprint_available():
            log.warning("PDF requested but weasyprint is not installed; skipping (pip install '.[pdf]')")
        else:
            def _pdf() -> None:
                assert html_text is not None
                p = write_pdf(html_text, out_dir / FILE_NAMES["pdf"])
                if p is None:
                    errors["pdf"] = "weasyprint rendering failed (see log)"
                else:
                    paths["pdf"] = p
            attempt("pdf", _pdf)

    # manifest ------------------------------------------------------------- #
    def _manifest() -> None:
        manifest = {
            "investigation_id": inv.investigation.investigation_id,
            "phone_masked": mask_phone(inv.phone.e164 or inv.phone.raw),
            "engine_version": inv.investigation.engine_version,
            "generated_at": utcnow().isoformat(timespec="seconds"),
            "formats_requested": wanted,
            "paths": {k: str(v.relative_to(out_dir)) if v.is_relative_to(out_dir) else str(v) for k, v in paths.items()},
            "errors": errors,
        }
        p = out_dir / "manifest.json"
        p.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        paths["manifest"] = p
    attempt("manifest", _manifest)

    log.info("Reports written", output_dir=str(out_dir), formats=",".join(wanted), errors=len(errors))
    return paths, errors


def write_reports(inv: Investigation, output_dir: Path | str, formats: list[str] | None = None) -> dict[str, Path]:
    """Write reports and return ``{format or file name: Path}`` (errors are logged, never raised)."""
    paths, _errors = write_reports_verbose(inv, output_dir, formats)
    return paths


__all__ = ["write_reports", "write_reports_verbose", "DEFAULT_FORMATS", "FILE_NAMES"]
