"""NEXUS Relational Trust Score — motor determinístico de risco e contágio.

Modelo: **erosão de confiança** (noisy-OR / probabilístico).

A empresa-alvo inicia com confiança = 1,0 (score 100). Cada gatilho calcula uma
**severidade contínua `s ∈ [0,1]`** a partir da magnitude real da situação (não
mais pontos fixos) e tem um **peso `w ∈ [0,1]`** = a fração MÁXIMA da confiança
que aquele tipo de sinal pode corroer. A erosão de cada sinal é `e = w·s` e é
aplicada sobre a confiança RESTANTE:

        confiança_final = ∏ (1 − wᵢ·sᵢ)            score = 100 · confiança_final

Propriedades (por isso é robusto e justo):
  * sempre em [0, 100] — não precisa de "clamp" artificial;
  * monotônico e proporcional — dívida de R$5 mil ≠ R$400 mi; inaptidão > baixada;
  * combinação probabilística (noisy-OR): sinais fortes derrubam muito, fracos
    pouco, e o impacto de cada novo sinal depende do que já pesou (sem dupla
    contagem nem "soma injusta" quando há muitos gatilhos);
  * a contribuição marginal de cada gatilho (em pontos) soma exatamente
    `100 − score`, então o detalhamento ("breakdown") continua aditivo e honesto.

Camadas:
  * Layer A (Direta)   — fatos sobre a própria empresa-alvo.
  * Layer B (Contágio) — risco propagado pela rede societária (proporcional, com
    baselines da Receita Federal e suavização de Laplace).
  * Fatos confirmados por fonte oficial (sanções CEIS/CNEP/Lista Suja, Dívida
    Ativa da PGFN) ancoram o veredito.

Totalmente reproduzível (sem aleatoriedade).
"""
from __future__ import annotations

import unicodedata
from datetime import date
from typing import Any

from app.core.ald import eh_ald

METODO = "erosao-confianca"  # noisy-OR multiplicativo com severidade contínua

# ===========================================================================
# PESOS w ∈ [0,1] — fração máxima da confiança que cada sinal pode corroer.
# (a "gravidade" do tipo de evento; a magnitude entra via severidade s)
# ===========================================================================
# --- Layer A: situação cadastral / especial / motivo -----------------------
W_INAPTA = 0.85               # inaptidão = inexistência de fato (pior que baixa)
W_BAIXADA = 0.70              # baixada (encerramento)
W_SUSPENSA = 0.35            # suspensa (temporária)
W_FALENCIA = 0.70            # falência/liquidação/intervenção
W_RECUPERACAO = 0.45         # recuperação judicial
W_MOTIVO_GRAVE = 0.60        # motivo: fraude/inexistência/simulação/interposição
W_MOTIVO_OMISSAO = 0.35      # motivo: apenas omissão de declarações
W_CNAE_ALD_PRIM = 0.22       # CNAE primário exposto a ALD
W_CNAE_ALD_SEC = 0.14        # CNAE de risco ALD em atividade secundária
W_NATUREZA = 0.12            # natureza sem blindagem patrimonial
W_SHELL = 0.30               # recém-aberta + capital irrisório (constituição de fachada)

# --- Sanções oficiais (fato confirmado) ------------------------------------
W_SANC_CEIS = 0.60           # inidônea/suspensa de licitar
W_SANC_CNEP = 0.85           # condenação anticorrupção (Lei 12.846)
W_SANC_ESCRAVO = 0.95        # "Lista Suja" do trabalho escravo (MTE)
W_SANC_REDE = 0.50           # contágio confirmado por sócio/satélite sancionado
K_SANC_REDE = 3.0            # saturação do nº de vínculos sancionados

# --- Dívida Ativa da União (PGFN) — fato confirmado, eixo financeiro --------
W_DIVIDA = 0.55              # dívida da própria empresa-alvo
K_DIVIDA_VALOR = 2_000_000.0  # R$: valor que satura a severidade (meia-força)
K_DIVIDA_INSC = 25.0         # nº de inscrições que satura (dívida crônica)
BOOST_AJUIZADA = 0.30        # piso de severidade quando há execução fiscal ajuizada
W_DIVIDA_REDE = 0.35         # contágio por empresas da rede com dívida
K_DIVIDA_REDE = 8.0          # saturação do nº de empresas devedoras na rede

