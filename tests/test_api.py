"""Smoke tests da API FastAPI."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from depara.api.main import app
from fastapi.testclient import TestClient

COST_STOCK = Path("data/depara-unimed/Base_PRODUTOS_CUSTO_ESTOQUE_23062026.csv")
UNIMED = Path("data/depara-unimed/Curva ABC - CD 05.26.xlsx")
FASE1 = Path("data/depara-unimed/fase1_comparison.csv")
MATCHES = Path("data/depara-unimed/fase1_llm_matches.csv")

pytestmark = pytest.mark.skipif(
    not COST_STOCK.exists() or not UNIMED.exists(),
    reason="Fixtures Global×Unimed ausentes",
)


def _config_payload(*, skip_match: bool = True, regenerate: bool = False) -> str:
    return json.dumps(
        {
            "subject": {"template": "global_cost_stock", "granularity": "auto"},
            "reference": {"template": "unimed_abc"},
            "match": {"skip_match": skip_match},
            "fase1": {"regenerate": regenerate, "skip_spacy": True},
        }
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_validate_ok(client: TestClient) -> None:
    with COST_STOCK.open("rb") as subj, UNIMED.open("rb") as ref:
        resp = client.post(
            "/v1/validate",
            data={"config": _config_payload()},
            files={
                "subject_file": ("subject.csv", subj, "text/csv"),
                "reference_file": ("reference.xlsx", ref, "application/octet-stream"),
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["subject"]["row_count"] > 0


def test_validate_invalid_mapping(client: TestClient) -> None:
    bad_config = json.dumps(
        {
            "subject": {
                "template": "custom",
                "columns": {"display_text": "NAO_EXISTE"},
            },
            "reference": {"template": "unimed_abc"},
        }
    )
    with COST_STOCK.open("rb") as subj, UNIMED.open("rb") as ref:
        resp = client.post(
            "/v1/validate",
            data={"config": bad_config},
            files={
                "subject_file": ("subject.csv", subj, "text/csv"),
                "reference_file": ("reference.xlsx", ref, "application/octet-stream"),
            },
        )
    assert resp.status_code == 422


def test_list_jobs_endpoint(client: TestClient, tmp_path: Path, monkeypatch) -> None:
    from depara.api.schemas import JobCreateConfig, SideRequest
    from depara.api.storage import JobStatus, create_job

    monkeypatch.setattr("depara.api.storage.JOBS_ROOT", tmp_path / "jobs")
    cfg = JobCreateConfig(
        subject=SideRequest(template="global_cost_stock"),
        reference=SideRequest(template="unimed_abc"),
    )
    record = create_job(cfg, COST_STOCK, UNIMED)
    record.status = JobStatus.COMPLETED
    record.save_status()

    resp = client.get("/v1/jobs")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) >= 1
    assert body[0]["job_id"] == record.job_id


def test_job_skip_match(client: TestClient, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("depara.api.storage.JOBS_ROOT", tmp_path / "jobs")

    if not FASE1.exists() or not MATCHES.exists():
        pytest.skip("fase1/matches fixtures ausentes para job skip_match")

    config = json.dumps(
        {
            "subject": {"template": "global_cost_stock"},
            "reference": {"template": "unimed_abc"},
            "match": {"skip_match": True},
            "fase1": {"regenerate": False, "skip_spacy": True},
        }
    )

    with COST_STOCK.open("rb") as subj, UNIMED.open("rb") as ref:
        create = client.post(
            "/v1/jobs",
            data={"config": config},
            files={
                "subject_file": ("subject.csv", subj, "text/csv"),
                "reference_file": ("reference.xlsx", ref, "application/octet-stream"),
            },
        )
    assert create.status_code == 202
    job_id = create.json()["job_id"]

    for _ in range(60):
        status = client.get(f"/v1/jobs/{job_id}")
        assert status.status_code == 200
        data = status.json()
        if data["status"] in ("completed", "failed"):
            break
        time.sleep(0.5)
    else:
        pytest.fail("Job não terminou a tempo")

    assert data["status"] == "completed", data.get("error")
    assert "price_report.csv" in data["artifacts"]

    artifact = client.get(f"/v1/jobs/{job_id}/artifacts/price_report.csv")
    assert artifact.status_code == 200
    assert len(artifact.content) > 100


def test_mark_orphan_jobs_failed(tmp_path: Path, monkeypatch) -> None:
    from depara.api.schemas import JobCreateConfig, SideRequest
    from depara.api.storage import STALE_JOB_ERROR, JobStatus, create_job, mark_orphan_jobs_failed

    jobs_root = tmp_path / "jobs"
    monkeypatch.setattr("depara.api.storage.JOBS_ROOT", jobs_root)
    cfg = JobCreateConfig(
        subject=SideRequest(template="global_cost_stock"),
        reference=SideRequest(template="unimed_abc"),
    )
    record = create_job(cfg, COST_STOCK, UNIMED)
    record.status = JobStatus.RUNNING
    record.progress = "pipeline"
    record.save_status()

    count = mark_orphan_jobs_failed()
    assert count == 1

    reloaded = json.loads((record.job_dir / "status.json").read_text(encoding="utf-8"))
    assert reloaded["status"] == "failed"
    assert reloaded["error"] == STALE_JOB_ERROR


def test_retry_failed_job(client: TestClient, tmp_path: Path, monkeypatch) -> None:
    from depara.api.schemas import JobCreateConfig, SideRequest
    from depara.api.storage import STALE_JOB_ERROR, JobStatus, create_job

    monkeypatch.setattr("depara.api.storage.JOBS_ROOT", tmp_path / "jobs")
    cfg = JobCreateConfig(
        subject=SideRequest(template="global_cost_stock"),
        reference=SideRequest(template="unimed_abc"),
    )
    record = create_job(cfg, COST_STOCK, UNIMED)
    record.status = JobStatus.FAILED
    record.error = STALE_JOB_ERROR
    record.save_status()

    resp = client.post(f"/v1/jobs/{record.job_id}/retry")
    assert resp.status_code == 202
    body = resp.json()
    assert body["job_id"] == record.job_id
    assert body["status"] in ("queued", "running", "completed", "failed")


def test_retry_running_job_conflict(client: TestClient, tmp_path: Path, monkeypatch) -> None:
    from depara.api.schemas import JobCreateConfig, SideRequest
    from depara.api.storage import JobStatus, create_job

    monkeypatch.setattr("depara.api.storage.JOBS_ROOT", tmp_path / "jobs")
    cfg = JobCreateConfig(
        subject=SideRequest(template="global_cost_stock"),
        reference=SideRequest(template="unimed_abc"),
    )
    record = create_job(cfg, COST_STOCK, UNIMED)
    record.status = JobStatus.RUNNING
    record.save_status()

    resp = client.post(f"/v1/jobs/{record.job_id}/retry")
    assert resp.status_code == 409
