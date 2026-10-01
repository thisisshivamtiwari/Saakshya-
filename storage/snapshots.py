"""Source snapshots (spec section 34): URL, title, retrieval time, bounded excerpt, content hash - never whole sites."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from core.models import Source


class SnapshotStore:
    def __init__(self, directory: Path | str) -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def save(self, source: Source, excerpt: str, *, max_chars: int = 1200) -> Path:
        payload = {
            "source_id": source.source_id, "url": source.url, "canonical_url": source.canonical_url,
            "title": source.title, "retrieved_at": source.retrieved_at.isoformat(), "content_hash": source.content_hash,
            "provider": source.provider, "excerpt": (excerpt or "")[:max_chars],
        }
        path = self.dir / f"{source.source_id}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load(self, source_id: str) -> Optional[dict]:
        path = self.dir / f"{source_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
