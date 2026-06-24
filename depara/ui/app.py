"""Wizard Streamlit para Depara API.

Uso local (dois terminais):

    # bash / fish — terminal 1 (sem --reload evita matar jobs longos)
    uv run uvicorn depara.api.main:app --port 8000

    # bash / fish — terminal 2
    uv run streamlit run depara/ui/app.py
"""

from __future__ import annotations

import json
import time
from typing import Any

import pandas as pd
import streamlit as st
from depara.api.schemas import JobCreateConfig, ValidateResponse
from depara.contract.templates import TEMPLATE_COLUMNS
from depara.ui.client import DeparaApiClient, DeparaApiError, ValidationErrorDetail
from depara.ui.env_settings import (
    ENV_FIELDS,
    env_default_caption,
    env_field_placeholder,
    load_env_defaults,
    merge_env_overrides,
)
from depara.ui.job_progress import (
    MAX_JOB_POLLS,
    MAX_WAIT_MINUTES,
    POLL_INTERVAL_SEC,
    elapsed_seconds,
    estimate_caption,
    eta_seconds,
    format_duration,
    progress_detail,
    progress_label,
    progress_percent,
)
from depara.ui.mapping_help import (
    LEVEL_BADGE,
    REFERENCE_SECTIONS,
    SUBJECT_SECTIONS,
    peek_upload_columns,
    preset_mapping_table,
)
from depara.ui.onboarding import render_onboarding_step
from depara.ui.presets import (
    ALLOWED_EXTENSIONS,
    DEFAULT_PRESET_ID,
    PRESETS,
    Preset,
    build_job_config,
)
from depara.ui.report_view import (
    IFRAME_CHROME_CSS,
    artifact_url,
    estimate_report_height,
    prepare_html_for_embed,
)

STEP_LABELS = ["Guia", "Arquivos", "Mapeamento", "Validar", "Resultado"]
DEFAULT_API_URL = "http://127.0.0.1:8000"


def _init_session() -> None:
    defaults: dict[str, Any] = {
        "step": 0,
        "preset_id": DEFAULT_PRESET_ID,
        "subject_bytes": None,
        "subject_name": None,
        "reference_bytes": None,
        "reference_name": None,
        "catalog_bytes": None,
        "catalog_name": None,
        "validation_ok": False,
        "validation_result": None,
        "job_id": None,
        "job_result": None,
        "poll_count": 0,
        "job_poll_exhausted": False,
        "custom_subject_cols": {},
        "custom_reference_cols": {},
        "granularity": "auto",
        "regenerate_fase1": False,
        "skip_spacy": True,
        "run_llm": False,
        "env_ui": {},
        "onboard_section_idx": 0,
        "onboard_section_radio": 0,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val
    if "env_defaults" not in st.session_state:
        st.session_state["env_defaults"] = load_env_defaults()


def _reset_wizard(*, keep_api: bool = True) -> None:
    api_url = st.session_state.get("api_url", DEFAULT_API_URL)
    keys_to_clear = [
        "step",
        "preset_id",
        "subject_bytes",
        "subject_name",
        "reference_bytes",
        "reference_name",
        "catalog_bytes",
        "catalog_name",
        "validation_ok",
        "validation_result",
        "job_id",
        "job_result",
        "poll_count",
        "job_poll_exhausted",
    ]
    for key in keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]
    for key in list(st.session_state.keys()):
        if str(key).startswith("artifact_cache_"):
            del st.session_state[key]
    st.session_state["onboard_section_idx"] = 0
    st.session_state.pop("onboard_section_radio", None)
    st.session_state.pop("onboard_section_pending", None)
    st.session_state.pop("onboard_tab", None)
    _init_session()
    if keep_api:
        st.session_state["api_url"] = api_url


def _client() -> DeparaApiClient:
    return DeparaApiClient(st.session_state.get("api_url", DEFAULT_API_URL))


