"""
Optional PDF export via WeasyPrint.

WeasyPrint is an optional extra (``pip install .[pdf]``) with heavy native
dependencies, so it is imported lazily and every failure - missing module
or a rendering error - is logged and turned into ``None`` rather than raised.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.logging import get_logger

log = get_logger(__name__)


def weasyprint_available() -> bool:
    """True when ``weasyprint`` can be imported."""
    try:
        import weasyprint  # noqa: F401
    except Exception:  # ImportError or OSError from missing native libs
        return False
    return True


def write_pdf(html: str, path: Path | str) -> Optional[Path]:
    """
    Render ``html`` (a self-contained document string) to ``path``.

    Returns the written path, or ``None`` when WeasyPrint is not importable
    or rendering fails.
    """
    out = Path(path)
    try:
        from weasyprint import HTML  # type: ignore[import-not-found]
    except ImportError:
        log.info("weasyprint not installed; skipping PDF export", path=str(out))
        return None
    except Exception as exc:  # e.g. OSError: missing pango/cairo
        log.warning("weasyprint import failed; skipping PDF export", error=str(exc))
        return None
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        HTML(string=html, base_url=str(out.parent)).write_pdf(str(out))
    except Exception as exc:
        log.warning("PDF rendering failed", path=str(out), error=str(exc))
        return None
    return out


__all__ = ["write_pdf", "weasyprint_available"]
