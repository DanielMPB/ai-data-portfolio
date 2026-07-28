"""NEXUS V2 — ETL de Endereços (cruzamento / "ninho de fachada").

Computa, a partir do Parquet bruto de `estabelecimentos` (Receita Federal), o
endereço normalizado de cada empresa (matriz) e quantas empresas compartilham
cada endereço — um sinal clássico de laranja/empresa de fachada quando muitas
co-locadas estão inaptas/baixadas.

Materializa `dados_processados/enderecos.duckdb` com:
  * empresa_endereco(raiz, endereco_key, endereco_fmt, uf)  — 1 linha por empresa
  * endereco_stats(endereco_key, total, inaptas, baixadas)  — agregado por endereço

Base separada do `nexus.duckdb` (mesmo padrão de `etl_sancoes.py`): o GraphDB faz
ATTACH dela se existir (fail-soft). Não exige reprocessar a base da Receita.

Endereços inválidos (sem CEP, sem logradouro, número "SN"/vazio, exterior) são
EXCLUÍDOS — senão criariam "ninhos" falsos de milhares de empresas.

Uso:
    python scripts/etl_enderecos.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # permite importar o pacote `app`

from app.core.config import settings  # noqa: E402

# Tokens de "número" que não identificam um imóvel específico → excluídos.
_NUM_INVALIDOS = (
    "", "SN", "SNR", "SN0", "S", "SEM", "SEMNUMERO", "SEMNR",
    "0", "00", "000", "0000",
)


def _sql_valid(parquet_glob: str) -> str:
    """CTE que normaliza e filtra os endereços válidos (matriz, domésticos).

    Números ausentes/"SN" NÃO são descartados — viram o sentinela 'SN' e seguem
    sendo agrupados por CEP+logradouro (específicos o bastante: quadras/blocos de
    Brasília, zona rural etc.). Só descartamos endereços sem CEP ou sem logradouro,
    que criariam ninhos falsos. A cobertura sobe e o sinal de "ninho" continua
    protegido pelo gate de fração comprometida no score.
    """
    invalidos = ", ".join(f"'{x}'" for x in _NUM_INVALIDOS)
    return f"""
WITH base AS (
  SELECT
    lpad(regexp_replace(cnpj, '[./-]', '', 'g'), 8, '0')                       AS raiz,
    TRY_CAST(situacao AS BIGINT)                                               AS situacao,
    -- inicio_atividade vem como inteiro AAAAMMDD gravado (errado) em TIMESTAMP_NS:
    -- epoch_ns() recupera o inteiro original e o reinterpretamos como data.
    TRY_CAST(strptime(lpad(CAST(epoch_ns(inicio_atividade) AS VARCHAR), 8, '0'),
                      '%Y%m%d') AS DATE)                                       AS inicio,
    nullif(trim(coalesce(tipo_logradouro, '')), 'nan')                        AS tipo,
    nullif(trim(coalesce(logradouro, '')), 'nan')                             AS logr,
    upper(regexp_replace(coalesce(numero, ''), '[^0-9A-Za-z]', '', 'g'))      AS num_raw,
    nullif(trim(coalesce(bairro, '')), 'nan')                                 AS bairro,
    lpad(regexp_replace(split_part(coalesce(cep, ''), '.', 1), '[^0-9]', '', 'g'), 8, '0') AS cep8,
    nullif(trim(coalesce(uf, '')), 'nan')                                     AS uf,
    TRY_CAST(pais AS BIGINT)                                                   AS pais,
    nullif(trim(coalesce(cidade_exterior, '')), 'nan')                        AS cidade_exterior
  FROM {parquet_glob}
  WHERE matriz_filial = 1
)
SELECT
  raiz, situacao, uf, inicio,
  -- número canônico: tokens vazios/"SN" viram o sentinela 'SN'
  (CASE WHEN num_raw IN ({invalidos}) THEN 'SN' ELSE num_raw END)             AS num,
  -- chave canônica do endereço (sem acento, maiúscula): CEP | logradouro | número
  (cep8 || '|' || strip_accents(upper(trim(coalesce(tipo, '') || ' ' || logr)))
        || '|' || (CASE WHEN num_raw IN ({invalidos}) THEN 'SN' ELSE num_raw END)) AS endereco_key,
  -- versão legível p/ exibição (preserva acentos)
  (trim(coalesce(tipo || ' ', '') || logr) || ', '
    || (CASE WHEN num_raw IN ({invalidos}) THEN 'S/N' ELSE num_raw END)
    || coalesce(' - ' || bairro, '') || ' - ' || coalesce(uf, '')
    || ' · CEP ' || substr(cep8, 1, 5) || '-' || substr(cep8, 6, 3))          AS endereco_fmt
