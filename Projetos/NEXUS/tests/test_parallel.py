"""Testes de computação paralela (portfólio multiprocessing). Requer base ETL."""
import duckdb
import pytest

from app.core.config import settings
from app.services.parallel import avaliar_portfolio, avaliar_portfolio_sequencial

pytestmark = pytest.mark.skipif(
    not settings.duckdb_path.exists(),
    reason="nexus.duckdb ausente — rode o ETL (Fase 0) antes.",
)


def _amostra(n: int) -> list[str]:
    con = duckdb.connect(str(settings.duckdb_path), read_only=True)
    rows = con.execute(
        "SELECT cnpj_basico FROM edges_socios GROUP BY 1 ORDER BY count(*) DESC LIMIT ?",
        [n],
    ).fetchall()
    con.close()
    return [r[0] for r in rows]


def test_sequencial_avalia_todos():
    cnpjs = _amostra(5)
    r = avaliar_portfolio_sequencial(cnpjs)
    assert r["total"] == 5
    assert len(r["resultados"]) == 5
    assert all("nexus_score" in x or "erro" in x for x in r["resultados"])


def test_paralelo_paridade_com_sequencial():
    cnpjs = _amostra(6)
    seq = avaliar_portfolio_sequencial(cnpjs)
    par = avaliar_portfolio(cnpjs, max_workers=2)
    assert par["workers"] == 2
    # mesmos scores, independentemente da ordem/execução
    by_seq = {x["cnpj"]: x.get("nexus_score") for x in seq["resultados"]}
    by_par = {x["cnpj"]: x.get("nexus_score") for x in par["resultados"]}
    assert by_seq == by_par


def test_paralelo_usa_multiplas_threads():
    cnpjs = _amostra(8)
    par = avaliar_portfolio(cnpjs, max_workers=4)
    threads = {x.get("thread") for x in par["resultados"] if "thread" in x}
    # com 4 workers e 8 tarefas, espera-se mais de uma thread efetivamente usada
    assert len(threads) >= 2
