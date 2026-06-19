"""Relatório HTML — comparativo preço Global (distribuidor) vs Unimed (compras)."""

from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from depara.price_sanity import (
    enrich_price_report,
    format_review_flags,
    has_review_flags,
    parse_review_flags,
)
from depara.sources import GLOBAL_DISTRIBUIDOR, UNIMED_COMPRAS, csv_to_internal


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


def _fmt_br(n: float | int, decimals: int = 2) -> str:
    if pd.isna(n):
        return "—"
    s = f"{n:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s


def _summary(df: pd.DataFrame) -> dict:
    gap_med = df["gap_global_custo_mediana_pct"]
    gap_ult = df["gap_global_custo_ultimo_pct"]
    confiaveis = df[df.get("preco_depara_ok", True) != False]  # noqa: E712
    gap_ok = confiaveis["gap_global_custo_mediana_pct"]
    preco_bad = int((~df.get("preco_depara_ok", True)).sum()) if "preco_depara_ok" in df.columns else 0
    outlier = int(
        df["review_flags"].str.contains("outlier_custo_ultimo|gap_inflado", na=False, regex=True).sum()
    )
    return {
        "total": len(df),
        "oportunidade_count": int((gap_ok < 0).sum()),
        "oportunidade_total": round(float(confiaveis["oportunidade_mensal_rs"].sum()), 0),
        "global_mais_caro_med": int((gap_ok > 0).sum()),
        "global_mais_barato_med": int((gap_ok < 0).sum()),
        "risco_total": round(float(confiaveis["risco_mensal_rs"].sum()), 0),
        "gap_mediano_med": round(float(gap_med.median()), 1),
        "gap_mediano_ult": round(float(gap_ult.median()), 1),
        "economia_total": round(float(confiaveis["risco_mensal_rs"].sum()), 0),
        "flagged": int(df["review_flags"].apply(has_review_flags).sum()),
        "preco_depara_ruim": preco_bad,
        "gap_inflado_outlier": outlier,
        "abc_a": int((df["unimed_abc"] == "A").sum()),
        "llm": int((df["match_source"] == "llm").sum()),
        "fuzzy": int((df["match_source"] == "fuzzy_alta").sum()),
    }


def _table_rows_compact(df: pd.DataFrame, *, use_mediana: bool = True) -> str:
    rows = []
    for _, r in df.iterrows():
        if use_mediana:
            gap = r["gap_global_custo_mediana_pct"]
            g_custo = r["global_custo_mediana"]
            econ = r.get("risco_mensal_rs", r.get("economia_potencial_mediana_rs", 0))
        else:
            gap = r["gap_global_custo_ultimo_pct"]
            g_custo = r["global_custo_ultimo"]
            econ = r.get("economia_potencial_rs", 0)
        u_ref = r.get("unimed_vl_por_unidade", r["unimed_vl_medio"])
        gap_cls = "pos" if gap > 0 else "neg" if gap < 0 else ""
        rows.append(
            f"<tr>"
            f"<td>{html.escape(str(r['linha_produto'])[:70])}</td>"
            f"<td class='num'>{_fmt_br(g_custo)}</td>"
            f"<td class='num'>{_fmt_br(u_ref)}</td>"
            f"<td class='num {gap_cls}'>{gap:+.1f}%</td>"
            f"<td class='num'>{_fmt_br(econ, 0)}</td>"
            f"<td><span class='abc abc-{html.escape(str(r['unimed_abc']))}'>"
            f"{html.escape(str(r['unimed_abc']))}</span></td>"
            f"</tr>"
        )
    return "\n".join(rows)


def _table_rows_oportunidade(df: pd.DataFrame) -> str:
    rows = []
    for _, r in df.iterrows():
        gap = r["gap_global_custo_mediana_pct"]
        u_ref = r.get("unimed_vl_por_unidade", r["unimed_vl_medio"])
        rows.append(
            f"<tr>"
            f"<td>{html.escape(str(r['linha_produto'])[:70])}</td>"
            f"<td class='num'>{_fmt_br(r['global_custo_mediana'])}</td>"
            f"<td class='num'>{_fmt_br(u_ref)}</td>"
            f"<td class='num neg'>{gap:+.1f}%</td>"
            f"<td class='num'>{_fmt_br(r.get('oportunidade_mensal_rs', 0), 0)}</td>"
            f"<td class='num'>{_fmt_br(r.get('unimed_prev_mes_qtd', 0), 0)}</td>"
            f"<td><span class='abc abc-{html.escape(str(r['unimed_abc']))}'>"
            f"{html.escape(str(r['unimed_abc']))}</span></td>"
            f"</tr>"
        )
    return "\n".join(rows)


