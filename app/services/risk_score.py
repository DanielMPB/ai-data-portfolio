"""NEXUS Relational Trust Score — motor determinístico de risco e contágio.

A empresa-alvo inicia com 100 pontos. Deduções são aplicadas em camadas:

  * Layer A (Direta)  — fatos sobre a própria empresa-alvo (situação, motivo,
    CNAE de risco, natureza sem blindagem).
  * Layer B (Contágio) — risco propagado pela rede societária, calculado de
    forma **proporcional e justa**:
      - é medido por sócio (cada sócio direto contribui com a fração de suas
        OUTRAS empresas que estão comprometidas) e depois promediado entre TODOS
        os sócios diretos — logo, muitos sócios "limpos" diluem uma eventual
        maçã podre, e a chance de cascata só pesa quando o comprometimento é
        concentrado;
      - usa baselines empíricos da base da Receita Federal (no Brasil ~45% das
        empresas estão baixadas e ~16% inaptas), penalizando apenas o EXCESSO
        sobre o esperado — uma rede "na média do país" não é punida;
      - separa inaptidão (sinal de fraude/inexistência, peso maior) de baixa
        (encerramento, peso menor);
      - aplica suavização de Laplace para não exagerar com amostras pequenas.

O resultado é totalmente reproduzível (sem aleatoriedade) e acompanha o
detalhamento ("breakdown") de cada penalidade acionada.
"""
from __future__ import annotations

import unicodedata
from typing import Any

from app.core.ald import eh_ald

# --- Layer A (direta) ------------------------------------------------------
PENA_STATUS_NEGATIVO = 50          # Inapta / Baixada
PENA_STATUS_SUSPENSA = 30          # Suspensa (situação temporária)
PENA_FALENCIA = 45                 # situação especial: falência/liquidação/intervenção
PENA_RECUPERACAO = 30              # situação especial: recuperação judicial
PENA_MOTIVO_CRIME = 30             # motivo associado a crime/omissão/inexistência
PENA_CNAE_ALD = 20                 # CNAE (primário ou secundário) exposto a ALD
PENA_NATUREZA_SEM_BLINDAGEM = 15   # natureza sem blindagem patrimonial

# --- Layer B (contágio) — calibragem proporcional --------------------------
BASE_INSOLVENCIA = 0.35            # fração "normal" de baixadas por sócio (baseline RF)
BASE_FRAUDE = 0.12                # fração "normal" de inaptas por sócio (baseline RF)
W_INSOLVENCIA = 30                # peso máx. do contágio por insolvência (baixadas)
W_FRAUDE = 60                    # peso máx. do contágio por fraude (inaptas) — pesa mais
W_ALD = 30                       # peso do contágio por exposição a setores de risco (ALD)
BASE_ALD = 0.0                   # ALD é raro (~0,08% das empresas) → qualquer presença conta
FATOR_SOCIO_ADMIN = 1.25          # multiplicador se o conector contaminado é Administrador
SUAVIZACAO = 1                   # Laplace: amortece sócios com poucas empresas
TETO_CONTAGIO = 65               # teto de pontos do Layer B

STATUS_NEGATIVOS = {"INAPTA", "BAIXADA"}

# Situação especial (estabelecimento) — sinais de distress financeiro.
KW_FALENCIA = ("FALID", "LIQUIDA", "INTERVENC", "MASSA FALIDA")
KW_RECUPERACAO = ("RECUPERACAO",)

# Palavras-chave (sem acento, maiúsculas) para os gatilhos textuais.
KW_MOTIVO_CRIME = (
    "INEXISTENCIA DE FATO", "OMISSAO", "OMISSO", "FRAUDE", "FRAUDULENT",
    "CRIME", "INTERPOSICAO", "SIMULACAO", "FALSA", "ILICIT",
)
KW_NATUREZA_SEM_BLINDAGEM = (
    "EMPRESARIO (INDIVIDUAL)", "EMPRESARIO INDIVIDUAL",
    "PRODUTOR RURAL (PESSOA FISICA)",
)
KW_ADMINISTRADOR = ("ADMINISTRADOR",)


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