# --- Layer B: contágio proporcional ----------------------------------------
BASE_INSOLVENCIA = 0.35      # fração "normal" de baixadas por sócio (baseline RF)
BASE_FRAUDE = 0.12           # fração "normal" de inaptas por sócio (baseline RF)
BASE_ALD = 0.0               # ALD é raro → qualquer presença conta
W_CONTAGIO = 0.55            # peso máx. do contágio societário
FATOR_SOCIO_ADMIN = 1.25     # multiplicador se o conector contaminado é Administrador
SUAVIZACAO = 1               # Laplace: amortece sócios com poucas empresas

# --- Endereço (cruzamento / co-localização) --------------------------------
W_END_REDE = 0.45            # co-localização ancorada na rede (mesmos sócios)
K_END_REDE = 4.0             # saturação (inaptas pesam 2,2; baixadas 0,7)
W_END_FARM = 0.40            # "shell farm": ativas recém-abertas da teia no endereço
K_END_FARM = 4.0
MIN_SHELL_FARM = 2           # nº mínimo de ativas recém-abertas p/ caracterizar farm
W_END_NINHO = 0.12           # indicador GLOBAL leve (concentração de INAPTAS)
MIN_NINHO = 10
BASE_NINHO_INAPTA = 0.30

STATUS_NEGATIVOS = {"INAPTA", "BAIXADA"}

# Situação especial (estabelecimento) — sinais de distress financeiro.
KW_FALENCIA = ("FALID", "LIQUIDA", "INTERVENC", "MASSA FALIDA")
KW_RECUPERACAO = ("RECUPERACAO",)

# Palavras-chave (sem acento, maiúsculas) para os gatilhos textuais.
KW_MOTIVO_GRAVE = (
    "INEXISTENCIA DE FATO", "FRAUDE", "FRAUDULENT", "CRIME",
    "INTERPOSICAO", "SIMULACAO", "FALSA", "ILICIT",
)
KW_MOTIVO_OMISSAO = ("OMISSAO", "OMISSO")
KW_NATUREZA_SEM_BLINDAGEM = (
    "EMPRESARIO (INDIVIDUAL)", "EMPRESARIO INDIVIDUAL",
    "PRODUTOR RURAL (PESSOA FISICA)",
)
KW_ADMINISTRADOR = ("ADMINISTRADOR",)

# Capital social × idade.
CAP_IRRISORIO = 1000.0       # capital social "simbólico" (R$)
NOVA_MESES = 24              # "recém-aberta": ≤ 2 anos

# --- Robustez do alvo -------------------------------------------------------
# Risco de ASSOCIAÇÃO (contágio da rede) e a MAGNITUDE da dívida só fazem sentido
# relativos à natureza da empresa: uma estatal/grande/antiga e ATIVA não é laranja
# nem fica insolvente por ter dívida tributária (em geral sub judice). Empresas
# claramente legítimas têm esses sinais atenuados; empresa nova/pequena/opaca
# (onde mora o laranja) tem robustez ≈ 0 e sofre o escrutínio cheio.
ATEN_MAX = 0.85                   # atenuação máx. dos sinais de rede/dívida p/ alvo robusto
K_ROBUSTEZ_IDADE = 120.0         # meses (~10 anos) p/ meia-robustez por idade
K_ROBUSTEZ_CAPITAL = 5_000_000.0  # R$ p/ meia-robustez por capital social
KW_NATUREZA_PUBLICA = (
    "ECONOMIA MISTA", "EMPRESA PUBLICA", "ADMINISTRACAO PUBLICA", "AUTARQUIA",
    "FUNDACAO", "ORGAO PUBLICO", "MUNICIPIO", "ESTADO OU DISTRITO", "UNIAO",
)


