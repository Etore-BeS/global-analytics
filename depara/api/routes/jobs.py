"""Rotas de jobs assíncronos."""

from __future__ import annotations

import json
from pathlib import Path

from depara.api.schemas import (
    JobCreateConfig,
    JobStatusResponse,
    MappingIssueResponse,
    SideValidationResponse,
    ValidateResponse,
    side_config_from_request,
)
from depara.api.storage import (
    JobStatus,
    create_job,
    list_jobs,
    load_job,
    reset_job_for_retry,
)
from depara.api.worker import run_job_async
from depara.contract.validation import validate_side_mapping
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

router = APIRouter(prefix="/v1", tags=["jobs"])

ARTIFACT_MEDIA = {
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".html": "text/html",
    ".json": "application/json",
}


def _save_upload(upload: UploadFile, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(upload.file.read())


@router.post("/validate", response_model=ValidateResponse)
async def validate_mapping(
    subject_file: UploadFile = File(...),
    reference_file: UploadFile = File(...),
    config: str = Form(...),
) -> ValidateResponse:
    cfg = JobCreateConfig.model_validate(json.loads(config))
    tmp = Path("exports/api_validate_tmp")
    tmp.mkdir(parents=True, exist_ok=True)
    subj_path = tmp / f"subject_{subject_file.filename}"
    ref_path = tmp / f"reference_{reference_file.filename}"
    _save_upload(subject_file, subj_path)
    _save_upload(reference_file, ref_path)

    result = validate_side_mapping(
        side_config_from_request(cfg.subject, subj_path),
        side_config_from_request(cfg.reference, ref_path),
    )

    if not result.valid:
        raise HTTPException(
            status_code=422,
            detail=ValidateResponse(
                valid=False,
                subject=_side_result(result.subject),
                reference=_side_result(result.reference),
            ).model_dump(),
        )

    return ValidateResponse(
        valid=True,
        subject=_side_result(result.subject),
        reference=_side_result(result.reference),
    )


def _side_result(side) -> SideValidationResponse:
    return SideValidationResponse(
        role=side.role,
        valid=side.valid,
        granularity=side.granularity,
        issues=[
            MappingIssueResponse(
                field=i.field,
                message=i.message,
                expected_column=i.expected_column,
            )
            for i in side.issues
        ],
        preview=side.preview,
        row_count=side.row_count,
    )


@router.post("/jobs", response_model=JobStatusResponse, status_code=202)
async def create_depara_job(
    subject_file: UploadFile = File(...),
    reference_file: UploadFile = File(...),
    config: str = Form(...),
    catalog_file: UploadFile | None = File(None),
) -> JobStatusResponse:
    cfg = JobCreateConfig.model_validate(json.loads(config))
    tmp = Path("exports/api_upload_tmp")
    tmp.mkdir(parents=True, exist_ok=True)
    subj_path = tmp / f"subject_{subject_file.filename}"
    ref_path = tmp / f"reference_{reference_file.filename}"
    _save_upload(subject_file, subj_path)
    _save_upload(reference_file, ref_path)

    catalog_path = None
    if catalog_file is not None:
        catalog_path = tmp / f"catalog_{catalog_file.filename}"
        _save_upload(catalog_file, catalog_path)

    validation = validate_side_mapping(
        side_config_from_request(cfg.subject, subj_path),
        side_config_from_request(cfg.reference, ref_path),
    )
    if not validation.valid:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Mapeamento inválido",
                "issues": [
                    {"role": i.role, "field": issue.field, "message": issue.message}
                    for i in (validation.subject, validation.reference)
                    for issue in i.issues
                ],
            },
        )

    record = create_job(cfg, subj_path, ref_path, catalog_path)
    run_job_async(record)
    data = record.to_status_dict()
    return JobStatusResponse(**{k: data[k] for k in JobStatusResponse.model_fields if k in data})


@router.get("/jobs", response_model=list[JobStatusResponse])
async def list_depara_jobs(limit: int = 20) -> list[JobStatusResponse]:
    rows = list_jobs(limit=limit)
    return [
        JobStatusResponse(**{k: row[k] for k in JobStatusResponse.model_fields if k in row})
        for row in rows
    ]


@router.post("/jobs/{job_id}/retry", response_model=JobStatusResponse, status_code=202)
async def retry_depara_job(job_id: str) -> JobStatusResponse:
    record = load_job(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    if record.status not in (JobStatus.FAILED, JobStatus.QUEUED):
        raise HTTPException(
            status_code=409,
            detail=f"Job em estado '{record.status.value}' não pode ser reexecutado",
        )
    record = reset_job_for_retry(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    run_job_async(record)
    data = record.to_status_dict()
    return JobStatusResponse(**{k: data[k] for k in JobStatusResponse.model_fields if k in data})


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str) -> JobStatusResponse:
    record = load_job(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    data = record.to_status_dict()
    return JobStatusResponse(
        **{k: data[k] for k in JobStatusResponse.model_fields if k in data}
    )


@router.get("/jobs/{job_id}/artifacts/{name}")
async def get_job_artifact(job_id: str, name: str) -> FileResponse:
    record = load_job(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    path = record._artifact_path(name)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Artefato '{name}' não encontrado")
    media = ARTIFACT_MEDIA.get(path.suffix, "application/octet-stream")
    headers: dict[str, str] = {}
    if path.suffix.lower() == ".html":
        headers["Content-Security-Policy"] = "frame-ancestors *"
    return FileResponse(path, media_type=media, filename=name, headers=headers)
