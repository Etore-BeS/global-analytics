"""Serialize enriched context for the pharmaceutical agent prompt."""

from __future__ import annotations

import json

from depara.medication.models import ClinicalPresentation, EnrichedCandidate


def format_source_block(source: ClinicalPresentation) -> str:
    lines = [
        f"display: {source.display_text}",
        f"medication_normalized: {source.medication_normalized or '—'}",
        f"form: {source.form_normalized or '—'}",
        f"route: {source.route_normalized or '—'}",
        f"medication_hash_id: {source.medication_hash_id or '—'}",
    ]
    if source.skipped:
        lines.append(f"norm_skipped: true ({source.skip_reason})")
    elif not source.medication_normalized or not source.form_normalized:
        lines.append("spec_incomplete: true (PA/forma não extraídos — confirmar clínica)")
    if source.pack_inferred_low_confidence:
        lines.append(
            "pack_inferred_low_confidence: true (embalagem inferida — validar preço unitário)"
        )
    return "\n".join(lines)


def format_candidates_block(candidates: list[EnrichedCandidate]) -> str:
    lines = []
    for i, c in enumerate(candidates, 1):
        signals = []
        if c.hash_match:
            signals.append("hash_match")
        if c.fuzzy_alta:
            signals.append("fuzzy_alta")
        if c.preco_ok:
            signals.append("preco_ok")
        sig_txt = ", ".join(signals) if signals else "—"
        fuzzy = f"{c.fuzzy_score:.2f}" if c.fuzzy_score is not None else "—"
        vpu = f"{c.vl_por_unidade:.4f}" if c.vl_por_unidade else "—"
        lines.append(
            f"{i}. cod_item={c.cod_item} | signals=[{sig_txt}] | fuzzy={fuzzy} | "
            f"vl_unit={vpu} | {c.desc_global}"
        )
    return "\n".join(lines)


def build_agent_context(
    source: ClinicalPresentation,
    candidates: list[EnrichedCandidate],
) -> str:
    return (
        "=== LINHA GLOBAL (normalizada) ===\n"
        f"{format_source_block(source)}\n\n"
        "=== CANDIDATOS UNIMED (com sinais) ===\n"
        f"{format_candidates_block(candidates)}\n"
    )


def context_to_jsonl_record(
    linha_produto: str,
    source: ClinicalPresentation,
    candidates: list[EnrichedCandidate],
    *,
    truth_cod_item: int | None = None,
) -> dict:
    return {
        "linha_produto": linha_produto,
        "source": source.model_dump(),
        "candidates": [c.model_dump() for c in candidates],
        "truth_cod_item": truth_cod_item,
        "prompt_preview": build_agent_context(source, candidates),
    }


def dump_jsonl_record(record: dict) -> str:
    return json.dumps(record, ensure_ascii=False)
