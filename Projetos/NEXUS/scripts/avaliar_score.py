"""Avaliação científica do NEXUS Trust Score.

Responde à pergunta que o benchmark de desempenho NÃO responde: *o score
detecta fraude bem?* Trata "detectar fraude" como classificação binária em que
o **risco = 100 − nexus_score** é a pontuação do classificador, e compara contra
baselines simples. Reporta, com intervalos de confiança por bootstrap:

  * Discriminação:  ROC-AUC e PR-AUC (average precision)
  * Operação:       precision / recall / F1 por limiar + matriz de confusão
  * Calibração:     curva de confiabilidade + Brier score
  * Baselines:      aleatório, regra "situação cadastral", regra "dívida"

INSUMO (o que faltava): um CSV rotulado `cnpj,label` onde label∈{0,1}
(1 = fraude/irregularidade confirmada). Gere o template com
`scripts/preparar_dataset_rotulado.py`.

Uso:
    python scripts/avaliar_score.py --labels data/rotulos.csv
    python scripts/avaliar_score.py --labels data/rotulos.csv --threshold 60
    python scripts/avaliar_score.py --labels data/rotulos.csv --scores-cache out/scores.csv

Dependência: numpy (apenas). As métricas são implementadas em numpy puro para
não exigir scikit-learn.
"""
from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

# Permite rodar como script solto (python scripts/avaliar_score.py).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.risk_score import calcular_score  # noqa: E402

N_BOOTSTRAP = 2000
RNG = np.random.default_rng(42)


