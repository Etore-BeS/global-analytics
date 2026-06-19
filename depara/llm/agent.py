"""Agent pydantic-ai para match clínico Unimed ↔ Global."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.models.test import TestModel

from depara.llm.config import DeparaLLMSettings
from depara.llm.schemas import LLMMatchOutput, MatchDecision

SYSTEM_PROMPT = """\
Você faz depara de produtos hospitalares/farmacêuticos entre dois catálogos.

CONTEXTO:
- GLOBAL (distribuidora): linhas clínicas e preços vêm do CSV global_df.csv (CUSTO_ENTRADA).
  Várias marcas/SKUs Global podem compartilhar a mesma linha clínica.
- UNIMED (compras): catálogo de referência é a Curva ABC (XLSX), coluna VL Médio (R$).
  Cada cod_item Unimed é uma apresentação clínica sem marca.
- Objetivo do depara: linha clínica GLOBAL → cod_item UNIMED equivalente.

REGRAS DE MATCH:
1. Mesma substância ou produto equivalente clínico.
2. Mesma dose/concentração (ex: 500mg/ml ≠ 500mg comprimido).
3. Mesma forma farmacêutica (comprimido, sol inj, xarope, etc.).
4. Mesma via quando relevante (IV, oral, nasal, tópico).
5. Volume/embalagem compatível quando especificado.
6. Marcas/nomes comerciais IGNORADOS — compare apresentação clínica.
7. Insumos (agulhas, cateteres, campos): match só se especificações compatíveis.
8. PREÇO: quando informado o custo Global (mediana R$/un), o VL Médio Unimed do
   candidato deve estar na faixa ~0,25× a 4× desse valor. Se todos os candidatos
   clínicos plausíveis violarem essa faixa, retorne no_match — preço divergente
   demais indica produto, dose, embalagem ou unidade incompatível (ex.: caixa vs
   unidade, saco autoclave vs saco comum, fixador IV vs curativo pediátrico).
9. Não force match só por dimensões vagas (ex.: saco 60L) se o uso clínico difere.

QUANDO NO_MATCH:
- Nenhum candidato tem apresentação clínica equivalente.
- Dose, forma ou via incompatíveis.
- Candidato é produto clínico diferente apesar de texto parecido.

FORMATO:
- decision="match": informe cod_item (inteiro) de UM candidato listado.
- decision="no_match": não inclua cod_item.
"""


@dataclass(frozen=True)
class MatchDeps:
    valid_cod_items: frozenset[int]


def _build_model(settings: DeparaLLMSettings):
    if settings.mode == "test":
        return TestModel(
            custom_output_args={
                "decision": "no_match",
                "confidence": 0.5,
                "reasoning": "Stub TestModel — sem chamada de API.",
            }
        )

    model_spec = settings.model
    if model_spec.startswith("openai:"):
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        model_name = model_spec.split(":", 1)[1]
        provider = OpenAIProvider(api_key=settings.openai_api_key)
        return OpenAIChatModel(model_name, provider=provider)

    if model_spec.startswith("anthropic:"):
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider

        model_name = model_spec.split(":", 1)[1]
        provider = AnthropicProvider(api_key=settings.anthropic_api_key)
        return AnthropicModel(model_name, provider=provider)

    return model_spec


def build_agent(settings: DeparaLLMSettings) -> Agent[MatchDeps, LLMMatchOutput]:
    settings.require_api_key()
    agent: Agent[MatchDeps, LLMMatchOutput] = Agent(
        model=_build_model(settings),
        output_type=LLMMatchOutput,
        deps_type=MatchDeps,
        system_prompt=SYSTEM_PROMPT,
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


def build_user_prompt(item_text: str, candidates_text: str) -> str:
    return (
        f"{item_text}\n\n"
        f"Candidatos Global (escolha UM cod_item ou no_match):\n"
        f"{candidates_text}"
    )
