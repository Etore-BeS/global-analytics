"""Fase 1: depara clínico — linha Global (global_df.csv) ↔ cod_item Unimed (Curva ABC)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

import pandas as pd
import spacy
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from thefuzz import fuzz, process

MethodName = Literal["fuzz_token_set", "fuzz_token_sort", "fuzz_wratio", "tfidf", "spacy"]


@dataclass(frozen=True)
class MatchResult:
    linha_produto: str
    cod_item: int
    desc_global: str
    score: float
    method: MethodName


def normalize_text(text: object, *, aggressive: bool = True) -> str:
    if pd.isna(text):
        return ""
    s = str(text).lower().strip()
    if aggressive:
        s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    replacements = {
        "solução injetável": "solucao injetavel",
        "solução injetavel": "solucao injetavel",
        "solucao injetavel": "sol inj",
        "sol injetavel": "sol inj",
        "solucao oral": "sol oral",
        "comprimido": "com",
        "comprimidos": "com",
        "capsula": "cap",
        "cápsula": "cap",
        "xarope": "xpe",
        "frasco ampola": "fa",
        "ampola": "amp",
        "seringa preenchida": "ser preenc",
        "caneta": "can",
        "po liofilizado": "po liof",
        "mg/ml": "mg ml",
        "mcg/ml": "mcg ml",
    }
    for old, new in replacements.items():
        s = s.replace(old, new)
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def load_global_linhas(path: str) -> pd.DataFrame:
    """Linhas clínicas e SKUs a partir do CSV Global (distribuidor)."""
    raw = pd.read_csv(path, encoding="latin-1")
    produtos = raw.drop_duplicates(subset=["COD_PRODUTO"])
    linhas = (
        produtos.groupby("LINHA_PRODUTO", as_index=False)
        .agg(
            principio_ativo=("PRINCIPIO_ATIVO", "first"),
            n_skus=("COD_PRODUTO", "nunique"),
            cod_produtos=("COD_PRODUTO", lambda x: list(x)),
            marcas=("MARCA", lambda x: sorted(set(x))),
            descricoes=("DESCRICAO_PRODUTO", lambda x: list(x)[:3]),
        )
        .rename(columns={"LINHA_PRODUTO": "linha_produto"})
    )
    linhas["texto_match"] = linhas["linha_produto"].map(normalize_text)
    linhas["texto_spacy"] = linhas["linha_produto"].map(
        lambda t: normalize_text(t, aggressive=False)
    )
    return linhas


def load_unimed_linhas(path: str) -> pd.DataFrame:
    """Alias legado — use load_global_linhas."""
    return load_global_linhas(path)


def load_unimed_catalog_items(path: str) -> pd.DataFrame:
    from depara.price_units import enrich_catalog_prices

    global_df = pd.read_excel(path)
    items = global_df.rename(
        columns={
            "Cod Item": "cod_item",
            "Desc Item": "desc_global",
            "VL Médio (R$)": "vl_medio",
            "ABC": "abc",
            "Un": "unidade",
        }
    )
    items["texto_match"] = items["desc_global"].map(normalize_text)
    items["texto_spacy"] = items["desc_global"].map(
        lambda t: normalize_text(t, aggressive=False)
    )
    return enrich_catalog_prices(items)


def load_global_items(path: str) -> pd.DataFrame:
    """Catálogo Unimed (Curva ABC). Alias: load_unimed_catalog_items."""
    return load_unimed_catalog_items(path)


def _fuzz_score(method: str, a: str, b: str) -> float:
    if method == "fuzz_token_set":
        return fuzz.token_set_ratio(a, b) / 100
    if method == "fuzz_token_sort":
        return fuzz.token_sort_ratio(a, b) / 100
    if method == "fuzz_wratio":
        return fuzz.WRatio(a, b) / 100
    raise ValueError(f"Unknown fuzz method: {method}")


def match_thefuzz(
    unimed: pd.DataFrame,
    global_items: pd.DataFrame,
    method: Literal["fuzz_token_set", "fuzz_token_sort", "fuzz_wratio"],
) -> pd.DataFrame:
    choices = list(global_items["texto_match"])
    cod_by_text = dict(zip(global_items["texto_match"], global_items["cod_item"]))
    desc_by_text = dict(zip(global_items["texto_match"], global_items["desc_global"]))

    scorer = lambda a, b: _fuzz_score(method, a, b) * 100  # noqa: E731

    rows = []
    for _, row in unimed.iterrows():
        query = row["texto_match"]
        if not query:
            continue
        best_text, score_raw = process.extractOne(query, choices, scorer=scorer)
        score = score_raw / 100
        cod_item = cod_by_text[best_text]
        rows.append(
            {
                "linha_produto": row["linha_produto"],
                "cod_item": cod_item,
                "desc_global": desc_by_text[best_text],
                "score": score,
                "method": method,
            }
        )
    return pd.DataFrame(rows)


def match_tfidf(unimed: pd.DataFrame, global_items: pd.DataFrame) -> pd.DataFrame:
    vectorizer = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(3, 5),
        min_df=1,
        sublinear_tf=True,
    )
    corpus = list(unimed["texto_match"]) + list(global_items["texto_match"])
    matrix = vectorizer.fit_transform(corpus)
    unimed_matrix = matrix[: len(unimed)]
    global_matrix = matrix[len(unimed) :]
    sim = cosine_similarity(unimed_matrix, global_matrix)

    best_idx = sim.argmax(axis=1)
    best_scores = sim.max(axis=1)

    rows = []
    for i, (_, row) in enumerate(unimed.iterrows()):
        j = best_idx[i]
        g = global_items.iloc[j]
        rows.append(
            {
                "linha_produto": row["linha_produto"],
                "cod_item": g["cod_item"],
                "desc_global": g["desc_global"],
                "score": float(best_scores[i]),
                "method": "tfidf",
            }
        )
    return pd.DataFrame(rows)


def match_spacy(unimed: pd.DataFrame, global_items: pd.DataFrame) -> pd.DataFrame:
    nlp = spacy.load("pt_core_news_md", disable=["ner", "parser"])
    unimed_docs = list(nlp.pipe(unimed["texto_spacy"], batch_size=256))
    global_docs = list(nlp.pipe(global_items["texto_spacy"], batch_size=256))

    rows = []
    for i, (_, row) in enumerate(unimed.iterrows()):
        udoc = unimed_docs[i]
        best_j = 0
        best_score = -1.0
        for j, gdoc in enumerate(global_docs):
            if udoc.vector_norm and gdoc.vector_norm:
                score = float(udoc.similarity(gdoc))
            else:
                score = _spacy_token_jaccard(udoc, gdoc)
            if score > best_score:
                best_score = score
                best_j = j
        g = global_items.iloc[best_j]
        rows.append(
            {
                "linha_produto": row["linha_produto"],
                "cod_item": g["cod_item"],
                "desc_global": g["desc_global"],
                "score": best_score,
                "method": "spacy",
            }
        )
    return pd.DataFrame(rows)


def _spacy_token_jaccard(doc_a: spacy.tokens.Doc, doc_b: spacy.tokens.Doc) -> float:
    tokens_a = {
        t.lemma_.lower()
        for t in doc_a
        if not t.is_space and not t.is_punct and t.lemma_ != "-PRON-"
    }
    tokens_b = {
        t.lemma_.lower()
        for t in doc_b
        if not t.is_space and not t.is_punct and t.lemma_ != "-PRON-"
    }
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def run_all_methods(
    global_distribuidor_path: str,
    unimed_catalogo_path: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    global_linhas = load_global_linhas(global_distribuidor_path)
    unimed_items = load_unimed_catalog_items(unimed_catalogo_path)

    method_frames = [
        match_thefuzz(global_linhas, unimed_items, "fuzz_token_set"),
        match_thefuzz(global_linhas, unimed_items, "fuzz_token_sort"),
        match_thefuzz(global_linhas, unimed_items, "fuzz_wratio"),
        match_tfidf(global_linhas, unimed_items),
        match_spacy(global_linhas, unimed_items),
    ]

    long_df = pd.concat(method_frames, ignore_index=True)

    pivot = global_linhas[["linha_produto", "principio_ativo", "n_skus", "marcas"]].copy()

    for method in long_df["method"].unique():
        m = long_df[long_df["method"] == method][
            ["linha_produto", "cod_item", "desc_global", "score"]
        ].rename(
            columns={
                "cod_item": f"cod_item_{method}",
                "desc_global": f"desc_{method}",
                "score": method,
            }
        )
        pivot = pivot.merge(m, on="linha_produto", how="left")

    score_cols = [c for c in pivot.columns if c in long_df["method"].unique()]
    pivot["score_mean"] = pivot[score_cols].mean(axis=1)
    pivot["score_max"] = pivot[score_cols].max(axis=1)
    pivot["score_std"] = pivot[score_cols].std(axis=1)

    # consensus: method that contributes the max score
    pivot["best_method"] = pivot[score_cols].idxmax(axis=1)
    pivot["best_cod_item"] = pivot.apply(
        lambda r: r[f"cod_item_{r['best_method']}"], axis=1
    )
    pivot["best_desc_global"] = pivot.apply(
        lambda r: r[f"desc_{r['best_method']}"], axis=1
    )

    pivot["confianca"] = _assign_confidence(pivot, score_cols)

    return long_df, pivot.sort_values("score_mean", ascending=False)


def _assign_confidence(pivot: pd.DataFrame, score_cols: list[str]) -> pd.Series:
    cod_cols = [c for c in pivot.columns if c.startswith("cod_item_")]

    def label(row: pd.Series) -> str:
        codes = [row[c] for c in cod_cols]
        n_unique = len(set(codes))
        primary = row.get("fuzz_token_set", 0)
        spacy = row.get("spacy", 0)
        if n_unique == 1 and primary >= 0.8:
            return "alta"
        if row["cod_item_fuzz_token_set"] == row["cod_item_spacy"] and primary >= 0.75:
            return "alta"
        if n_unique <= 2 and row["score_mean"] >= 0.75:
            return "media"
        if row["score_mean"] >= 0.6:
            return "baixa"
        return "revisar"

    return pivot.apply(label, axis=1)


def method_summary(comparison: pd.DataFrame) -> pd.DataFrame:
    score_cols = [c for c in comparison.columns if c.startswith(("fuzz_", "tfidf", "spacy"))]
    rows = []
    for col in score_cols:
        s = comparison[col]
        rows.append(
            {
                "method": col,
                "mean": s.mean(),
                "median": s.median(),
                "p90": s.quantile(0.9),
                "pct_ge_0.8": (s >= 0.8).mean() * 100,
                "pct_ge_0.7": (s >= 0.7).mean() * 100,
                "pct_lt_0.5": (s < 0.5).mean() * 100,
            }
        )
    return pd.DataFrame(rows).sort_values("mean", ascending=False)


def method_agreement(comparison: pd.DataFrame) -> pd.DataFrame:
    cod_cols = [c for c in comparison.columns if c.startswith("cod_item_")]
    cod_matrix = comparison[cod_cols].values
    n = len(comparison)
    all_same = sum(len(set(row)) == 1 for row in cod_matrix)
    pairs = []
    methods = [c.replace("cod_item_", "") for c in cod_cols]
    for i, m1 in enumerate(methods):
        for m2 in methods[i + 1 :]:
            agree = (comparison[f"cod_item_{m1}"] == comparison[f"cod_item_{m2}"]).mean()
            pairs.append({"method_a": m1, "method_b": m2, "agreement_pct": agree * 100})
    summary = pd.DataFrame(pairs).sort_values("agreement_pct", ascending=False)
    summary.attrs["all_methods_same_pct"] = all_same / n * 100
    return summary
