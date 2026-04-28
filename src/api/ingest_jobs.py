from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from src.knowledge.ingester import DocumentIngester


JobStatus = Literal["queued", "running", "completed", "failed"]


class IngestJobManager:
    """Small in-memory async ingestion runner for MVP throughput improvements."""

    def __init__(self, max_workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def submit(self, *, modality: str, source: str, category: str = "REGULATION") -> str:
        job_id = str(uuid.uuid4())
        payload = {
            "job_id": job_id,
            "modality": modality,
            "source": source,
            "category": category,
            "status": "queued",
            "created_at": datetime.utcnow().isoformat(),
            "started_at": None,
            "completed_at": None,
            "result": None,
            "error": None,
        }
        with self._lock:
            self._jobs[job_id] = payload

        self._executor.submit(self._run_job, job_id)
        return job_id

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_recent(self, n: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._jobs.values())
        items.sort(key=lambda x: x["created_at"], reverse=True)
        return items[:n]

    def _run_job(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job["status"] = "running"
            job["started_at"] = datetime.utcnow().isoformat()

        try:
            result = self._execute(job)
            with self._lock:
                job["status"] = "completed"
                job["result"] = result
                job["completed_at"] = datetime.utcnow().isoformat()
        except Exception as e:
            with self._lock:
                job["status"] = "failed"
                job["error"] = str(e)
                job["completed_at"] = datetime.utcnow().isoformat()

    def _execute(self, job: dict[str, Any]) -> dict[str, Any]:
        ingester = DocumentIngester()
        src = job["source"]
        category = job["category"]
        modality = job["modality"]

        if modality == "pdf":
            return ingester.ingest_pdf(Path(src), category=category)
        if modality == "image":
            return ingester.ingest_image(Path(src), category=category)
        if modality == "text":
            return ingester.ingest_text(src, title="Queued Text", category=category, source="queue")
        raise ValueError(f"Unsupported modality: {modality}")


_job_manager: IngestJobManager | None = None


def get_job_manager() -> IngestJobManager:
    global _job_manager
    if _job_manager is None:
        _job_manager = IngestJobManager()
    return _job_manager
