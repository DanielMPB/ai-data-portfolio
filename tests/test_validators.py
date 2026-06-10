"""Fase 1 — testes do validador de CNPJ alfanumérico (Módulo 11 estendido)."""
from app.core.validators import (
    calcular_dvs,
    normalizar_cnpj,
    raiz_cnpj,
    validar_cnpj_alfanumerico,
)


def test_dv_numerico_classico():
    # 11.222.333/0001-81 — CNPJ numérico válido conhecido
    assert calcular_dvs("112223330001") == "81"
    assert validar_cnpj_alfanumerico("11.222.333/0001-81")


def test_dv_alfanumerico_oficial_rfb():
    # Exemplo oficial RFB do novo padrão: 12.ABC.345/01DE-35
    assert calcular_dvs("12ABC34501DE") == "35"
    assert validar_cnpj_alfanumerico("12.ABC.345/01DE-35")


def test_valor_letra_A():
    # 'A' (ASCII 65) deve valer 17 (65-48); reflete-se no DV calculado
    assert ord("A") - 48 == 17


def test_dv_invalido():
    assert not validar_cnpj_alfanumerico("11222333000182")
    assert not validar_cnpj_alfanumerico("12.ABC.345/01DE-00")


def test_formato_invalido():
    assert not validar_cnpj_alfanumerico("123")           # curto
    assert not validar_cnpj_alfanumerico("12ABC34501DEAB")  # DV não numérico


def test_normalizacao():
    assert normalizar_cnpj("11.222.333/0001-81") == "11222333000181"
    assert normalizar_cnpj("12.abc.345/01de-35") == "12ABC34501DE35"


def test_raiz():
    assert raiz_cnpj("11.222.333/0001-81") == "11222333"
    assert raiz_cnpj("48847523") == "48847523"
