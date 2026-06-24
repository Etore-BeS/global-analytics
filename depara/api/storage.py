"""Armazenamento local de jobs da API."""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from depara.api.schemas import JobCreateConfig, side_config_from_request
from depara.contract.models import JobConfig

JOBS_ROOT = Path("exports/api_jobs")


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


STALE_JOB_ERROR = (
    "Execução interrompida (servidor reiniciou ou worker morreu). Reexecute o job."
)


@dataclass
class JobRecord:
    job_id: str
    status: JobStatus
    job_dir: Path
    config: JobConfig
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    progress: str | None = None
    error: str | None = None

    def status_path(self) -> Path:
        return self.job_dir / "status.json"

    def to_status_dict(self) -> dict:
        artifacts = {}
        if self.status == JobStatus.COMPLETED:
            for name in (
                "price_report.csv",
                "price_report.xlsx",
                "price_report.html",
                "matches.csv",
                "summary.json",
                "fase1_comparison.csv",
            ):
                path = self._artifact_path(name)
                if path.exists():
                    artifacts[name] = f"/v1/jobs/{self.job_id}/artifacts/{name}"
        return {
            "job_id": self.job_id,
            "status": self.status.value,
            "progress": self.progress,
            "error": self.error,
            "artifacts": artifacts,
            "created_at": self.created_at,
        }

    def _artifact_path(self, name: str) -> Path:
        mapping = {
            "price_report.csv": self.job_dir / "price_report.csv",
            "price_report.xlsx": self.job_dir / "price_report.xlsx",
            "price_report.html": self.job_dir / "price_report.html",
            "matches.csv": self.job_dir / "matches.csv",
            "summary.json": self.job_dir / "summary.json",
            "fase1_comparison.csv": self.job_dir / "fase1_comparison.csv",
        }
        return mapping.get(name, self.job_dir / name)

    def save_status(self) -> None:
        self.status_path().write_text(
            json.dumps(self.to_status_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def create_job(
    config: JobCreateConfig,
    subject_path: Path,
    reference_path: Path,
    catalog_path: Path | None = None,
) -> JobRecord:
    job_id = uuid.uuid4().hex
    job_dir = JOBS_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    side_a = side_config_from_request(
        config.subject, job_dir / ("subject" + subject_path.suffix)
    )
    side_b = side_config_from_request(
        config.reference, job_dir / ("reference" + reference_path.suffix)
    )

    shutil.copy2(subject_path, side_a.path)
    shutil.copy2(reference_path, side_b.path)

    if catalog_path is not None:
        cat_dest = job_dir / ("catalog" + catalog_path.suffix)
        shutil.copy2(catalog_path, cat_dest)
        side_a.catalog_enrichment = cat_dest

    job_config = JobConfig(
        side_a=side_a,
        side_b=side_b,
        match=config.match,
        fase1=config.fase1,
        env_overrides=config.env_overrides,
        output_dir=job_dir,
        fase1_path=job_dir / "fase1_comparison.csv",
        matches_path=job_dir / "matches.csv",
    )

    if not config.fase1.regenerate:
        default_fase1 = Path("data/depara-unimed/fase1_comparison.csv")
        default_matches = Path("data/depara-unimed/fase1_llm_matches.csv")
        if default_fase1.exists():
            shutil.copy2(default_fase1, job_config.fase1_path)
        if default_matches.exists():
            shutil.copy2(default_matches, job_config.matches_path)
    elif config.match.skip_match:
        default_matches = Path("data/depara-unimed/fase1_llm_matches.csv")
        if default_matches.exists():
            shutil.copy2(default_matches, job_config.matches_path)

    (job_dir / "config.json").write_text(
        job_config.model_dump_json(indent=2),
        encoding="utf-8",
    )

    record = JobRecord(
        job_id=job_id,
        status=JobStatus.QUEUED,
        job_dir=job_dir,
        config=job_config,
    )
    record.save_status()
    return record


def load_job(job_id: str) -> JobRecord | None:
    job_dir = JOBS_ROOT / job_id
    status_path = job_dir / "status.json"
    config_path = job_dir / "config.json"
    if not status_path.exists() or not config_path.exists():
        return None
    status_data = json.loads(status_path.read_text(encoding="utf-8"))
    config = JobConfig.model_validate_json(config_path.read_text(encoding="utf-8"))
    return JobRecord(
        job_id=job_id,
        status=JobStatus(status_data["status"]),
        job_dir=job_dir,
        config=config,
        created_at=status_data.get("created_at", ""),
        progress=status_data.get("progress"),
        error=status_data.get("error"),
    )


def update_job(record: JobRecord) -> None:
    record.save_status()


def mark_orphan_jobs_failed() -> int:
    """Marca jobs queued/running como failed após restart da API (worker em thread)."""
    if not JOBS_ROOT.exists():
        return 0
    count = 0
    for status_path in JOBS_ROOT.glob("*/status.json"):
        try:
            data = json.loads(status_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("status") not in (JobStatus.QUEUED.value, JobStatus.RUNNING.value):
            continue
        data["status"] = JobStatus.FAILED.value
        data["error"] = STALE_JOB_ERROR
        data["progress"] = None
        status_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        count += 1
    return count


def reset_job_for_retry(job_id: str) -> JobRecord | None:
    record = load_job(job_id)
    if record is None:
        return None
    record.status = JobStatus.QUEUED
    record.progress = None
    record.error = None
    record.save_status()
    return record


def list_jobs(limit: int = 20) -> list[dict]:
    """Lista jobs recentes a partir de status.json em exports/api_jobs/."""
    if not JOBS_ROOT.exists():
        return []
    rows: list[dict] = []
    for status_path in JOBS_ROOT.glob("*/status.json"):
        try:
            data = json.loads(status_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        rows.append(data)
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return rows[:limit]