# ===========================================================================
# 0. Métricas em numpy puro (substituem sklearn)
# ===========================================================================
def roc_auc_score(y: np.ndarray, s: np.ndarray) -> float:
    """AUC via estatística de Mann-Whitney U (com tratamento de empates)."""
    pos = s[y == 1]
    neg = s[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(len(s), float)
    ranks[order] = np.arange(1, len(s) + 1)
    # média de ranks para empates
    _, inv, counts = np.unique(s, return_inverse=True, return_counts=True)
    sums = np.zeros(len(counts))
    np.add.at(sums, inv, ranks)
    ranks = (sums / counts)[inv]
    r_pos = ranks[y == 1].sum()
    n_p, n_n = len(pos), len(neg)
    return float((r_pos - n_p * (n_p + 1) / 2) / (n_p * n_n))


def average_precision_score(y: np.ndarray, s: np.ndarray) -> float:
    """Average precision = área sob a curva precision-recall (PR-AUC)."""
    order = np.argsort(-s, kind="mergesort")
    y = y[order]
    tp = np.cumsum(y)
    fp = np.cumsum(1 - y)
    precision = tp / np.maximum(tp + fp, 1)
    total_pos = y.sum()
    if total_pos == 0:
        return float("nan")
    recall = tp / total_pos
    # soma de precision nos pontos onde recall aumenta (um novo positivo é recuperado)
    delta = np.diff(np.concatenate(([0.0], recall)))
    return float(np.sum(precision * delta))


def brier_score_loss(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def precision_recall_f1(y: np.ndarray, y_hat: np.ndarray) -> tuple[float, float, float]:
    tp = int(np.sum((y_hat == 1) & (y == 1)))
    fp = int(np.sum((y_hat == 1) & (y == 0)))
    fn = int(np.sum((y_hat == 0) & (y == 1)))
    pr = tp / (tp + fp) if tp + fp else 0.0
    rc = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * pr * rc / (pr + rc) if pr + rc else 0.0
    return pr, rc, f1


def confusion_2x2(y: np.ndarray, y_hat: np.ndarray) -> tuple[int, int, int, int]:
    tn = int(np.sum((y_hat == 0) & (y == 0)))
    fp = int(np.sum((y_hat == 1) & (y == 0)))
    fn = int(np.sum((y_hat == 0) & (y == 1)))
    tp = int(np.sum((y_hat == 1) & (y == 1)))
    return tn, fp, fn, tp


def calibration_curve(y: np.ndarray, p: np.ndarray, n_bins: int = 5
                      ) -> tuple[np.ndarray, np.ndarray]:
    """Bins por quantil: retorna (fração real de positivos, prob média prevista)."""
    quantis = np.quantile(p, np.linspace(0, 1, n_bins + 1))
    quantis = np.unique(quantis)
    if len(quantis) < 2:
        raise ValueError("variância insuficiente para binar")
    frac_real, frac_prev = [], []
    for lo, hi, ultimo in zip(quantis[:-1], quantis[1:],
                              [False] * (len(quantis) - 2) + [True]):
        mask = (p >= lo) & (p <= hi if ultimo else p < hi)
        if mask.sum() == 0:
            continue
        frac_real.append(float(y[mask].mean()))
        frac_prev.append(float(p[mask].mean()))
    return np.array(frac_real), np.array(frac_prev)


# ===========================================================================
# 1. Obtenção dos scores para os CNPJs rotulados
# ===========================================================================
def _remover_fontes_oficiais(consulta: dict) -> dict:
    """Zera TODAS as camadas confirmadas por fonte oficial (sanção + dívida,
    do alvo e da rede), deixando só os sinais INFERIDOS (cadastro + rede
    societária + endereço). Usado p/ medir o poder preditivo sem *leakage*:
    como o rótulo vem da sanção, mantê-la no score seria trapaça."""
    consulta = dict(consulta)
    consulta["_sancoes_alvo"] = []
    consulta["_dividas_alvo"] = None
    consulta["_dividas_rede"] = 0
    vinculos = []
    for v in consulta.get("_vinculos") or []:
        v = dict(v)
        v["sancoes_socio"] = None
        v["sancoes_satelite"] = None
        vinculos.append(v)
    consulta["_vinculos"] = vinculos
    return consulta


def scores_do_modelo(cnpjs: list[str], apenas_inferidos: bool = False
                     ) -> dict[str, float]:
    """Consulta o grafo e roda o motor de risco para cada CNPJ.

    Retorna {cnpj: risco∈[0,100]}, onde risco = 100 − nexus_score.
    Se `apenas_inferidos`, remove as camadas confirmadas por fonte oficial
    (avaliação livre de vazamento). Importação tardia do GraphDB.
    """
    from app.services.graph_db import get_graph_db

    db = get_graph_db()
    out: dict[str, float] = {}
    for cnpj in cnpjs:
        try:
            consulta = db.consultar(cnpj)
            if apenas_inferidos:
                consulta = _remover_fontes_oficiais(consulta)
            r = calcular_score(consulta)
            out[cnpj] = 100.0 - float(r["nexus_score"])
        except Exception as exc:  # noqa: BLE001 — não derrubar o lote por 1 CNPJ
            print(f"  [aviso] falha em {cnpj}: {exc}", file=sys.stderr)
    return out


# ===========================================================================
# 2. Baselines (o "comparação com baseline" que a crítica cobra)
# ===========================================================================
def baseline_aleatorio(_consulta: dict) -> float:
    """Risco aleatório — piso de referência (AUC esperado ≈ 0,5)."""
    return float(RNG.uniform(0, 100))


def baseline_situacao(consulta: dict) -> float:
    """Regra ingênua: só olha a situação cadastral da própria empresa."""
    s = str((consulta.get("_empresa_raw") or {}).get("situacao_cadastral", "")).upper()
    return {"INAPTA": 90.0, "BAIXADA": 60.0, "SUSPENSA": 40.0}.get(s, 0.0)


def baseline_divida(consulta: dict) -> float:
    """Regra ingênua: só olha se há dívida ativa na União."""
    d = consulta.get("_dividas_alvo") or {}
    return 80.0 if int(d.get("inscricoes") or 0) > 0 else 0.0


BASELINES: dict[str, Callable[[dict], float]] = {
    "aleatorio": baseline_aleatorio,
    "regra_situacao": baseline_situacao,
    "regra_divida": baseline_divida,
}


# ===========================================================================
# 3. Métricas com intervalo de confiança por bootstrap
# ===========================================================================
@dataclass
class Metricas:
    nome: str
    roc_auc: float = 0.0
    pr_auc: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    brier: float = 0.0
    ic: dict[str, tuple[float, float]] = field(default_factory=dict)


def _ic95(valores: np.ndarray) -> tuple[float, float]:
    return float(np.percentile(valores, 2.5)), float(np.percentile(valores, 97.5))


def avaliar(nome: str, y: np.ndarray, risco: np.ndarray, threshold: float) -> Metricas:
    """Calcula métricas pontuais + IC95% por bootstrap estratificado."""
    p = risco / 100.0                       # risco→probabilidade p/ Brier/calibração
    y_hat = (risco >= threshold).astype(int)

    m = Metricas(nome=nome)
    m.roc_auc = roc_auc_score(y, risco)
    m.pr_auc = average_precision_score(y, risco)
    pr, rc, f1 = precision_recall_f1(y, y_hat)
    m.precision, m.recall, m.f1 = pr, rc, f1
    m.brier = brier_score_loss(y, p)

    n = len(y)
    boot = {k: [] for k in ("roc_auc", "pr_auc", "precision", "recall", "f1")}
    for _ in range(N_BOOTSTRAP):
        idx = RNG.integers(0, n, n)
        yb, rb = y[idx], risco[idx]
        if yb.sum() == 0 or yb.sum() == len(yb):
            continue                        # amostra degenerada (só uma classe)
        yhb = (rb >= threshold).astype(int)
        boot["roc_auc"].append(roc_auc_score(yb, rb))
        boot["pr_auc"].append(average_precision_score(yb, rb))
        pb, rcb, f1b = precision_recall_f1(yb, yhb)
        boot["precision"].append(pb)
        boot["recall"].append(rcb)
        boot["f1"].append(f1b)
    m.ic = {k: _ic95(np.array(v)) for k, v in boot.items() if v}
    return m


def melhor_threshold(y: np.ndarray, risco: np.ndarray) -> tuple[float, float]:
    """Limiar que maximiza F1 (útil pra reportar o ponto de operação ótimo)."""
    melhor_f1, melhor_t = 0.0, 50.0
    for t in range(0, 101, 1):
        yhat = (risco >= t).astype(int)
        _, _, f1 = precision_recall_f1(y, yhat)
        if f1 > melhor_f1:
            melhor_f1, melhor_t = float(f1), float(t)
    return melhor_t, melhor_f1


# ===========================================================================
# 4. Relatório
# ===========================================================================
def _linha_ic(m: Metricas, campo: str) -> str:
    val = getattr(m, campo)
    if campo in m.ic:
        lo, hi = m.ic[campo]
        return f"{val:.3f} [{lo:.3f}–{hi:.3f}]"
    return f"{val:.3f}"


def imprimir_relatorio(modelos: list[Metricas], y: np.ndarray,
                       risco_nexus: np.ndarray, threshold: float) -> None:
    n, pos = len(y), int(y.sum())
    print("\n" + "=" * 70)
    print("AVALIAÇÃO DO NEXUS TRUST SCORE")
    print("=" * 70)
    print(f"Amostra: {n} empresas | fraude={pos} ({pos / n:.1%}) | "
          f"limiar de decisão: risco ≥ {threshold:.0f}")
    print(f"Prevalência (AUC-PR de um classificador aleatório) ≈ {pos / n:.3f}\n")

    cab = f"{'modelo':<18}{'ROC-AUC':<22}{'PR-AUC':<22}{'F1':<22}"
    print(cab)
    print("-" * len(cab))
    for m in modelos:
        print(f"{m.nome:<18}{_linha_ic(m, 'roc_auc'):<22}"
              f"{_linha_ic(m, 'pr_auc'):<22}{_linha_ic(m, 'f1'):<22}")

    nexus = next(m for m in modelos if m.nome == "nexus")
    print("\n— NEXUS no ponto de operação —")
    print(f"  precision: {_linha_ic(nexus, 'precision')}")
    print(f"  recall:    {_linha_ic(nexus, 'recall')}")
    print(f"  Brier:     {nexus.brier:.3f}  (menor = melhor calibrado)")

    y_hat = (risco_nexus >= threshold).astype(int)
    tn, fp, fn, tp = confusion_2x2(y, y_hat)
    print("\n— Matriz de confusão (NEXUS) —")
    print(f"            previu_limpo  previu_fraude")
    print(f"  é_limpo   {tn:>11}  {fp:>13}")
    print(f"  é_fraude  {fn:>11}  {tp:>13}")

    t_otimo, f1_otimo = melhor_threshold(y, risco_nexus)
    print(f"\n— Limiar ótimo (max F1): risco ≥ {t_otimo:.0f}  →  F1={f1_otimo:.3f}")

    print("\n— Calibração (risco previsto × fração real de fraude) —")
    try:
        frac_real, frac_prev = calibration_curve(y, risco_nexus / 100.0, n_bins=5)
        for prev, real in zip(frac_prev, frac_real):
            print(f"  risco≈{prev * 100:5.1f}  →  fraude real {real:5.1%}")
    except ValueError:
        print("  (amostra pequena demais para curva de calibração)")
    print("=" * 70 + "\n")


# ===========================================================================
# 5. I/O
# ===========================================================================
def carregar_labels(caminho: Path) -> dict[str, int]:
    rotulos: dict[str, int] = {}
    with caminho.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            cnpj = str(row["cnpj"]).strip()
            rotulos[cnpj] = int(row["label"])
    return rotulos


def carregar_cache(caminho: Path) -> dict[str, float]:
    cache: dict[str, float] = {}
    with caminho.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            cache[str(row["cnpj"]).strip()] = float(row["risco"])
    return cache


def salvar_cache(caminho: Path, risco: dict[str, float]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["cnpj", "risco"])
        for cnpj, r in risco.items():
            w.writerow([cnpj, r])


def main() -> None:
    ap = argparse.ArgumentParser(description="Avalia o NEXUS Trust Score.")
    ap.add_argument("--labels", required=True, type=Path,
                    help="CSV rotulado: colunas cnpj,label (label 1=fraude)")
    ap.add_argument("--threshold", type=float, default=50.0,
                    help="Limiar de risco p/ classificar como fraude (default 50)")
    ap.add_argument("--scores-cache", type=Path,
                    help="CSV cnpj,risco para reusar (evita reconsultar o grafo)")
    ap.add_argument("--apenas-inferidos", action="store_true",
                    help="Remove camadas oficiais (sanção/dívida) p/ medir o poder "
                         "preditivo do motor inferido sem vazamento de rótulo")
    args = ap.parse_args()

    rotulos = carregar_labels(args.labels)
    cnpjs = list(rotulos)
    print(f"Carregados {len(cnpjs)} CNPJs rotulados de {args.labels}")

    if args.scores_cache and args.scores_cache.exists():
        risco_map = carregar_cache(args.scores_cache)
        print(f"Scores lidos do cache {args.scores_cache}")
    else:
        modo = "INFERIDO (sem fontes oficiais)" if args.apenas_inferidos else "completo"
        print(f"Consultando o grafo e calculando scores... [modo: {modo}]")
        risco_map = scores_do_modelo(cnpjs, apenas_inferidos=args.apenas_inferidos)
        if args.scores_cache:
            salvar_cache(args.scores_cache, risco_map)
            print(f"Cache salvo em {args.scores_cache}")

    # Mantém só CNPJs com score e rótulo válidos.
    cnpjs = [c for c in cnpjs if c in risco_map]
    if not cnpjs:
        sys.exit("Nenhum CNPJ com score calculado — verifique o grafo/labels.")
    y = np.array([rotulos[c] for c in cnpjs])
    risco_nexus = np.array([risco_map[c] for c in cnpjs])
    if y.sum() == 0 or y.sum() == len(y):
        sys.exit("Dataset tem uma única classe — avaliação impossível.")

    modelos = [avaliar("nexus", y, risco_nexus, args.threshold)]

    # Baselines: precisam reconsultar o grafo (usam campos da consulta).
    if not (args.scores_cache and args.scores_cache.exists()):
        from app.services.graph_db import get_graph_db
        db = get_graph_db()
        consultas = {c: db.consultar(c) for c in cnpjs}
        for nome, fn in BASELINES.items():
            rb = np.array([fn(consultas[c]) for c in cnpjs])
            modelos.append(avaliar(nome, y, rb, args.threshold))

    imprimir_relatorio(modelos, y, risco_nexus, args.threshold)


if __name__ == "__main__":
    main()
