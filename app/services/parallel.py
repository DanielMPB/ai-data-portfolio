"""Computação paralela — due diligence de portfólio em múltiplos núcleos.

Avaliar uma carteira (dezenas/centenas de CNPJs) é uma carga embaraçosamente
paralela: cada empresa é independente. A análise é dominada pela consulta
analítica ao DuckDB, uma operação **nativa que libera o GIL** durante a execução
— portanto um `ThreadPoolExecutor` distribui as consultas por vários núcleos com
paralelismo real, sem o custo/instabilidade de serializar objetos nativos entre
processos.

Cada thread usa um *cursor* independente da conexão DuckDB compartilhada
(`con.cursor()` cria uma conexão à mesma base, segura para uso concorrente).
"""
from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.services.graph_db import GraphDB, get_graph_db
from app.services.graph_mining import minerar
from app.services.risk_score import calcular_score


def _avaliar_um(db: GraphDB, cnpj: str) -> dict[str, Any]:
    """Tarefa unitária (thread): consulta + score + mining para um único CNPJ."""
    try:
        res = db.consultar(cnpj)
        raiz = res["empresa_principal"]["cnpj"]
        score = calcular_score(res)
        mining = minerar(res["grafo"], raiz)
        return {
            "cnpj": raiz,
            "razao_social": res["empresa_principal"]["razao_social"],
            "situacao": res["empresa_principal"]["situacao"],
            "nexus_score": score["nexus_score"],
            "classificacao": score["classificacao"],
            "satelites": score["satelites_analisadas"],
            "grupo_economico": mining["grupo_economico"]["tamanho"],
            "thread": threading.get_ident(),
        }
    except Exception as exc:  # noqa: BLE001 — isola falha de 1 CNPJ sem derrubar o lote
        return {"cnpj": cnpj, "erro": str(exc)}


def avaliar_portfolio(
    cnpjs: list[str], max_workers: int | None = None
) -> dict[str, Any]:
    """Avalia uma carteira de CNPJs em paralelo (threads). Retorna resultados + telemetria."""
    n_workers = max_workers or min(8, os.cpu_count() or 1) or 1
    db = get_graph_db()
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=n_workers) as ex:
        resultados = list(ex.map(lambda c: _avaliar_um(db, c), cnpjs))
    dt = time.perf_counter() - t0
    return {
        "total": len(cnpjs),
        "workers": n_workers,
        "tempo_segundos": round(dt, 3),
        "resultados": resultados,
    }


def avaliar_portfolio_sequencial(cnpjs: list[str]) -> dict[str, Any]:
    """Versão sequencial (1 thread) — usada apenas para benchmark comparativo."""
    db = get_graph_db()
    t0 = time.perf_counter()
    resultados = [_avaliar_um(db, c) for c in cnpjs]
    dt = time.perf_counter() - t0
    return {
        "total": len(cnpjs),
        "workers": 1,
        "tempo_segundos": round(dt, 3),
        "resultados": resultados,
    }