def _layer_b(vinculos: list[dict[str, Any]], raiz: str) -> dict[str, Any]:
    """Calcula o contágio proporcional por sócio. Retorna pontos + telemetria."""
    # Agrega, por sócio direto, as OUTRAS empresas (satélites) e suas situações.
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
            # (situação, é_ALD primário/secundário, distress especial) por satélite
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
            continue  # sócio sem outras empresas → contribui 0 (dilui/diversifica)
        # Insolvência inclui satélites baixadas E em falência/liquidação/RJ (distress).
        nb = sum(1 for sit, _, dist in sats.values() if sit == "BAIXADA" or dist)
        ni = sum(1 for sit, _, _ in sats.values() if sit == "INAPTA")
        # Interação ALD × comprometida: setor de risco que também faliu pesa o dobro
        # (factoring/câmbio fantasma que fechou = padrão clássico de shell/laranja).
        ald_pts = sum(
            (2 if (sit in STATUS_NEGATIVOS or dist) else 1)
            for sit, ald, dist in sats.values() if ald
        )
        # Suavização de Laplace: amostras pequenas não disparam o sinal cheio.
        fr_b = nb / (m + SUAVIZACAO)
        fr_i = ni / (m + SUAVIZACAO)
        fr_ald = min(1.0, ald_pts / (m + SUAVIZACAO))
        soma_fr_baixada += fr_b
        soma_fr_inapta += fr_i
        soma_fr_ald += fr_ald
        if s["admin"] and (fr_i > BASE_FRAUDE or fr_b > 0.6 or fr_ald > 0):
            admin_contaminado = True

    resultado = {
        "socios_diretos": n_socios,
        "satelites": len(satelites_distintos),
        "insolvencia_media": 0.0,
        "inaptidao_media": 0.0,
        "ald_medio": 0.0,
        "pontos": 0,
        "motivos": [],
    }
    if n_socios == 0 or not satelites_distintos:
        return resultado

    # Média entre TODOS os sócios diretos (os "limpos" entram como 0 → diluição).
    avg_baixada = soma_fr_baixada / n_socios
    avg_inapta = soma_fr_inapta / n_socios
    avg_ald = soma_fr_ald / n_socios
    resultado["insolvencia_media"] = round(avg_baixada, 3)
    resultado["inaptidao_media"] = round(avg_inapta, 3)
    resultado["ald_medio"] = round(avg_ald, 3)

    p_insolv = W_INSOLVENCIA * max(0.0, avg_baixada - BASE_INSOLVENCIA)
    p_fraude = W_FRAUDE * max(0.0, avg_inapta - BASE_FRAUDE)
    p_ald = W_ALD * max(0.0, avg_ald - BASE_ALD)
    fator = FATOR_SOCIO_ADMIN if admin_contaminado else 1.0
    pontos = min(TETO_CONTAGIO, int(round((p_insolv + p_fraude + p_ald) * fator)))

    motivos = []
    if p_fraude >= 1:
        motivos.append(f"Inaptidão concentrada na rede ({avg_inapta:.0%}/sócio, "
                       f"acima do esperado {BASE_FRAUDE:.0%})")
    if p_insolv >= 1:
        motivos.append(f"Insolvência difusa ({avg_baixada:.0%}/sócio baixadas, "
                       f"acima do esperado {BASE_INSOLVENCIA:.0%})")
    if p_ald >= 1:
        motivos.append(f"Exposição a setores de risco/ALD na rede ({avg_ald:.0%}/sócio)")
    if admin_contaminado and pontos:
        motivos.append(f"conector contaminado é Sócio-Administrador (×{FATOR_SOCIO_ADMIN})")

    resultado["pontos"] = pontos
    resultado["motivos"] = motivos
    return resultado


def calcular_score(consulta: dict[str, Any]) -> dict[str, Any]:
    """Computa o NEXUS Relational Trust Score a partir do resultado de `GraphDB.consultar`.

    Espera as chaves internas `_empresa_raw` (linha de nodes_empresas) e
    `_vinculos` (linhas do grafo de 2º grau).
    """
    empresa = consulta.get("_empresa_raw") or {}
    vinculos = consulta.get("_vinculos") or []
    raiz = consulta["empresa_principal"]["cnpj"]

    score = 100
    penalidades: list[dict[str, Any]] = []

    def aplicar(camada: str, pontos: int, motivo: str) -> None:
        nonlocal score
        if pontos <= 0:
            return
        score -= pontos
        penalidades.append({"camada": camada, "pontos": -pontos, "motivo": motivo})

    # ---------------- Layer A: Direta ----------------
    situacao = _norm(empresa.get("situacao_cadastral"))
    if situacao in STATUS_NEGATIVOS:
        aplicar("A", PENA_STATUS_NEGATIVO,
                f"Situação cadastral: {empresa.get('situacao_cadastral')}")
    elif situacao == "SUSPENSA":
        aplicar("A", PENA_STATUS_SUSPENSA, "Situação cadastral: Suspensa")

    # Situação especial: distress financeiro (falência/RJ/liquidação)
    distress = _distress_especial(empresa.get("situacao_especial"))
    if distress == "falencia":
        aplicar("A", PENA_FALENCIA, f"Situação especial: {empresa.get('situacao_especial')}")
    elif distress == "recuperacao":
        aplicar("A", PENA_RECUPERACAO, f"Situação especial: {empresa.get('situacao_especial')}")

    if _contem(empresa.get("motivo_situacao"), KW_MOTIVO_CRIME):
        aplicar("A", PENA_MOTIVO_CRIME,
                f"Motivo de risco: {empresa.get('motivo_situacao')}")

    # CNAE de risco ALD — primário OU secundário
    prim_ald = eh_ald(empresa.get("cnae_codigo"))
    if prim_ald:
        aplicar("A", PENA_CNAE_ALD, f"CNAE exposto a ALD: {empresa.get('cnae')}")
    elif _truthy(empresa.get("ald_secundario")):
        aplicar("A", PENA_CNAE_ALD, "CNAE de risco ALD em atividade secundária")

    if _contem(empresa.get("natureza_juridica"), KW_NATUREZA_SEM_BLINDAGEM):
        aplicar("A", PENA_NATUREZA_SEM_BLINDAGEM,
                f"Natureza sem blindagem patrimonial: {empresa.get('natureza_juridica')}")

    # ---------------- Layer B: Contágio (proporcional) ----------------
    b = _layer_b(vinculos, raiz)
    if b["pontos"]:
        aplicar("B", b["pontos"], "; ".join(b["motivos"]))

    score = max(0, min(100, score))

    if score >= 70:
        classificacao = "Baixo Risco"
    elif score >= 40:
        classificacao = "Risco Moderado"
    else:
        classificacao = "Alto Risco"

    return {
        "nexus_score": score,
        "classificacao": classificacao,
        "satelites_analisadas": b["satelites"],
        "socios_diretos": b["socios_diretos"],
        "rede": {
            "insolvencia_media": b["insolvencia_media"],
            "inaptidao_media": b["inaptidao_media"],
            "ald_medio": b["ald_medio"],
        },
        "penalidades": penalidades,
    }
