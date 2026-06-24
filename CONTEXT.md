# Glossário — Depara Global × Unimed

## Linha clínica (L2)

Apresentação clínica usada no depara: princípio ativo + dose + forma + via + volume do recipiente quando relevante. Uma linha Global mapeia para um `Cod Item` Unimed.

## SKU (L3)

Produto comercial com marca e `COD_PRODUTO`. Várias marcas podem compartilhar a mesma linha clínica.

## Embalagem comercial (L4)

Quantidade na caixa ou pacote (`cx c/50`, `pct c/100`). Não define identidade L2; entra na normalização de preço (R$/unidade clínica).

## Unidade clínica

Unidade de uso do paciente: ampola (AP), comprimido (CP), frasco (FR), unidade (UN), etc.

## Depara

Mapeamento entre catálogos com códigos diferentes, por equivalência clínica (não por marca ou embalagem).

## Oportunidade

Global mais barata que a referência Unimed (gap mediana negativo). Impacto mensal = diferença × volume previsto.

## Risco

Global mais cara que a referência Unimed (gap mediano positivo). Impacto mensal = diferença × volume previsto.

## VL Médio (Unimed)

Preço médio de referência da Curva ABC — benchmark de compras, não necessariamente contrato vigente.

## CUSTO_ENTRADA (Global)

Custo histórico de entrada na distribuidora por SKU/marca. Comparado após normalização para R$/unidade clínica L2.

## Subject (lado A)

Catálogo cujas linhas clínicas serão mapeadas — o lado “sujeito” do depara. Pode ser informado em granularidade SKU ou linha clínica.

## Reference (lado B)

Catálogo de benchmark — o lado “referência” com preço e código canônico (`canonical_id`) para comparação.

## Granularidade

Nível de identidade do subject: **SKU** (produto comercial com código) ou **linha clínica** (L2, apresentação clínica agregada).
