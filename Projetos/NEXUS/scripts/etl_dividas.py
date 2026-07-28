"""NEXUS V2 — ETL de Dívida Ativa da União (PGFN).

Ingere os CSVs de devedores que o usuário baixa do portal de Dados Abertos da
PGFN e deposita em ``Dados Brutos/dividas/`` e materializa
``dados_processados/dividas.duckdb`` (tabela ``dividas`` agregada por raiz de
CNPJ: nº de inscrições, valor consolidado e se há execução fiscal ajuizada).

Fecha o eixo FINANCEIRO do score: inadimplência fiscal confirmada e oficial.
Base separada do ``nexus.duckdb`` (mesmo padrão de sanções/endereços) — anexada
via ATTACH (fail-soft).

Aquisição dos dados (manual, uma vez):
  https://www.gov.br/pgfn/.../dados-abertos  (Dívida Ativa da União) → baixar os
  CSVs (por estado/origem) e extrair em ``Dados Brutos/dividas/``. São arquivos
  grandes; pode baixar só os que interessam (o ETL agrega o que estiver lá).

Uso:
    python scripts/etl_dividas.py
"""
from __future__ import annotations

import os
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402


def _norm(h: str) -> str:
    s = unicodedata.normalize("NFKD", h or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = "".join(c if c.isalnum() else " " for c in s)
    return " ".join(s.upper().split())


def _find(cols: list[str], *grupos: tuple[str, ...]) -> str | None:
    norm = {c: _norm(c) for c in cols}
    for chaves in grupos:
        for c in cols:
            if all(k in norm[c] for k in chaves):
                return c
    return None


def main() -> int:
    import duckdb

    src = settings.dividas_brutos
    arquivos = sorted(src.rglob("*.csv")) if src.exists() else []
    if not arquivos:
        print(f"ERRO: nenhum .csv em {src}", file=sys.stderr)
        print("Baixe os dados abertos da Dívida Ativa da União (PGFN) e extraia lá.",
              file=sys.stderr)
        return 1

    settings.dados_processados.mkdir(parents=True, exist_ok=True)
    db_path = settings.dividas_db
    if db_path.exists():
        db_path.unlink()

    t0 = time.perf_counter()
    print(f"NEXUS V2 — ETL de Dívida Ativa (PGFN) | {len(arquivos)} arquivo(s)")
    con = duckdb.connect(str(db_path))
    con.execute("SET enable_progress_bar=false")
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET max_temp_directory_size='200GiB'")
    con.execute("PRAGMA threads=" + str(min(4, os.cpu_count() or 4)))
    con.execute("CREATE TABLE _stage(raiz VARCHAR, valor DOUBLE, ajuiz INTEGER)")

    # Arquivos de sanção (CEIS/CNEP/Lista Suja) às vezes vão parar nesta pasta por
    # engano; eles também têm coluna de CNPJ e até "VALOR DA MULTA" — ignorá-los
    # evita transformar multa/sanção em "dívida ativa".
    _NAO_DIVIDA = ("ceis", "cnep", "escravo", "suja", "sancoes", "sancao")

    total_lidos = 0
    for f in arquivos:
        if any(k in f.name.lower() for k in _NAO_DIVIDA):
            print(f"  ! {f.name}: arquivo de sanção (não é dívida) — pulando.")
            continue
        rd = f"read_csv_auto('{f.as_posix()}', all_varchar=true, ignore_errors=true)"
        try:
            cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {rd}").fetchall()]
        except duckdb.Error as exc:
            print(f"  ! {f.name}: não foi possível ler ({exc}) — pulando.")
            continue
        cdoc = _find(cols, ("CPF", "CNPJ"), ("CNPJ",))
        if not cdoc:
            print(f"  ! {f.name}: coluna de CNPJ não localizada — pulando.")
            continue
        cval = _find(cols, ("VALOR", "CONSOLIDADO"), ("VALOR",))
        caju = _find(cols, ("AJUIZ",))
        docd = f"regexp_replace(\"{cdoc}\", '[^0-9]', '', 'g')"
        if cval:
            valx = (f"coalesce(TRY_CAST(CASE WHEN position(',' in \"{cval}\") > 0 "
                    f"THEN replace(replace(\"{cval}\", '.', ''), ',', '.') "
                    f"ELSE \"{cval}\" END AS DOUBLE), 0)")
        else:
            valx = "0"
        ajux = f"CASE WHEN upper(\"{caju}\") LIKE 'S%' THEN 1 ELSE 0 END" if caju else "0"
        con.execute(
            f"INSERT INTO _stage SELECT substr({docd}, 1, 8) AS raiz, {valx} AS valor, "
            f"{ajux} AS ajuiz FROM {rd} WHERE length({docd}) = 14"
        )
        n = con.execute("SELECT COUNT(*) FROM _stage").fetchone()[0] - total_lidos
        total_lidos += n
        print(f"  -> {f.name}: {n:,} inscrições PJ")

    con.execute(
        "CREATE TABLE dividas AS "
        "SELECT raiz, COUNT(*) AS inscricoes, SUM(valor) AS valor, MAX(ajuiz) AS ajuizadas "
        "FROM _stage GROUP BY raiz"
    )
    con.execute("CREATE INDEX idx_div_raiz ON dividas(raiz)")
    n_emp = con.execute("SELECT COUNT(*) FROM dividas").fetchone()[0]
    con.close()
    print(f"OK - dividas.duckdb: {total_lidos:,} inscrições | {n_emp:,} empresas devedoras "
          f"em {time.perf_counter()-t0:.1f}s -> {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
