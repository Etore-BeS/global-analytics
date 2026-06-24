"""Schemas da API FastAPI — subject/reference mapeiam para side_a/side_b."""

from __future__ import annotations

from typing import Literal

from depara.contract.models import (
    Fase1Config,
    Granularity,
    MatchConfig,
    PricePolicy,
    SideConfig,
    TemplateId,
)
from pydantic import BaseModel, Field


class SideRequest(BaseModel):
    template: TemplateId = "custom"
    columns: dict[str, str] = Field(default_factory=dict)
    granularity: Granularity = "auto"
    price_policy: PricePolicy | None = None


class JobCreateConfig(BaseModel):
    subject: SideRequest
    reference: SideRequest
    match: MatchConfig = Field(default_factory=MatchConfig)
    fase1: Fase1Config = Field(default_factory=Fase1Config)
    env_overrides: dict[str, str] = Field(default_factory=dict)


class MappingIssueResponse(BaseModel):
    field: str
    message: str
    expected_column: str | None = None


class SideValidationResponse(BaseModel):
    role: Literal["subject", "reference"]
    valid: bool
    granularity: Granularity | None = None
    issues: list[MappingIssueResponse] = Field(default_factory=list)
    preview: list[dict[str, str]] = Field(default_factory=list)
    row_count: int = 0


class ValidateResponse(BaseModel):
    valid: bool
    subject: SideValidationResponse
    reference: SideValidationResponse


class JobStatusResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "completed", "failed"]
    progress: str | None = None
    error: str | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)
    created_at: str | None = None


def side_config_from_request(req: SideRequest, path) -> SideConfig:
    return SideConfig(
        path=path,
        template=req.template,
        columns=req.columns,
        granularity=req.granularity,
        price_policy=req.price_policy,
    )
