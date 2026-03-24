"""Shared base types and behavior for venue ingestion engines."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from utils.http_utils import download_file

logger = logging.getLogger(__name__)


class VenueIngestion(ABC):
    def __init__(self) -> None:
        self.last_discovery_summary: dict[str, Any] | None = None
        self.root: Path = Path()
        self.user_agent: str = ""
        self.dry_run: bool = False
        self.start: date | None = None
        self.end: date | None = None
        self.assets: tuple[str, ...] = ()
        self.spec: Any = None
        self.records: list[dict[str, Any]] = []
        self.run_id: str = ""
        self.manifest: dict[str, Any] = {}

    @abstractmethod
    def discover(self) -> None:
        raise NotImplementedError

    def download_all(self) -> dict[str, int]:
        stats = {"downloaded_files": 0, "downloaded_bytes": 0, "skipped_existing_files": 0, "pending_files": 0}
        for index, record in enumerate(self.records, start=1):
            target = Path(record["path"])
            if target.exists():
                stats["skipped_existing_files"] += 1
                continue
            if self.dry_run:
                stats["pending_files"] += 1
                continue
            logger.info("[download] %s %d/%d %s", record["dataset"], index, len(self.records), record["filename"])
            stats["downloaded_bytes"] += download_file(record["url"], target, user_agent=self.user_agent)
            stats["downloaded_files"] += 1
        return stats

    def write_manifest(self) -> Path:
        target = self.root / "_meta" / "runs" / f"{self.run_id}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.manifest, indent=2) + "\n", encoding="utf-8")
        return target

    def resolve_date_window(self) -> tuple[date, date] | None:
        effective_start = max(self.spec.start_date, self.start) if self.start else self.spec.start_date
        today = datetime.now(UTC).date()
        effective_end = min(today, self.end) if self.end else today
        if effective_end < effective_start:
            return None
        return effective_start, effective_end
