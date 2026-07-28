"""Fase 3 — testes da Calculadora de RI (parsing + contrato, com LLM mockado)."""
import asyncio

from fastapi.testclient import TestClient

import app.services.ir_agent as ir_agent
from app.main import app
from app.services.ir_agent import PayloadRI, _extrair_rating, auditar
from app.services.llm_client import LLMUnavailableError

PAYLOAD = {
    "setor": "Tecnologia",
    "liquidez_imediata": 0.8,
    "reserva_contingencia": 500_000.0,
    "disponibilidade_liquida_protecao": 1_200_000.0,
    "grau_cobertura_crise": 6.0,
    "prazo_medio_recebimento": 45,
    "prazo_medio_pagamento": 30,
}

_RESPOSTA_FAKE = (
    "# DIAGNÓSTICO DA SAÚDE DE CAIXA E LIQUIDEZ\n- Liquidez apertada\n"
    "# AVALIAÇÃO DA RESERVA E BLINDAGEM DE CONTINGÊNCIA\n- Reserva prudente\n"
    "# VULNERABILIDADES CRÍTICAS E PONTOS DE ATENÇÃO\n- PMR > PMP\n"
    "# PLANO DE AÇÃO E RECOMENDAÇÕES PARA INVESTIDORES\n- Renegociar prazos\n"
    "# RATING FINAL DE MATURIDADE FINANCEIRA\nRATING: B\nBlindagem sólida.\n"
)


class _FakeLLM:
    model = "gemma-fake"

    def __init__(self, resposta: str = _RESPOSTA_FAKE, falha: bool = False):
        self._resposta = resposta
        self._falha = falha

    async def chat(self, system, user, **kwargs):
        if self._falha:
            raise LLMUnavailableError("offline")
        return self._resposta


def test_extrair_rating_remove_linha():
    rating, relatorio = _extrair_rating(_RESPOSTA_FAKE)
    assert rating == "B"
    assert "RATING: B" not in relatorio
    # o título da seção (sem dois-pontos) NÃO deve ser confundido com o rating
    assert "# RATING FINAL DE MATURIDADE FINANCEIRA" in relatorio
    assert relatorio.startswith("# DIAGNÓSTICO")


def test_titulo_secao_nao_e_confundido_com_rating():
    # "RATING FINAL DE..." (sem ":") não deve casar; só "RATING: X" conta
    rating, _ = _extrair_rating("# RATING FINAL DE MATURIDADE FINANCEIRA\nRATING: A\n")
    assert rating == "A"


def test_extrair_rating_default_quando_ausente():
    rating, _ = _extrair_rating("# Diagnóstico\n- algo")
    assert rating == "C"


def test_remove_bloco_de_raciocinio():
    # Modelos com reasoning (Gemma 4) emitem <thought>...</thought> antes da resposta
    from app.services.llm_client import _limpar_raciocinio
    bruto = "<thought>vou analisar os dados...</thought>\n# DIAGNÓSTICO\n- ok"
    limpo = _limpar_raciocinio(bruto)
    assert "<thought>" not in limpo
    assert limpo.startswith("# DIAGNÓSTICO")


def test_auditar_com_llm_injetado():
    res = asyncio.run(auditar(PayloadRI(**PAYLOAD), llm=_FakeLLM()))
    assert res["rating"] == "B"
    assert "VULNERABILIDADES CRÍTICAS" in res["relatorio_markdown"]
    assert res["modelo"] == "gemma-fake"


def test_endpoint_ir_ok(monkeypatch):
    monkeypatch.setattr(ir_agent, "get_llm", lambda: _FakeLLM())
    with TestClient(app) as c:
        r = c.post("/api/v1/calculator/ir", json=PAYLOAD)
    assert r.status_code == 200
    body = r.json()
    assert body["rating"] == "B"
    assert "# DIAGNÓSTICO DA SAÚDE DE CAIXA E LIQUIDEZ" in body["relatorio_markdown"]


def test_endpoint_ir_llm_offline_retorna_503(monkeypatch):
    monkeypatch.setattr(ir_agent, "get_llm", lambda: _FakeLLM(falha=True))
    with TestClient(app) as c:
        r = c.post("/api/v1/calculator/ir", json=PAYLOAD)
    assert r.status_code == 503


def test_endpoint_ir_payload_invalido_retorna_422():
    with TestClient(app) as c:
        r = c.post("/api/v1/calculator/ir", json={"faturamento_anual": 1.0})
    assert r.status_code == 422
