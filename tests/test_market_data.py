"""Fase 4 — testes do terminal B3 (parsing/contrato com mocks; rede opcional)."""
import os

from fastapi.testclient import TestClient

import app.services.market_data as market
from app.main import app
from app.services.market_data import _extrair_veredito, _normalizar_ticker

_DADOS_FAKE = {
    "ticker": "PETR4.SA",
    "nome": "Petrobras",
    "preco_atual": 41.14,
    "moeda": "BRL",
    "multiplos": {"pl": 5.06, "dy": 9.41, "roe": 25.6},
    "historico": [
        {"data": "2025-12-09", "fechamento": 29.96},
        {"data": "2026-06-09", "fechamento": 41.14},
    ],
}


class _FakeLLM:
    model = "gemma-fake"

    async def chat(self, system, user, **kwargs):
        return "VEREDITO: STRONG BUY\nMúltiplos atrativos: P/L baixo e DY elevado."


def test_normalizar_ticker():
    assert _normalizar_ticker("petr4") == "PETR4.SA"
    assert _normalizar_ticker("VALE3.SA") == "VALE3.SA"


def test_extrair_veredito_strong_buy():
    v, tese = _extrair_veredito("VEREDITO: STRONG BUY\nTese aqui.")
    assert v == "STRONG BUY"
    assert tese == "Tese aqui."


def test_extrair_veredito_buy_mapeia_para_strong_buy():
    v, _ = _extrair_veredito("VEREDITO: BUY\n...")
    assert v == "STRONG BUY"


def test_extrair_veredito_default_hold():
    v, _ = _extrair_veredito("não consegui decidir")
    assert v == "HOLD"


def test_endpoint_analyze_ok(monkeypatch):
    monkeypatch.setattr(market, "obter_acao", lambda t: _DADOS_FAKE)
    monkeypatch.setattr(market, "get_llm", lambda: _FakeLLM())
    with TestClient(app) as c:
        r = c.post("/api/v1/market/analyze", json={"ticker": "PETR4"})
    assert r.status_code == 200
    body = r.json()
    assert body["veredito"] == "STRONG BUY"
    assert body["multiplos"]["pl"] == 5.06


def test_endpoint_stock_ok(monkeypatch):
    monkeypatch.setattr(market, "obter_acao", lambda t: _DADOS_FAKE)
    with TestClient(app) as c:
        r = c.get("/api/v1/market/stock/PETR4")
    assert r.status_code == 200
    assert r.json()["ticker"] == "PETR4.SA"


# --- Teste de rede real (opcional): só roda com NEXUS_TEST_NETWORK=1 ---
import pytest  # noqa: E402


@pytest.mark.skipif(
    os.environ.get("NEXUS_TEST_NETWORK") != "1",
    reason="Teste de rede desativado (defina NEXUS_TEST_NETWORK=1 para rodar).",
)
def test_obter_acao_rede_real():
    d = market.obter_acao("PETR4")
    assert d["ticker"] == "PETR4.SA"
    assert d["historico"] and d["preco_atual"] > 0
