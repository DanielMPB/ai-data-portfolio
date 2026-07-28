"""Validação de CNPJ no padrão Alfanumérico (Julho/2026).

A partir de julho/2026 o CNPJ passa a aceitar caracteres alfanuméricos (A-Z e 0-9)
nas 12 primeiras posições (raiz + ordem), mantendo os 2 dígitos verificadores (DV)
numéricos. O cálculo do DV usa o **Módulo 11 estendido**: cada caractere é convertido
para seu valor numérico subtraindo a constante 48 do código ASCII
(ex.: '0' = 48-48 = 0; 'A' = 65-48 = 17).
"""
from __future__ import annotations

import re

# Pesos cíclicos do Módulo 11 (da direita para a esquerda: 2..9).
_PESOS_DV1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]          # sobre os 12 primeiros
_PESOS_DV2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]       # sobre os 13 primeiros

_RE_NAO_ALFANUM = re.compile(r"[^0-9A-Z]")
_RE_VALIDO = re.compile(r"^[0-9A-Z]{12}[0-9]{2}$")


def normalizar_cnpj(cnpj: str) -> str:
    """Remove pontuação física (pontos, barras, hífens, espaços) e padroniza maiúsculas.

    Não trunca zeros à esquerda — o valor permanece textual.
    """
    return _RE_NAO_ALFANUM.sub("", (cnpj or "").upper())


def _valor_char(c: str) -> int:
    """Valor numérico do caractere no Módulo 11 estendido (ASCII - 48)."""
    return ord(c) - 48


def _calcular_dv(base: str, pesos: list[int]) -> int:
    """Calcula um dígito verificador para `base` usando os `pesos` informados."""
    soma = sum(_valor_char(c) * p for c, p in zip(base, pesos))
    resto = soma % 11
    return 0 if resto < 2 else 11 - resto


def calcular_dvs(base12: str) -> str:
    """Retorna os 2 dígitos verificadores para uma raiz+ordem de 12 caracteres."""
    base12 = base12.upper()
    dv1 = _calcular_dv(base12, _PESOS_DV1)
    dv2 = _calcular_dv(base12 + str(dv1), _PESOS_DV2)
    return f"{dv1}{dv2}"


def validar_cnpj_alfanumerico(cnpj: str) -> bool:
    """Valida um CNPJ alfanumérico completo (14 posições) pelos seus DVs."""
    limpo = normalizar_cnpj(cnpj)
    if not _RE_VALIDO.match(limpo):
        return False
    return calcular_dvs(limpo[:12]) == limpo[12:]


def raiz_cnpj(cnpj: str) -> str:
    """Extrai a raiz de 8 caracteres (chave de grupo econômico) do CNPJ."""
    limpo = normalizar_cnpj(cnpj)
    return limpo[:8]
