"""Fase 2 — testes determinísticos do NEXUS Relational Trust Score."""
from app.services.risk_score import calcular_score

RAIZ = "12345678"


def _consulta(empresa: dict | None = None, vinculos: list[dict] | None = None) -> dict:
    return {
        "empresa_principal": {"cnpj": RAIZ},
        "_empresa_raw": empresa or {"situacao_cadastral": "Ativa"},
        "_vinculos": vinculos or [],
    }


def _v(socio: str, empresa: str, situacao: str, qualif: str = "Sócio",
       cnae: str | None = None, sit_especial: str | None = None,
       ald_sec: bool = False) -> dict:
    """Um vínculo (sócio → empresa). empresa==RAIZ representa o vínculo direto."""
    return {
        "cnpj_cpf_socio": socio,
        "cnpj_basico": empresa,
        "situacao_cadastral": situacao,
        "qualificacao_do_socio": qualif,
        "identificador_de_socio": "PF",
        "cnae_codigo": cnae,
        "situacao_especial": sit_especial,
        "ald_secundario": ald_sec,
    }


# ---------------- Layer A (direta) ----------------
def test_empresa_limpa_score_100():
    r = calcular_score(_consulta())
    assert r["nexus_score"] == 100
    assert r["classificacao"] == "Baixo Risco"
    assert r["penalidades"] == []


def test_layer_a_status_negativo():
    assert calcular_score(_consulta({"situacao_cadastral": "Baixada"}))["nexus_score"] == 50


def test_layer_a_suspensa():
    assert calcular_score(_consulta({"situacao_cadastral": "Suspensa"}))["nexus_score"] == 70


def test_layer_a_motivo_crime():
    r = calcular_score(_consulta(
        {"situacao_cadastral": "Ativa", "motivo_situacao": "INEXISTENCIA DE FATO"}))
    assert r["nexus_score"] == 70


def test_layer_a_cnae_ald():
    # Código 6491300 = factoring (lista curada), não mais por texto
    r = calcular_score(_consulta(
        {"situacao_cadastral": "Ativa", "cnae_codigo": "6491300"}))
    assert r["nexus_score"] == 80


def test_layer_a_cnae_codigo_falso_positivo_nao_pune():
    # "Aluguel de jóias" tem outro código — não deve cair na lista ALD
    r = calcular_score(_consulta(
        {"situacao_cadastral": "Ativa", "cnae_codigo": "7729201"}))
    assert r["nexus_score"] == 100


def test_layer_a_natureza_sem_blindagem():
    r = calcular_score(_consulta(
        {"situacao_cadastral": "Ativa", "natureza_juridica": "Empresário (Individual)"}))
    assert r["nexus_score"] == 85


def test_layer_a_situacao_especial_falencia():
    r = calcular_score(_consulta(
        {"situacao_cadastral": "Ativa", "situacao_especial": "FALIDO"}))
    assert r["nexus_score"] == 55  # -45


def test_layer_a_situacao_especial_recuperacao():
    r = calcular_score(_consulta(
        {"situacao_cadastral": "Ativa", "situacao_especial": "RECUPERACAO JUDICIAL"}))
    assert r["nexus_score"] == 70  # -30


def test_layer_a_ald_secundario():
    # CNAE primário não-ALD, mas secundário é factoring → -20
    r = calcular_score(_consulta(
        {"situacao_cadastral": "Ativa", "cnae_codigo": "4322302", "ald_secundario": True}))
    assert r["nexus_score"] == 80


def test_ald_secundario_string_false_nao_pune():
    # Regressão: DuckDB all_varchar pode entregar a string "false" (truthy em Python)
    r = calcular_score(_consulta(
        {"situacao_cadastral": "Ativa", "cnae_codigo": "4322302", "ald_secundario": "false"}))
    assert r["nexus_score"] == 100
    r2 = calcular_score(_consulta(
        {"situacao_cadastral": "Ativa", "cnae_codigo": "4322302", "ald_secundario": "true"}))
    assert r2["nexus_score"] == 80


# ---------------- Layer B (contágio proporcional) ----------------
def test_diversificacao_protege_maca_podre():
    """10 sócios diretos; apenas 1 tem 1 empresa baixada → impacto ~nulo."""
    v = [_v(f"S{i}", RAIZ, "Ativa") for i in range(10)]
    v.append(_v("S0", "EMPX", "Baixada"))
    r = calcular_score(_consulta(None, v))
    assert r["nexus_score"] == 100
    assert r["socios_diretos"] == 10


def test_fraude_concentrada_derruba_score():
    """2 sócios, cada um ligado a 5 empresas inaptas → Risco Moderado/Alto."""
    v = [_v("A", RAIZ, "Ativa"), _v("B", RAIZ, "Ativa")]
    for i in range(5):
        v.append(_v("A", f"IA{i}", "Inapta"))
        v.append(_v("B", f"IB{i}", "Inapta"))
    r = calcular_score(_consulta(None, v))
    assert 40 <= r["nexus_score"] < 70
    assert any(p["camada"] == "B" for p in r["penalidades"])


