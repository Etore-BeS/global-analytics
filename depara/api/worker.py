"""Worker assíncrono para jobs de depara."""

from __future__ import annotations

import logging
import shutil
import threading

from depara.api.env_overrides import apply_env_overrides
from depara.api.storage import JobRecord, JobStatus, update_job
from depara.pipeline.run_job import run_job

logger = logging.getLogger(__name__)


def _finalize_artifacts(record: JobRecord, result) -> None:
    """Copia/renomeia artefatos para nomes estáveis na raiz do job."""
    mapping = {
        result.price_report_csv: record.job_dir / "price_report.csv",
        result.price_report_csv.with_suffix(".xlsx"): record.job_dir / "price_report.xlsx",
        result.price_report_csv.with_suffix(".html"): record.job_dir / "price_report.html",
        result.matches_path: record.job_dir / "matches.csv",
        result.summary_path: record.job_dir / "summary.json",
    }
    fase1 = record.config.fase1_path
    if fase1 and fase1.exists():
        mapping[fase1] = record.job_dir / "fase1_comparison.csv"

    for src, dst in mapping.items():
        if src.exists() and src != dst:
            shutil.copy2(src, dst)


def run_job_async(record: JobRecord) -> None:
    thread = threading.Thread(target=_execute_job, args=(record,), daemon=True)
    thread.start()


def _execute_job(record: JobRecord) -> None:
    record.status = JobStatus.RUNNING
    record.progress = "starting"
    update_job(record)

    try:
        record.progress = "pipeline"
        update_job(record)
        with apply_env_overrides(record.config.env_overrides):
            result = run_job(record.config)
        _finalize_artifacts(record, result)
        record.status = JobStatus.COMPLETED
        record.progress = "done"
        record.error = None
    except Exception as exc:  # noqa: BLE001
        logger.exception("Job %s falhou", record.job_id)
        record.status = JobStatus.FAILED
        record.error = str(exc)
        record.progress = None
    finally:
        update_job(record)