def _render_stepper(current: int) -> None:
    cols = st.columns(len(STEP_LABELS))
    for i, (col, label) in enumerate(zip(cols, STEP_LABELS, strict=True)):
        with col:
            if i < current:
                st.markdown(f"✅ **{i + 1}. {label}**")
            elif i == current:
                st.markdown(f"▶️ **{i + 1}. {label}**")
            else:
                st.markdown(f"{i + 1}. {label}")


def _new_analysis(*, key: str = "new_analysis") -> None:
    if st.button("Nova análise", type="primary", key=key, use_container_width=True):
        _reset_wizard(keep_api=True)
        st.rerun()


def _ensure_job_result(client: DeparaApiClient, job_id: str):
    from depara.api.schemas import JobStatusResponse

    cached = st.session_state.get("job_result")
    if isinstance(cached, JobStatusResponse) and cached.job_id == job_id:
        return cached
    job = client.get_job(job_id)
    st.session_state["job_result"] = job
    return job


def _sidebar_env_settings() -> None:
    st.sidebar.header("Variáveis de ambiente (LLM)")
    st.sidebar.caption(
        "Campos vazios usam o `.env` do servidor. "
        "O placeholder de cada campo mostra o valor padrão atual."
    )
    defaults = st.session_state.get("env_defaults", load_env_defaults())

    for field in ENV_FIELDS:
        placeholder = env_field_placeholder(field, defaults)
        st.sidebar.text_input(
            field.label,
            placeholder=placeholder,
            help=field.help_text,
            type="password" if field.secret else "default",
            key=f"env_{field.env_key}",
        )
        current = (st.session_state.get(f"env_{field.env_key}") or "").strip()
        if not current:
            caption = env_default_caption(field, defaults)
            if caption:
                st.sidebar.caption(caption)

    ui = {f.env_key: st.session_state.get(f"env_{f.env_key}", "") or "" for f in ENV_FIELDS}
    st.session_state["env_ui"] = ui
    effective = merge_env_overrides(ui)
    if effective:
        st.sidebar.info(f"{len(effective)} override(s) ativo(s) neste job")
    elif defaults.get("OPENAI_API_KEY") or defaults.get("ANTHROPIC_API_KEY"):
        st.sidebar.caption("Credenciais: usando `.env`")
    else:
        st.sidebar.warning("Nenhuma API key no `.env` — configure se for usar LLM")


def _sidebar() -> None:
    st.sidebar.header("Conexão")
    st.session_state["api_url"] = st.sidebar.text_input(
        "URL da API",
        value=st.session_state.get("api_url", DEFAULT_API_URL),
    )
    client = _client()
    if client.health():
        st.sidebar.success("API online")
    else:
        st.sidebar.error("API offline")
        st.sidebar.caption(
            "Suba a API: `uv run uvicorn depara.api.main:app --port 8000` "
            "(evite `--reload` durante jobs longos)"
        )
    docs_url = f"{st.session_state['api_url'].rstrip('/')}/docs"
    st.sidebar.markdown(f"[Documentação OpenAPI]({docs_url})")

    st.sidebar.divider()
    if st.sidebar.button("Ver guia de uso", use_container_width=True):
        st.session_state["step"] = 0
        st.session_state["onboard_section_idx"] = 0
        st.session_state["onboard_section_radio"] = 0
        st.session_state.pop("onboard_section_pending", None)
        st.session_state.pop("onboard_tab", None)
        st.rerun()

    st.sidebar.divider()
    _new_analysis(key="sidebar_new_analysis")

    _sidebar_env_settings()

    st.sidebar.divider()
    st.sidebar.header("Jobs recentes")
    if not client.health():
        st.sidebar.caption("Indisponível — API offline")
        return
    try:
        jobs = client.list_jobs(limit=10)
    except DeparaApiError:
        st.sidebar.caption("Não foi possível listar jobs")
        return
    if not jobs:
        st.sidebar.caption("Nenhum job ainda")
        return
    for job in jobs:
        label = f"{job.status} · {job.job_id[:8]}…"
        if st.sidebar.button(label, key=f"job_{job.job_id}"):
            st.session_state["job_id"] = job.job_id
            st.session_state["job_result"] = job
            st.session_state["step"] = 4
            st.session_state["validation_ok"] = True
            st.session_state["poll_count"] = 0
            st.session_state["job_poll_exhausted"] = False
            st.rerun()