def test_multiplicador_socio_administrador():
    """O mesmo cenário de fraude, mas com conector Administrador, pune mais."""
    base = [_v("A", RAIZ, "Ativa"), _v("B", RAIZ, "Ativa")]
    fraude = []
    for i in range(5):
        fraude.append(_v("A", f"IA{i}", "Inapta"))
        fraude.append(_v("B", f"IB{i}", "Inapta"))
    sem_admin = calcular_score(_consulta(None, base + fraude))["nexus_score"]
    base_adm = [_v("A", RAIZ, "Ativa", "Administrador"), _v("B", RAIZ, "Ativa", "Administrador")]
    fraude_adm = [
        _v(s, c, "Inapta", "Administrador")
        for (s, c) in [("A", f"IA{i}") for i in range(5)] + [("B", f"IB{i}") for i in range(5)]
    ]
    com_admin = calcular_score(_consulta(None, base_adm + fraude_adm))["nexus_score"]
    assert com_admin < sem_admin


def test_rede_tipica_do_pais_nao_colapsa():
    """Rede ~na média (50% baixada, ~18% inapta) com vários sócios → pouco impacto."""
    v = []
    for s in range(8):
        v.append(_v(f"P{s}", RAIZ, "Ativa"))
        for c in range(10):
            sit = "Baixada" if c < 5 else "Inapta" if c < 7 else "Ativa"
            v.append(_v(f"P{s}", f"C{s}_{c}", sit))
    r = calcular_score(_consulta(None, v))
    assert r["nexus_score"] >= 75  # não colapsa para ~0


def test_contagio_ald_setor_risco():
    """Sócio com participações externas em factoring (ALD) → contágio mesmo ativas."""
    limpa = [_v("A", RAIZ, "Ativa"), _v("A", "C1", "Ativa")]
    com_ald = [_v("A", RAIZ, "Ativa"), _v("A", "C1", "Ativa", cnae="6491300")]
    s_limpa = calcular_score(_consulta(None, limpa))["nexus_score"]
    r_ald = calcular_score(_consulta(None, com_ald))
    assert r_ald["nexus_score"] < s_limpa
    assert any("ALD" in p["motivo"] for p in r_ald["penalidades"])


def test_interacao_ald_comprometida_pesa_dobro():
    """Mesma inaptidão, mas em setor ALD pesa mais (interação ALD × comprometida)."""
    inapta_comum = [_v("A", RAIZ, "Ativa"), _v("A", "C1", "Inapta")]
    inapta_ald = [_v("A", RAIZ, "Ativa"), _v("A", "C1", "Inapta", cnae="6491300")]
    s_comum = calcular_score(_consulta(None, inapta_comum))["nexus_score"]
    s_ald = calcular_score(_consulta(None, inapta_ald))["nexus_score"]
    assert s_ald < s_comum


def test_contagio_situacao_especial_satelite():
    """Satélite em falência conta como insolvência no contágio (como baixada)."""
    com_distress = [_v("A", RAIZ, "Ativa"),
                    _v("A", "C1", "Ativa", sit_especial="FALIDO"),
                    _v("A", "C2", "Ativa", sit_especial="EM LIQUIDACAO")]
    limpa = [_v("A", RAIZ, "Ativa"), _v("A", "C1", "Ativa"), _v("A", "C2", "Ativa")]
    assert calcular_score(_consulta(None, com_distress))["nexus_score"] < \
           calcular_score(_consulta(None, limpa))["nexus_score"]


def test_ald_distante_diluido():
    """1 factoring entre muitos sócios limpos → impacto desprezível (diluição)."""
    v = [_v(f"S{i}", RAIZ, "Ativa") for i in range(12)]
    v.append(_v("S0", "C1", "Ativa", cnae="6491300"))
    assert calcular_score(_consulta(None, v))["nexus_score"] >= 97


def test_clamp_minimo_zero():
    """Alvo inapta + motivo-crime + ALD + rede de fraude concentrada → 0 (clamp)."""
    empresa = {
        "situacao_cadastral": "Inapta",
        "motivo_situacao": "OMISSAO CONTUMAZ",
        "cnae_codigo": "6612603",
        "natureza_juridica": "Empresário (Individual)",
    }
    v = [_v("A", RAIZ, "Ativa", "Administrador")]
    for i in range(6):
        v.append(_v("A", f"I{i}", "Inapta", "Administrador"))
    r = calcular_score(_consulta(empresa, v))
    assert r["nexus_score"] == 0
    assert r["classificacao"] == "Alto Risco"
