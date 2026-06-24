"""Relatório HTML — comparativo preço Global (distribuidor) vs Unimed (compras)."""

from __future__ import annotations

import html
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import pandas as pd
from depara.fase2_prices import _unimed_catalog_prices
from depara.llm.config import DeparaLLMSettings
from depara.price_sanity import (
    enrich_price_report,
    format_review_flags,
    has_review_flags,
    parse_review_flags,
)
from depara.price_units import infer_pack_qty, vl_por_unidade
from depara.sources import GLOBAL_DISTRIBUIDOR, UNIMED_COMPRAS, csv_to_internal


def _plausible_df(df: pd.DataFrame) -> pd.DataFrame:
    if "projecao_financeira_plausivel" in df.columns:
        return df[df["projecao_financeira_plausivel"] == True]  # noqa: E712
    if "preco_depara_ok" in df.columns:
        return df[df["preco_depara_ok"] != False]  # noqa: E712
    return df


def load_unimed_sem_global(
    unimed_catalog_path: Path,
    covered_cod_items: set[int],
) -> pd.DataFrame:
    """Itens Unimed (Curva ABC) sem depara Global — potencial fora do catálogo Global."""
    catalog = _unimed_catalog_prices(unimed_catalog_path)
    gaps = catalog[~catalog["unimed_cod_item"].isin(covered_cod_items)].copy()
    gaps["pack_qty_unimed"] = gaps.apply(
        lambda r: max(
            infer_pack_qty(str(r["desc_item_unimed"]), str(r.get("unimed_un", ""))),
            1,
        ),
        axis=1,
    )
    gaps["unimed_vl_por_unidade"] = gaps.apply(
        lambda r: vl_por_unidade(
            float(r["unimed_vl_medio"]),
            str(r["desc_item_unimed"]),
            str(r.get("unimed_un", "")) if pd.notna(r.get("unimed_un")) else None,
        ),
        axis=1,
    )
    return gaps.sort_values("unimed_prev_mes_rs", ascending=False, na_position="last")


def _gap_spend_by_abc(gaps: pd.DataFrame) -> dict[str, float]:
    if gaps.empty:
        return {}
    return (
        gaps.groupby("unimed_abc", dropna=False)["unimed_prev_mes_rs"]
        .sum()
        .sort_index()
        .to_dict()
    )


def _prepare_df(csv_path: Path) -> pd.DataFrame:
    return enrich_price_report(csv_to_internal(pd.read_csv(csv_path)))


