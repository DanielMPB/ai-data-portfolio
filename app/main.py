"""NEXUS V2 — Aplicação FastAPI (gerenciamento de rotas assíncronas).

Backend-First: todas as rotas analíticas são expostas e homologadas no Swagger UI
(`/docs`) antes de qualquer acoplamento de interface.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path as FilePath

from fastapi import FastAPI, HTTPException, Path, Response
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope


class NoCacheStaticFiles(StaticFiles):
    """Serve estáticos com revalidação obrigatória — edições de CSS/JS aparecem
    no refresh normal, sem precisar versionar a URL."""

    async def get_response(self, path: str, scope: Scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        return resp

from app.core.validators import normalizar_cnpj, validar_cnpj_alfanumerico
from app.services.graph_db import GraphDB, get_graph_db
from app.services.graph_mining import minerar
from app.services.ir_agent import PayloadRI, auditar
from app.services.llm_client import LLMUnavailableError
from app.services.market_data import (
    TickerNaoEncontrado,
    analisar,
    market_overview,
    obter_acao,
    recomendacao_dia,
)
from app.services.parallel import avaliar_portfolio
from app.services.risk_score import calcular_score
from pydantic import BaseModel, Field


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicializa a engine DuckDB no startup (falha cedo se o ETL não rodou).
    try:
        get_graph_db()
    except FileNotFoundError as exc:
        # Não derruba a API — rotas que dependem da base retornarão 503.
        app.state.db_error = str(exc)
    else:
        app.state.db_error = None
    yield


app = FastAPI(
    title="NEXUS V2",
    version="2.0.0",
    description="Plataforma de due diligence corporativa — grafos societários, "
    "score de risco, calculadora de RI e terminal de mercado.",
    lifespan=lifespan,
)


def _db() -> GraphDB:
    """Acessa a engine de grafo ou retorna 503 se a base não está disponível."""
    try:
        return get_graph_db()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


def _resolver_raiz(cnpj: str) -> str:
    """Valida a entrada e devolve a raiz de 8 caracteres para consulta.

    Aceita a raiz (8 chars) ou o CNPJ completo (14 chars, com DV validado).
    """
    limpo = normalizar_cnpj(cnpj)
    if len(limpo) == 8:
        return limpo
    if len(limpo) == 14:
        if not validar_cnpj_alfanumerico(limpo):
            raise HTTPException(status_code=422, detail="CNPJ inválido (dígitos verificadores).")
        return limpo[:8]
    raise HTTPException(
        status_code=422,
        detail="Informe a raiz (8) ou o CNPJ completo (14 caracteres alfanuméricos).",
    )


@app.get("/health", tags=["infra"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/empresa/{cnpj}", tags=["due-diligence"])
async def empresa(cnpj: str = Path(..., description="Raiz (8) ou CNPJ completo (14)")):
    """Grafo societário de 2º grau da empresa-alvo (contrato homologado)."""
    raiz = _resolver_raiz(cnpj)
    resultado = _db().consultar(raiz)
    if resultado["_empresa_raw"] is None and not resultado["grafo"]["edges"]:
        raise HTTPException(status_code=404, detail="Empresa não encontrada na base.")
    # Motor de risco (Fase 2): score determinístico + contágio de rede.
    risco = calcular_score(resultado)
    # Graph mining: estrutura latente da rede societária (centralidade, grupo econômico).
    mineracao = minerar(resultado["grafo"], raiz)
    return {
        "empresa_principal": resultado["empresa_principal"],
        "risco": risco,
        "graph_mining": mineracao,
        "grafo": resultado["grafo"],
    }


# Amostra: a rede societária COMPLETA da HELPMED (~763 nós) — uma única empresa
# de rede gigante que renderiza bem, sem travar o navegador.
_AMOSTRA_CNPJS = ["48847523"]
_AMOSTRA_LIMITE = 800  # rede completa (HELPMED fica abaixo do teto)
_amostra_cache: bytes | None = None  # JSON já serializado (conjunto fixo → calcula 1x)


@app.get("/api/v1/amostra/rede", tags=["due-diligence"])
async def amostra_rede():
    """Grafo combinado de 10 empresas reais com muitas ligações (amostra fixa, cacheada)."""
    global _amostra_cache
    if _amostra_cache is None:
        db = _db()
        nodes: dict[str, Any] = {}
        edges: list[dict[str, Any]] = []
        vistos: set[str] = set()
        empresas: list[str] = []
        for cnpj in _AMOSTRA_CNPJS:
            r = db.consultar(cnpj, limite=_AMOSTRA_LIMITE)
            if r["_empresa_raw"]:
                empresas.append(r["empresa_principal"]["razao_social"])
            for nd in r["grafo"]["nodes"]:
                nodes.setdefault(nd["id"], nd)
            for e in r["grafo"]["edges"]:
                chave = f"{e['from']}|{e['to']}"
                if chave not in vistos:
                    vistos.add(chave)
                    edges.append(e)
        resultado = {"grafo": {"nodes": list(nodes.values()), "edges": edges}, "empresas": empresas}
        _amostra_cache = json.dumps(resultado, ensure_ascii=False).encode("utf-8")
    return Response(content=_amostra_cache, media_type="application/json")


class PortfolioRequest(BaseModel):
    cnpjs: list[str] = Field(..., min_length=1, max_length=500,
                             description="Lista de CNPJs/raízes a avaliar.")
    workers: int | None = Field(default=None, ge=1, le=32,
                                description="Nº de threads (default: núcleos da máquina).")


@app.post("/api/v1/portfolio/risco", tags=["due-diligence"])
async def portfolio_risco(req: PortfolioRequest):
    """Due diligence de uma carteira de CNPJs em PARALELO.

    Distribui a análise (grafo + score + mining) por múltiplos núcleos via
    ThreadPoolExecutor (as consultas DuckDB liberam o GIL).
    """
    # Executa o pool fora do event loop para não bloquear a API.
    return await asyncio.to_thread(avaliar_portfolio, req.cnpjs, req.workers)


@app.post("/api/v1/calculator/ir", tags=["calculadora-ri"])
async def calculator_ir(payload: PayloadRI):
    """Auditoria de maturidade de RI via LLM: Rating A–D + relatório Markdown."""
    try:
        return await auditar(payload)
    except LLMUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


class AnaliseMercadoRequest(BaseModel):
    ticker: str


@app.get("/api/v1/market/overview", tags=["mercado-b3"])
async def market_overview_route():
    """Panorama de mercado: cotações macro + watchlist de blue chips."""
    return await asyncio.to_thread(market_overview)


@app.get("/api/v1/market/recomendacao-dia", tags=["mercado-b3"])
async def market_recomendacao_dia():
    """Relatório de IA: melhores compras e empresas a evitar hoje (cesta ampla da B3)."""
    try:
        return await recomendacao_dia()
    except TickerNaoEncontrado as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except LLMUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/v1/market/stock/{ticker}", tags=["mercado-b3"])
async def market_stock(ticker: str):
    """Série histórica de 6 meses + múltiplos fundamentais (P/L, DY, ROE)."""
    try:
        return obter_acao(ticker)
    except TickerNaoEncontrado as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/v1/market/analyze", tags=["mercado-b3"])
async def market_analyze(req: AnaliseMercadoRequest):
    """Advisor IA: veredito STRONG BUY | HOLD | SELL + tese de valuation."""
    try:
        return await analisar(req.ticker)
    except TickerNaoEncontrado as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except LLMUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


# ---------------------------------------------------------------------------
# Frontend estático (Fase 5) — montado por último para não sombrear /api e /docs.
# Serve frontend/index.html em "/" e os assets (style.css, app.js).
# ---------------------------------------------------------------------------
_FRONTEND_DIR = FilePath(__file__).resolve().parents[1] / "frontend"
if _FRONTEND_DIR.exists():
    app.mount("/", NoCacheStaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")
