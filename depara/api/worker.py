"""Worker assíncrono para jobs de depara."""

from __future__ import annotations

import logging
import shutil
import threading
import time

from depara.api.env_overrides import apply_env_overrides
from depara.api.schemas import JobProgressInfo
from depara.api.storage import JobRecord, JobStatus, update_job
from depara.pipeline.progress import JobProgress
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


def _progress_callback(record: JobRecord):
    last_save = 0.0
    last_pct = -1
    last_phase = ""

    def _cb(progress: JobProgress) -> None:
        nonlocal last_save, last_pct, last_phase
        now = time.monotonic()
        phase_changed = progress.phase != last_phase
        pct_jump = abs(progress.percent - last_pct) >= 2
        if not (phase_changed or pct_jump or now - last_save >= 2.0):
            return
        record.progress = JobProgressInfo.model_validate(progress.to_dict())
        update_job(record)
        last_save = now
        last_pct = progress.percent
        last_phase = progress.phase

    return _cb


def _execute_job(record: JobRecord) -> None:
    record.status = JobStatus.RUNNING
    record.progress = JobProgressInfo(
        phase="starting",
        label="Iniciando pipeline…",
        percent=0,
    )
    update_job(record)

    try:
        with apply_env_overrides(record.config.env_overrides):
            result = run_job(record.config, on_progress=_progress_callback(record))
        _finalize_artifacts(record, result)
        record.status = JobStatus.COMPLETED
        record.progress = JobProgressInfo(
            phase="done",
            label="Concluído",
            percent=100,
        )
        record.error = None
    except Exception as exc:  # noqa: BLE001
        logger.exception("Job %s falhou", record.job_id)
        record.status = JobStatus.FAILED
        record.error = str(exc)
        record.progress = None
    finally:
        update_job(record)
