"""Calculadora de Relações com Investidores (RI) baseada em IA.

Encapsula os indicadores de caixa e liquidez em um prompt estruturado de auditoria
financeira. O LLM retorna um relatório em Markdown com cinco seções fixas e um
Rating Final de Maturidade Financeira (A a D).
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from app.services.llm_client import LLMClient, get_llm

# Aceita "RATING: B", "RATING FINAL: B", "RATING_FINAL: B" e "RATING: [B]".
# Exige os dois-pontos para não casar com o título "RATING FINAL DE MATURIDADE...".
_RE_RATING = re.compile(r"RATING[_ ]*(?:FINAL[_ ]*)?:\s*\[?\s*([ABCD])", re.IGNORECASE)


class PayloadRI(BaseModel):
    """Contrato de entrada da auditoria de saúde de caixa e liquidez."""

    setor: str = Field(..., description="Setor/segmento de atuação da empresa.")
    liquidez_imediata: float = Field(
        ..., description="Índice de Liquidez Imediata (Disponível / Passivo Circulante).")
    reserva_contingencia: float = Field(..., description="Reserva de contingência (R$).")
    disponibilidade_liquida_protecao: float = Field(
        ..., description="Disponibilidade líquida de proteção (R$).")
    grau_cobertura_crise: float = Field(
        ..., description="Grau de cobertura de crise: meses de operação cobertos pela reserva.")
    prazo_medio_recebimento: int = Field(
        ..., ge=0, description="Prazo Médio de Recebimento — PMR (dias).")
    prazo_medio_pagamento: int = Field(
        ..., ge=0, description="Prazo Médio de Pagamento — PMP (dias).")


_SYSTEM = (
    "Você é um auditor sênior de Relações com Investidores (RI) e analista de risco de "
    "crédito e liquidez corporativa. Avalie a saúde de caixa, a blindagem de contingência "
    "e a maturidade financeira da empresa com rigor técnico, considerando o cenário "
    "macroeconômico do SETOR informado. Responda SEMPRE em português do Brasil."
)

_INSTRUCOES = (
    "Produza um relatório em Markdown com EXATAMENTE estas cinco seções, nesta ordem, "
    "cada uma iniciada por `# ` (título de nível 1):\n\n"
    "# DIAGNÓSTICO DA SAÚDE DE CAIXA E LIQUIDEZ\n"
    "Analise o Índice de Liquidez Imediata e a Disponibilidade Líquida frente ao cenário "
    "macroeconômico do setor da empresa.\n\n"
    "# AVALIAÇÃO DA RESERVA E BLINDAGEM DE CONTINGÊNCIA\n"
    "Avalie o Grau de Cobertura de Crise. Explique se a proporção de contingência escolhida "
    "pela empresa é prudente, agressiva ou insuficiente para a realidade do segmento dela.\n\n"
    "# VULNERABILIDADES CRÍTICAS E PONTOS DE ATENÇÃO\n"
    "Aponte os principais gargalos detectados, como riscos de insolvência, dependência "
    "excessiva de recebíveis de clientes (analise o PMR), ou desalinhamento de prazos de "
    "pagamento (compare PMR e PMP).\n\n"
    "# PLANO DE AÇÃO E RECOMENDAÇÕES PARA INVESTIDORES\n"
    "Enumere passos práticos para a gerência mitigar os riscos encontrados e forneça uma "
    "tese clara de como um investidor institucional enxergaria a governança desse caixa.\n\n"
    "# RATING FINAL DE MATURIDADE FINANCEIRA\n"
    "Inicie esta seção EXATAMENTE com a linha `RATING: X` (X = uma única letra A, B, C ou D). "
    "A = Excelente blindagem; D = Alto risco de insolvência técnica. Em seguida, justifique "
    "o veredito em 1-2 frases."
)


def _montar_prompt(p: PayloadRI) -> str:
    return (
        f"{_INSTRUCOES}\n\n"
        "## Indicadores financeiros da empresa\n"
        f"- Setor da empresa: {p.setor}\n"
        f"- Índice de Liquidez Imediata: {p.liquidez_imediata:.2f}\n"
        f"- Reserva de Contingência: R$ {p.reserva_contingencia:,.2f}\n"
        f"- Disponibilidade Líquida de Proteção: R$ {p.disponibilidade_liquida_protecao:,.2f}\n"
        f"- Grau de Cobertura de Crise: {p.grau_cobertura_crise:.1f} meses\n"
        f"- Prazo Médio de Recebimento (PMR): {p.prazo_medio_recebimento} dias\n"
        f"- Prazo Médio de Pagamento (PMP): {p.prazo_medio_pagamento} dias\n"
    )


def _extrair_rating(texto: str) -> tuple[str, str]:
    """Extrai o rating (A-D) e remove a linha `RATING: X` do corpo (fica no badge)."""
    m = _RE_RATING.search(texto)
    rating = m.group(1).upper() if m else "C"
    relatorio = _RE_RATING.sub("", texto, count=1).strip()
    return rating, relatorio


async def auditar(payload: PayloadRI, llm: LLMClient | None = None) -> dict[str, Any]:
    """Executa a auditoria de RI via LLM e retorna rating + relatório Markdown."""
    client = llm or get_llm()
    resposta = await client.chat(_SYSTEM, _montar_prompt(payload), max_tokens=4000)
    rating, relatorio = _extrair_rating(resposta)
    return {
        "rating": rating,
        "relatorio_markdown": relatorio,
        "modelo": client.model,
    }