def _file_ok(name: str | None) -> bool:
    if not name:
        return False
    return any(name.lower().endswith(ext) for ext in ALLOWED_EXTENSIONS)


def _step_files() -> None:
    st.subheader("Passo 2 — Arquivos")
    st.caption(
        "Envie o catálogo **sujeito** (Side A) e o catálogo **referência** (Side B) "
        "para comparar preços após depara clínico."
    )

    preset_ids = list(PRESETS.keys())
    labels = [PRESETS[pid].label for pid in preset_ids]
    idx = preset_ids.index(st.session_state.get("preset_id", DEFAULT_PRESET_ID))
    choice = st.radio("Preset", labels, index=idx)
    st.session_state["preset_id"] = preset_ids[labels.index(choice)]
    preset = PRESETS[st.session_state["preset_id"]]
    st.info(preset.description)

    subject = st.file_uploader(
        "Catálogo sujeito (Side A)",
        type=["csv", "xlsx", "xls"],
        help="Linhas clínicas ou SKUs a mapear (ex.: base custo/estoque Global).",
    )
    if subject is not None:
        st.session_state["subject_bytes"] = subject.getvalue()
        st.session_state["subject_name"] = subject.name

    reference = st.file_uploader(
        "Catálogo referência (Side B)",
        type=["csv", "xlsx", "xls"],
        help="Benchmark de preços (ex.: Curva ABC Unimed).",
    )
    if reference is not None:
        st.session_state["reference_bytes"] = reference.getvalue()
        st.session_state["reference_name"] = reference.name

    if preset.needs_catalog:
        with st.expander("O que é o catálogo de enriquecimento?", expanded=True):
            st.markdown(
                """
                **Arquivo:** planilha tipo `BASE_LINHA_PRODUTOS` (cadastro de produtos Global).

                **Para que serve:** o preset *Global compras históricas* traz entradas de compra
                (`global_df`) com **código de produto** e **custo**, mas **sem embalagem
                estruturada** (ex.: `CX C/ 100`, unidade clínica). Este catálogo faz um *join*
                por `COD_PRODUTO` e anexa colunas como `EMBALAGEM`, `UNIDADE` e `UNIDADE_VENDA`.

                **Por que importa:** sem ele, o pipeline ainda roda, porém com menos contexto de
                embalagem para normalizar e auditar preços. Com ele, o enriquecimento fica alinhado
                ao cadastro oficial de SKUs.

                **Por que só neste preset:** no preset *custo/estoque*, a planilha sujeito já
                traz `EMBALAGEM` e custo por unidade clínica — o join seria redundante.
                No *personalizado*, você mapeia manualmente se a planilha já tiver esses campos.
                """
            )
        catalog = st.file_uploader(
            "Catálogo de enriquecimento — BASE_LINHA_PRODUTOS (opcional)",
            type=["csv", "xlsx", "xls"],
            key="catalog_uploader",
            help=(
                "Join por COD_PRODUTO. Recomendado para compras históricas; "
                "omita se a planilha sujeito já tiver embalagem."
            ),
        )
        if catalog is not None:
            st.session_state["catalog_bytes"] = catalog.getvalue()
            st.session_state["catalog_name"] = catalog.name

    can_continue = (
        st.session_state.get("subject_bytes")
        and st.session_state.get("reference_bytes")
        and _file_ok(st.session_state.get("subject_name"))
        and _file_ok(st.session_state.get("reference_name"))
    )
    col1, col2 = st.columns(2)
    with col1:
        if st.button("← Voltar ao guia"):
            st.session_state["step"] = 0
            st.rerun()
    with col2:
        if st.button("Continuar →", type="primary", disabled=not can_continue):
            st.session_state["step"] = 2
            st.session_state["validation_ok"] = False
            st.session_state["validation_result"] = None
            st.rerun()


