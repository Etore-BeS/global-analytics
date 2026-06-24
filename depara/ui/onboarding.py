"""Passo educativo inicial do wizard — guia para analistas e farmacêuticos."""

from __future__ import annotations

from collections.abc import Callable

import streamlit as st

ONBOARD_TAB_LABELS: tuple[str, ...] = (
    "Visão geral",
    "Preparar planilhas",
    "Escolher preset",
    "Interpretar resultados",
    "Checklist",
)

_STATE_IDX = "onboard_section_idx"
_STATE_RADIO = "onboard_section_radio"
_STATE_PENDING = "onboard_section_pending"


def _ensure_onboard_state() -> None:
    """Estado do guia — chaves distintas do widget radio (evita conflito Streamlit)."""
    if "onboard_tab" in st.session_state:
        st.session_state.pop("onboard_tab", None)
    if _STATE_IDX not in st.session_state:
        st.session_state[_STATE_IDX] = 0
    if _STATE_RADIO not in st.session_state:
        st.session_state[_STATE_RADIO] = st.session_state[_STATE_IDX]


def _apply_pending_section() -> None:
    pending = st.session_state.pop(_STATE_PENDING, None)
    if pending is None:
        return
    clamped = max(0, min(int(pending), len(ONBOARD_TAB_LABELS) - 1))
    st.session_state[_STATE_IDX] = clamped
    st.session_state[_STATE_RADIO] = clamped


def _queue_section(target: int) -> None:
    st.session_state[_STATE_PENDING] = target
    st.rerun()


def render_onboarding_step() -> None:
    st.subheader("Passo 1 — Guia de uso")
    st.caption(
        "Leia antes de enviar planilhas. Escrito para analistas financeiros e farmacêuticos "
        "de qualquer distribuidora — sem exigir conhecimento de sistemas internos."
    )

    _ensure_onboard_state()
    _apply_pending_section()

    st.radio(
        "Seção do guia",
        options=list(range(len(ONBOARD_TAB_LABELS))),
        format_func=lambda i: ONBOARD_TAB_LABELS[i],
        horizontal=True,
        label_visibility="collapsed",
        key=_STATE_RADIO,
    )

    radio_idx = int(st.session_state[_STATE_RADIO])
    if radio_idx != st.session_state[_STATE_IDX]:
        st.session_state[_STATE_IDX] = radio_idx
        st.rerun()

    idx = int(st.session_state[_STATE_IDX])

    st.divider()
    _render_onboard_panel(idx)
    st.divider()

    _render_onboard_nav(idx)


def _render_onboard_panel(idx: int) -> None:
    panels: tuple[Callable[[], None], ...] = (
        _tab_visao_geral,
        _tab_preparar_arquivos,
        _tab_escolher_preset,
        _tab_interpretar_resultados,
        _tab_checklist,
    )
    panels[idx]()


def _render_onboard_nav(idx: int) -> None:
    last = len(ONBOARD_TAB_LABELS) - 1
    col_prev, col_next = st.columns(2)

    with col_prev:
        if idx > 0 and st.button("← Seção anterior", use_container_width=True, key="onboard_prev"):
            _queue_section(idx - 1)

    with col_next:
        if idx < last:
            next_label = f"Próximo: {ONBOARD_TAB_LABELS[idx + 1]} →"
            if st.button(next_label, type="primary", use_container_width=True, key="onboard_next"):
                _queue_section(idx + 1)
        elif st.button(
            "Entendi — enviar arquivos →",
            type="primary",
            use_container_width=True,
            key="onboard_done",
        ):
            st.session_state.pop(_STATE_PENDING, None)
            st.session_state["step"] = 1
            st.rerun()


def _tab_visao_geral() -> None:
    st.markdown(
        """
        ### O que esta ferramenta faz?

        Responde: *Para cada medicamento da **minha distribuidora**, pago **mais ou menos**
        que um **benchmark** — e qual o **impacto em R$/mês**?*

        **Etapa 1 — Depara clínico:** traduz “mesmo produto, códigos diferentes” entre catálogos.

        **Etapa 2 — Comparativo de preços:** compara custo seu vs referência, normalizado por
        unidade clínica (comprimido, ampola…), e calcula **oportunidade** e **risco**.
        """
    )
    st.markdown("**Vocabulário mínimo**")
    st.table(
        {
            "Termo": [
                "Sujeito (Side A)",
                "Referência (Side B)",
                "Linha clínica (L2)",
                "SKU",
                "Depara",
                "Gap",
                "Oportunidade",
                "Risco",
            ],
            "Significado": [
                "Seu catálogo — o que você analisa",
                "Benchmark de preços (ex.: curva ABC)",
                "Apresentação: princípio + dose + forma",
                "Produto comercial com marca/embalagem",
                "Vínculo clínico entre seu item e o benchmark",
                "Diferença % entre seu custo e a referência",
                "Você paga menos → potencial competitivo",
                "Você paga mais → reprecificar ou renegociar",
            ],
        }
    )
    st.markdown(
        """
        **O que você não precisa:** programar, usar os mesmos nomes de coluna dos exemplos
        Global/Unimed, ou rodar IA na primeira análise (pode reutilizar depara existente).
        """
    )


