"""Testes do client HTTP da UI."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
from depara.api.schemas import JobCreateConfig, SideRequest, ValidateResponse
from depara.ui.client import DeparaApiClient, ValidationErrorDetail


def _minimal_config() -> JobCreateConfig:
    return JobCreateConfig(
        subject=SideRequest(template="global_cost_stock"),
        reference=SideRequest(template="unimed_abc"),
    )


def test_health_ok() -> None:
    client = DeparaApiClient("http://test")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "ok"}
    http = MagicMock()
    http.get.return_value = mock_resp
    with patch.object(httpx.Client, "__enter__", return_value=http):
        with patch.object(httpx.Client, "__exit__", return_value=None):
            assert client.health() is True


def test_validate_success() -> None:
    client = DeparaApiClient("http://test")
    body = {
        "valid": True,
        "subject": {
            "role": "subject",
            "valid": True,
            "granularity": "sku",
            "issues": [],
            "preview": [],
            "row_count": 10,
        },
        "reference": {
            "role": "reference",
            "valid": True,
            "granularity": None,
            "issues": [],
            "preview": [],
            "row_count": 5,
        },
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = body
    mock_resp.raise_for_status = MagicMock()

    http = MagicMock()
    http.post.return_value = mock_resp
    with patch.object(httpx.Client, "__enter__", return_value=http):
        with patch.object(httpx.Client, "__exit__", return_value=None):
            result = client.validate(b"s", "s.csv", b"r", "r.xlsx", _minimal_config())
    assert isinstance(result, ValidateResponse)
    assert result.valid is True


def test_validate_422() -> None:
    client = DeparaApiClient("http://test")
    detail = {
        "valid": False,
        "subject": {
            "role": "subject",
            "valid": False,
            "issues": [{"field": "display_text", "message": "missing"}],
        },
        "reference": {"role": "reference", "valid": True, "issues": []},
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 422
    mock_resp.json.return_value = {"detail": detail}

    http = MagicMock()
    http.post.return_value = mock_resp
    with patch.object(httpx.Client, "__enter__", return_value=http):
        with patch.object(httpx.Client, "__exit__", return_value=None):
            result = client.validate(b"s", "s.csv", b"r", "r.xlsx", _minimal_config())
    assert isinstance(result, ValidationErrorDetail)
    assert result.valid is False


def test_list_jobs() -> None:
    client = DeparaApiClient("http://test")
    rows = [{"job_id": "abc", "status": "completed", "artifacts": {}}]
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = rows
    mock_resp.raise_for_status = MagicMock()

    http = MagicMock()
    http.get.return_value = mock_resp
    with patch.object(httpx.Client, "__enter__", return_value=http):
        with patch.object(httpx.Client, "__exit__", return_value=None):
            jobs = client.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].job_id == "abc"