# ===========================================================================
# Helpers numéricos
# ===========================================================================
def _clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def _sat(x: float, k: float) -> float:
    """Saturação suave: 0 em x=0, 0,5 em x=k, →1 quando x→∞. (x, k ≥ 0)"""
    return x / (x + k) if x and x > 0 else 0.0


def _noisy_or(*severidades: float) -> float:
    """Combina severidades independentes: 1 − ∏(1 − sᵢ)."""
    prod = 1.0
    for s in severidades:
        prod *= (1.0 - _clamp01(s))
    return 1.0 - prod


def _norm(texto: Any) -> str:
    """Normaliza para comparação: sem acentos, maiúsculas, sem espaços nas bordas."""
    if not texto:
        return ""
    s = unicodedata.normalize("NFKD", str(texto))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.upper().strip()


def _contem(texto: str, palavras: tuple[str, ...]) -> bool:
    alvo = _norm(texto)
    return any(p in alvo for p in palavras)


def _truthy(x: Any) -> bool:
    """Booleano robusto: trata strings 'true'/'false' (DuckDB all_varchar) e None."""
    if isinstance(x, str):
        return x.strip().lower() == "true"
    return bool(x)


def _to_float(x: Any) -> float | None:
    """Converte capital social textual (DuckDB all_varchar) em float, tolerando vírgula."""
    if x is None:
        return None
    try:
        return float(str(x).strip().replace(",", "."))
    except (ValueError, TypeError):
        return None


def _distress_especial(situacao_especial: Any) -> str:
    """Classifica a situação especial: 'falencia', 'recuperacao' ou '' (nenhuma)."""
    s = _norm(situacao_especial)
    if not s:
        return ""
    if any(k in s for k in KW_FALENCIA):
        return "falencia"
    if any(k in s for k in KW_RECUPERACAO):
        return "recuperacao"
    return ""


# ===========================================================================
# Layer B — contágio proporcional (retorna SEVERIDADES, não pontos)
# ===========================================================================
def _layer_b(vinculos: list[dict[str, Any]], raiz: str) -> dict[str, Any]:
    """Contágio proporcional por sócio. Devolve severidades + telemetria."""
    socios: dict[str, dict[str, Any]] = {}
    for v in vinculos:
        doc = v.get("cnpj_cpf_socio")
        rel = v.get("cnpj_basico")
        if not doc:
            continue
        s = socios.setdefault(doc, {"sats": {}, "admin": False})
        if _contem(v.get("qualificacao_do_socio"), KW_ADMINISTRADOR):
            s["admin"] = True
        if rel and rel != raiz:
            ald = eh_ald(v.get("cnae_codigo")) or _truthy(v.get("ald_secundario"))
            s["sats"][rel] = (
                _norm(v.get("situacao_cadastral")),
                ald,
                _distress_especial(v.get("situacao_especial")),
            )

    n_socios = len(socios)
    satelites_distintos: set[str] = set()
    soma_fr_baixada = soma_fr_inapta = soma_fr_ald = 0.0
    admin_contaminado = False

    for s in socios.values():
        sats = s["sats"]
        satelites_distintos.update(sats.keys())
        m = len(sats)
        if m == 0:
            continue
        nb = sum(1 for sit, _, dist in sats.values() if sit == "BAIXADA" or dist)
        ni = sum(1 for sit, _, _ in sats.values() if sit == "INAPTA")
        ald_pts = sum(
            (2 if (sit in STATUS_NEGATIVOS or dist) else 1)
            for sit, ald, dist in sats.values() if ald
        )
        fr_b = nb / (m + SUAVIZACAO)
        fr_i = ni / (m + SUAVIZACAO)
        fr_ald = min(1.0, ald_pts / (m + SUAVIZACAO))
        soma_fr_baixada += fr_b
        soma_fr_inapta += fr_i
        soma_fr_ald += fr_ald
        if s["admin"] and (fr_i > BASE_FRAUDE or fr_b > 0.6 or fr_ald > 0):
            admin_contaminado = True

    resultado = {
        "socios_diretos": n_socios, "satelites": len(satelites_distintos),
        "insolvencia_media": 0.0, "inaptidao_media": 0.0, "ald_medio": 0.0,
        "s_fraude": 0.0, "s_insolv": 0.0, "s_ald": 0.0,
        "admin": False, "motivos": [],
    }
    if n_socios == 0 or not satelites_distintos:
        return resultado

    avg_baixada = soma_fr_baixada / n_socios
    avg_inapta = soma_fr_inapta / n_socios
    avg_ald = soma_fr_ald / n_socios
    resultado["insolvencia_media"] = round(avg_baixada, 3)
    resultado["inaptidao_media"] = round(avg_inapta, 3)
    resultado["ald_medio"] = round(avg_ald, 3)

    # Severidade = excesso sobre o baseline, normalizado para [0,1].
    s_fraude = _clamp01((avg_inapta - BASE_FRAUDE) / (1 - BASE_FRAUDE))
    s_insolv = _clamp01((avg_baixada - BASE_INSOLVENCIA) / (1 - BASE_INSOLVENCIA))
    s_ald = _clamp01(avg_ald - BASE_ALD)
    resultado.update(s_fraude=s_fraude, s_insolv=s_insolv, s_ald=s_ald,
                     admin=admin_contaminado)

    motivos = []
    if s_fraude > 0:
        motivos.append(f"Inaptidão concentrada na rede ({avg_inapta:.0%}/sócio, "
                       f"acima do esperado {BASE_FRAUDE:.0%})")
    if s_insolv > 0:
        motivos.append(f"Insolvência difusa ({avg_baixada:.0%}/sócio baixadas, "
                       f"acima do esperado {BASE_INSOLVENCIA:.0%})")
    if s_ald > 0:
        motivos.append(f"Exposição a setores de risco/ALD na rede ({avg_ald:.0%}/sócio)")
    if admin_contaminado and (s_fraude or s_insolv or s_ald):
        motivos.append(f"conector contaminado é Sócio-Administrador (×{FATOR_SOCIO_ADMIN})")
    resultado["motivos"] = motivos
    return resultado


