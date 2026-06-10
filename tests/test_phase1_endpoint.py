"""Fase 1 — smoke test do endpoint de grafo (requer base ETL gerada)."""
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

pytestmark = pytest.mark.skipif(
    not settings.duckdb_path.exists(),
    reason="nexus.duckdb ausente — rode o ETL (Fase 0) antes.",
)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_dv_invalido_retorna_422(client):
    assert client.get("/api/v1/empresa/11222333000182").status_code == 422


def test_formato_invalido_retorna_422(client):
    assert client.get("/api/v1/empresa/123").status_code == 422


def test_inexistente_retorna_404(client):
    # Raiz alfanumérica sintética, ausente da base (CNPJs da RF ainda são numéricos).
    assert client.get("/api/v1/empresa/ZZZZZZZZ").status_code == 404


def test_amostra_rede(client):
    r = client.get("/api/v1/amostra/rede?n=4")
    assert r.status_code == 200
    d = r.json()
    assert {"grafo", "empresas"} <= d.keys()
    assert {"nodes", "edges"} <= d["grafo"].keys()
    assert d["grafo"]["nodes"], "amostra deve retornar nós"
    grupos = {n["group"] for n in d["grafo"]["nodes"]}
    assert "Alvo" in grupos


def test_contrato_grafo(client):
    # Busca uma raiz real presente na base de amostra/full
    import duckdb

    con = duckdb.connect(str(settings.duckdb_path), read_only=True)
    raiz = con.execute(
        "SELECT cnpj_basico FROM edges_socios GROUP BY 1 ORDER BY count(*) DESC LIMIT 1"
    ).fetchone()[0]
    con.close()

    r = client.get(f"/api/v1/empresa/{raiz}")
    assert r.status_code == 200
    d = r.json()
    assert "empresa_principal" in d and "grafo" in d
    assert {"nodes", "edges"} <= d["grafo"].keys()
    grupos = {n["group"] for n in d["grafo"]["nodes"]}
    assert "Alvo" in grupos
    # o nó alvo deve existir exatamente uma vez
    assert sum(n["group"] == "Alvo" for n in d["grafo"]["nodes"]) == 1
