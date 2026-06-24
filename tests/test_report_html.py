"""Testes do relatório HTML."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from depara.report_html import (
    TableColumn,
    _active_column_indices,
    _cols_price_compare,
    generate_html_report,
    load_unimed_sem_global,
)


def test_load_unimed_sem_global_excludes_covered() -> None:
    unimed = Path("data/depara-unimed/Curva ABC - CD 05.26.xlsx")
    if not unimed.exists():
        return
    gaps = load_unimed_sem_global(unimed, {83665, 87444})
    assert (gaps["unimed_cod_item"] == 83665).sum() == 0
    assert (gaps["unimed_cod_item"] == 87444).sum() == 0
    assert len(gaps) > 0


def test_active_column_indices_drops_all_null() -> None:
    cols = [
        TableColumn("Nome", "text", "text", lambda r: r["n"], always=True),
        TableColumn("Vazio", "num", "money", lambda r: r.get("vazio")),
        TableColumn("Cheio", "num", "money", lambda r: r.get("val")),
    ]
    rows = [pd.Series({"n": "A", "val": 10}), pd.Series({"n": "B", "val": 20})]
    assert _active_column_indices(cols, rows) == [0, 2]


def test_emb_columns_omitted_when_all_unit_pack() -> None:
    row = pd.Series(
        {
            "linha_produto": "TESTE",
            "global_custo_mediana": 5.0,
            "global_custo_ultimo": 5.0,
            "unimed_vl_por_unidade": 6.0,
            "unimed_vl_medio": 6.0,
            "unimed_prev_mes_qtd": 100,
            "unimed_prev_mes_rs": 600.0,
            "gap_global_custo_mediana_pct": -10.0,
            "oportunidade_mensal_rs": 100.0,
            "unimed_abc": "B",
            "pack_qty_global": 1,
            "pack_qty_unimed": 1,
        }
    )
    labels = [c.label for c in _cols_price_compare(show_oport=True)]
    active = _active_column_indices(_cols_price_compare(show_oport=True), [row])
    active_labels = [labels[i] for i in active]
    assert "R$/emb · Global mediana" not in active_labels
    assert "R$/emb · Unimed" not in active_labels
    assert "R$/un · Global mediana" in active_labels


def test_generate_html_includes_sem_global_section(tmp_path: Path) -> None:
    pilot = Path("exports/run_pilot/price_report.csv")
    if not pilot.exists():
        return
    out = tmp_path / "report.html"
    generate_html_report(pilot, out)
    text = out.read_text(encoding="utf-8")
    assert "sem fornecimento Global" in text
    assert "oportChart" in text
    assert "semGlobalChart" in text
    assert "coberturaChart" in text
    assert 'class="sortable"' in text
    assert "R$/un · Global mediana" in text
    assert "R$/mês · Unimed Prev Mês" in text
    assert "Gap % (mediana)" in text
    assert 'class="money"' in text
    assert "col-legend" in text
    assert 'class="report-nav"' in text
    assert "Piloto analítico" in text
    assert "cobertura-bar" in text
    assert "<details" in text and "De onde vêm os preços" in text
    assert "table-footer" in text
    assert "sticky-col" in text
    assert 'id="sec-oport"' in text
    assert text.index("Oportunidades — Global mais barato") < text.index(
        "Itens Unimed sem fornecimento Global"
    )