# ===========================================================================
# Camadas que aplicam erosão via callback `aplicar(camada, w, s, motivo)`
# ===========================================================================
def _layer_sancoes(consulta: dict[str, Any], vinculos: list[dict[str, Any]],
                   aplicar: Any, aten: float = 1.0) -> dict[str, Any]:
    """Sanções oficiais VIGENTES (CEIS/CNEP/Lista Suja) — fato confirmado.

    `aten` atenua só o CONTÁGIO da rede (associação); a sanção do próprio alvo é
    fato categórico e não é atenuada.
    """
    sancoes_alvo = consulta.get("_sancoes_alvo") or []
    resultado: dict[str, Any] = {
        "alvo_vigente": False, "alvo": [], "rede_socios": 0,
        "rede_satelites": 0, "confirmada": False,
    }

    # Layer A: Trabalho Escravo > CNEP > CEIS. Mais sanções → severidade um pouco maior.
    if sancoes_alvo:
        fontes = {x.get("fonte") for x in sancoes_alvo}
        if "TRABALHO_ESCRAVO" in fontes:
            w, rotulo = W_SANC_ESCRAVO, "Lista Suja do Trabalho Escravo (MTE)"
        elif "CNEP" in fontes:
            w, rotulo = W_SANC_CNEP, "CNEP — condenação anticorrupção (Lei 12.846)"
        else:
            w, rotulo = W_SANC_CEIS, "CEIS — inidônea/suspensa de licitar"
        s = _noisy_or(0.85, 0.15 * _sat(len(sancoes_alvo) - 1, 3))  # ≥0,85; sobe com nº
        orgaos = sorted({x.get("orgao") for x in sancoes_alvo if x.get("orgao")})
        motivo = f"Sanção oficial VIGENTE — {rotulo}"
        if orgaos:
            motivo += f" · {', '.join(orgaos[:2])}"
        aplicar("A", "sancao", w, s, motivo)
        resultado["alvo_vigente"] = True
        resultado["confirmada"] = True
        resultado["alvo"] = [
            {"fonte": x.get("fonte"), "tipo_sancao": x.get("tipo_sancao"),
             "orgao": x.get("orgao"), "processo": x.get("processo")}
            for x in sancoes_alvo
        ]

    # Layer B: contágio confirmado por sócios/satélites sancionados.
    socios_sanc: dict[str, dict[str, Any]] = {}
    sat_sanc: set[str] = set()
    for v in vinculos:
        if v.get("sancoes_socio"):
            socios_sanc[v.get("cnpj_cpf_socio")] = v
        if v.get("sancoes_satelite") and v.get("cnpj_basico"):
            sat_sanc.add(v["cnpj_basico"])

    n_soc, n_sat = len(socios_sanc), len(sat_sanc)
    if n_soc or n_sat:
        admin = any(_contem(v.get("qualificacao_do_socio"), KW_ADMINISTRADOR)
                    for v in socios_sanc.values())
        s = _sat(1.5 * n_soc + n_sat, K_SANC_REDE)
        if admin:
            s = _clamp01(s * FATOR_SOCIO_ADMIN)
        partes = []
        if n_soc:
            partes.append(f"{n_soc} sócio(s)")
        if n_sat:
            partes.append(f"{n_sat} empresa(s) da rede")
        motivo = ("Contágio CONFIRMADO: " + " e ".join(partes)
                  + " com sanção oficial vigente (CEIS/CNEP/Lista Suja)")
        if admin:
            motivo += f" — inclui Sócio-Administrador (×{FATOR_SOCIO_ADMIN})"
        aplicar("B", "sancao_rede", W_SANC_REDE, s * aten, motivo)
        resultado["confirmada"] = True

    resultado["rede_socios"] = n_soc
    resultado["rede_satelites"] = n_sat
    return resultado