def _build_config_from_state(preset: Preset) -> JobCreateConfig:
    subj_cols = st.session_state.get("custom_subject_cols") or {}
    ref_cols = st.session_state.get("custom_reference_cols") or {}
    env = merge_env_overrides(st.session_state.get("env_ui", {}))
    return build_job_config(
        preset,
        subject_columns=subj_cols if preset.id == "custom" else None,
        reference_columns=ref_cols if preset.id == "custom" else None,
        granularity=st.session_state.get("granularity", "auto"),
        skip_match=not st.session_state.get("run_llm", False),
        regenerate_fase1=st.session_state.get("regenerate_fase1", False),
        skip_spacy=st.session_state.get("skip_spacy", True),
        env_overrides=env,
    )


def _render_column_picker(side: str, sections: tuple, uploaded_cols: list[str]) -> dict[str, str]:
    """Formulário de mapeamento com selects quando há colunas detectadas."""
    mapped: dict[str, str] = {}
    options = [""] + uploaded_cols

    for section in sections:
        st.markdown(f"**{section.title}**")
        st.caption(section.intro)
        for field in section.fields:
            badge = LEVEL_BADGE.get(field.level, field.level)
            col_a, col_b = st.columns([1, 1])
            with col_a:
                st.markdown(f"{badge} · **{field.title}** (`{field.key}`)")
                st.caption(field.description)
                if field.tip:
                    st.caption(f"💡 {field.tip}")
                if field.examples:
                    st.caption(f"Exemplos: {', '.join(f'`{e}`' for e in field.examples)}")
            with col_b:
                if uploaded_cols:
                    pick = st.selectbox(
                        "Coluna na planilha",
                        options=options,
                        format_func=lambda x: x or "— selecione —",
                        key=f"{side}_sel_{field.key}",
                    )
                    if pick:
                        mapped[field.key] = pick
                else:
                    manual = st.text_input(
                        "Nome da coluna",
                        key=f"{side}_txt_{field.key}",
                        placeholder=field.examples[0] if field.examples else "",
                    )
                    if manual.strip():
                        mapped[field.key] = manual.strip()
        st.divider()
    return mapped


def _show_uploaded_headers() -> tuple[list[str], list[str]]:
    subj_cols: list[str] = []
    ref_cols: list[str] = []
    if st.session_state.get("subject_bytes") and st.session_state.get("subject_name"):
        subj_cols = peek_upload_columns(
            st.session_state["subject_bytes"],
            st.session_state["subject_name"],
        )
    if st.session_state.get("reference_bytes") and st.session_state.get("reference_name"):
        ref_cols = peek_upload_columns(
            st.session_state["reference_bytes"],
            st.session_state["reference_name"],
        )
    if subj_cols or ref_cols:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Colunas detectadas — sujeito**")
            st.code(", ".join(subj_cols) if subj_cols else "(não foi possível ler)")
        with c2:
            st.markdown("**Colunas detectadas — referência**")
            st.code(", ".join(ref_cols) if ref_cols else "(não foi possível ler)")
    return subj_cols, ref_cols


