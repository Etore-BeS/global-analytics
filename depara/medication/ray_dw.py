"""Path setup for ray-dw-pipeline shared normalization layer."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_DEFAULT_RAY_DW = Path(__file__).resolve().parents[2].parent / "ray-dw-pipeline"
_SHARED_PYTHON = "src/layers/shared/python"


def ray_dw_shared_path() -> Path:
    env = os.environ.get("RAY_DW_PIPELINE_ROOT")
    root = Path(env) if env else _DEFAULT_RAY_DW
    return root / _SHARED_PYTHON


def ensure_ray_dw_path() -> Path:
    shared = ray_dw_shared_path()
    shared_str = str(shared.resolve())
    if shared_str not in sys.path:
        sys.path.insert(0, shared_str)
    return shared
