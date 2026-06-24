"""Textos didáticos e metadados para mapeamento de colunas na UI."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Literal

import pandas as pd
from depara.contract.models import TemplateId
from depara.contract.templates import TEMPLATE_COLUMNS

Requirement = Literal["obrigatório", "recomendado", "opcional", "condicional"]


@dataclass(frozen=True)
class FieldHelp:
    key: str
    title: str
    description: str
    level: Requirement
    examples: tuple[str, ...]
    tip: str = ""


@dataclass(frozen=True)
class MappingSection:
    title: str
    intro: str
    fields: tuple[FieldHelp, ...]


SUBJECT_SECTIONS: tuple[MappingSection, ...] = (
    MappingSection(
        title="Identidade clínica",
        intro=(
            "O depara compara **linhas clínicas** (L2): princípio + dose + forma. "
            "Se sua planilha tem várias marcas/SKUs por linha, informe também o código do produto."
        ),
        fields=(
            FieldHelp(
                key="display_text",
                title="Texto clínico (linha L2)",
                description=(
                    "Descrição da apresentação clínica usada no matching. "
                    "É o campo mais importante — fuzzy, TF-IDF e LLM leem este texto."
                ),
                level="obrigatório",
                examples=("LINHA_PRODUTO", "Descricao_Clinica", "Apresentacao"),
                tip="Deve ser estável por linha clínica, não por marca comercial.",
            ),
            FieldHelp(
                key="product_code",
                title="Código do produto (SKU)",
                description=(
                    "Identificador comercial único. Obrigatório se a planilha tem "
                    "várias linhas por produto (modo SKU). Usado para agregar custos por linha."
                ),
                level="condicional",
                examples=("CODPROD", "COD_PRODUTO", "Sku"),
            ),
            FieldHelp(
                key="principio_ativo",
                title="Princípio ativo",
                description=(
                    "Acelera a fase1. Se ausente, o sistema tenta extrair do texto clínico."
                ),
                level="opcional",
                examples=("PRINCIPIO_ATIVO", "Principio"),
            ),
            FieldHelp(
                key="brand",
                title="Marca",
                description="Aparece no relatório e na priorização LLM.",
                level="opcional",
                examples=("MARCA", "Fabricante"),
            ),
        ),
    ),
    MappingSection(
        title="Preço e estoque (sujeito)",
        intro=(
            "Escolha **um** caminho: coluna única de compra (`price_amount`) **ou** par "
            "custo real + última entrada (`cost_real` + `cost_last_entry`) "
            "para snapshot de estoque."
        ),
        fields=(
            FieldHelp(
                key="price_amount",
                title="Preço/custo de compra",
                description=(
                    "Histórico de entradas: uma coluna com valor por unidade clínica. "
                    "Use quando cada linha é uma transação de compra."
                ),
                level="condicional",
                examples=("CUSTO_ENTRADA", "Preco_Compra", "Valor"),
            ),
            FieldHelp(
                key="cost_real",
                title="Custo real (estoque)",
                description=(
                    "Snapshot: custo atual por unidade clínica. "
                    "Par com cost_last_entry no modo dual."
                ),
                level="condicional",
                examples=("CUSTOREAL", "Custo_Real"),
            ),
            FieldHelp(
                key="cost_last_entry",
                title="Último custo de entrada",
                description=(
                    "Snapshot: último preço pago na última NF. "
                    "Comparado como referência secundária."
                ),
                level="condicional",
                examples=("CUSTOULTENT", "Ultimo_Custo"),
            ),
            FieldHelp(
                key="stock_qty",
                title="Quantidade em estoque",
                description=(
                    "Filtra SKUs elegíveis na política “mínimo com estoque”. "
                    "Necessário quando usa cost_real em base de estoque."
                ),
                level="condicional",
                examples=("ESTOQUE_DISPONIVEL", "Estoque", "Qtd"),
            ),
            FieldHelp(
                key="entry_date",
                title="Data da entrada",
                description="Histórico de compras: ordena entradas para calcular “último custo”.",
                level="opcional",
                examples=("DT_ENTRADA", "Data_Compra"),
            ),
        ),
    ),
    MappingSection(
        title="Embalagem e unidade",
        intro=(
            "Normalizam preço para **R$/unidade clínica** (ampola, comprimido…). "
            "Sem estes campos, comparações podem ficar distorcidas quando o preço é por caixa."
        ),
        fields=(
            FieldHelp(
                key="pack_description",
                title="Descrição da embalagem",
                description=(
                    'Texto com "cx c/50", "pct c/100" etc. '
                    "Usado para dividir preço por unidade."
                ),
                level="recomendado",
                examples=("EMBALAGEM", "Embalagem", "Pack"),
            ),
            FieldHelp(
                key="clinical_unit",
                title="Unidade clínica",
                description="Unidade de uso: AP, CP, FR, UN…",
                level="recomendado",
                examples=("UNIDADE", "Un", "Unidade_Clinica"),
            ),
            FieldHelp(
                key="sale_unit",
                title="Unidade de venda",
                description="Desambigua quando difere da unidade clínica.",
                level="opcional",
                examples=("UNIDADE_VENDA", "Un_Venda"),
            ),
        ),
    ),
)

REFERENCE_SECTIONS: tuple[MappingSection, ...] = (
    MappingSection(
        title="Catálogo de referência (benchmark)",
        intro=(
            "Uma linha por item de referência. O `canonical_id` vira o código no relatório final. "
            "O `display_text` alimenta o matching; o `price_amount` é o preço benchmark."
        ),
        fields=(
            FieldHelp(
                key="canonical_id",
                title="ID canônico",
                description=(
                    "Código estável do item na referência (ex.: Cod Item Unimed). "
                    "Deve ser único."
                ),
                level="obrigatório",
                examples=("Cod Item", "cod_item", "ID"),
            ),
            FieldHelp(
                key="display_text",
                title="Descrição para matching",
                description="Texto comparado com a linha clínica do sujeito.",
                level="obrigatório",
                examples=("Desc Item", "Descricao", "Produto"),
            ),
            FieldHelp(
                key="price_amount",
                title="Preço benchmark",
                description=(
                    "Valor médio ou contrato de referência. "
                    "Normalizado por embalagem quando necessário."
                ),
                level="obrigatório",
                examples=("VL Médio (R$)", "Preco_Medio", "Valor"),
            ),
            FieldHelp(
                key="clinical_unit",
                title="Unidade",
                description="Ajuda a interpretar se o preço é por caixa ou por unidade clínica.",
                level="recomendado",
                examples=("Un", "Unidade"),
            ),
            FieldHelp(
                key="volume_previsto",
                title="Volume previsto (mês)",
                description=(
                    "Quantidade mensal estimada — usada para calcular "
                    "impacto R$ (oportunidade/risco)."
                ),
                level="opcional",
                examples=("Prev Mês", "Volume_Mes", "Qtd_Prevista"),
            ),
            FieldHelp(
                key="abc_class",
                title="Classe ABC",
                description="Repassada ao relatório quando disponível.",
                level="opcional",
                examples=("ABC", "Curva"),
            ),
            FieldHelp(
                key="policy",
                title="Política de compra",
                description="Metadado opcional da Curva ABC.",
                level="opcional",
                examples=("Política", "Politica_Compra"),
            ),
        ),
    ),
)

LEVEL_BADGE = {
    "obrigatório": "🔴 Obrigatório",
    "recomendado": "🟡 Recomendado",
    "opcional": "⚪ Opcional",
    "condicional": "🟠 Condicional",
}


def field_by_key(sections: tuple[MappingSection, ...], key: str) -> FieldHelp | None:
    for section in sections:
        for field in section.fields:
            if field.key == key:
                return field
    return None


def preset_mapping_table(template: TemplateId) -> pd.DataFrame:
    """Tabela canônico → coluna física do preset."""
    cols = TEMPLATE_COLUMNS.get(template, {})
    if not cols:
        return pd.DataFrame(columns=["Campo canônico", "Coluna na planilha", "Nível"])
    rows = []
    sections = SUBJECT_SECTIONS if template != "unimed_abc" else REFERENCE_SECTIONS
    for canonical, physical in cols.items():
        help_ = field_by_key(sections, canonical)
        rows.append(
            {
                "Campo canônico": canonical,
                "Coluna na planilha": physical,
                "Nível": help_.level if help_ else "—",
                "Para quê": help_.title if help_ else "",
            }
        )
    return pd.DataFrame(rows)


def peek_upload_columns(data: bytes, filename: str) -> list[str]:
    """Lista cabeçalhos do arquivo enviado (para ajudar no mapeamento manual)."""
    buf = BytesIO(data)
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    try:
        if suffix in {"xlsx", "xls"}:
            df = pd.read_excel(buf, nrows=0)
        else:
            df = pd.read_csv(buf, encoding="latin-1", nrows=0)
    except Exception:  # noqa: BLE001
        return []
    return [str(c) for c in df.columns]
