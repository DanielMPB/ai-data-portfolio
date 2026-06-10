"""Barramento Quantitativo de Mercado (B3) + Advisor IA.

Coleta métricas de mercado via `yfinance` (sufixo `.SA` da B3) e consolida uma
matriz fundamentalista (P/L, Dividend Yield, ROE) com 6 meses de série histórica.
O Advisor submete a matriz ao LLM, que emite um veredito ancorado: STRONG BUY |
HOLD | SELL, com tese descritiva de valuation.
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any

import yfinance as yf

from app.services.llm_client import LLMClient, get_llm

_RE_VEREDITO = re.compile(r"(STRONG BUY|BUY|HOLD|SELL)", re.IGNORECASE)
_VEREDITOS_VALIDOS = {"STRONG BUY", "HOLD", "SELL"}

# ---- Panorama de mercado (painel macro + watchlist) -----------------------
_MACRO = [("^BVSP", "IBOVESPA", "pts"), ("BRL=X", "Dólar", "R$"),
          ("EURBRL=X", "Euro", "R$"), ("^VIX", "VIX", "")]
_WATCH = [("PETR4", "Petrobras"), ("VALE3", "Vale"),
          ("ITUB4", "Itaú Unibanco"), ("WEGE3", "WEG")]
# Cesta líquida da B3 para o ranking de maiores altas/baixas do dia.
_MOVERS = ["PETR4", "VALE3", "ITUB4", "BBDC4", "B3SA3", "ABEV3", "WEGE3", "BBAS3",
           "ITSA4", "RENT3", "SUZB3", "GGBR4", "JBSS3", "LREN3", "ELET3", "RADL3",
           "PRIO3", "EQTL3", "HAPV3", "MGLU3"]
_overview_cache: dict[str, Any] = {"ts": 0.0, "data": None}
_OVERVIEW_TTL = 300  # segundos


def market_overview() -> dict[str, Any]:
    """Painel macro (Ibovespa, Dólar, Euro, VIX) + watchlist de blue chips.

    Um único download em lote do yfinance, com cache (TTL) e degradação graciosa.
    """
    now = time.time()
    if _overview_cache["data"] and now - _overview_cache["ts"] < _OVERVIEW_TTL:
        return _overview_cache["data"]

    todos = [t[0] for t in _MACRO] + [m + ".SA" for m in _MOVERS]
    try:
        df = yf.download(todos, period="3mo", group_by="ticker",
                         progress=False, threads=True)
    except Exception:  # noqa: BLE001 — sem rede/yfinance fora do ar
        df = None

    def closes(tk: str) -> list[float]:
        try:
            s = df[tk]["Close"].dropna()
            return [round(float(x), 2) for x in s.tolist()]
        except Exception:  # noqa: BLE001
            return []

    def var(cl: list[float]) -> float | None:
        return round((cl[-1] / cl[-2] - 1) * 100, 2) if len(cl) >= 2 else None

    macro = []
    for tk, nome, uni in _MACRO:
        cl = closes(tk)
        macro.append({"nome": nome, "unidade": uni,
                      "valor": cl[-1] if cl else None, "variacao": var(cl)})

    watch = []
    for tk, nome in _WATCH:
        cl = closes(tk + ".SA")
        watch.append({"ticker": tk, "nome": nome,
                      "preco": cl[-1] if cl else None, "variacao": var(cl),
                      "sparkline": cl[-22:]})

    # Maiores altas e baixas do dia (cesta líquida).
    variacoes = []
    for tk in _MOVERS:
        v = var(closes(tk + ".SA"))
        if v is not None:
            variacoes.append({"ticker": tk, "variacao": v})
    variacoes.sort(key=lambda x: x["variacao"], reverse=True)
    movers = {"altas": variacoes[:5], "baixas": list(reversed(variacoes[-5:]))} if variacoes else {"altas": [], "baixas": []}

    data = {"macro": macro, "watchlist": watch, "movers": movers,
            "ibov_serie": closes("^BVSP")}
    _overview_cache.update(ts=now, data=data)
    return data


class TickerNaoEncontrado(LookupError):
    """O ticker não retornou dados de mercado."""


def _normalizar_ticker(ticker: str) -> str:
    t = (ticker or "").strip().upper()
    if not t:
        raise TickerNaoEncontrado("Ticker vazio.")
    return t if t.endswith(".SA") else f"{t}.SA"


def obter_acao(ticker: str) -> dict[str, Any]:
    """Série histórica de 6 meses + múltiplos fundamentais de um papel da B3."""
    simbolo = _normalizar_ticker(ticker)
    papel = yf.Ticker(simbolo)

    hist = papel.history(period="6mo")
    if hist is None or hist.empty:
        raise TickerNaoEncontrado(f"Sem dados de mercado para {simbolo}.")

    historico = [
        {"data": idx.strftime("%Y-%m-%d"),
         "fechamento": round(float(row["Close"]), 2),
         # NaN != NaN → guarda contra volume ausente sem depender de pandas
         "volume": int(row["Volume"]) if row["Volume"] == row["Volume"] else 0}
        for idx, row in hist.iterrows()
    ]

    try:
        info = papel.info or {}
    except Exception:  # noqa: BLE001 — .info pode falhar por rede/scraping
        info = {}

    # yfinance (>=1.x) já retorna dividendYield em percentual; ROE vem como fração.
    roe = info.get("returnOnEquity")
    multiplos = {
        "pl": _arred(info.get("trailingPE")),
        "dy": _arred(info.get("dividendYield")),
        "roe": _arred(roe * 100 if isinstance(roe, (int, float)) else None),
    }

    fechs = [h["fechamento"] for h in historico]
    return {
        "ticker": simbolo,
        "nome": info.get("longName") or info.get("shortName") or simbolo,
        "preco_atual": fechs[-1],
        "moeda": info.get("currency", "BRL"),
        "multiplos": multiplos,
        "valor_mercado": info.get("marketCap"),
        "maxima_periodo": round(max(fechs), 2),
        "minima_periodo": round(min(fechs), 2),
        "variacao_periodo": round((fechs[-1] / fechs[0] - 1) * 100, 2) if len(fechs) > 1 else None,
        "variacao_dia": round((fechs[-1] / fechs[-2] - 1) * 100, 2) if len(fechs) > 1 else None,
        "historico": historico,
    }


def _arred(v: Any) -> float | None:
    return round(float(v), 2) if isinstance(v, (int, float)) else None


# ---- Recomendação do dia (relatório de IA sobre uma cesta ampla da B3) -----
# Universo diversificado: blue chips + mid/small caps menos conhecidas.
_UNIVERSO = [
    "PETR4", "VALE3", "ITUB4", "BBDC4", "ABEV3", "B3SA3", "WEGE3", "BBAS3", "ITSA4",
    "ELET3", "RENT3", "SUZB3", "PRIO3", "RADL3", "JBSS3", "GGBR4", "LREN3", "RAIL3",
    "POMO4", "TUPY3", "GRND3", "FRAS3", "LEVE3", "DXCO3", "MYPK3", "KEPL3", "UNIP6",
    "CSMG3", "VULC3", "SEER3", "MOVI3", "SLCE3", "AGRO3", "DIRR3", "POSI3", "INTB3",
]
_rec_cache: dict[str, Any] = {"ts": 0.0, "data": None}
_REC_TTL = 600  # segundos

_REC_SYSTEM = (
    "Você é um estrategista de investimentos sênior cobrindo a bolsa brasileira (B3). "
    "Combina o desempenho recente das ações com seu conhecimento fundamentalista das "
    "empresas para orientar investidores. Responde SEMPRE em português do Brasil."
)


def _coletar_universo() -> list[dict[str, Any]]:
    tk = [t + ".SA" for t in _UNIVERSO]
    try:
        df = yf.download(tk, period="1mo", group_by="ticker", progress=False, threads=True)
    except Exception:  # noqa: BLE001
        df = None
    out: list[dict[str, Any]] = []
    for t in _UNIVERSO:
        try:
            s = df[t + ".SA"]["Close"].dropna()
            cl = [float(x) for x in s.tolist()]
            if len(cl) >= 2:
                out.append({"t": t, "p": round(cl[-1], 2),
                            "dia": round((cl[-1] / cl[-2] - 1) * 100, 2),
                            "mes": round((cl[-1] / cl[0] - 1) * 100, 2)})
        except Exception:  # noqa: BLE001
            pass
    return out


def _rec_prompt(tabela: str) -> str:
    return (
        "Com base no desempenho recente das ações da B3 abaixo (variação do dia e do mês) "
        "e no seu conhecimento sobre essas empresas, produza um relatório de recomendações "
        "do dia em Markdown, com EXATAMENTE estas seções (cada uma com `# ` no título):\n\n"
        "# PANORAMA DO MERCADO HOJE\n"
        "2-3 frases sobre o humor do mercado e setores em destaque/pressão.\n\n"
        "# MELHORES OPORTUNIDADES DE COMPRA\n"
        "Liste de 4 a 6 ações para comprar hoje. IMPORTANTE: inclua empresas de menor porte "
        "e menos conhecidas (small/mid caps), não apenas blue chips. Para cada, use um bullet "
        "com o ticker em negrito, o nome da empresa e 1-2 frases de justificativa ancoradas "
        "nos dados e/ou nos fundamentos.\n\n"
        "# EMPRESAS PARA EVITAR HOJE\n"
        "Liste de 3 a 5 ações para evitar ou ter cautela, com justificativa em bullets.\n\n"
        "# ESTRATÉGIA RECOMENDADA\n"
        "Feche com uma orientação prática de alocação e gestão de risco.\n\n"
        "Use apenas os preços fornecidos (não invente valores) e finalize lembrando que isto "
        "não constitui recomendação formal de investimento.\n\n"
        "Dados recentes (B3):\n" + tabela
    )


async def recomendacao_dia(llm: LLMClient | None = None) -> dict[str, Any]:
    """Relatório de IA: melhores compras e empresas a evitar hoje (cesta ampla da B3)."""
    now = time.time()
    if _rec_cache["data"] and now - _rec_cache["ts"] < _REC_TTL:
        return _rec_cache["data"]
    dados = await asyncio.to_thread(_coletar_universo)
    if not dados:
        raise TickerNaoEncontrado("Sem dados de mercado para gerar a recomendação.")
    tabela = "\n".join(
        f"- {d['t']}: R$ {d['p']:.2f} | dia {d['dia']:+.2f}% | mês {d['mes']:+.2f}%" for d in dados)
    client = llm or get_llm()
    relatorio = await client.chat(_REC_SYSTEM, _rec_prompt(tabela), max_tokens=2400)
    data = {"relatorio_markdown": relatorio, "modelo": client.model, "universo": len(dados)}
    _rec_cache.update(ts=now, data=data)
    return data


_SYSTEM = (
    "Você é um analista quantitativo de equities da bolsa brasileira (B3). "
    "Emita teses de investimento técnicas, objetivas e ancoradas nos múltiplos "
    "fundamentais. Responda SEMPRE em português do Brasil."
)


def _montar_prompt(dados: dict[str, Any]) -> str:
    m = dados["multiplos"]
    serie = dados["historico"]
    linhas = [
        "Com base na matriz fundamentalista abaixo, emita o veredito.",
        "A primeira linha DEVE ser: `VEREDITO: X` onde X ∈ {STRONG BUY, HOLD, SELL}.",
        "Em seguida, escreva uma tese de valuation concisa (3-5 frases).",
        "",
        f"## {dados['nome']} ({dados['ticker']})",
        f"- Preço atual: {dados['preco_atual']} {dados['moeda']}",
    ]
    if len(serie) >= 2 and serie[0]["fechamento"]:
        var_6m = (serie[-1]["fechamento"] / serie[0]["fechamento"] - 1) * 100
        linhas.append(f"- Variação 6 meses: {var_6m:.1f}%")
    linhas += [
        f"- P/L (Preço/Lucro): {m['pl']}",
        f"- Dividend Yield: {m['dy']}%",
        f"- ROE: {m['roe']}%",
    ]
    return "\n".join(linhas) + "\n"


def _extrair_veredito(texto: str) -> tuple[str, str]:
    m = _RE_VEREDITO.search(texto.upper())
    bruto = m.group(1).upper() if m else "HOLD"
    veredito = "STRONG BUY" if bruto in {"STRONG BUY", "BUY"} else bruto
    if veredito not in _VEREDITOS_VALIDOS:
        veredito = "HOLD"
    tese = _RE_VEREDITO.sub("", texto, count=1)
    tese = re.sub(r"^\s*VEREDITO\s*[:\-]?\s*", "", tese, flags=re.IGNORECASE).strip(" \n:-")
    return veredito, tese.strip()


async def analisar(ticker: str, llm: LLMClient | None = None) -> dict[str, Any]:
    """Consolida a matriz fundamentalista e emite o parecer do Advisor IA."""
    dados = obter_acao(ticker)
    client = llm or get_llm()
    resposta = await client.chat(_SYSTEM, _montar_prompt(dados), max_tokens=1500)
    veredito, tese = _extrair_veredito(resposta)
    return {
        "ticker": dados["ticker"],
        "nome": dados["nome"],
        "veredito": veredito,
        "tese": tese,
        "multiplos": dados["multiplos"],
        "modelo": client.model,
    }
