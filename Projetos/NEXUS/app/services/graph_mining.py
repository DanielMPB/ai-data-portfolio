"""Graph Mining sobre a rede societária de 2º grau.

Enquanto `graph_db.py` faz a *travessia* do grafo (recuperação de vínculos),
este módulo aplica **mineração de grafos** com NetworkX para extrair padrões e
estruturas latentes da teia societária:

  * Centralidade de grau — identifica o sócio "conector" (hub) que costura o
    grupo econômico (potencial laranja / administrador-chave).
  * Componentes conexos — delimita o **grupo econômico oculto** (holding) ao qual
    a empresa-alvo pertence.
  * Pontos de articulação (cut vertices) — sócios/empresas cuja remoção
    fragmentaria a rede (pontos de fragilidade/controle).
  * Densidade e métricas estruturais — coesão da rede.
"""
from __future__ import annotations

from typing import Any

import networkx as nx


def construir_grafo(grafo: dict[str, Any]) -> nx.Graph:
    """Constrói um grafo NetworkX não-direcionado a partir do contrato de grafo."""
    g = nx.Graph()
    for n in grafo["nodes"]:
        g.add_node(n["id"], label=n.get("label"), group=n.get("group"))
    for e in grafo["edges"]:
        g.add_edge(e["from"], e["to"], label=e.get("label"))
    return g


def minerar(grafo: dict[str, Any], raiz: str) -> dict[str, Any]:
    """Extrai métricas de graph mining da rede societária da empresa-alvo."""
    g = construir_grafo(grafo)
    n_nos = g.number_of_nodes()
    n_arestas = g.number_of_edges()

    if n_nos <= 1:
        return {
            "total_nos": n_nos,
            "total_arestas": n_arestas,
            "densidade": 0.0,
            "grupo_economico": {"tamanho": n_nos, "empresas": int(g.has_node(raiz)), "socios": 0},
            "socio_conector_central": None,
            "pontos_articulacao": 0,
        }

    # --- Centralidade de grau: maior "hub" entre os sócios (conectores) ---
    centralidade = nx.degree_centrality(g)
    socios = [n for n, d in g.nodes(data=True) if str(d.get("group", "")).startswith("Socio")]
    socio_central = None
    if socios:
        top = max(socios, key=lambda n: centralidade[n])
        socio_central = {
            "id": top,
            "nome": g.nodes[top].get("label"),
            "centralidade_grau": round(centralidade[top], 4),
            "vinculos": g.degree(top),
        }

    # --- Grupo econômico: componente conexo que contém a empresa-alvo ---
    if g.has_node(raiz):
        componente = nx.node_connected_component(g, raiz)
    else:
        componente = set()
    sub = g.subgraph(componente)
    empresas_grupo = sum(
        1 for _, d in sub.nodes(data=True)
        if d.get("group") in ("Alvo", "EmpresaRelacionada")
    )
    socios_grupo = sum(
        1 for _, d in sub.nodes(data=True)
        if str(d.get("group", "")).startswith("Socio")
    )

    # --- Pontos de articulação (cut vertices) ---
    try:
        pontos = list(nx.articulation_points(g))
    except Exception:  # noqa: BLE001 — robustez a grafos degenerados
        pontos = []

    return {
        "total_nos": n_nos,
        "total_arestas": n_arestas,
        "densidade": round(nx.density(g), 4),
        "grupo_economico": {
            "tamanho": len(componente),
            "empresas": empresas_grupo,
            "socios": socios_grupo,
        },
        "socio_conector_central": socio_central,
        "pontos_articulacao": len(pontos),
    }
