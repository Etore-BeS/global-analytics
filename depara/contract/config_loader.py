"""Carrega JobConfig de YAML ou JSON."""

from __future__ import annotations

import json
from pathlib import Path

from depara.contract.models import JobConfig


def load_job_config(path: Path) -> JobConfig:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError(
                "PyYAML necessário para configs .yaml — instale com: uv add pyyaml"
            ) from exc
        data = yaml.safe_load(text)
    elif suffix == ".json":
        data = json.loads(text)
    else:
        raise ValueError(f"Formato de config não suportado: {suffix} (use .yaml ou .json)")
    return JobConfig.model_validate(data)
