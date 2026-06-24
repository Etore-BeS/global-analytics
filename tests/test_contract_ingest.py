"""Testes de ingest via templates."""

from __future__ import annotations

from pathlib import Path

from depara.contract.config_loader import load_job_config
from depara.contract.ingest import (
    ingest_global_cost_stock,
    ingest_global_purchases,
    ingest_side_a_linhas,
    ingest_unimed_catalog,
)
from depara.contract.models import SideConfig
from depara.fase1_similarity import principio_from_linha
from depara.price_sanity import linha_cost_stats


def test_load_job_config_yaml() -> None:
    cfg = load_job_config(Path("configs/job_pilot.yaml"))
    assert cfg.side_a.template == "global_purchases"
    assert cfg.side_b.template == "unimed_abc"
    assert cfg.match.limit == 150


def test_load_job_cost_stock_config() -> None:
    cfg = load_job_config(Path("configs/job_cost_stock.yaml"))
    assert cfg.side_a.template == "global_cost_stock"
    assert cfg.match.run_all is True


def test_principio_from_linha() -> None:
    assert principio_from_linha(" DEXAMETASONA (4MG/ML SOL INJ) ") == "DEXAMETASONA"


def test_ingest_global_cost_stock() -> None:
    side = SideConfig(
        path=Path("data/depara-unimed/Base_PRODUTOS_CUSTO_ESTOQUE_23062026.csv"),
        template="global_cost_stock",
    )
    df = ingest_global_cost_stock(side)
    assert "CUSTOREAL" in df.columns
    assert "CUSTOULTENT" in df.columns
    assert "ESTOQUE_DISPONIVEL" in df.columns
    assert "EMBALAGEM" in df.columns
    assert "PRINCIPIO_ATIVO" in df.columns
    assert df["PRINCIPIO_ATIVO"].str.contains("DEXAMETASONA").any()


def test_ingest_side_a_linhas_cost_stock() -> None:
    side = SideConfig(
        path=Path("data/depara-unimed/Base_PRODUTOS_CUSTO_ESTOQUE_23062026.csv"),
        template="global_cost_stock",
    )
    linhas = ingest_side_a_linhas(side)
    assert "linha_produto" in linhas.columns
    assert "principio_ativo" in linhas.columns
    assert linhas["n_skus"].min() >= 1


def test_linha_cost_stats_snapshot_dexametasona() -> None:
    path = "data/depara-unimed/Base_PRODUTOS_CUSTO_ESTOQUE_23062026.csv"
    stats = linha_cost_stats(path)
    row = stats[
        stats.linha_produto.str.contains("DEXAMETASONA.*4MG/ML", na=False, regex=True)
    ].iloc[0]
    assert row.global_custo_min > 0
    assert 0.5 < row.global_custo_mediana < 2.0


def test_ingest_global_purchases_with_catalog() -> None:
    side = SideConfig(
        path=Path("data/depara-unimed/global_df.csv"),
        template="global_purchases",
        catalog_enrichment=Path("data/depara-unimed/BASE_LINHA_PRODUTOS.csv"),
    )
    df = ingest_global_purchases(side)
    assert "CUSTO_ENTRADA" in df.columns
    assert "EMBALAGEM" in df.columns or "pack_description" in df.columns


def test_ingest_unimed_catalog() -> None:
    side = SideConfig(
        path=Path("data/depara-unimed/Curva ABC - CD 05.26.xlsx"),
        template="unimed_abc",
    )
    df = ingest_unimed_catalog(side)
    assert "cod_item" in df.columns
    assert "vl_por_unidade" in df.columns
