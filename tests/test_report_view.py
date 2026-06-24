"""Embed do relatório HTML no Streamlit."""

from __future__ import annotations

from depara.ui.report_view import (
    artifact_url,
    estimate_report_height,
    prepare_html_for_embed,
)


def test_artifact_url() -> None:
    url = artifact_url("http://127.0.0.1:8000/", "abc123", "price_report.html")
    assert url == "http://127.0.0.1:8000/v1/jobs/abc123/artifacts/price_report.html"


def test_prepare_html_for_embed_injects_anchor_and_height_script() -> None:
    raw = "<!DOCTYPE html><html><head></head><body><a href='#x'>x</a></body></html>"
    out = prepare_html_for_embed(raw)
    assert "depara-streamlit-embed" in out
    assert "streamlit:setFrameHeight" in out
    assert 'href^="#"' in out


def test_prepare_html_idempotent() -> None:
    once = prepare_html_for_embed("<html><head></head><body></body></html>")
    twice = prepare_html_for_embed(once)
    assert once == twice


def test_estimate_report_height_scales_with_content() -> None:
    small = estimate_report_height("<html><body></body></html>")
    big = estimate_report_height("<section></section>" * 10 + "<tr></tr>" * 50)
    assert big > small