def _layer_dividas(consulta: dict[str, Any], aplicar: Any, aten: float = 1.0) -> dict[str, Any]:
    """Dívida Ativa da União (PGFN) — inadimplência fiscal CONFIRMADA.

    Severidade escala com o VALOR (saturação ~R$2M) e o nº de inscrições; a
    execução fiscal ajuizada estabelece um piso. `aten` torna a MAGNITUDE relativa
    à robustez do alvo (uma estatal/gigante não fica insolvente por dívida
    tributária, em geral sub judice).
    """
    d = consulta.get("_dividas_alvo") or None
    rede = int(consulta.get("_dividas_rede") or 0)
    res: dict[str, Any] = {"alvo": None, "rede": rede, "confirmada": False}

    if d and int(d.get("inscricoes") or 0) > 0:
        valor = float(d.get("valor") or 0)
        inscricoes = int(d["inscricoes"])
        ajuizadas = int(d.get("ajuizadas") or 0)
        s = _noisy_or(_sat(valor, K_DIVIDA_VALOR), 0.4 * _sat(inscricoes, K_DIVIDA_INSC))
        if ajuizadas:
            s = _noisy_or(s, BOOST_AJUIZADA)
        motivo = f"Dívida ativa na União (PGFN): {inscricoes} inscrição(ões)"
        if valor:
            motivo += f", R$ {valor:,.0f}"
        if ajuizadas:
            motivo += " — com execução fiscal ajuizada"
        aplicar("A", "divida", W_DIVIDA, s * aten, motivo)
        res["alvo"] = {"valor": valor, "inscricoes": inscricoes, "ajuizadas": ajuizadas}
        res["confirmada"] = True

    if rede:
        s = _sat(rede, K_DIVIDA_REDE)
        aplicar("B", "divida_rede", W_DIVIDA_REDE, s * aten,
                f"{rede} empresa(s) da rede com dívida ativa na União (PGFN)")
        res["confirmada"] = True

    return res


