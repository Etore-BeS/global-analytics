"""Prompt e agente para reanálise de depara com divergência de preço."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic_ai import Agent, ModelRetry, RunContext

from depara.llm.agent import _build_model
from depara.llm.config import DeparaLLMSettings
from depara.llm.schemas import LLMMatchOutput, MatchDecision

REANALYZE_SYSTEM_PROMPT = """\
Você refaz depara entre preços Global (distribuidor, global_df.csv) e Unimed (compras, Curva ABC).

CONTEXTO DESTA RODADA:
- O match anterior foi REJEITADO porque o preço não bate (produto errado, unidade errada ou dose/embalagem diferente).
- Você recebe custo Global (mediana R$/un de compra) e candidatos Unimed com VL Médio, unidade de venda e VL/un normalizado.

REGRAS CLÍNICAS (obrigatório):
1. Mesma substância / mesmo insumo com mesmas especificações (calibre, tamanho, volume, dose, via, forma).
2. Spray nasal ≠ solução IV. Eletrodo ECG ≠ pulseira de identificação. Luva vinil ≠ luva nitrílica (salvo equivalência explícita).
3. Dispositivo de incontinência ≠ medicamento biológico (ex.: skyrizi).
4. Não repita o match anterior se o preço prova que era produto diferente.

REGRAS DE PREÇO (crítico — use para validar o produto):
5. Compare custo Global (R$/un comprada) com VL/un normalizado do candidato Unimed.
6. Unimed frequentemente cotiza CAIXA/KIT (ex.: cx c/100 → divida VL por 100). Global quase sempre compra por UNIDADE.
7. Preços compatíveis: ratio VL/un ÷ custo Global entre ~0,3× e 3× após normalizar embalagem.
8. Ratio >5× ou <0,2× após normalizar → produto ou unidade errada — descarte o candidato.
9. Se NENHUM candidato passar clínica + preço, retorne no_match (não force match).

MATCH ANTERIOR REJEITADO:
- Trate como negativo: explique por que estava errado (produto, unidade ou embalagem).

FORMATO:
- decision="match": cod_item de UM candidato listado.
- decision="no_match": sem cod_item — preferível a match errado.
- reasoning: cite comparação clínica E comparação de preço/un (valores numéricos).
"""


@dataclass(frozen=True)
class MatchDeps:
    valid_cod_items: frozenset[int]


def build_reanalyze_agent(settings: DeparaLLMSettings) -> Agent[MatchDeps, LLMMatchOutput]:
    reanalyze_settings = settings.model_copy(update={"model": settings.reanalyze_model})
    reanalyze_settings.require_api_key()
    agent: Agent[MatchDeps, LLMMatchOutput] = Agent(
        model=_build_model(reanalyze_settings),
        output_type=LLMMatchOutput,
        deps_type=MatchDeps,
        system_prompt=REANALYZE_SYSTEM_PROMPT,
        retries=2,
    )

    @agent.output_validator
    def validate_cod_item(
        ctx: RunContext[MatchDeps], output: LLMMatchOutput
    ) -> LLMMatchOutput:
        if output.decision == MatchDecision.MATCH and output.cod_item not in ctx.deps.valid_cod_items:
            valid = sorted(ctx.deps.valid_cod_items)
            raise ModelRetry(
                f"cod_item={output.cod_item} não está entre os candidatos válidos: {valid}. "
                "Escolha um cod_item da lista ou retorne decision=no_match."
            )
        return output

    return agent


def build_reanalyze_user_prompt(item_text: str, candidates_text: str) -> str:
    return (
        f"{item_text}\n\n"
        f"Candidatos Unimed (escolha UM cod_item ou no_match):\n"
        f"{candidates_text}"
    )