def _step_mapping() -> None:
    st.subheader("Passo 3 — Mapeamento e execução")
    preset = PRESETS[st.session_state["preset_id"]]

    with st.expander("Como funciona o mapeamento?", expanded=preset.id == "custom"):
        st.markdown(
            """
            Cada planilha usa **nomes de coluna diferentes**. O pipeline precisa saber qual coluna
            da sua planilha corresponde a cada **campo canônico** (nome interno fixo).

            - **Sujeito (Side A):** o catálogo que você quer mapear e comparar preços.
            - **Referência (Side B):** benchmark com preço e código (ex.: Curva ABC).

            Campos marcados como **obrigatório** bloqueiam a validação se faltarem.
            **Recomendado** melhora a normalização de preço por embalagem.
            """
        )

    subj_headers, ref_headers = _show_uploaded_headers()

    if preset.id == "custom":
        st.markdown("### Mapeamento manual — sujeito")
        subj_cols = _render_column_picker("subj", SUBJECT_SECTIONS, subj_headers)
        st.session_state["custom_subject_cols"] = subj_cols

        st.markdown("### Mapeamento manual — referência")
        ref_cols = _render_column_picker("ref", REFERENCE_SECTIONS, ref_headers)
        st.session_state["custom_reference_cols"] = ref_cols

        st.session_state["granularity"] = st.selectbox(
            "Granularidade do sujeito",
            ["auto", "sku", "clinical_line"],
            format_func=lambda x: {
                "auto": "Detectar automaticamente",
                "sku": "SKU — várias linhas por produto comercial",
                "clinical_line": "Linha clínica — uma linha por apresentação L2",
            }[x],
            help=(
                "Use SKU se a planilha tem CODPROD + LINHA_PRODUTO repetida. "
                "Use linha clínica se já há uma linha por apresentação."
            ),
        )
    else:
        st.success(f"Preset **{preset.label}** — colunas pré-configuradas.")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Sujeito → colunas**")
            st.dataframe(
                preset_mapping_table(preset.subject.template),
                use_container_width=True,
                hide_index=True,
            )
        with c2:
            st.markdown("**Referência → colunas**")
            st.dataframe(
                preset_mapping_table(preset.reference.template),
                use_container_width=True,
                hide_index=True,
            )
        with st.expander("Detalhes dos campos do preset"):
            subject_keys = set(TEMPLATE_COLUMNS.get(preset.subject.template, {}))
            ref_keys = set(TEMPLATE_COLUMNS.get(preset.reference.template, {}))
            for section in SUBJECT_SECTIONS:
                st.markdown(f"**{section.title}** — {section.intro}")
                for field in section.fields:
                    if field.key in subject_keys:
                        st.markdown(
                            f"- `{field.key}` ({LEVEL_BADGE[field.level]}): {field.description}"
                        )
            st.divider()
            for section in REFERENCE_SECTIONS:
                for field in section.fields:
                    if field.key in ref_keys:
                        st.markdown(
                            f"- `{field.key}` ({LEVEL_BADGE[field.level]}): {field.description}"
                        )

    with st.expander("Opções de execução"):
        st.session_state["regenerate_fase1"] = st.checkbox(
            "Regenerar fase1 (similaridade)",
            value=st.session_state.get("regenerate_fase1", False),
            help="Recalcula fase1_comparison.csv — pode levar vários minutos.",
        )
        if st.session_state["regenerate_fase1"]:
            st.session_state["skip_spacy"] = st.checkbox(
                "Pular similaridade spaCy (mais rápido)",
                value=st.session_state.get("skip_spacy", True),
            )
        st.session_state["run_llm"] = st.checkbox(
            "Executar match LLM",
            value=st.session_state.get("run_llm", False),
        )
        if st.session_state["run_llm"]:
            st.warning(
                "Match LLM consome tempo e requer API key — configure na sidebar "
                "ou no `.env` do servidor."
            )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("← Voltar"):
            st.session_state["step"] = 1
            st.rerun()
    with col2:
        if st.button("Continuar →", type="primary"):
            st.session_state["step"] = 3
            st.session_state["validation_ok"] = False
            st.rerun()


def _show_validation_success(result: ValidateResponse) -> None:
    st.success("Mapeamento válido")
    c1, c2 = st.columns(2)
    with c1:
        st.metric("Linhas sujeito", result.subject.row_count)
        if result.subject.granularity:
            st.caption(f"Granularidade detectada: **{result.subject.granularity}**")
        if result.subject.preview:
            st.dataframe(pd.DataFrame(result.subject.preview), use_container_width=True)
    with c2:
        st.metric("Linhas referência", result.reference.row_count)
        if result.reference.preview:
            st.dataframe(pd.DataFrame(result.reference.preview), use_container_width=True)