def _flag_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Flags heurísticas de match/gap (complementam price_sanity)."""
    out = df.copy()
    flags: list[list[str]] = []

    for _, r in out.iterrows():
        row_flags = parse_review_flags(r.get("review_flags"))
        if r["global_custo_ultimo"] <= 0:
            row_flags.append("custo_global_zero")
        if r["unimed_vl_medio"] < 1 and r["gap_global_custo_ultimo_pct"] > 200:
            row_flags.append("gap_extremo_ref_baixa")
        if r["gap_global_custo_ultimo_pct"] > 200:
            row_flags.append("gap_muito_alto")
        if r["match_confidence"] < 0.75:
            row_flags.append("match_baixa_confianca")
        if r["match_source"] == "fuzzy_alta" and abs(r["gap_global_custo_ultimo_pct"]) > 100:
            row_flags.append("fuzzy_alta_gap_alto")
        flags.append(row_flags)

    out["review_flags"] = [format_review_flags(f) for f in flags]
    return out


def _fmt_br(n: float | int | None, decimals: int = 2) -> str:
    if n is None or pd.isna(n):
        return "—"
    s = f"{float(n):,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s


def _fmt_money(n: float | int | None, *, decimals: int = 2) -> str:
    if n is None or pd.isna(n):
        return "—"
    return f"R$ {_fmt_br(n, decimals)}"


def _is_empty_raw(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    if value == "":
        return True
    return False


ColKind = Literal["text", "money", "pct", "qty"]
SortKind = Literal["text", "num", "none"]


@dataclass
class TableColumn:
    label: str
    sort: SortKind
    kind: ColKind
    raw: Callable[[pd.Series], object]
    always: bool = False
    sticky: bool = False
    decimals: int = 2
    extra_cls: Callable[[pd.Series], str] | None = None
    display: Callable[[object, pd.Series], str] | None = None


def _format_by_kind(kind: ColKind, raw: object, *, decimals: int = 2) -> str:
    if _is_empty_raw(raw):
        return "—"
    if kind == "money":
        return _fmt_money(float(raw), decimals=decimals)
    if kind == "pct":
        return f"{float(raw):+.1f}%"
    if kind == "qty":
        return _fmt_br(raw, 0)
    return html.escape(str(raw))


def _active_column_indices(columns: list[TableColumn], rows: list[pd.Series]) -> list[int]:
    active: list[int] = []
    for j, col in enumerate(columns):
        if col.always:
            active.append(j)
            continue
        if any(not _is_empty_raw(col.raw(r)) for r in rows):
            active.append(j)
    return active


def _sort_val(raw: object) -> str | float:
    if _is_empty_raw(raw):
        return ""
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return raw
    return str(raw)


def _td(
    content: str,
    *,
    kind: ColKind = "text",
    sort_val: str | float | None = None,
    extra_cls: str = "",
    sticky: bool = False,
) -> str:
    parts: list[str] = []
    if kind in ("money", "pct", "qty"):
        parts.append(kind)
    elif kind == "text":
        pass
    if sticky:
        parts.append("sticky-col")
    if extra_cls:
        parts.append(extra_cls)
    cls = " ".join(parts)
    cls_attr = f' class="{cls}"' if cls else ""
    sv = ""
    if sort_val is not None and sort_val != "":
        sv = f' data-sort-value="{sort_val}"'
    return f"<td{cls_attr}{sv}>{content}</td>"


def _sortable_table(
    table_id: str,
    headers: list[tuple[str, SortKind, ColKind]],
    body_rows: list[str],
    *,
    footer_text: str | None = None,
) -> str:
    ths = []
    for i, (label, sort_type, kind) in enumerate(headers):
        cls_parts: list[str] = []
        if i == 0:
            cls_parts.append("sticky-col")
        if kind == "money":
            cls_parts.append("money")
        elif kind == "qty":
            cls_parts.append("qty")
        elif kind == "pct":
            cls_parts.append("pct")
        cls_attr = f' class="{" ".join(cls_parts)}"' if cls_parts else ""
        if sort_type == "none":
            ths.append(f"<th{cls_attr}>{html.escape(label)}</th>")
        else:
            ths.append(
                f'<th data-sort="{i}" data-type="{sort_type}"{cls_attr}>'
                f"{html.escape(label)}</th>"
            )
    thead = "<thead><tr>" + "".join(ths) + "</tr></thead>"
    tfoot = ""
    if footer_text:
        tfoot = (
            f'<tfoot><tr><td colspan="{len(headers)}" class="table-footer">'
            f"{footer_text}</td></tr></tfoot>"
        )
    return (
        f'<div class="table-scroll"><table id="{table_id}" class="sortable">'
        f"{thead}<tbody>{''.join(body_rows)}</tbody>{tfoot}</table></div>"
    )


def _render_data_table(
    table_id: str,
    columns: list[TableColumn],
    rows: list[pd.Series],
    *,
    footer_text: str | None = None,
    tr_attrs: Callable[[pd.Series], str] | None = None,
) -> str:
    active = _active_column_indices(columns, rows)
    active_cols = [columns[i] for i in active]
    headers = [(c.label, c.sort, c.kind) for c in active_cols]
    body: list[str] = []
    for r in rows:
        cells: list[str] = []
        for col in active_cols:
            raw = col.raw(r)
            text = col.display(raw, r) if col.display else _format_by_kind(col.kind, raw, decimals=col.decimals)
            xcls = col.extra_cls(r) if col.extra_cls else ""
            cells.append(
                _td(
                    text,
                    kind=col.kind,
                    sort_val=_sort_val(raw),
                    extra_cls=xcls,
                    sticky=col.sticky,
                )
            )
        open_tr = f"<tr {tr_attrs(r)}>" if tr_attrs else "<tr>"
        body.append(open_tr + "".join(cells) + "</tr>")
    return _sortable_table(table_id, headers, body, footer_text=footer_text)


def _abc_cell(abc: object) -> str:
    a = html.escape(str(abc))
    return f'<span class="abc abc-{a}">{a}</span>'


def _cols_price_compare(*, show_oport: bool = False, show_risco: bool = False) -> list[TableColumn]:
    cols: list[TableColumn] = [
        TableColumn(
            "Produto (linha Global)",
            "text",
            "text",
            lambda r: r["linha_produto"],
            always=True,
            sticky=True,
            display=lambda raw, _r: html.escape(str(raw)[:72]),
        ),
        TableColumn("R$/un · Global mediana", "num", "money", lambda r: _price_bundle(r)["g_med"]),
        TableColumn("R$/un · Global último", "num", "money", lambda r: _price_bundle(r)["g_ult"]),
        TableColumn("R$/emb · Global mediana", "num", "money", lambda r: _price_bundle(r)["g_emb_med"]),
        TableColumn("R$/emb · Global último", "num", "money", lambda r: _price_bundle(r)["g_emb_ult"]),
        TableColumn(
            "R$/mês · projeção Global",
            "num",
            "money",
            lambda r: _price_bundle(r)["g_total_est"],
            decimals=0,
        ),
        TableColumn("R$/un · Unimed ref.", "num", "money", lambda r: _price_bundle(r)["u_unit"]),
        TableColumn("R$/emb · Unimed", "num", "money", lambda r: _price_bundle(r)["u_pack"]),
        TableColumn(
            "R$/mês · Unimed Prev Mês",
            "num",
            "money",
            lambda r: _price_bundle(r)["u_total"],
            decimals=0,
        ),
        TableColumn(
            "Gap % (mediana)",
            "num",
            "pct",
            lambda r: r["gap_global_custo_mediana_pct"],
            extra_cls=lambda r: (
                "neg" if float(r["gap_global_custo_mediana_pct"]) < 0
                else "pos" if float(r["gap_global_custo_mediana_pct"]) > 0
                else ""
            ),
        ),
    ]
    if show_oport:
        cols.append(
            TableColumn(
                "R$/mês · oportunidade",
                "num",
                "money",
                lambda r: r.get("oportunidade_mensal_rs"),
                decimals=0,
            )
        )
        cols.append(
            TableColumn(
                "Qtd · Prev Mês",
                "num",
                "qty",
                lambda r: r.get("unimed_prev_mes_qtd"),
            )
        )
    if show_risco:
        cols.append(
            TableColumn(
                "R$/mês · risco",
                "num",
                "money",
                lambda r: r.get("risco_mensal_rs"),
                decimals=0,
            )
        )
    cols.append(
        TableColumn(
            "Curva ABC",
            "text",
            "text",
            lambda r: r["unimed_abc"],
            always=True,
            display=lambda raw, _r: _abc_cell(raw),
        )
    )
    return cols


def _cols_sem_global() -> list[TableColumn]:
    return [
        TableColumn(
            "Cód. Unimed",
            "num",
            "qty",
            lambda r: r["unimed_cod_item"],
            always=True,
            sticky=True,
            display=lambda raw, _r: str(int(raw)),
        ),
        TableColumn(
            "Produto Unimed",
            "text",
            "text",
            lambda r: r["desc_item_unimed"],
            always=True,
            display=lambda raw, _r: html.escape(str(raw)[:70]),
        ),
        TableColumn(
            "Curva ABC",
            "text",
            "text",
            lambda r: r["unimed_abc"],
            always=True,
            display=lambda raw, _r: _abc_cell(raw),
        ),
        TableColumn(
            "Unidade venda",
            "text",
            "text",
            lambda r: r.get("unimed_un", ""),
            display=lambda raw, _r: html.escape(str(raw)[:12]),
        ),
        TableColumn("R$/un · Unimed ref.", "num", "money", lambda r: r.get("unimed_vl_por_unidade")),
        TableColumn(
            "R$/emb · Unimed",
            "num",
            "money",
            lambda r: (
                float(r["unimed_vl_medio"])
                if int(r.get("pack_qty_unimed") or 1) > 1
                else None
            ),
        ),
        TableColumn(
            "Qtd por emb.",
            "num",
            "qty",
            lambda r: int(r.get("pack_qty_unimed") or 1) if int(r.get("pack_qty_unimed") or 1) > 1 else None,
        ),
        TableColumn("Qtd · Prev Mês", "num", "qty", lambda r: r.get("unimed_prev_mes_qtd")),
        TableColumn(
            "R$/mês · gasto Prev Mês",
            "num",
            "money",
            lambda r: r["unimed_prev_mes_rs"],
            decimals=0,
            extra_cls=lambda _r: "highlight-gap",
        ),
        TableColumn(
            "Política compras",
            "text",
            "text",
            lambda r: r.get("unimed_politica", ""),
            display=lambda raw, _r: html.escape(str(raw)[:28]),
        ),
    ]


def _cols_full() -> list[TableColumn]:
    base = _cols_price_compare(show_oport=True, show_risco=True)
    # substituir primeira coluna por versão mais curta e inserir marcas
    base[0] = TableColumn(
        "Produto (linha Global)",
        "text",
        "text",
        lambda r: r["linha_produto"],
        always=True,
        sticky=True,
        display=lambda raw, _r: html.escape(str(raw)[:65]),
    )
    base.insert(
        1,
        TableColumn(
            "Marcas Global",
            "text",
            "text",
            lambda r: r.get("marcas", ""),
            display=lambda raw, _r: html.escape(str(raw)[:40]),
        ),
    )
    base.extend([
        TableColumn(
            "Origem depara",
            "text",
            "text",
            lambda r: r.get("match_source", ""),
            display=lambda raw, _r: html.escape(str(raw)),
        ),
        TableColumn(
            "Flags revisão",
            "text",
            "text",
            lambda r: r.get("review_flags", "") or None,
            display=lambda raw, _r: (
                f'<span class="flag">{html.escape(str(raw))}</span>' if raw else "—"
            ),
        ),
    ])
    return base


def _cols_preco_ruim() -> list[TableColumn]:
    return [
        TableColumn(
            "Produto (linha Global)",
            "text",
            "text",
            lambda r: r["linha_produto"],
            always=True,
            sticky=True,
            display=lambda raw, _r: html.escape(str(raw)[:55]),
        ),
        TableColumn("R$/un · Global mediana", "num", "money", lambda r: _price_bundle(r)["g_med"]),
        TableColumn("R$/un · Global último", "num", "money", lambda r: _price_bundle(r)["g_ult"]),
        TableColumn("R$/un · Unimed ref.", "num", "money", lambda r: _price_bundle(r)["u_unit"]),
        TableColumn("Gap % (mediana)", "num", "pct", lambda r: r["gap_global_custo_mediana_pct"]),
        TableColumn(
            "Match Unimed",
            "text",
            "text",
            lambda r: r.get("desc_item_unimed", r.get("desc_unimed_match", "")),
            display=lambda raw, _r: html.escape(str(raw)[:55]),
        ),
        TableColumn(
            "Flags revisão",
            "text",
            "text",
            lambda r: r.get("review_flags", "") or None,
            display=lambda raw, _r: html.escape(str(raw)) if raw else "—",
        ),
    ]


def _series_rows(df: pd.DataFrame) -> list[pd.Series]:
    return [row for _, row in df.iterrows()]


def _full_tr_attrs(r: pd.Series) -> str:
    gap = float(r["gap_global_custo_mediana_pct"])
    flag = html.escape(str(r.get("review_flags", "")))
    abc = html.escape(str(r["unimed_abc"]))
    return f'data-abc="{abc}" data-gap="{gap}" data-flag="{flag}"'


def _pack_qty(row: pd.Series, side: str) -> int:
    col = f"pack_qty_{side}"
    val = row.get(col, 1)
    try:
        return max(int(val), 1) if pd.notna(val) else 1
    except (TypeError, ValueError):
        return 1


def _emb_price(unit: float | None, pack_qty: int) -> float | None:
    if unit is None or pd.isna(unit) or pack_qty <= 1:
        return None
    return float(unit) * pack_qty


def _price_bundle(row: pd.Series) -> dict[str, float | None]:
    pq_g = _pack_qty(row, "global")
    pq_u = _pack_qty(row, "unimed")
    g_med = row.get("global_custo_mediana")
    g_ult = row.get("global_custo_ultimo")
    u_unit = row.get("unimed_vl_por_unidade")
    if u_unit is None or pd.isna(u_unit):
        u_unit = row.get("unimed_vl_medio")
    u_pack = row.get("unimed_vl_medio")
    qtd = row.get("unimed_prev_mes_qtd")
    g_med_f = float(g_med) if pd.notna(g_med) else None
    g_ult_f = float(g_ult) if pd.notna(g_ult) else None
    u_unit_f = float(u_unit) if pd.notna(u_unit) else None
    u_pack_f = float(u_pack) if pd.notna(u_pack) else None
    qtd_f = float(qtd) if pd.notna(qtd) else None
    return {
        "g_med": g_med_f,
        "g_ult": g_ult_f,
        "g_emb_med": _emb_price(g_med_f, pq_g),
        "g_emb_ult": _emb_price(g_ult_f, pq_g),
        "g_total_est": g_med_f * qtd_f if g_med_f and qtd_f else None,
        "u_unit": u_unit_f,
        "u_pack": u_pack_f if pq_u > 1 else None,
        "u_total": float(row["unimed_prev_mes_rs"]) if pd.notna(row.get("unimed_prev_mes_rs")) else None,
        "pq_g": pq_g,
        "pq_u": pq_u,
    }


SORTABLE_TABLES_JS = """
function initSortableTables() {
  document.querySelectorAll('table.sortable').forEach(table => {
    const tbody = table.tBodies[0];
    if (!tbody) return;
    table.querySelectorAll('th[data-sort]').forEach(th => {
      th.addEventListener('click', () => {
        const col = +th.dataset.sort;
        const type = th.dataset.type || 'text';
        const asc = th.classList.toggle('asc');
        th.classList.toggle('desc', !asc);
        table.querySelectorAll('th[data-sort]').forEach(h => {
          if (h !== th) h.classList.remove('asc', 'desc');
        });
        const rows = [...tbody.rows];
        rows.sort((a, b) => {
          const ac = a.cells[col];
          const bc = b.cells[col];
          const av = ac?.dataset.sortValue ?? ac?.textContent ?? '';
          const bv = bc?.dataset.sortValue ?? bc?.textContent ?? '';
          if (type === 'num') {
            const an = parseFloat(av) || 0;
            const bn = parseFloat(bv) || 0;
            return asc ? an - bn : bn - an;
          }
          return asc ? String(av).localeCompare(String(bv), 'pt') : String(bv).localeCompare(String(av), 'pt');
        });
        rows.forEach(r => tbody.appendChild(r));
      });
    });
  });
}
initSortableTables();
"""


def _summary(df: pd.DataFrame, gaps: pd.DataFrame | None = None) -> dict:
    confiaveis = _plausible_df(df)
    gap_med = df["gap_global_custo_mediana_pct"]
    gap_ult = df["gap_global_custo_ultimo_pct"]
    gap_ok = confiaveis["gap_global_custo_mediana_pct"]
    preco_bad = int((~df.get("preco_depara_ok", True)).sum()) if "preco_depara_ok" in df.columns else 0
    outlier = int(
        df["review_flags"].str.contains("outlier_custo_ultimo|gap_inflado", na=False, regex=True).sum()
    )
    oport_total = round(float(confiaveis["oportunidade_mensal_rs"].sum()), 0)
    risco_total = round(float(confiaveis["risco_mensal_rs"].sum()), 0)
    dedup = confiaveis.groupby("unimed_cod_item", as_index=False).agg(
        oportunidade_mensal_rs=("oportunidade_mensal_rs", "max"),
        risco_mensal_rs=("risco_mensal_rs", "max"),
    )
    oport_dedup = round(float(dedup["oportunidade_mensal_rs"].sum()), 0)
    risco_dedup = round(float(dedup["risco_mensal_rs"].sum()), 0)
    plausivel_n = len(confiaveis)
    out: dict = {
        "total": len(df),
        "plausivel_count": plausivel_n,
        "oportunidade_count": int((gap_ok < 0).sum()),
        "oportunidade_total": oport_total,
        "oportunidade_deduplicada": oport_dedup,
        "global_mais_caro_med": int((gap_ok > 0).sum()),
        "global_mais_barato_med": int((gap_ok < 0).sum()),
        "risco_total": risco_total,
        "risco_deduplicado": risco_dedup,
        "gap_mediano_med": round(float(gap_med.median()), 1),
        "gap_mediano_ult": round(float(gap_ult.median()), 1),
        "flagged": int(df["review_flags"].apply(has_review_flags).sum()),
        "preco_depara_ruim": preco_bad,
        "gap_inflado_outlier": outlier,
        "abc_a": int((df["unimed_abc"] == "A").sum()),
        "llm": int((df["match_source"] == "llm").sum()),
        "fuzzy": int((df["match_source"] == "fuzzy_alta").sum()),
        "cod_items_cobertos": int(df["unimed_cod_item"].nunique()),
    }
    if gaps is not None and not gaps.empty:
        gasto_sem = float(gaps["unimed_prev_mes_rs"].sum())
        gasto_coberto = float(
            df.drop_duplicates("unimed_cod_item")["unimed_prev_mes_rs"].sum()
        )
        gasto_total = gasto_sem + gasto_coberto
        out.update(
            {
                "sem_global_count": len(gaps),
                "sem_global_gasto_mes": round(gasto_sem, 0),
                "gasto_coberto_mes": round(gasto_coberto, 0),
                "gasto_total_unimed_mes": round(gasto_total, 0),
                "cobertura_gasto_pct": round(gasto_coberto / gasto_total * 100, 1)
                if gasto_total > 0
                else 0.0,
            }
        )
    else:
        out.update(
            {
                "sem_global_count": 0,
                "sem_global_gasto_mes": 0,
                "gasto_coberto_mes": 0,
                "gasto_total_unimed_mes": 0,
                "cobertura_gasto_pct": 0.0,
            }
        )
    return out


def _chart_bars(labels: list[str], values: list[float], *, max_label: int = 42) -> tuple[list[str], list[float]]:
    short = [lbl[:max_label] + ("…" if len(lbl) > max_label else "") for lbl in labels]
    return short, values


def generate_html_report(
    csv_path: Path,
    output_path: Path,
    *,
    title: str = "Comparativo de Preços — Global (distribuidor) vs Unimed (compras)",
    unimed_catalog_path: Path | None = None,
) -> Path:
    df = _flag_rows(_prepare_df(csv_path))
    df = df.sort_values("unimed_prev_mes_rs", ascending=False, na_position="last")

    unimed_path = unimed_catalog_path or DeparaLLMSettings().unimed_catalogo_path
    covered = set(df["unimed_cod_item"].dropna().astype(int))
    gaps = (
        load_unimed_sem_global(unimed_path, covered)
        if unimed_path.exists()
        else pd.DataFrame()
    )

    s = _summary(df, gaps)
    confiaveis = _plausible_df(df)
    oportunidades = confiaveis[confiaveis["gap_global_custo_mediana_pct"] < 0].sort_values(
        "oportunidade_mensal_rs", ascending=False
    )
    top_caro = confiaveis[confiaveis["gap_global_custo_mediana_pct"] > 0].sort_values(
        "risco_mensal_rs", ascending=False
    )
    preco_ruim = df[df["review_flags"].apply(
        lambda val: "preco_depara_incompativel" in parse_review_flags(val)
    )]

    hist_bins = [-100, -50, -20, 0, 20, 50, 100, 500, 10000]
    hist_labels = ["≤-50%", "-50 a -20", "-20 a 0", "0 a 20", "20 a 50", "50 a 100", "100 a 500", ">500%"]
    hist_counts = pd.cut(
        confiaveis["gap_global_custo_mediana_pct"], bins=hist_bins
    ).value_counts().sort_index()
    hist_data = [int(hist_counts.get(b, 0)) for b in hist_counts.index]

    gap_abc = _gap_spend_by_abc(gaps)

    top_op_chart = oportunidades.head(10)
    op_labels, op_vals = _chart_bars(
        top_op_chart["linha_produto"].astype(str).tolist(),
        top_op_chart["oportunidade_mensal_rs"].astype(float).tolist(),
    )

    top_gap_chart = gaps.head(10) if not gaps.empty else pd.DataFrame()
    gap_labels, gap_vals = (
        _chart_bars(
            top_gap_chart["desc_item_unimed"].astype(str).tolist(),
            top_gap_chart["unimed_prev_mes_rs"].astype(float).tolist(),
        )
        if not top_gap_chart.empty
        else ([], [])
    )

    generated = datetime.now().strftime("%d/%m/%Y %H:%M")

    gaps_shown = gaps.head(50)
    risco_shown = top_caro.head(50)
    gasto_sem_visivel = float(gaps_shown["unimed_prev_mes_rs"].sum()) if not gaps_shown.empty else 0.0
    pct_sem_visivel = (
        gasto_sem_visivel / s["sem_global_gasto_mes"] * 100 if s["sem_global_gasto_mes"] else 0.0
    )
    risco_visivel = float(risco_shown["risco_mensal_rs"].sum()) if not risco_shown.empty else 0.0
    pct_risco_visivel = risco_visivel / s["risco_total"] * 100 if s["risco_total"] else 0.0

    footer_oport = (
        f"Σ oportunidade: R$ {_fmt_br(s['oportunidade_total'], 0)} "
        f"(deduplicado por item Unimed: R$ {_fmt_br(s['oportunidade_deduplicada'], 0)})"
    )
    footer_sem = (
        f"Mostrando {len(gaps_shown)} de {s['sem_global_count']:,} itens · "
        f"R$ {_fmt_br(gasto_sem_visivel, 0)} ({pct_sem_visivel:.1f}% do gasto sem Global)"
    )
    footer_risco = (
        f"Mostrando {len(risco_shown)} de {len(top_caro)} linhas · "
        f"R$ {_fmt_br(risco_visivel, 0)} ({pct_risco_visivel:.1f}% do risco total)"
    )

    tbl_oport = _render_data_table(
        "oportTable",
        _cols_price_compare(show_oport=True),
        _series_rows(oportunidades),
        footer_text=footer_oport,
    )
    tbl_sem_global = _render_data_table(
        "semGlobalTable",
        _cols_sem_global(),
        _series_rows(gaps_shown),
        footer_text=footer_sem,
    )
    tbl_risco = _render_data_table(
        "riscoTable",
        _cols_price_compare(show_risco=True),
        _series_rows(risco_shown),
        footer_text=footer_risco,
    )
    tbl_preco_ruim = _render_data_table(
        "precoRuimTable",
        _cols_preco_ruim(),
        _series_rows(preco_ruim.head(25)),
    )
    tbl_full = _render_data_table(
        "fullTable",
        _cols_full(),
        _series_rows(df),
        tr_attrs=_full_tr_attrs,
    )

    doc = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg: #0f1419; --card: #1a2332; --text: #e7ecf3; --muted: #8b9cb3;
    --accent: #3b82f6; --pos: #f87171; --neg: #4ade80; --warn: #fbbf24;
    --gap: #a78bfa; --border: #2d3a4f;
  }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text);
    margin: 0; padding: 1.5rem; line-height: 1.5; max-width: 1400px; margin-inline: auto; }}
  h1 {{ font-size: 1.65rem; margin: 0 0 .25rem; }}
  .subtitle {{ color: var(--muted); font-size: .9rem; margin-bottom: 1.25rem; }}
  .hero-cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; margin-bottom: 1.5rem; }}
  @media (max-width: 960px) {{ .hero-cards {{ grid-template-columns: 1fr 1fr; }} }}
  @media (max-width: 520px) {{ .hero-cards {{ grid-template-columns: 1fr; }} }}
  .hero-card {{ border-radius: 12px; padding: 1.25rem 1.35rem; border: 1px solid var(--border);
    position: relative; overflow: hidden; }}
  .hero-card .tag {{ font-size: .7rem; text-transform: uppercase; letter-spacing: .06em; opacity: .85; }}
  .hero-card .val {{ font-size: 1.85rem; font-weight: 800; margin: .35rem 0 .15rem; line-height: 1.1; }}
  .hero-card .sub {{ font-size: .8rem; opacity: .75; }}
  .hero-card.oport {{ background: linear-gradient(135deg, #14532d 0%, #1a2332 100%); border-color: #166534; }}
  .hero-card.oport .val {{ color: #4ade80; }}
  .hero-card.risco {{ background: linear-gradient(135deg, #450a0a 0%, #1a2332 100%); border-color: #991b1b; }}
  .hero-card.risco .val {{ color: #f87171; }}
  .hero-card.gap-card {{ background: linear-gradient(135deg, #4c1d95 0%, #1a2332 100%); border-color: #6d28d9; }}
  .hero-card.gap-card .val {{ color: #c4b5fd; }}
  .hero-card.cobertura {{ background: linear-gradient(135deg, #1e3a5f 0%, #1a2332 100%); border-color: #2563eb; }}
  .hero-card.cobertura .val {{ color: #93c5fd; }}
  .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: .65rem; margin-bottom: 1.25rem; }}
  .kpi {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: .85rem; }}
  .kpi .val {{ font-size: 1.35rem; font-weight: 700; }}
  .kpi .lbl {{ font-size: .68rem; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }}
  section {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px;
    padding: 1.25rem; margin-bottom: 1.25rem; scroll-margin-top: 1rem; }}
  section h2 {{ font-size: 1.05rem; margin: 0 0 .75rem; color: var(--accent); }}
  section .note {{ color: var(--muted); font-size: .85rem; margin: -.25rem 0 1rem; }}
  .report-nav {{ display: flex; flex-wrap: wrap; gap: .35rem 1rem; margin-bottom: 1.25rem;
    padding: .65rem 1rem; background: var(--card); border: 1px solid var(--border); border-radius: 8px; }}
  .report-nav a {{ color: var(--muted); text-decoration: none; font-size: .84rem; }}
  .report-nav a:hover {{ color: var(--accent); }}
  .pilot-banner {{ background: #1e293b; border: 1px solid #334155; border-radius: 10px;
    padding: 1rem 1.25rem; margin-bottom: 1.25rem; font-size: .88rem; }}
  .pilot-banner strong {{ color: var(--text); }}
  .pilot-banner .warn {{ color: #fbbf24; margin: .5rem 0 0; }}
  .cobertura-bar {{ height: 10px; background: var(--border); border-radius: 5px;
    overflow: hidden; margin-top: .65rem; max-width: 480px; }}
  .cobertura-fill {{ height: 100%; background: linear-gradient(90deg, #2563eb, #3b82f6); min-width: 3px; }}
  .cobertura-label {{ font-size: .75rem; color: var(--muted); margin-top: .35rem; }}
  details.sources {{ background: #1e293b; border: 1px solid var(--border); border-radius: 8px;
    padding: .65rem 1.25rem; margin-bottom: 1.25rem; font-size: .85rem; }}
  details.sources summary {{ cursor: pointer; color: var(--muted); font-weight: 600; }}
  details.sources summary:hover {{ color: var(--text); }}
  details.sources dl {{ display: grid; grid-template-columns: 140px 1fr; gap: .35rem .75rem;
    margin: .75rem 0 0; }}
  details.sources dt {{ color: var(--muted); }}
  details.sources dd {{ margin: 0; }}
  .charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.25rem; }}
  .charts-3 {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1rem; }}
  @media (max-width: 1000px) {{ .charts, .charts-3 {{ grid-template-columns: 1fr; }} }}
  .chart-box {{ height: 280px; position: relative; }}
  .chart-box.tall {{ height: 340px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: .82rem; }}
  .table-scroll {{ overflow: auto; max-height: 520px; margin-top: .5rem; }}
  thead th {{ position: sticky; top: 0; background: var(--card); z-index: 2;
    box-shadow: 0 1px 0 var(--border); }}
  th.sticky-col, td.sticky-col {{ position: sticky; left: 0; background: var(--card); z-index: 1;
    box-shadow: 1px 0 0 var(--border); }}
  thead th.sticky-col {{ z-index: 3; }}
  tfoot td.table-footer {{ background: #141c28; color: var(--muted); font-size: .78rem;
    padding: .55rem .6rem; border-top: 1px solid var(--border); }}
  th, td {{ padding: .45rem .6rem; text-align: left; border-bottom: 1px solid var(--border); white-space: nowrap; }}
  th {{ color: var(--muted); font-weight: 600; user-select: none; }}
  th[data-sort] {{ cursor: pointer; }}
  th[data-sort]:hover {{ color: var(--text); }}
  th[data-sort].asc::after {{ content: ' ▲'; font-size: .65rem; opacity: .7; }}
  th[data-sort].desc::after {{ content: ' ▼'; font-size: .65rem; opacity: .7; }}
  td:first-child, th:first-child {{ white-space: normal; min-width: 180px; max-width: 320px; }}
  th.money, td.money {{ text-align: right; font-variant-numeric: tabular-nums; }}
  th.money {{ color: #86efac; }}
  th.qty, td.qty {{ text-align: right; font-variant-numeric: tabular-nums; color: var(--text); }}
  th.pct, td.pct {{ text-align: right; font-variant-numeric: tabular-nums; }}
  td.pct.pos, .pct.pos {{ color: var(--pos); }}
  td.pct.neg, .pct.neg {{ color: var(--neg); }}
  td.money.highlight-gap {{ color: #c4b5fd; font-weight: 600; }}
  .col-legend {{ font-size: .78rem; color: var(--muted); margin: -.5rem 0 1.25rem; }}
  .col-legend .money {{ color: #86efac; font-weight: 600; }}
  .col-legend .qty {{ color: #93c5fd; font-weight: 600; }}
  .col-legend .pct {{ color: #fbbf24; font-weight: 600; }}
  .abc {{ display: inline-block; padding: .1rem .4rem; border-radius: 4px; font-weight: 700; font-size: .7rem; }}
  .abc-A {{ background: #7f1d1d; color: #fecaca; }}
  .abc-B {{ background: #713f12; color: #fde68a; }}
  .abc-C {{ background: #1e3a5f; color: #93c5fd; }}
  .flag {{ font-size: .7rem; color: var(--warn); }}
  .alert {{ background: #422006; border: 1px solid #92400e; border-radius: 6px; padding: .75rem 1rem;
    margin-bottom: 1rem; font-size: .85rem; }}
  .alert.info {{ background: #1e293b; border-color: var(--border); }}
  .alert ul {{ margin: .5rem 0 0 1rem; padding: 0; }}
  .filters {{ display: flex; gap: .75rem; flex-wrap: wrap; margin-bottom: .75rem; }}
  .filters input, .filters select {{ background: var(--bg); border: 1px solid var(--border); color: var(--text);
    padding: .4rem .6rem; border-radius: 4px; }}
</style>
</head>
<body>
<h1>{html.escape(title)}</h1>
<p class="subtitle">Gerado em {generated}</p>
<p class="col-legend"><span class="money">R$</span> = valor em reais (cabeçalhos verdes) ·
<span class="qty">Qtd</span> = quantidade · <span class="pct">%</span> = percentual ·
colunas 100% vazias são ocultadas</p>

<nav class="report-nav" aria-label="Seções do relatório">
  <a href="#sec-resumo">Resumo</a>
  <a href="#sec-graficos">Gráficos</a>
  <a href="#sec-oport">Oportunidades</a>
  <a href="#sec-sem-global">Sem Global</a>
  <a href="#sec-risco">Risco</a>
  <a href="#sec-qualidade">Qualidade</a>
  <a href="#sec-tudo">Tabela completa</a>
</nav>

<div class="pilot-banner" id="sec-resumo">
  <strong>Piloto analítico</strong> — {s['total']} linhas com depara · {s['plausivel_count']} projeções plausíveis
  · {s['cod_items_cobertos']} itens Unimed cobertos · {s['preco_depara_ruim']} depara ≠ preço
  <p class="warn">Apenas {s['cobertura_gasto_pct']:.1f}% do gasto Prev Mês Unimed (Curva ABC) está coberto por depara.
  Conclusões de preço valem para a amostra; expansão de catálogo é o maior alavancador de volume.</p>
  <div class="cobertura-bar" title="Cobertura de gasto Unimed">
    <div class="cobertura-fill" style="width: {max(s['cobertura_gasto_pct'], 0.5):.2f}%"></div>
  </div>
  <div class="cobertura-label">R$ {_fmt_br(s['gasto_coberto_mes'], 0)} cobertos de R$ {_fmt_br(s['gasto_total_unimed_mes'], 0)} Prev Mês</div>
</div>

<div class="hero-cards">
  <div class="hero-card oport">
    <div class="tag">Oportunidade comercial</div>
    <div class="val">R$ {_fmt_br(s['oportunidade_total'], 0)}</div>
    <div class="sub">{s['oportunidade_count']} linhas · dedup item: R$ {_fmt_br(s['oportunidade_deduplicada'], 0)}/mês</div>
  </div>
  <div class="hero-card risco">
    <div class="tag">Risco de perda</div>
    <div class="val">R$ {_fmt_br(s['risco_total'], 0)}</div>
    <div class="sub">{s['global_mais_caro_med']} linhas · dedup item: R$ {_fmt_br(s['risco_deduplicado'], 0)}/mês</div>
  </div>
  <div class="hero-card gap-card">
    <div class="tag">Fora do catálogo Global</div>
    <div class="val">R$ {_fmt_br(s['sem_global_gasto_mes'], 0)}</div>
    <div class="sub">{s['sem_global_count']:,} itens Unimed · gasto mensal sem depara Global</div>
  </div>
  <div class="hero-card cobertura">
    <div class="tag">Cobertura de gasto</div>
    <div class="val">{s['cobertura_gasto_pct']:.1f}%</div>
    <div class="sub">R$ {_fmt_br(s['gasto_coberto_mes'], 0)} de R$ {_fmt_br(s['gasto_total_unimed_mes'], 0)} Prev Mês</div>
  </div>
</div>

<div class="kpis">
  <div class="kpi"><div class="val">{s['total']}</div><div class="lbl">Linhas c/ depara</div></div>
  <div class="kpi"><div class="val">{s['gap_mediano_med']:+.1f}%</div><div class="lbl">Gap mediano</div></div>
  <div class="kpi"><div class="val">{s['preco_depara_ruim']}</div><div class="lbl">Depara ≠ preço</div></div>
  <div class="kpi"><div class="val">{s['flagged']}</div><div class="lbl">Com flags</div></div>
</div>

<details class="sources">
  <summary>De onde vêm os preços e fórmulas</summary>
  <dl>
    <dt>Global</dt>
    <dd><strong>{html.escape(GLOBAL_DISTRIBUIDOR['entidade'])}</strong> — <code>{html.escape(GLOBAL_DISTRIBUIDOR['arquivo'])}</code> · {html.escape(GLOBAL_DISTRIBUIDOR['descricao'])}</dd>
    <dt>Unimed</dt>
    <dd><strong>{html.escape(UNIMED_COMPRAS['entidade'])}</strong> — <code>{html.escape(UNIMED_COMPRAS['arquivo'])}</code> · {html.escape(UNIMED_COMPRAS['descricao'])}</dd>
    <dt>Projeção Global</dt>
    <dd>mediana Global/un × Prev Mês qtd — estimativa hipotética, não gasto real.</dd>
    <dt>Prev Mês Unimed</dt>
    <dd>Gasto real da Curva ABC (coluna Prev Mês R$).</dd>
    <dt>Oportunidade</dt>
    <dd>(ref. Unimed/un − mediana Global/un) × qtd · só projeções plausíveis (ratio 0,25×–4×).</dd>
  </dl>
</details>

<section id="sec-graficos">
  <h2>Visão executiva — gráficos</h2>
  <div class="charts">
    <div class="chart-box tall"><canvas id="oportChart"></canvas></div>
    <div class="chart-box tall"><canvas id="semGlobalChart"></canvas></div>
  </div>
  <div class="charts-3" style="margin-top:1.25rem">
    <div class="chart-box"><canvas id="coberturaChart"></canvas></div>
    <div class="chart-box"><canvas id="gapAbcChart"></canvas></div>
    <div class="chart-box"><canvas id="histChart"></canvas></div>
  </div>
</section>

<section id="sec-oport">
  <h2>Oportunidades — Global mais barato ({len(oportunidades)} linhas)</h2>
  <p class="note">Global abaixo da ref. Unimed/un. Colunas <span class="money">R$</span> são monetárias; projeção Global ≠ gasto real Unimed.</p>
  {tbl_oport}
</section>

<section id="sec-sem-global">
  <h2>Itens Unimed sem fornecimento Global — dinheiro na mesa ({s['sem_global_count']:,} itens)</h2>
  <p class="note">Compras Unimed (Prev Mês R$) em produtos sem depara com linha clínica Global. Top 50 por gasto — use ordenação nas colunas.</p>
  {tbl_sem_global}
</section>

<section id="sec-risco">
  <h2>Global mais caro — risco de perda ({len(top_caro)} linhas)</h2>
  <p class="note">Global acima da referência Unimed. Top 50 por risco mensal estimado.</p>
  {tbl_risco}
</section>

<section id="sec-qualidade">
  <h2>Depara incompatível com preço ({len(preco_ruim)})</h2>
  {tbl_preco_ruim}
</section>

<section id="sec-tudo">
  <h2>Tabela completa — linhas com depara</h2>
  <div class="filters">
    <input type="search" id="search" placeholder="Buscar linha ou marca…">
    <select id="abcFilter"><option value="">ABC — todos</option><option value="A">A</option><option value="B">B</option><option value="C">C</option></select>
    <select id="gapFilter"><option value="">Gap — todos</option><option value="caro">Global mais caro</option><option value="barato">Global mais barato</option><option value="flag">Só flagged</option></select>
  </div>
  {tbl_full}
</section>

<script>
const chartDefaults = {{
  responsive: true,
  maintainAspectRatio: false,
  plugins: {{ legend: {{ labels: {{ color: '#e7ecf3', boxWidth: 12 }} }} }},
  scales: {{
    x: {{ ticks: {{ color: '#8b9cb3' }}, grid: {{ color: '#2d3a4f' }} }},
    y: {{ ticks: {{ color: '#8b9cb3' }}, grid: {{ color: '#2d3a4f' }} }}
  }}
}};

new Chart(document.getElementById('oportChart'), {{
  type: 'bar',
  data: {{
    labels: {json.dumps(op_labels)},
    datasets: [{{ label: 'Oportunidade R$/mês', data: {json.dumps(op_vals)},
      backgroundColor: '#4ade80', borderRadius: 4 }}]
  }},
  options: {{ ...chartDefaults, indexAxis: 'y',
    plugins: {{ ...chartDefaults.plugins, title: {{ display: true, text: 'Top 10 oportunidades (R$/mês)', color: '#e7ecf3' }} }},
    scales: {{ x: {{ ...chartDefaults.scales.x, ticks: {{ callback: v => 'R$ ' + v.toLocaleString('pt-BR') }} }},
      y: {{ ...chartDefaults.scales.y, ticks: {{ autoSkip: false, font: {{ size: 10 }} }} }} }}
  }}
}});

new Chart(document.getElementById('semGlobalChart'), {{
  type: 'bar',
  data: {{
    labels: {json.dumps(gap_labels)},
    datasets: [{{ label: 'Gasto Prev Mês R$', data: {json.dumps(gap_vals)},
      backgroundColor: '#a78bfa', borderRadius: 4 }}]
  }},
  options: {{ ...chartDefaults, indexAxis: 'y',
    plugins: {{ ...chartDefaults.plugins, title: {{ display: true, text: 'Top 10 itens sem Global (gasto Unimed)', color: '#e7ecf3' }} }},
    scales: {{ x: {{ ...chartDefaults.scales.x, ticks: {{ callback: v => 'R$ ' + v.toLocaleString('pt-BR') }} }},
      y: {{ ...chartDefaults.scales.y, ticks: {{ autoSkip: false, font: {{ size: 10 }} }} }} }}
  }}
}});

new Chart(document.getElementById('coberturaChart'), {{
  type: 'doughnut',
  data: {{
    labels: ['Com depara Global', 'Sem fornecimento Global'],
    datasets: [{{ data: [{s['gasto_coberto_mes']}, {s['sem_global_gasto_mes']}],
      backgroundColor: ['#3b82f6', '#7c3aed'], borderWidth: 0 }}]
  }},
  options: {{ responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ position: 'bottom', labels: {{ color: '#e7ecf3' }} }},
      title: {{ display: true, text: 'Gasto Unimed Prev Mês', color: '#e7ecf3' }} }}
  }}
}});

new Chart(document.getElementById('gapAbcChart'), {{
  type: 'bar',
  data: {{
    labels: {json.dumps(list(gap_abc.keys()))},
    datasets: [{{ label: 'Gasto sem Global R$', data: {json.dumps(list(gap_abc.values()))},
      backgroundColor: ['#f87171','#fbbf24','#60a5fa'], borderRadius: 4 }}]
  }},
  options: {{ ...chartDefaults,
    plugins: {{ ...chartDefaults.plugins, title: {{ display: true, text: 'Gasto sem Global por curva ABC', color: '#e7ecf3' }}, legend: {{ display: false }} }}
  }}
}});

const histLabels = {json.dumps(hist_labels)};
const histData = {json.dumps(hist_data)};
new Chart(document.getElementById('histChart'), {{
  type: 'bar',
  data: {{ labels: histLabels, datasets: [{{ label: 'Linhas', data: histData, backgroundColor: '#3b82f6', borderRadius: 3 }}] }},
  options: {{ ...chartDefaults,
    plugins: {{ ...chartDefaults.plugins, title: {{ display: true, text: 'Distribuição de gaps (%)', color: '#e7ecf3' }}, legend: {{ display: false }} }},
    scales: {{ x: {{ ...chartDefaults.scales.x, ticks: {{ maxRotation: 45, font: {{ size: 9 }} }} }}, y: chartDefaults.scales.y }}
  }}
}});

const search = document.getElementById('search');
const abcF = document.getElementById('abcFilter');
const gapF = document.getElementById('gapFilter');
const tbody = document.querySelector('#fullTable tbody');

function filterRows() {{
  const q = search.value.toLowerCase();
  const abc = abcF.value;
  const gap = gapF.value;
  [...tbody.rows].forEach(tr => {{
    const text = tr.textContent.toLowerCase();
    const matchAbc = !abc || tr.dataset.abc === abc;
    const g = parseFloat(tr.dataset.gap);
    const matchGap = !gap || (gap === 'caro' && g > 0) || (gap === 'barato' && g < 0)
      || (gap === 'flag' && tr.dataset.flag);
    tr.style.display = (text.includes(q) && matchAbc && matchGap) ? '' : 'none';
  }});
}}
search.addEventListener('input', filterRows);
abcF.addEventListener('change', filterRows);
gapF.addEventListener('change', filterRows);

{SORTABLE_TABLES_JS}
</script>
</body>
</html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(doc, encoding="utf-8")
    return output_path