FROM base
WHERE (pais = 0 OR pais IS NULL)
  AND cidade_exterior IS NULL
  AND logr IS NOT NULL AND length(logr) >= 4
  AND regexp_replace(cep8, '0', '', 'g') <> ''      -- CEP não é só zeros
"""


def main() -> int:
    import duckdb

    glob = settings.dados_brutos / "estabelecimentos" / "*.parquet"
    if not list((settings.dados_brutos / "estabelecimentos").glob("*.parquet")):
        print(f"ERRO: estabelecimentos não encontrados em {glob.parent}", file=sys.stderr)
        return 1
    parquet_glob = f"read_parquet('{glob.as_posix()}')"

    settings.dados_processados.mkdir(parents=True, exist_ok=True)
    db_path = settings.enderecos_db
    if db_path.exists():
        db_path.unlink()

    t0 = time.perf_counter()
    print("NEXUS V2 — ETL de Endereços (cruzamento)")
    con = duckdb.connect(str(db_path))
    con.execute("SET enable_progress_bar=false")
    con.execute("SET preserve_insertion_order=false")      # reduz o pico de memória/temp
    con.execute("SET max_temp_directory_size='200GiB'")    # spill out-of-core sem teto baixo
    con.execute("PRAGMA threads=" + str(min(4, __import__("os").cpu_count() or 4)))

    # 1 linha por empresa (matriz) — sem materializar a CTE gigante de normalização
    # (era o que estourava o diretório temporário). A chave/fmt/situação já saem aqui.
    print("  -> empresa_endereco ...")
    con.execute(
        "CREATE TABLE empresa_endereco AS "
        "SELECT raiz, any_value(endereco_key) AS endereco_key, "
        "       any_value(endereco_fmt) AS endereco_fmt, any_value(uf) AS uf, "
        "       any_value(situacao) AS situacao, any_value(inicio) AS inicio_atividade "
        f"FROM ({_sql_valid(parquet_glob)}) GROUP BY raiz"
    )
    # Agregado por endereço a partir da tabela já reduzida (1 linha/empresa → COUNT(*)).
    print("  -> endereco_stats ...")
    con.execute(
        "CREATE TABLE endereco_stats AS "
        "SELECT endereco_key, COUNT(*) AS total, "
        "       COUNT(*) FILTER (WHERE situacao = 2) AS ativas, "
        "       COUNT(*) FILTER (WHERE situacao = 4) AS inaptas, "
        "       COUNT(*) FILTER (WHERE situacao = 8) AS baixadas "
        "FROM empresa_endereco GROUP BY endereco_key"
    )
    con.execute("CREATE INDEX idx_empend_raiz ON empresa_endereco(raiz)")
    con.execute("CREATE INDEX idx_empend_key ON empresa_endereco(endereco_key)")
    con.execute("CREATE INDEX idx_endstats_key ON endereco_stats(endereco_key)")

    n_emp = con.execute("SELECT COUNT(*) FROM empresa_endereco").fetchone()[0]
    n_end = con.execute("SELECT COUNT(*) FROM endereco_stats").fetchone()[0]
    ninhos = con.execute(
        "SELECT COUNT(*) FROM endereco_stats WHERE total >= 10").fetchone()[0]
    con.close()
    print(f"OK - enderecos.duckdb: {n_emp:,} empresas | {n_end:,} enderecos "
          f"({ninhos:,} com 10+ empresas) em {time.perf_counter()-t0:.1f}s -> {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