def _layer_endereco(consulta: dict[str, Any], aplicar: Any, aten: float = 1.0) -> dict[str, Any]:
    """Cruzamento de endereços: co-localização ancorada na rede + shell farm +
    indicador global leve de concentração de inaptas. INAPTA ≫ BAIXADA.
    `aten` atenua tudo (são sinais de associação) p/ alvo claramente legítimo."""
    e = consulta.get("_endereco") or {}
    total = int(e.get("total") or 0)
    inaptas = int(e.get("inaptas") or 0)
    ri = int(e.get("rede_inaptas") or 0)
    rb = int(e.get("rede_baixadas") or 0)
    rar = int(e.get("rede_ativas_recentes") or 0)
    acionado = False

    # (1) Co-localização ANCORADA na rede (mesmos sócios + mesmo endereço).
    if ri or rb:
        s = _sat(2.2 * ri + 0.7 * rb, K_END_REDE)
        partes = []
        if ri:
            partes.append(f"{ri} inapta(s)")
        if rb:
            partes.append(f"{rb} baixada(s)")
        aplicar("B", "endereco_rede", W_END_REDE, s * aten,
                "Co-localização na própria teia: " + " e ".join(partes)
                + " no mesmo endereço da empresa-alvo")
        acionado = True

    # (2) Shell farm ativo.
    if rar >= MIN_SHELL_FARM:
        aplicar("B", "shell_farm", W_END_FARM, _sat(rar, K_END_FARM) * aten,
                f"Possível 'shell farm': {rar} empresas ativas recém-abertas da teia "
                f"no mesmo endereço da empresa-alvo")
        acionado = True

    # (3) Indicador GLOBAL leve: concentração de INAPTAS no endereço (investigar).
    if total >= MIN_NINHO and inaptas:
        frac = inaptas / total
        s = _clamp01((frac - BASE_NINHO_INAPTA) / (1 - BASE_NINHO_INAPTA))
        if s > 0:
            aplicar("A", "endereco_global", W_END_NINHO, s * aten,
                    f"Endereço compartilhado: {total} empresas no mesmo endereço, "
                    f"{inaptas} inaptas ({frac:.0%}) — investigar")
            acionado = True

    return {
        "acionado": acionado, "endereco_alvo": e.get("endereco_alvo"),
        "empresas_no_endereco": total, "ativas_no_endereco": int(e.get("ativas") or 0),
        "inaptas_no_endereco": inaptas, "baixadas_no_endereco": int(e.get("baixadas") or 0),
        "rede_mesmo_endereco": int(e.get("rede_mesmo_endereco") or 0),
        "rede_inaptas": ri, "rede_baixadas": rb, "rede_ativas_recentes": rar,
    }


def _robustez_alvo(empresa: dict[str, Any], idade_meses: int | None) -> float:
    """Robustez da empresa-alvo ∈ [0,1] — quão "claramente legítima/estabelecida"
    ela é. Usada só para ATENUAR sinais de associação (contágio) e a magnitude da
    dívida — nunca os fatos categóricos próprios. Só empresa ATIVA ganha robustez.
    """
    if _norm(empresa.get("situacao_cadastral")) != "ATIVA":
        return 0.0
    nat = _norm(empresa.get("natureza_juridica"))
    porte = _norm(empresa.get("porte"))
    capital = _to_float(empresa.get("capital_social")) or 0.0
    sinais: list[float] = []
    if any(k in nat for k in KW_NATUREZA_PUBLICA):
        sinais.append(1.0)                       # ente público/economia mista → não é laranja
    if "ANONIMA" in nat or "DEMAIS" in porte:
        sinais.append(0.6)                       # S.A. ou grande porte
    if idade_meses:
        sinais.append(0.7 * _sat(idade_meses, K_ROBUSTEZ_IDADE))
    if capital:
        sinais.append(0.5 * _sat(capital, K_ROBUSTEZ_CAPITAL))
    return _noisy_or(*sinais) if sinais else 0.0