def _table_rows(df: pd.DataFrame, limit: int | None = None) -> str:
    rows = []
    subset = df.head(limit) if limit else df
    for _, r in subset.iterrows():
        gap = r["gap_global_custo_mediana_pct"]
        gap_cls = "pos" if gap > 0 else "neg" if gap < 0 else ""
        gap_ult = r["gap_global_custo_ultimo_pct"]
        flag = r.get("review_flags", "")
        flag_html = f'<span class="flag">{html.escape(flag)}</span>' if flag else ""
        rows.append(
            f"""<tr data-abc="{html.escape(str(r['unimed_abc']))}" """
            f"""data-gap="{gap}" data-gap-ult="{gap_ult}" data-flag="{html.escape(flag)}">"""
            f"""<td>{html.escape(str(r['linha_produto'])[:70])}</td>"""
            f"""<td>{html.escape(str(r['marcas']))}</td>"""
            f"""<td class="num">{_fmt_br(r['global_custo_ultimo'])}</td>"""
            f"""<td class="num">{_fmt_br(r['global_custo_medio'])}</td>"""
            f"""<td class="num">{_fmt_br(r['global_custo_mediana'])}</td>"""
            f"""<td class="num">{_fmt_br(r.get('unimed_vl_por_unidade', r['unimed_vl_medio']))}</td>"""
            f"""<td class="num {gap_cls}">{gap:+.1f}%</td>"""
            f"""<td class="num">{_fmt_br(r.get('economia_potencial_mediana_rs', r['economia_potencial_rs']), 0)}</td>"""
            f"""<td><span class="abc abc-{html.escape(str(r['unimed_abc']))}">"""
            f"""{html.escape(str(r['unimed_abc']))}</span></td>"""
            f"""<td>{html.escape(str(r['match_source']))}</td>"""
            f"""<td>{flag_html}</td>"""
            f"""</tr>"""
        )
    return "\n".join(rows)


def _table_rows_preco_ruim(df: pd.DataFrame) -> str:
    rows = []
    for _, r in df.iterrows():
        gap = r["gap_global_custo_mediana_pct"]
        gap_cls = "pos" if gap > 0 else "neg" if gap < 0 else ""
        desc = str(r.get("desc_item_unimed", r.get("desc_unimed_match", "")))[:55]
        rows.append(
            f"<tr>"
            f"<td>{html.escape(str(r['linha_produto'])[:55])}</td>"
            f"<td class='num'>{_fmt_br(r['global_custo_mediana'])}</td>"
            f"<td class='num'>{_fmt_br(r.get('unimed_vl_por_unidade', r['unimed_vl_medio']))}</td>"
            f"<td class='num {gap_cls}'>{gap:+.1f}%</td>"
            f"<td>{html.escape(desc)}</td>"
            f"<td><span class='flag'>{html.escape(str(r.get('review_flags','')))}</span></td>"
            f"</tr>"
        )
    return "\n".join(rows)