def _tab_preparar_arquivos() -> None:
    st.markdown("### Dois arquivos obrigatórios (CSV ou Excel)")
    st.markdown("#### 1. Catálogo sujeito — sua distribuidora")
    st.table(
        {
            "Conceito": [
                "Descrição clínica",
                "Código interno",
                "Custo / preço entrada",
                "Embalagem",
                "Estoque",
            ],
            "Exemplos de coluna": [
                "LINHA_PRODUTO, Descrição",
                "CODPROD, SKU",
                "CUSTOREAL, Custo",
                "EMBALAGEM, Pack",
                "ESTOQUE, Saldo",
            ],
            "Uso": [
                "Identificar medicamento no depara",
                "Diferenciar marcas",
                "Base da comparação",
                "Normalizar R$/unidade",
                "Priorizar SKUs com giro",
            ],
        }
    )
    st.markdown("#### 2. Catálogo referência — benchmark")
    st.table(
        {
            "Conceito": [
                "Código do item",
                "Descrição",
                "Preço referência",
                "Volume previsto",
            ],
            "Exemplos de coluna": [
                "Cod Item, Código",
                "Desc Item, Produto",
                "VL Médio, Preço ref",
                "Prev Mês, Consumo",
            ],
            "Uso": [
                "Chave do benchmark",
                "Conferência humana",
                "Preço de comparação",
                "Projetar R$/mês",
            ],
        }
    )
    st.markdown(
        """
        #### Opcional — Catálogo de enriquecimento

        Só no preset **compras históricas**: cadastro mestre com embalagem (`CX C/ 100`)
        quando o histórico de compras não traz essas colunas. Join por código de produto.

        #### Dicas

        - Uma linha = um SKU ou linha clínica (sem totais agregados).
        - Primeira linha = cabeçalho com nomes de coluna.
        - Custos numéricos; descrições com princípio, dose e forma.
        - Exporte dados brutos do ERP, não relatório com células mescladas.
        """
    )


def _tab_escolher_preset() -> None:
    st.markdown("### Qual preset escolher?")
    st.table(
        {
            "Preset": [
                "Custo/estoque × ABC",
                "Compras históricas × ABC",
                "Personalizado",
            ],
            "Use quando": [
                "Snapshot: custo, estoque por SKU hoje",
                "Histórico de entradas de compra",
                "Layout de colunas diferente dos exemplos",
            ],
            "Arquivo sujeito típico": [
                "Extrato custo + estoque (WMS/ERP)",
                "Relatório de compras + catálogo embalagem",
                "Qualquer planilha — mapeamento manual",
            ],
        }
    )
    st.markdown(
        """
        **Referência:** nos exemplos Global×Unimed é uma Curva ABC. Outro benchmark → preset
        **Personalizado** e mapeie colunas no passo 3.

        **Opções avançadas (Mapeamento):**

        - *Regenerar fase1* — recalcula similaridade (demorado).
        - *Match LLM* — IA revisa pares clínicos (requer API key).
        - Primeira análise: deixe LLM desligado se já houver depara salvo.
        """
    )


def _tab_interpretar_resultados() -> None:
    st.markdown("### Artefatos gerados")
    st.table(
        {
            "Arquivo": ["Relatório HTML", "Excel / CSV", "Matches"],
            "Público": ["Diretoria, compras", "Analista financeiro", "Farmacêutico"],
            "Uso": [
                "KPIs, gráficos, filtros",
                "Pivot e auditoria linha a linha",
                "Pares clínicos aceitos no depara",
            ],
        }
    )
    st.markdown(
        """
        ### Indicadores no topo

        - **Oportunidade/mês (plausível)** — economia potencial vs benchmark.
        - **Risco/mês (plausível)** — quanto você paga a mais.
        - **Linhas plausíveis** — linhas com sanidade de preço OK.

        ### Gap

        - Negativo → custo **abaixo** do benchmark → **oportunidade**.
        - Positivo → custo **acima** → **risco**.

        Preços são comparados em **R$/unidade clínica**, não R$/caixa.

        ### Flags de atenção

        - Match baixa confiança → validar com farmacêutico.
        - Gap extremo → possível erro de embalagem ou depara.
        - Sem depara → item sem par no benchmark.

        ### Próximos passos

        1. Filtrar oportunidades por volume.
        2. Validar riscos com compras.
        3. Exportar Excel para renegociação.
        """
    )


def _tab_checklist() -> None:
    st.markdown("### Antes de enviar arquivos, confira:")
    checks = [
        "Tenho **dois arquivos**: sujeito + referência (benchmark).",
        "Primeira linha = **cabeçalho** com nomes de coluna.",
        "Sujeito tem **descrição clínica** e **custo numérico**.",
        "Referência tem **código**, **descrição** e **preço**.",
        "Compras históricas: tenho ou sei que preciso do **catálogo de embalagem**.",
        "Escolhi o **preset** mais parecido com meus dados.",
        "API **online** (verde na sidebar).",
    ]
    for i, item in enumerate(checks):
        st.checkbox(item, key=f"onboard_check_{i}")

    st.info(
        "Não precisa marcar todos para avançar. O passo **Validar** aponta colunas faltantes."
    )