def _layer_perfil(empresa: dict[str, Any], idade_meses: int | None,
                  aplicar: Any) -> dict[str, Any]:
    """Perfil cadastral: recém-aberta + capital irrisório = constituição de fachada.

    Severidade contínua = (quão nova) × (quão baixo o capital). Isolados não pesam.
    """
    capital = _to_float(empresa.get("capital_social"))
    if idade_meses is not None and capital is not None and idade_meses <= NOVA_MESES \
            and capital < CAP_IRRISORIO:
        s_idade = _clamp01((NOVA_MESES - idade_meses) / NOVA_MESES)
        s_capital = _clamp01((CAP_IRRISORIO - capital) / CAP_IRRISORIO)
        s = s_idade * s_capital
        if s > 0:
            aplicar("A", "perfil", W_SHELL, s,
                    f"Empresa recém-aberta ({idade_meses} meses) com capital social "
                    f"irrisório (R$ {capital:,.0f}) — padrão de constituição de fachada")
    return {"capital_social": capital, "idade_meses": idade_meses}


# ===========================================================================
# Cálculo principal
# ===========================================================================
def calcular_score(consulta: dict[str, Any]) -> dict[str, Any]:
    """Computa o NEXUS Trust Score (modelo de erosão de confiança).

    Espera `_empresa_raw` (linha de nodes_empresas) e `_vinculos` (grafo 2º grau);
    opcionalmente `_sancoes_alvo`, `_dividas_alvo`, `_dividas_rede`, `_endereco`,
    `_empresa_inicio` (camadas externas — fail-soft se ausentes).
    """
    empresa = consulta.get("_empresa_raw") or {}
    vinculos = consulta.get("_vinculos") or []
    raiz = consulta["empresa_principal"]["cnpj"]

    # Idade e robustez do alvo: atenuam o risco de ASSOCIAÇÃO (contágio) e a
    # MAGNITUDE da dívida — uma empresa claramente legítima não é "de risco" só
    # porque seus sócios tiveram outras empresas que não deram certo.
    inicio = consulta.get("_empresa_inicio")
    idade_meses = (max(0, (date.today() - inicio).days) // 30
                   if isinstance(inicio, date) else None)
    robustez = _robustez_alvo(empresa, idade_meses)
    aten = 1.0 - ATEN_MAX * robustez

    trust = 1.0
    penalidades: list[dict[str, Any]] = []

    def aplicar(camada: str, tipo: str, w: float, s: float, motivo: str) -> None:
        """Corrói a confiança restante por `e = w·s` e registra o impacto marginal.

        `tipo` é a chave estável do gatilho (ex.: 'divida', 'sancao', 'contagio') —
        o frontend a usa para exibir um título/explicação em linguagem leiga.
        """
        nonlocal trust
        e = _clamp01(w) * _clamp01(s)
        if e <= 0:
            return
        pts = trust * e * 100.0
        trust *= (1.0 - e)
        penalidades.append({
            "camada": camada, "tipo": tipo, "pontos": -round(pts),
            "severidade": round(_clamp01(s), 3), "motivo": motivo,
        })

    # ---------------- Layer A: Direta ----------------
    situacao = _norm(empresa.get("situacao_cadastral"))
    if situacao == "INAPTA":
        aplicar("A", "situacao", W_INAPTA, 1.0, "Situação cadastral: Inapta (inexistência de fato)")
    elif situacao == "BAIXADA":
        aplicar("A", "situacao", W_BAIXADA, 1.0, "Situação cadastral: Baixada")
    elif situacao == "SUSPENSA":
        aplicar("A", "situacao", W_SUSPENSA, 1.0, "Situação cadastral: Suspensa")

    distress = _distress_especial(empresa.get("situacao_especial"))
    if distress == "falencia":
        aplicar("A", "situacao_especial", W_FALENCIA, 1.0,
                f"Situação especial: {empresa.get('situacao_especial')}")
    elif distress == "recuperacao":
        aplicar("A", "situacao_especial", W_RECUPERACAO, 1.0,
                f"Situação especial: {empresa.get('situacao_especial')}")

    if _contem(empresa.get("motivo_situacao"), KW_MOTIVO_GRAVE):
        aplicar("A", "motivo", W_MOTIVO_GRAVE, 1.0,
                f"Motivo de risco: {empresa.get('motivo_situacao')}")
    elif _contem(empresa.get("motivo_situacao"), KW_MOTIVO_OMISSAO):
        aplicar("A", "motivo", W_MOTIVO_OMISSAO, 1.0,
                f"Motivo de risco: {empresa.get('motivo_situacao')}")

    if eh_ald(empresa.get("cnae_codigo")):
        aplicar("A", "cnae_ald", W_CNAE_ALD_PRIM, 1.0, f"CNAE exposto a ALD: {empresa.get('cnae')}")
    elif _truthy(empresa.get("ald_secundario")):
        aplicar("A", "cnae_ald", W_CNAE_ALD_SEC, 1.0, "CNAE de risco ALD em atividade secundária")

    if _contem(empresa.get("natureza_juridica"), KW_NATUREZA_SEM_BLINDAGEM):
        aplicar("A", "natureza", W_NATUREZA, 1.0,
                f"Natureza sem blindagem patrimonial: {empresa.get('natureza_juridica')}")

    # ---------------- Fatos confirmados (fonte oficial) ----------------
    # Sanção própria = fato categórico (não atenua); dívida = magnitude relativa (atenua).
    s_sanc = _layer_sancoes(consulta, vinculos, aplicar, aten)
    div = _layer_dividas(consulta, aplicar, aten)

    # ---------------- Layer B: Contágio (proporcional, atenuado) ----------------
    b = _layer_b(vinculos, raiz)
    s_contagio = _noisy_or(b["s_fraude"], 0.6 * b["s_insolv"], 0.6 * b["s_ald"])
    if b["admin"]:
        s_contagio = _clamp01(s_contagio * FATOR_SOCIO_ADMIN)
    if s_contagio > 0:
        aplicar("B", "contagio", W_CONTAGIO, s_contagio * aten, "; ".join(b["motivos"]))

    # ---------------- Endereço + Perfil (inferido) ----------------
    end = _layer_endereco(consulta, aplicar, aten)
    perfil = _layer_perfil(empresa, idade_meses, aplicar)

    score = round(trust * 100)

    if score >= 70:
        classificacao = "Baixo Risco"
    elif score >= 40:
        classificacao = "Risco Moderado"
    else:
        classificacao = "Alto Risco"

    oficial = s_sanc["confirmada"] or div["confirmada"]
    if oficial:
        confianca = "Confirmado por fonte oficial (CEIS/CNEP, PGFN, Lista Suja)"
    elif penalidades:
        confianca = "Inferido (estrutura de rede + cadastro da Receita Federal)"
    else:
        confianca = "Sem gatilhos nas fontes consultadas"

    return {
        "nexus_score": score,
        "classificacao": classificacao,
        "metodo": METODO,
        "robustez_alvo": round(robustez, 3),
        "satelites_analisadas": b["satelites"],
        "socios_diretos": b["socios_diretos"],
        "rede": {
            "insolvencia_media": b["insolvencia_media"],
            "inaptidao_media": b["inaptidao_media"],
            "ald_medio": b["ald_medio"],
        },
        "veredito_confianca": confianca,
        "ancorada_em_sancao": oficial,
        "sancoes": {
            "alvo_vigente": s_sanc["alvo_vigente"], "alvo": s_sanc["alvo"],
            "rede_socios": s_sanc["rede_socios"], "rede_satelites": s_sanc["rede_satelites"],
        },
        "endereco": {
            "endereco_alvo": end["endereco_alvo"],
            "empresas_no_endereco": end["empresas_no_endereco"],
            "ativas_no_endereco": end["ativas_no_endereco"],
            "inaptas_no_endereco": end["inaptas_no_endereco"],
            "baixadas_no_endereco": end["baixadas_no_endereco"],
            "rede_mesmo_endereco": end["rede_mesmo_endereco"],
            "rede_inaptas": end["rede_inaptas"],
            "rede_baixadas": end["rede_baixadas"],
            "rede_ativas_recentes": end["rede_ativas_recentes"],
        },
        "dividas": {"alvo": div["alvo"], "rede": div["rede"]},
        "perfil": {
            "capital_social": perfil["capital_social"],
            "idade_meses": perfil["idade_meses"],
        },
        "penalidades": penalidades,
    }