def _show_validation_errors(detail: ValidationErrorDetail) -> None:
    st.error("Mapeamento inválido — corrija os campos abaixo")
    rows = []
    for issue in detail.subject_issues:
        rows.append({"lado": "sujeito", **issue})
    for issue in detail.reference_issues:
        rows.append({"lado": "referência", **issue})
    if rows:
        st.table(pd.DataFrame(rows))
    elif detail.raw:
        st.json(detail.raw)


def _step_validate() -> None:
    st.subheader("Passo 4 — Validar")
    preset = PRESETS[st.session_state["preset_id"]]
    config = _build_config_from_state(preset)
    client = _client()

    if not client.health():
        st.error("API offline. Suba o uvicorn antes de validar.")
        return

    col1, col2 = st.columns(2)
    with col1:
        if st.button("← Voltar", key="validate_back"):
            st.session_state["step"] = 2
            st.rerun()

    with col2:
        validate_clicked = st.button("Validar mapeamento", type="secondary")

    if validate_clicked:
        with st.spinner("Validando…"):
            result = client.validate(
                st.session_state["subject_bytes"],
                st.session_state["subject_name"],
                st.session_state["reference_bytes"],
                st.session_state["reference_name"],
                config,
            )
        st.session_state["validation_result"] = result
        st.session_state["validation_ok"] = isinstance(result, ValidateResponse)

    result = st.session_state.get("validation_result")
    if result is not None:
        if isinstance(result, ValidateResponse):
            _show_validation_success(result)
        else:
            _show_validation_errors(result)

    run_disabled = not st.session_state.get("validation_ok") or not client.health()
    if isinstance(result, ValidateResponse):
        st.info(
            estimate_caption(
                regenerate_fase1=st.session_state.get("regenerate_fase1", False),
                skip_spacy=st.session_state.get("skip_spacy", True),
                run_llm=st.session_state.get("run_llm", False),
                subject_rows=result.subject.row_count,
            )
        )
    if st.button("Executar análise →", type="primary", disabled=run_disabled):
        st.session_state["step"] = 4
        st.session_state["job_id"] = None
        st.session_state["job_result"] = None
        st.session_state["poll_count"] = 0
        st.session_state["job_poll_exhausted"] = False
        st.rerun()


def _reset_job_polling() -> None:
    st.session_state["job_result"] = None
    st.session_state["poll_count"] = 0
    st.session_state["job_poll_exhausted"] = False


def _poll_job(client: DeparaApiClient, job_id: str) -> None:
    """Um poll por rerun — evita loop bloqueante que reinicia após timeout."""
    poll_count = st.session_state.get("poll_count", 0) + 1
    st.session_state["poll_count"] = poll_count

    job = client.get_job(job_id)
    pct = progress_percent(job)
    label = progress_label(job)
    detail = progress_detail(job)

    st.progress(pct / 100.0, text=f"{pct}% — {label}")

    elapsed = elapsed_seconds(job.created_at, time.time())
    eta = eta_seconds(elapsed, pct)
    metrics: list[str] = []
    if elapsed is not None:
        metrics.append(f"Decorrido: **{format_duration(elapsed)}**")
    if eta is not None:
        metrics.append(f"Restante estimado: **~{format_duration(eta)}**")
    if detail:
        metrics.append(detail)
    if metrics:
        st.caption(" · ".join(metrics))

    if job.status in ("completed", "failed"):
        st.session_state["job_result"] = job
        st.session_state["poll_count"] = 0
        st.session_state["job_poll_exhausted"] = False
        st.rerun()
        return

    if poll_count >= MAX_JOB_POLLS:
        st.session_state["job_poll_exhausted"] = True
        st.warning(
            f"Tempo máximo de acompanhamento ({MAX_WAIT_MINUTES} min) esgotado. "
            "O job pode ainda estar rodando na API — recarregue ou use **Reexecutar**."
        )
        return

    time.sleep(POLL_INTERVAL_SEC)
    st.rerun()


