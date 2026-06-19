"""Schemas Pydantic para o match LLM (pydantic-ai output_type)."""

from __future__ import annotations

import ast
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MatchDecision(StrEnum):
    MATCH = "match"
    NO_MATCH = "no_match"


class GlobalCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cod_item: int = Field(description="Código do item no catálogo Unimed/Curva ABC")
    desc_global: str = Field(description="Descrição do item no catálogo Unimed")
    abc: str | None = Field(default=None, description="Classificação ABC")
    vl_medio: float | None = Field(
        default=None,
        description="VL Médio (R$) de referência Unimed para este cod_item",
    )
    unidade: str | None = Field(default=None, description="Unidade de venda Unimed (Un)")
    vl_por_unidade: float | None = Field(
        default=None,
        description="VL Médio normalizado por unidade (ex.: caixa c/100 → VL/100)",
    )


class UnimedLinhaInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    linha_produto: str = Field(description="Apresentação clínica Unimed (LINHA_PRODUTO)")
    principio_ativo: str = Field(description="Princípio ativo cadastrado na Unimed")
    n_skus: int = Field(description="Quantidade de SKUs/marcas nessa linha")
    marcas: list[str] = Field(default_factory=list, description="Marcas disponíveis na Unimed")
    descricoes_amostra: list[str] = Field(
        default_factory=list,
        description="Amostra de descrições comerciais (DESCRICAO_PRODUTO)",
    )
    custo_mediano: float | None = Field(
        default=None,
        description="Mediana de CUSTO_ENTRADA (R$/un) nas compras Global desta linha",
    )
    custo_medio: float | None = Field(
        default=None,
        description="Média de CUSTO_ENTRADA (R$/un) nas compras Global desta linha",
    )
    custo_min: float | None = Field(default=None, description="Mínimo CUSTO_ENTRADA Global")
    custo_max: float | None = Field(default=None, description="Máximo CUSTO_ENTRADA Global")
    match_anterior_cod_item: int | None = Field(
        default=None, description="cod_item do match anterior rejeitado por preço"
    )
    match_anterior_desc: str | None = Field(default=None, description="Descrição do match anterior")
    match_anterior_vl_medio: float | None = Field(default=None, description="VL Médio do match anterior")


class LLMMatchOutput(BaseModel):
    """Resposta estruturada do agente — escolha entre os candidatos fornecidos."""

    model_config = ConfigDict(extra="forbid")

    decision: MatchDecision = Field(
        description="match se houver candidato Global equivalente; no_match caso contrário"
    )
    cod_item: int | None = Field(
        default=None,
        description="Cod Item Global escolhido; omitir ou null quando decision=no_match",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confiança no match (0=nenhuma, 1=certeza)",
    )
    reasoning: str = Field(
        description="Justificativa curta: princípio, dose, forma, via e volume comparados"
    )

    @model_validator(mode="after")
    def decision_matches_cod_item(self) -> Self:
        if self.decision == MatchDecision.MATCH and self.cod_item is None:
            raise ValueError("cod_item é obrigatório quando decision=match")
        if self.decision == MatchDecision.NO_MATCH and self.cod_item is not None:
            raise ValueError("cod_item deve ser null quando decision=no_match")
        return self


def parse_list_field(value: object) -> list[str]:
    """Parse list columns from DataFrame (list, CSV repr, or scalar)."""
    if value is None or (isinstance(value, float) and value != value):
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            try:
                parsed = ast.literal_eval(text)
                if isinstance(parsed, list):
                    return [str(v) for v in parsed]
            except (SyntaxError, ValueError):
                pass
        return [text] if text else []
    if hasattr(value, "__iter__"):
        return [str(v) for v in value]
    return [str(value)]


def output_cod_item(output: LLMMatchOutput) -> int | None:
    return output.cod_item if output.decision == MatchDecision.MATCH else None


class MatchRecord(BaseModel):
    """Resultado enriquecido para export (teste ou produção)."""

    model_config = ConfigDict(extra="forbid")

    linha_produto: str
    principio_ativo: str
    n_skus: int
    marcas: list[str]
    decision: MatchDecision
    cod_item: int | None
    desc_global: str | None
    confidence: float
    reasoning: str
    n_candidates: int
    candidate_cod_items: list[int]
    model: str
    cached: bool = False
    error: str | None = None
    run_pass: str = "initial"