def generate_html_report(
    csv_path: Path,
    output_path: Path,
    *,
    title: str = "Comparativo de Preços — Global (distribuidor) vs Unimed (compras)",
) -> Path:
    df = _flag_rows(_prepare_df(csv_path))
    df = df.sort_values("unimed_prev_mes_rs", ascending=False, na_position="last")
    s = _summary(df)

    confiaveis = df[df.get("preco_depara_ok", True) != False]  # noqa: E712
    top_oportunidades = confiaveis[confiaveis["gap_global_custo_mediana_pct"] < 0].nlargest(
        15, "oportunidade_mensal_rs"
    )
    top_caro = confiaveis[confiaveis["gap_global_custo_mediana_pct"] > 0].nlargest(
        15, "risco_mensal_rs"
    )
    flagged = df[df["review_flags"].apply(has_review_flags)].sort_values(
        "gap_global_custo_ultimo_pct", key=abs, ascending=False
    )
    preco_ruim = df[df["review_flags"].apply(
        lambda s: "preco_depara_incompativel" in parse_review_flags(s)
    )]

    hist_bins = [-100, -50, -20, 0, 20, 50, 100, 500, 10000]
    hist_labels = ["≤-50%", "-50 a -20", "-20 a 0", "0 a 20", "20 a 50", "50 a 100", "100 a 500", ">500%"]
    hist_counts = pd.cut(
        confiaveis["gap_global_custo_mediana_pct"], bins=hist_bins
    ).value_counts().sort_index()
    hist_data = [int(hist_counts.get(b, 0)) for b in hist_counts.index]

    abc_counts = df["unimed_abc"].value_counts().to_dict()

    generated = datetime.now().strftime("%d/%m/%Y %H:%M")

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
    --border: #2d3a4f;
  }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text);
    margin: 0; padding: 1.5rem; line-height: 1.5; }}
  h1 {{ font-size: 1.5rem; margin: 0 0 .25rem; }}
  .subtitle {{ color: var(--muted); font-size: .9rem; margin-bottom: 1.5rem; }}
  .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: .75rem; margin-bottom: 1.5rem; }}
  .kpi {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; }}
  .kpi .val {{ font-size: 1.6rem; font-weight: 700; }}
  .kpi .lbl {{ font-size: .75rem; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }}
  section {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px;
    padding: 1.25rem; margin-bottom: 1.25rem; }}
  section h2 {{ font-size: 1rem; margin: 0 0 1rem; color: var(--accent); }}
  .charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }}
  @media (max-width: 800px) {{ .charts {{ grid-template-columns: 1fr; }} }}
  .chart-box {{ height: 220px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: .82rem; }}
  th, td {{ padding: .45rem .6rem; text-align: left; border-bottom: 1px solid var(--border); }}
  th {{ color: var(--muted); font-weight: 600; cursor: pointer; user-select: none; }}
  th:hover {{ color: var(--text); }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  td.pos, .num.pos {{ color: var(--pos); }}
  td.neg, .num.neg {{ color: var(--neg); }}
  .abc {{ display: inline-block; padding: .1rem .4rem; border-radius: 4px; font-weight: 700; font-size: .7rem; }}
  .abc-A {{ background: #7f1d1d; color: #fecaca; }}
  .abc-B {{ background: #713f12; color: #fde68a; }}
  .abc-C {{ background: #1e3a5f; color: #93c5fd; }}
  .flag {{ font-size: .7rem; color: var(--warn); }}
  .alert {{ background: #422006; border: 1px solid #92400e; border-radius: 6px; padding: .75rem 1rem;
    margin-bottom: 1rem; font-size: .85rem; }}
  .alert ul {{ margin: .5rem 0 0 1rem; padding: 0; }}
  .filters {{ display: flex; gap: .75rem; flex-wrap: wrap; margin-bottom: .75rem; }}
  .filters input, .filters select {{ background: var(--bg); border: 1px solid var(--border); color: var(--text);
    padding: .4rem .6rem; border-radius: 4px; }}
  .sources {{ background: #1e293b; border: 1px solid var(--border); border-radius: 8px;
    padding: 1rem 1.25rem; margin-bottom: 1.25rem; font-size: .85rem; }}
  .sources dl {{ display: grid; grid-template-columns: 140px 1fr; gap: .35rem .75rem; margin: 0; }}
  .sources dt {{ color: var(--muted); }}
  .sources dd {{ margin: 0; }}
</style>
</head>
<body>
<h1>{html.escape(title)}</h1>
<p class="subtitle">Gerado em {generated} · {s['total']} linhas clínicas com depara<br>
Gap &lt; 0 = Global <strong>mais barato</strong> que a compra atual Unimed (oportunidade comercial) · preços por unidade comparável</p>

<div class="sources">
  <strong>De onde vêm os preços</strong>
  <dl>
    <dt>Global</dt>
    <dd><strong>{html.escape(GLOBAL_DISTRIBUIDOR['entidade'])}</strong> — arquivo <code>{html.escape(GLOBAL_DISTRIBUIDOR['arquivo'])}</code>,
    coluna origem <code>{html.escape(GLOBAL_DISTRIBUIDOR['coluna_preco'])}</code>.
    {html.escape(GLOBAL_DISTRIBUIDOR['descricao'])}</dd>
    <dt>Unimed</dt>
    <dd><strong>{html.escape(UNIMED_COMPRAS['entidade'])}</strong> — arquivo <code>{html.escape(UNIMED_COMPRAS['arquivo'])}</code>,
    coluna origem <code>{html.escape(UNIMED_COMPRAS['coluna_preco'])}</code>.
    {html.escape(UNIMED_COMPRAS['descricao'])}</dd>
    <dt>Depara</dt>
    <dd>Linha clínica Global (<code>LINHA_PRODUTO</code> no CSV) → <code>cod_item</code> Unimed (Curva ABC). Códigos de produto <em>não</em> batem entre sistemas.</dd>
    <dt>Gap principal</dt>
    <dd>Mediana Global vs VL Médio Unimed <strong>normalizado por unidade</strong> (caixa/kit/rolo ÷ qtd na descrição).</dd>
    <dt>Oportunidade</dt>
    <dd>Quando Global &lt; Unimed: economia mensal estimada = (ref. Unimed/un − mediana Global/un) × Prev Mês qtd.</dd>
  </dl>
</div>

<div class="alert">
  <strong>⚠ Gaps extremos no top — leia antes de usar</strong>
  <ul>
    <li><strong>{s['preco_depara_ruim']}</strong> linhas com depara incompatível com preço (ratio mediana/ref &gt;4× ou &lt;0,25×) — ex.: saco autoclave → saco lixo, fixador IV → curativo pediátrico.</li>
    <li><strong>{s['gap_inflado_outlier']}</strong> linhas onde gap por <em>último</em> está inflado por outlier (ex.: piperacilina Sandoz R$180 vs mediana R$13 — depara OK, última NF atípica).</li>
    <li>Top “economia potencial” usa <strong>mediana</strong> e exclui depara com preço incompatível.</li>
    <li>ETANERCEPTE caneta 1ml: ERELZI R$2.230 vs NEPEXTO R$400 na mesma linha — biosimilar vs origem; compare por SKU em <code>fase2_price_sku.csv</code>.</li>
  </ul>
</div>

<div class="alert">
  <strong>Conferência dos dados</strong>
  <ul>
    <li><strong>{s['oportunidade_count']}</strong> oportunidades (Global mais barato, depara OK) · Σ <strong>R$ {_fmt_br(s['oportunidade_total'], 0)}</strong>/mês estimados.</li>
    <li><strong>{s['global_mais_caro_med']}</strong> linhas com Global acima da ref. Unimed · Σ risco <strong>R$ {_fmt_br(s['risco_total'], 0)}</strong>/mês.</li>
    <li><strong>{s['preco_depara_ruim']}</strong> depara incompatível com preço (excluídos das oportunidades).</li>
    <li><strong>{s['flagged']}</strong> linhas com flags de revisão.</li>
  </ul>
</div>

<div class="kpis">
  <div class="kpi"><div class="val">{s['total']}</div><div class="lbl">Linhas c/ depara</div></div>
  <div class="kpi"><div class="val">{s['oportunidade_count']}</div><div class="lbl">Oportunidades</div></div>
  <div class="kpi"><div class="val">R$ {_fmt_br(s['oportunidade_total'], 0)}</div><div class="lbl">Σ oportunidade/mês</div></div>
  <div class="kpi"><div class="val">{s['global_mais_caro_med']}</div><div class="lbl">Global &gt; Unimed</div></div>
  <div class="kpi"><div class="val">{s['gap_mediano_med']:+.1f}%</div><div class="lbl">Gap mediano (med.)</div></div>
  <div class="kpi"><div class="val">{s['preco_depara_ruim']}</div><div class="lbl">Depara ≠ preço</div></div>
  <div class="kpi"><div class="val">{s['flagged']}</div><div class="lbl">Com flags</div></div>
</div>

<section>
  <h2>Oportunidades — Global mais barato que compra atual Unimed (top 15)</h2>
  <p class="note" style="color:var(--muted);font-size:.85rem;margin:-.5rem 0 1rem">
    Só linhas com depara OK. Ordenado por economia mensal estimada (R$). Preços por unidade comparável.
  </p>
  <table><thead><tr>
    <th>Linha Global (dist.)</th><th>Preço G med./un</th><th>Ref. Unimed/un</th><th>Gap</th><th>Oportun. mensal</th><th>Prev mês qtd</th><th>ABC</th>
  </tr></thead><tbody>
  {_table_rows_oportunidade(top_oportunidades)}
  </tbody></table>
</section>

<section>
  <h2>Distribuição de gaps (depara OK)</h2>
  <div class="charts">
    <div class="chart-box"><canvas id="histChart"></canvas></div>
    <div class="chart-box"><canvas id="abcChart"></canvas></div>
  </div>
</section>

<section>
  <h2>Global mais caro que Unimed — risco de perda (top 15, depara OK)</h2>
  <table><thead><tr>
    <th>Linha Global (dist.)</th><th>Preço G med./un</th><th>Ref. Unimed/un</th><th>Gap</th><th>Risco mensal</th><th>ABC</th>
  </tr></thead><tbody>
  {_table_rows_compact(top_caro)}
  </tbody></table>
  <p class="note">Risco = (preço Global mediana − ref. Unimed/un) × Prev Mês qtd Unimed.</p>
</section>

<section>
  <h2>Depara incompatível com preço ({len(preco_ruim)})</h2>
  <table><thead><tr>
    <th>Linha Global</th><th>Mediana G</th><th>Ref. U</th><th>Gap med.</th><th>Match Unimed</th><th>Flags</th>
  </tr></thead><tbody>
  {_table_rows_preco_ruim(preco_ruim.head(25))}
  </tbody></table>
</section>

<section>
  <h2>⚠ Linhas para revisar manualmente ({len(flagged)})</h2>
  <table><thead><tr>
    <th>Linha Global</th><th>Último G</th><th>Ref. U</th><th>Gap</th><th>Match</th><th>Flags</th>
  </tr></thead><tbody>
  {_table_rows(flagged, limit=50)}
  </tbody></table>
</section>

<section>
  <h2>Tabela completa</h2>
  <div class="filters">
    <input type="search" id="search" placeholder="Buscar linha ou marca…">
    <select id="abcFilter"><option value="">ABC — todos</option><option value="A">A</option><option value="B">B</option><option value="C">C</option></select>
    <select id="gapFilter"><option value="">Gap — todos</option><option value="caro">Global mais caro</option><option value="barato">Global mais barato</option><option value="flag">Só flagged</option></select>
  </div>
  <div style="overflow-x:auto; max-height:520px; overflow-y:auto">
  <table id="fullTable"><thead><tr>
    <th data-sort="0">Linha Global (dist.)</th><th data-sort="1">Marcas Global</th>
    <th data-sort="2">Preço G último</th><th data-sort="3">Preço G médio</th><th data-sort="4">Preço G mediana</th>
    <th data-sort="5">Preço Unimed</th><th data-sort="6">Gap med %</th><th data-sort="7">Economia med.</th>
    <th data-sort="8">ABC</th><th data-sort="9">Match</th><th>Flags</th>
  </tr></thead><tbody>
  {_table_rows(df)}
  </tbody></table>
  </div>
</section>

<script>
const histLabels = {json.dumps(hist_labels)};
const histData = {json.dumps(hist_data)};
const abcData = {json.dumps(abc_counts)};

new Chart(document.getElementById('histChart'), {{
  type: 'bar',
  data: {{ labels: histLabels, datasets: [{{ label: 'Linhas', data: histData, backgroundColor: '#3b82f6' }}] }},
  options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }},
    scales: {{ x: {{ ticks: {{ color: '#8b9cb3', maxRotation: 45 }} }}, y: {{ ticks: {{ color: '#8b9cb3' }} }} }} }}
}});
new Chart(document.getElementById('abcChart'), {{
  type: 'doughnut',
  data: {{ labels: Object.keys(abcData), datasets: [{{ data: Object.values(abcData),
    backgroundColor: ['#f87171','#fbbf24','#60a5fa'] }}] }},
  options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ labels: {{ color: '#e7ecf3' }} }} }} }}
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

document.querySelectorAll('#fullTable th[data-sort]').forEach(th => {{
  th.addEventListener('click', () => {{
    const col = +th.dataset.sort;
    const rows = [...tbody.rows].filter(r => r.style.display !== 'none');
    const asc = th.classList.toggle('asc');
    th.classList.toggle('desc', !asc);
    rows.sort((a,b) => {{
      const av = a.cells[col].textContent.replace(/[^\\d,.+-]/g,'').replace(',','.');
      const bv = b.cells[col].textContent.replace(/[^\\d,.+-]/g,'').replace(',','.');
      const an = parseFloat(av) || 0, bn = parseFloat(bv) || 0;
      if (!isNaN(an) && !isNaN(bn) && av !== '' && bv !== '') return asc ? an - bn : bn - an;
      return asc ? av.localeCompare(bv) : bv.localeCompare(av);
    }});
    rows.forEach(r => tbody.appendChild(r));
  }});
}});
</script>
</body>
</html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(doc, encoding="utf-8")
    return output_path