def _render_job_failed(client: DeparaApiClient, job_id: str, error: str | None) -> None:
    st.error(f"Job falhou: {error or 'erro desconhecido'}")
    st.caption("Veja os logs do terminal onde o uvicorn está rodando.")
    if st.button("Reexecutar job", type="primary", key="retry_failed_job"):
        try:
            job = client.retry_job(job_id)
        except DeparaApiError as exc:
            st.error(str(exc))
            return
        st.session_state["job_id"] = job.job_id
        _reset_job_polling()
        st.rerun()


def _fetch_artifact_cache(
    client: DeparaApiClient,
    job_id: str,
    names: tuple[str, ...],
) -> dict[str, bytes]:
    cache_key = f"artifact_cache_{job_id}"
    cached: dict[str, bytes] = st.session_state.get(cache_key, {})
    for name in names:
        if name not in cached:
            try:
                cached[name] = client.fetch_artifact_bytes(job_id, name)
            except DeparaApiError:
                continue
    st.session_state[cache_key] = cached
    return cached


def _render_downloads_panel(client: DeparaApiClient, job_id: str) -> None:
    st.markdown("### Downloads")
    artifacts = (
        ("price_report.xlsx", "Relatório Excel", "Planilha completa para análise", "primary"),
        ("price_report.html", "Relatório HTML", "Relatório interativo offline", "primary"),
        ("price_report.csv", "CSV preços", "Dados tabulares do comparativo", "secondary"),
        ("matches.csv", "Matches LLM", "Depara clínico aprovado", "secondary"),
    )
    names = tuple(a[0] for a in artifacts)
    data_by_name = _fetch_artifact_cache(client, job_id, names)

    with st.container(border=True):
        st.caption("Artefatos gerados nesta análise — clique para baixar.")
        row1 = st.columns(2)
        row2 = st.columns(2)
        rows = (row1, row2)
        for idx, (filename, title, desc, kind) in enumerate(artifacts):
            with rows[idx // 2][idx % 2]:
                payload = data_by_name.get(filename)
                if payload is None:
                    st.warning(f"**{title}** — indisponível")
                    continue
                mime = (
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    if filename.endswith(".xlsx")
                    else "text/html" if filename.endswith(".html") else "text/csv"
                )
                st.markdown(f"**{title}**")
                st.caption(desc)
                st.download_button(
                    f"Baixar {filename}",
                    data=payload,
                    file_name=filename,
                    mime=mime,
                    type="primary" if kind == "primary" else "secondary",
                    use_container_width=True,
                    key=f"dl_panel_{job_id}_{filename}",
                )


def _render_results(client: DeparaApiClient, job_id: str) -> None:
    report_html_url = artifact_url(
        st.session_state.get("api_url", DEFAULT_API_URL),
        job_id,
        "price_report.html",
    )

    header_left, header_right = st.columns([3, 1])
    with header_left:
        st.success(f"Análise concluída · job `{job_id[:8]}…`")
    with header_right:
        _new_analysis(key="results_new_analysis")

    try:
        summary_bytes = client.fetch_artifact_bytes(job_id, "summary.json")
        summary = json.loads(summary_bytes)
    except DeparaApiError:
        summary = {}

    if summary:
        st.subheader("Indicadores")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(
            "Oportunidade/mês (plausível)",
            f"R$ {summary.get('oportunidade_mensal_rs_plausivel', 0):,.2f}",
        )
        c2.metric(
            "Risco/mês (plausível)",
            f"R$ {summary.get('risco_mensal_rs_plausivel', 0):,.2f}",
        )
        c3.metric("Linhas no relatório", summary.get("report_linhas", "—"))
        c4.metric(
            "Linhas plausíveis",
            summary.get("report_linhas_projecao_plausivel", "—"),
        )

    _render_downloads_panel(client, job_id)

    st.subheader("Relatório interativo")
    html_bytes = _fetch_artifact_cache(client, job_id, ("price_report.html",)).get(
        "price_report.html"
    )
    if html_bytes is None:
        st.warning("Relatório HTML ainda não disponível.")
        return

    open_col, _ = st.columns([1, 2])
    with open_col:
        st.link_button(
            "Abrir em nova aba",
            report_html_url,
            type="secondary",
            use_container_width=True,
            help="Visualização em tela cheia — ideal para apresentar.",
        )

    st.markdown(IFRAME_CHROME_CSS, unsafe_allow_html=True)
    html = html_bytes.decode("utf-8")
    st.components.v1.html(
        prepare_html_for_embed(html),
        height=estimate_report_height(html),
        scrolling=False,
    )


def _step_results() -> None:
    st.subheader("Passo 5 — Resultado")
    client = _client()

    if not client.health():
        st.error("API offline")
        return

    top_left, top_right = st.columns([3, 1])
    with top_right:
        _new_analysis(key="step_results_new_analysis")

    job_id = st.session_state.get("job_id")
    job_result = st.session_state.get("job_result")

    if st.session_state.get("job_poll_exhausted") and job_id:
        st.warning("Polling interrompido por timeout.")
        if st.button("Reexecutar job", type="primary", key="retry_exhausted_job"):
            try:
                job = client.retry_job(job_id)
            except DeparaApiError as exc:
                st.error(str(exc))
                return
            st.session_state["job_id"] = job.job_id
            _reset_job_polling()
            st.rerun()
        if st.button("← Voltar para validação"):
            st.session_state["step"] = 3
            _reset_job_polling()
            st.session_state["job_id"] = None
            st.rerun()
        return

    if job_id is None:
        preset = PRESETS[st.session_state["preset_id"]]
        config = _build_config_from_state(preset)
        with st.spinner("Enviando job…"):
            try:
                job = client.create_job(
                    st.session_state["subject_bytes"],
                    st.session_state["subject_name"],
                    st.session_state["reference_bytes"],
                    st.session_state["reference_name"],
                    config,
                    catalog_bytes=st.session_state.get("catalog_bytes"),
                    catalog_name=st.session_state.get("catalog_name"),
                )
            except DeparaApiError as exc:
                st.error(str(exc))
                if exc.detail:
                    st.json(exc.detail)
                return
        st.session_state["job_id"] = job.job_id
        _reset_job_polling()
        job_id = job.job_id
        job_result = None

    if job_id and (
        job_result is None
        or getattr(job_result, "job_id", None) != job_id
    ):
        job_result = _ensure_job_result(client, job_id)

    if job_result.status not in ("completed", "failed"):
        estimate = estimate_caption(
            regenerate_fase1=st.session_state.get("regenerate_fase1", False),
            skip_spacy=st.session_state.get("skip_spacy", True),
            run_llm=st.session_state.get("run_llm", False),
            subject_rows=(
                st.session_state.get("validation_result").subject.row_count
                if isinstance(st.session_state.get("validation_result"), ValidateResponse)
                else None
            ),
        )
        with st.status("Processando análise…", expanded=True):
            st.caption(estimate)
            _poll_job(client, job_id)
        return

    if job_result.status == "failed":
        _render_job_failed(client, job_id, job_result.error)
    else:
        _render_results(client, job_id)


def main() -> None:
    st.set_page_config(
        page_title="Depara — Global × Referência",
        page_icon="💊",
        layout="wide",
    )
    _init_session()
    _sidebar()

    st.title("Depara clínico + comparativo de preços")
    _render_stepper(st.session_state["step"])

    step = st.session_state["step"]
    if step == 0:
        render_onboarding_step()
    elif step == 1:
        _step_files()
    elif step == 2:
        _step_mapping()
    elif step == 3:
        _step_validate()
    elif step == 4:
        _step_results()


if __name__ == "__main__":
    main()
