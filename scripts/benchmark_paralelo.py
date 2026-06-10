"""Benchmark de computação paralela — due diligence de portfólio.

Compara o tempo de avaliação de uma carteira de CNPJs em modo sequencial
(1 núcleo) versus paralelo (ProcessPoolExecutor, N núcleos), evidenciando o
speedup obtido com computação paralela.

Uso:
    python scripts/benchmark_paralelo.py            # 60 CNPJs
    python scripts/benchmark_paralelo.py 200 8      # 200 CNPJs, 8 workers
"""
from __future__ import annotations

import os
import sys

# Permite rodar como script solto (garante o pacote `app` no path).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import duckdb  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services.parallel import (  # noqa: E402
    avaliar_portfolio,
    avaliar_portfolio_sequencial,
)


def amostrar_cnpjs(n: int) -> list[str]:
    con = duckdb.connect(str(settings.duckdb_path), read_only=True)
    linhas = con.execute(
        "SELECT cnpj_basico FROM edges_socios "
        "GROUP BY 1 ORDER BY count(*) DESC LIMIT ?", [n]
    ).fetchall()
    con.close()
    return [r[0] for r in linhas]


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else (os.cpu_count() or 1)

    if not settings.duckdb_path.exists():
        print("Base ausente — rode o ETL antes (scripts/etl_nexus.py).")
        return 1

    cnpjs = amostrar_cnpjs(n)
    print(f"Benchmark | {len(cnpjs)} CNPJs | {os.cpu_count()} núcleos disponíveis\n")

    seq = avaliar_portfolio_sequencial(cnpjs)
    print(f"  Sequencial (1 núcleo) : {seq['tempo_segundos']:.2f}s")

    par = avaliar_portfolio(cnpjs, max_workers=workers)
    print(f"  Paralelo ({par['workers']} núcleos): {par['tempo_segundos']:.2f}s")

    if par["tempo_segundos"] > 0:
        speedup = seq["tempo_segundos"] / par["tempo_segundos"]
        print(f"\n  Speedup: {speedup:.2f}x  "
              f"(eficiência ~{speedup / par['workers'] * 100:.0f}% por núcleo)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
