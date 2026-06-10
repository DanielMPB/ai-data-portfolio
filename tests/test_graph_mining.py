"""Testes do módulo de Graph Mining (NetworkX)."""
from app.services.graph_mining import construir_grafo, minerar

RAIZ = "00000001"


def _grafo_exemplo() -> dict:
    # Alvo conectado por 2 sócios; um sócio (S1) também liga a 2 empresas-satélite.
    nodes = [
        {"id": RAIZ, "label": "Alvo", "group": "Alvo"},
        {"id": "S1", "label": "Sócio Hub", "group": "SocioPF"},
        {"id": "S2", "label": "Sócio Periférico", "group": "SocioPF"},
        {"id": "E1", "label": "Satélite 1", "group": "EmpresaRelacionada"},
        {"id": "E2", "label": "Satélite 2", "group": "EmpresaRelacionada"},
    ]
    edges = [
        {"from": "S1", "to": RAIZ, "label": "Sócio Direto"},
        {"from": "S2", "to": RAIZ, "label": "Sócio Direto"},
        {"from": "S1", "to": "E1", "label": "Participação Externa"},
        {"from": "S1", "to": "E2", "label": "Participação Externa"},
    ]
    return {"nodes": nodes, "edges": edges}


def test_construir_grafo():
    g = construir_grafo(_grafo_exemplo())
    assert g.number_of_nodes() == 5
    assert g.number_of_edges() == 4


def test_socio_central_e_o_hub():
    m = minerar(_grafo_exemplo(), RAIZ)
    assert m["socio_conector_central"]["id"] == "S1"  # maior grau
    assert m["socio_conector_central"]["vinculos"] == 3


def test_grupo_economico_abrange_satelites():
    m = minerar(_grafo_exemplo(), RAIZ)
    # tudo está conexo: 3 empresas (alvo + 2 satélites) e 2 sócios
    assert m["grupo_economico"]["empresas"] == 3
    assert m["grupo_economico"]["socios"] == 2
    assert m["grupo_economico"]["tamanho"] == 5


def test_pontos_articulacao():
    # S1 é ponto de articulação (remoção isola E1 e E2)
    m = minerar(_grafo_exemplo(), RAIZ)
    assert m["pontos_articulacao"] >= 1


def test_grafo_trivial():
    m = minerar({"nodes": [{"id": RAIZ, "group": "Alvo"}], "edges": []}, RAIZ)
    assert m["densidade"] == 0.0
    assert m["socio_conector_central"] is None
