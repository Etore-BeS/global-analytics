"""App mínimo para AppTest do guia onboarding."""

import streamlit as st
from depara.ui.onboarding import render_onboarding_step

st.session_state.setdefault("step", 0)
if st.session_state["step"] == 0:
    render_onboarding_step()
else:
    st.write("files step")
