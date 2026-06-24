# Regras de normalização de preço por unidade clínica L2

Unidade canônica de comparação: unidade clínica de uso (ampola, comprimido, frasco…).

## Global — histórico de compras (`CUSTO_ENTRADA`)

O custo de entrada na distribuidora **já é registrado por unidade clínica** (ampola, seringa,
comprimido, rolo individual). A embalagem comercial em `BASE_LINHA_PRODUTOS` (`CX C/ N`)
descreve como o SKU é vendido — **não divide** o valor de compra.

## Global — snapshot custo/estoque (`CUSTOREAL`, `CUSTOULTENT`)

Base `BASE_PRODUTOS_CUSTO_ESTOQUE`: 1 linha por SKU. Valores já são R$/unidade clínica.

- **CUSTOREAL**: custo real de estoque — mediana por linha; **mínimo entre SKUs com estoque > 0**
  como referência principal de oportunidade.
- **CUSTOULTENT**: último custo de entrada — mínimo entre SKUs elegíveis → coluna `global_custo_ultimo`.
- Fallback: se nenhum SKU da linha tiver estoque, usa SKUs com `CUSTOREAL > 0`.
- Embalagem (`EMBALAGEM`) já vem na planilha — não requer join com `BASE_LINHA_PRODUTOS`.

## Unimed (`VL Médio`)

O VL Médio da Curva ABC pode ser por **embalagem** (`pct c/100`, `cx c/12`). Normalizar
dividindo por `N` inferido da descrição ou regex.

## Prioridade de inferência de embalagem (lado Unimed)

1. Regex em `Desc Item` (`cx c/N`, `pct c/N`, `kit c/N`)
2. Campo estruturado quando disponível
3. Default: qty=1, flag `pack_inferred_low_confidence`

## Sanidade de depara (relatório)

Ratio Global ÷ Unimed (ambos unitários L2) deve estar entre 0,25× e 4×.

- Match clínico **não** é bloqueado por preço — flags no relatório.
- Oportunidade/risco/economia só entram nos totais quando `projecao_financeira_plausivel`.

## Flags

- `pack_inferred_low_confidence` — qty inferida só por regex/default
- `preco_depara_incompativel` — ratio fora da faixa
- `projecao_financeira_bloqueada` — projeção zerada (preço ou outlier de último custo)
- `outlier_custo_ultimo` — último custo Global >> mediana
