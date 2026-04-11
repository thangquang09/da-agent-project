"""File-based artifact store for heavyweight data (PNG charts, report markdown, CSV).

All heavy data is stored as physical files under ARTIFACT_ROOT.
PostgreSQL only holds metadata/pointers — never binary or base64.

Directory convention:
    {ARTIFACT_ROOT}/{thread_id}/{turn_number}/
        chart_{short_uuid}.png
        chart_{short_uuid}.svg
        report.md
        section_{section_id}.png
        data_{result_id}.csv
"""

from __future__ import annotations

import shutil
import threading
import uuid
from pathlib import Path
from typing import Any

from app.logger import logger

DEFAULT_ARTIFACT_ROOT = Path("./artifacts")


class ArtifactFileStore:
    """Filesystem store for conversation artifacts.

    Each artifact is saved as a file under ``{root}/{thread_id}/{turn}/`` and
    the returned value is a *relative path* that can be converted to a URL
    via ``get_artifact_url()``.
    """

    def __init__(self, root: Path | str | None = None) -> None:
        if root is None:
            from app.config import load_settings

            root = getattr(load_settings(), "artifact_root", str(DEFAULT_ARTIFACT_ROOT))
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        logger.info("ArtifactFileStore initialized (root={root})", root=self._root)

    def _dir_for_turn(self, thread_id: str, turn_number: int) -> Path:
        d = self._root / thread_id / str(turn_number)
        d.mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    def _short_uuid() -> str:
        return uuid.uuid4().hex[:8]

    def save_chart(
        self,
        thread_id: str,
        turn_number: int,
        image_data: bytes,
        image_format: str = "png",
    ) -> str:
        """Save a chart image to disk. Returns relative path like ``{thread_id}/{turn}/chart_xxx.png``."""
        d = self._dir_for_turn(thread_id, turn_number)
        ext = image_format.lower().lstrip(".")
        if ext == "jpeg":
            ext = "jpg"
        filename = f"chart_{self._short_uuid()}.{ext}"
        path = d / filename
        path.write_bytes(image_data)
        rel = f"{thread_id}/{turn_number}/{filename}"
        logger.debug("Saved chart artifact: {rel}", rel=rel)
        return rel

    def save_report_markdown(
        self,
        thread_id: str,
        turn_number: int,
        markdown: str,
    ) -> str:
        """Save report markdown to disk. Returns relative path."""
        d = self._dir_for_turn(thread_id, turn_number)
        filename = "report.md"
        path = d / filename
        path.write_text(markdown, encoding="utf-8")
        rel = f"{thread_id}/{turn_number}/{filename}"
        logger.debug("Saved report markdown: {rel}", rel=rel)
        return rel

    def save_report_section_chart(
        self,
        thread_id: str,
        turn_number: int,
        section_id: str,
        image_data: bytes,
        image_format: str = "png",
    ) -> str:
        """Save a report section chart image to disk. Returns relative path."""
        d = self._dir_for_turn(thread_id, turn_number)
        ext = image_format.lower().lstrip(".")
        if ext == "jpeg":
            ext = "jpg"
        safe_section = section_id.replace(" ", "_").replace("/", "_")[:32]
        filename = f"section_{safe_section}_{self._short_uuid()}.{ext}"
        path = d / filename
        path.write_bytes(image_data)
        rel = f"{thread_id}/{turn_number}/{filename}"
        logger.debug("Saved section chart: {rel}", rel=rel)
        return rel

    def save_data_csv(
        self,
        thread_id: str,
        turn_number: int,
        data: str,
        prefix: str = "data",
    ) -> str:
        """Save CSV/JSON data content to disk. Returns relative path."""
        d = self._dir_for_turn(thread_id, turn_number)
        filename = f"{prefix}_{self._short_uuid()}.csv"
        path = d / filename
        path.write_text(data, encoding="utf-8")
        rel = f"{thread_id}/{turn_number}/{filename}"
        logger.debug("Saved data artifact: {rel}", rel=rel)
        return rel

    def resolve_path(self, relative_path: str) -> Path:
        """Convert a relative path to an absolute filesystem path."""
        return self._root / relative_path

    def get_artifact_url(self, relative_path: str) -> str:
        """Convert a relative path to a URL path served by the backend.

        Returns a path like ``/artifacts/{thread_id}/{turn}/chart_xxx.png``
        that the frontend can use directly in ``<img src=...>``.
        """
        return f"/artifacts/{relative_path}"

    def file_exists(self, relative_path: str) -> bool:
        """Check if an artifact file exists on disk."""
        return (self._root / relative_path).exists()

    def get_file_size(self, relative_path: str) -> int:
        """Return file size in bytes, or 0 if not found."""
        p = self._root / relative_path
        if p.exists():
            return p.stat().st_size
        return 0

    def delete_thread(self, thread_id: str) -> int:
        """Delete all artifact files for a thread. Returns number of files deleted."""
        thread_dir = self._root / thread_id
        if not thread_dir.exists():
            return 0
        file_count = sum(1 for _ in thread_dir.rglob("*") if _.is_file())
        shutil.rmtree(thread_dir)
        logger.info(
            "Deleted artifact dir: thread={thread}, files={count}",
            thread=thread_id[:8],
            count=file_count,
        )
        return file_count

    def cleanup_turn(self, thread_id: str, turn_number: int) -> int:
        """Delete all artifact files for a specific turn. Returns number of files deleted."""
        turn_dir = self._root / thread_id / str(turn_number)
        if not turn_dir.exists():
            return 0
        file_count = sum(1 for _ in turn_dir.iterdir() if _.is_file())
        shutil.rmtree(turn_dir)
        return file_count


_instance: ArtifactFileStore | None = None
_lock = threading.Lock()


def get_artifact_file_store() -> ArtifactFileStore:
    """Get or create the ArtifactFileStore singleton (thread-safe)."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = ArtifactFileStore()
    return _instance
