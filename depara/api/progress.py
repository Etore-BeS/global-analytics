"""Progresso de job — módulo leve (UI e API importam daqui)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class JobProgressInfo(BaseModel):
    phase: str
    label: str
    percent: int = Field(default=0, ge=0, le=100)
    current: int | None = None
    total: int | None = None
    detail: str | None = None


_LEGACY_PROGRESS: dict[str, tuple[str, int]] = {
    "starting": ("Iniciando pipeline…", 5),
    "pipeline": ("Processando pipeline…", 45),
    "done": ("Concluído", 100),
}


def coerce_progress(raw: object) -> JobProgressInfo | None:
    """Aceita progresso estruturado ou strings legadas de status.json antigos."""
    if raw is None:
        return None
    if isinstance(raw, JobProgressInfo):
        return raw
    if isinstance(raw, str):
        label, pct = _LEGACY_PROGRESS.get(raw, (raw, 25))
        return JobProgressInfo(phase=raw, label=label, percent=pct)
    if isinstance(raw, dict):
        return JobProgressInfo.model_validate(raw)
    return None
