"""Setores CNAE sensíveis a Lavagem de Dinheiro (ALD) — fonte única de verdade.

Lista curada de códigos (7 dígitos) usada tanto pelo motor de score quanto pelo
ETL (para pré-marcar CNAE secundário). Curada a partir da tabela oficial de CNAEs,
evitando falsos positivos de busca textual (ex.: "aluguel de jóias", "obras de
arte" da engenharia civil).
"""
from __future__ import annotations

CNAE_ALD_CODES: frozenset[str] = frozenset({
    "0724301",  # Extração de minério de metais preciosos
    "0724302",  # Beneficiamento de minério de metais preciosos
    "0893200",  # Extração de gemas (pedras preciosas e semipreciosas)
    "2442300",  # Metalurgia dos metais preciosos
    "3211601",  # Lapidação de gemas
    "6438701",  # Bancos de câmbio
    "6491300",  # Sociedades de fomento mercantil - factoring
    "6612603",  # Corretoras de câmbio
    "8299706",  # Casas lotéricas
    "9200302",  # Exploração de apostas em corridas de cavalos
    "9200399",  # Exploração de jogos de azar e apostas não especificados
})


def eh_ald(cnae_codigo: object) -> bool:
    """True se o código CNAE (7 dígitos) é de setor sensível a ALD."""
    if not cnae_codigo:
        return False
    return str(cnae_codigo).zfill(7) in CNAE_ALD_CODES


def secundario_tem_ald(cnae_secundario: object) -> bool:
    """True se a lista de CNAEs secundários (string 'cod,cod,...') tem algum ALD."""
    if not cnae_secundario:
        return False
    return any(
        c.strip().zfill(7) in CNAE_ALD_CODES
        for c in str(cnae_secundario).split(",") if c.strip()
    )
