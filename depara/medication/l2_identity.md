# Identidade L2 — apresentação clínica

O depara mapeia **apresentações clínicas** (nível L2), não SKUs comerciais nem embalagens.

## Entra na identidade (`medication_hash_id`)

- Princípio ativo
- Dose por unidade de uso
- Forma farmacêutica
- Via (quando relevante)
- Volume do recipiente (injetáveis), quando extraído do texto

## Fora da identidade (L3/L4)

- Marca / `COD_PRODUTO`
- `cx c/N` — normalizar só no preço (R$/unidade)

## Casos de referência

| A | B | Mesmo item L2? |
|---|---|----------------|
| paracetamol 500 mg comprimido | paracetamol 500 mg comprimido cx c/100 | Sim |
| 100 mg/4 ml sol inj | 50 mg/4 ml sol inj | Não |
| bevacizumabe 25 mg/ml frasco 4 ml | bevacizumabe 25 mg/ml frasco 16 ml | Não (clínico); validar hash ray-dw |

## Limitações conhecidas do normalizador v2

- Textos muito comerciais (embalagem ANVISA) podem não extrair forma/volume.
- Volume total do frasco (4 ml vs 16 ml) pode colapsar no mesmo hash se só concentração for capturada — medir no benchmark.
