"""Testes de navegação do guia onboarding (Streamlit AppTest)."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


def _onboarding_app() -> AppTest:
    root = Path(__file__).resolve().parents[1]
    script = root / "depara" / "ui" / "_onboarding_test_app.py"
    return AppTest.from_file(str(script))


def test_onboarding_next_section_no_session_state_error() -> None:
    at = _onboarding_app()
    at.run(timeout=15)
    assert not at.exception
    assert at.session_state["onboard_section_idx"] == 0

    at.button(key="onboard_next").click().run(timeout=15)
    assert not at.exception
    assert at.session_state["onboard_section_idx"] == 1

    at.button(key="onboard_next").click().run(timeout=15)
    assert not at.exception
    assert at.session_state["onboard_section_idx"] == 2


def test_onboarding_done_goes_to_files_step() -> None:
    at = _onboarding_app()
    at.session_state["onboard_section_idx"] = 4
    at.session_state["onboard_section_radio"] = 4
    at.run(timeout=15)

    at.button(key="onboard_done").click().run(timeout=15)
    assert not at.exception
    assert at.session_state["step"] == 1
