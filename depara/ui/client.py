"""Client HTTP para a Depara FastAPI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx
from depara.api.schemas import JobCreateConfig, JobStatusResponse, ValidateResponse


@dataclass
class ValidationErrorDetail:
    valid: bool
    subject_issues: list[dict[str, Any]]
    reference_issues: list[dict[str, Any]]
    raw: Any


class DeparaApiError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None, detail: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


class DeparaApiClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8000", timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self.base_url, timeout=self.timeout)

    def health(self) -> bool:
        try:
            with self._client() as client:
                resp = client.get("/health")
                return resp.status_code == 200 and resp.json().get("status") == "ok"
        except httpx.HTTPError:
            return False

    def validate(
        self,
        subject_bytes: bytes,
        subject_name: str,
        reference_bytes: bytes,
        reference_name: str,
        config: JobCreateConfig,
    ) -> ValidateResponse | ValidationErrorDetail:
        config_json = config.model_dump_json()
        files = {
            "subject_file": (subject_name, subject_bytes, "application/octet-stream"),
            "reference_file": (reference_name, reference_bytes, "application/octet-stream"),
        }
        with self._client() as client:
            resp = client.post("/v1/validate", data={"config": config_json}, files=files)
        if resp.status_code == 422:
            detail = resp.json().get("detail", {})
            if isinstance(detail, dict) and "subject" in detail:
                return ValidationErrorDetail(
                    valid=False,
                    subject_issues=detail.get("subject", {}).get("issues", []),
                    reference_issues=detail.get("reference", {}).get("issues", []),
                    raw=detail,
                )
            return ValidationErrorDetail(
                valid=False,
                subject_issues=[],
                reference_issues=[],
                raw=detail,
            )
        resp.raise_for_status()
        return ValidateResponse.model_validate(resp.json())

    def create_job(
        self,
        subject_bytes: bytes,
        subject_name: str,
        reference_bytes: bytes,
        reference_name: str,
        config: JobCreateConfig,
        catalog_bytes: bytes | None = None,
        catalog_name: str | None = None,
    ) -> JobStatusResponse:
        config_json = config.model_dump_json()
        files: list[tuple[str, tuple[str, bytes, str]]] = [
            ("subject_file", (subject_name, subject_bytes, "application/octet-stream")),
            ("reference_file", (reference_name, reference_bytes, "application/octet-stream")),
        ]
        if catalog_bytes is not None and catalog_name:
            files.append(
                ("catalog_file", (catalog_name, catalog_bytes, "application/octet-stream"))
            )
        with self._client() as client:
            resp = client.post(
                "/v1/jobs",
                data={"config": config_json},
                files=files,
            )
        if resp.status_code == 422:
            raise DeparaApiError(
                "Mapeamento inválido",
                status_code=422,
                detail=resp.json().get("detail"),
            )
        resp.raise_for_status()
        return JobStatusResponse.model_validate(resp.json())

    def get_job(self, job_id: str) -> JobStatusResponse:
        with self._client() as client:
            resp = client.get(f"/v1/jobs/{job_id}")
        if resp.status_code == 404:
            raise DeparaApiError("Job não encontrado", status_code=404)
        resp.raise_for_status()
        return JobStatusResponse.model_validate(resp.json())

    def retry_job(self, job_id: str) -> JobStatusResponse:
        with self._client() as client:
            resp = client.post(f"/v1/jobs/{job_id}/retry")
        if resp.status_code == 404:
            raise DeparaApiError("Job não encontrado", status_code=404)
        if resp.status_code == 409:
            raise DeparaApiError(
                "Job não pode ser reexecutado neste estado",
                status_code=409,
                detail=resp.json().get("detail"),
            )
        resp.raise_for_status()
        return JobStatusResponse.model_validate(resp.json())

    def list_jobs(self, limit: int = 20) -> list[JobStatusResponse]:
        with self._client() as client:
            resp = client.get("/v1/jobs", params={"limit": limit})
        resp.raise_for_status()
        return [JobStatusResponse.model_validate(row) for row in resp.json()]

    def fetch_artifact_bytes(self, job_id: str, name: str) -> bytes:
        with self._client() as client:
            resp = client.get(f"/v1/jobs/{job_id}/artifacts/{name}")
        if resp.status_code == 404:
            raise DeparaApiError(f"Artefato '{name}' não encontrado", status_code=404)
        resp.raise_for_status()
        return resp.content

    @staticmethod
    def config_json(config: JobCreateConfig) -> str:
        return json.dumps(config.model_dump(), ensure_ascii=False)
