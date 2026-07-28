"""NEXUS V2 — Fase 0: Pipeline de Engenharia de Dados (ETL Massivo).

Consolida, desambigua e higieniza a base pública fragmentada da Receita Federal
(Parquet particionado em `Dados Brutos/`) em dois artefatos analíticos:

  - dados_processados/nodes_empresas.csv  (entidades corporativas decodificadas)
  - dados_processados/edges_socios.csv    (matriz relacional de vínculos societários)

E, ao final, materializa `dados_processados/nexus.duckdb` com índices para
consultas de grafo em milissegundos.

Princípios:
  * Lazy Evaluation com `pl.scan_parquet()`.
  * Escrita via `sink_csv()` (motor streaming nativo) → proteção contra OOM nos 4,68 GB.
  * Blindagem do CNPJ alfanumérico (padrão Julho/2026): pontuação física expurgada,
    identificadores persistidos como String (pl.Utf8), zeros à esquerda preservados.

Uso:
    python scripts/etl_nexus.py --sample   # 1 partição por base (validação rápida)
    python scripts/etl_nexus.py            # base completa (streaming)
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # permite importar o pacote `app`
DADOS_BRUTOS = ROOT / "Dados Brutos"
DADOS_PROCESSADOS = ROOT / "dados_processados"

from app.core.ald import CNAE_ALD_CODES  # noqa: E402

# Lista de códigos ALD formatada para SQL (DuckDB).
_ALD_SQL_LIST = ", ".join(f"'{c}'" for c in sorted(CNAE_ALD_CODES))

# ---------------------------------------------------------------------------
# Tabelas de decodificação estáticas (códigos oficiais da Receita Federal)
# ---------------------------------------------------------------------------
SITUACAO_MAP = {1: "Nula", 2: "Ativa", 3: "Suspensa", 4: "Inapta", 8: "Baixada"}
PORTE_MAP = {0: "Não Informado", 1: "Microempresa (ME)", 3: "EPP", 5: "Demais"}
IDENTIFICADOR_MAP = {1: "PJ", 2: "PF", 3: "EXTERIOR"}


def _glob(base: str, sample: bool) -> str:
    """Caminho-glob para uma base; em modo sample lê apenas a 1ª partição."""
    fname = "0.parquet" if sample else "*.parquet"
    return str(DADOS_BRUTOS / base / fname)


def _clean_str(col: str) -> pl.Expr:
    """Normaliza string suja: 'nan' literal → null, trim de espaços."""
    return (
        pl.col(col)
        .cast(pl.Utf8)
        .str.strip_chars()
        .replace({"nan": None, "NAN": None, "": None})
    )


def _clean_id(col: str) -> pl.Expr:
    """Blindagem de identificador: expurga pontuação física (. / -), mantém Utf8.

    Preserva máscaras de CPF de sócio (ex.: ``***775488**``) e caracteres
    alfanuméricos A-Z do novo padrão de CNPJ (Julho/2026).
    """
    return (
        pl.col(col)
        .cast(pl.Utf8)
        .str.strip_chars()
        .str.replace_all(r"[.\-/]", "")
        .replace({"nan": None, "": None})
    )


def _lookup(base: str, sample: bool, alias: str) -> pl.LazyFrame:
    """Tabela de decodificação (codigo, descricao) renomeada para join."""
    return (
        pl.scan_parquet(_glob(base, sample))
        .select(
            pl.col("codigo"),
            _clean_str("descricao").alias(alias),
        )
    )


def build_nodes(sample: bool) -> pl.LazyFrame:
    """nodes_empresas.csv — entidades corporativas com textos decodificados."""
    empresas = pl.scan_parquet(_glob("empresas", sample)).select(
        _clean_id("cnpj_8").str.zfill(8).alias("cnpj"),
        _clean_str("razao_social").alias("razao_social"),
        pl.col("natureza_juridica").cast(pl.Int64),
        pl.col("capital_social").cast(pl.Float64).alias("capital_social"),
        pl.col("porte_empresa").cast(pl.Int64),
    )

    # situação/motivo/CNAE vivem no estabelecimento MATRIZ (matriz_filial == 1)
    estab = (
        pl.scan_parquet(_glob("estabelecimentos", sample))
        .filter(pl.col("matriz_filial") == 1)
        .select(
            _clean_id("cnpj").str.zfill(8).alias("cnpj"),
            pl.col("situacao").cast(pl.Int64),
            pl.col("motivo_situacao").cast(pl.Int64),
            _clean_id("cnae_fiscal").str.zfill(7).alias("cnae_fiscal"),
            _clean_str("cnae_secundario").alias("cnae_secundario"),
            _clean_str("situacao_especial").alias("situacao_especial"),
            _clean_str("uf").alias("uf"),
        )
        # garante 1 linha por raiz mesmo se houver duplicidade de matriz
        .unique(subset=["cnpj"], keep="first")
        # pré-marca se algum CNAE secundário é de setor ALD
        .with_columns(
            pl.col("cnae_secundario").fill_null("").str.split(",")
            .list.eval(pl.element().str.strip_chars().str.zfill(7).is_in(list(CNAE_ALD_CODES)))
            .list.any().fill_null(False).alias("ald_secundario")
        )
    )

    # CNAE canonizado em 7 dígitos nos dois lados do join (evita falha por zeros à esquerda)
    cnaes = (
        pl.scan_parquet(_glob("cnaes", sample))
        .select(
            pl.col("codigo").cast(pl.Utf8).str.zfill(7).alias("codigo"),
            _clean_str("descricao").alias("cnae_desc"),
        )
    )
    motivos = _lookup("motivos", sample, "motivo_situacao_desc")  # codigo: Int64
    naturezas = _lookup("naturezas", sample, "natureza_juridica_desc")  # Int64

    nodes = (
        empresas.join(estab, on="cnpj", how="left")
        .join(cnaes, left_on="cnae_fiscal", right_on="codigo", how="left")
        .join(motivos, left_on="motivo_situacao", right_on="codigo", how="left")
        .join(naturezas, left_on="natureza_juridica", right_on="codigo", how="left")
        .with_columns(
            pl.col("situacao")
            .replace_strict(SITUACAO_MAP, default="Desconhecida", return_dtype=pl.Utf8)
            .alias("situacao_cadastral"),
            pl.col("porte_empresa")
            .replace_strict(PORTE_MAP, default="Não Informado", return_dtype=pl.Utf8)
            .alias("porte"),
        )
        .select(
            "cnpj",
            "razao_social",
            "situacao_cadastral",
            pl.col("motivo_situacao_desc").alias("motivo_situacao"),
            pl.col("cnae_desc").alias("cnae"),
            pl.col("cnae_fiscal").alias("cnae_codigo"),
            "ald_secundario",
            "situacao_especial",
            pl.col("natureza_juridica_desc").alias("natureza_juridica"),
            "capital_social",
            "porte",
            "uf",
        )
    )
    return nodes


def build_edges(sample: bool) -> pl.LazyFrame:
    """edges_socios.csv — vínculos societários (nomes de coluna do SQL homologado)."""
    qualificacoes = _lookup("qualificacoes", sample, "qualificacao_do_socio")  # Int64

    edges = (
        pl.scan_parquet(_glob("socios", sample))
        .select(
            _clean_id("cnpj").str.zfill(8).alias("cnpj_basico"),
            _clean_id("cpf_cnpj_socio").alias("cnpj_cpf_socio"),
            _clean_str("nome_socio").alias("nome_socio_razao_social"),
            pl.col("qualificacao_socio").cast(pl.Int64),
            pl.col("identificador_socio").cast(pl.Int64),
        )
        .join(qualificacoes, left_on="qualificacao_socio", right_on="codigo", how="left")
        .with_columns(
            pl.col("identificador_socio")
            .replace_strict(IDENTIFICADOR_MAP, default="PF", return_dtype=pl.Utf8)
            .alias("identificador_de_socio"),
        )
        .filter(pl.col("cnpj_cpf_socio").is_not_null())
        .select(
            "cnpj_basico",
            "cnpj_cpf_socio",
            "nome_socio_razao_social",
            "qualificacao_do_socio",
            "identificador_de_socio",
        )
    )
    return edges


# ---------------------------------------------------------------------------
# Motor DuckDB (default p/ base completa): robusto e out-of-core.
# O motor de streaming do Polars (sink_csv) pode estourar (segfault) no join
# global de ~30M+ linhas dos 4,68 GB. O DuckDB executa o join derramando para
# disco, com paralelismo interno (PRAGMA threads), sem risco de OOM.
# ---------------------------------------------------------------------------
def _pq(base: str, sample: bool) -> str:
    """String de leitura read_parquet() para uma base (amostra = só 0.parquet)."""
    fname = "0.parquet" if sample else "*.parquet"
    return f"read_parquet('{(DADOS_BRUTOS / base / fname).as_posix()}')"


def _sql_nodes(sample: bool) -> str:
    return f"""
COPY (
  SELECT
    lpad(regexp_replace(e.cnpj_8, '[./-]', '', 'g'), 8, '0')           AS cnpj,
    nullif(trim(e.razao_social), 'nan')                               AS razao_social,
    CASE est.situacao WHEN 1 THEN 'Nula' WHEN 2 THEN 'Ativa'
         WHEN 3 THEN 'Suspensa' WHEN 4 THEN 'Inapta' WHEN 8 THEN 'Baixada'
         ELSE 'Desconhecida' END                                      AS situacao_cadastral,
    nullif(trim(mot.descricao), 'nan')                                AS motivo_situacao,
    nullif(trim(cna.descricao), 'nan')                                AS cnae,
    est.cnae_fiscal                                                   AS cnae_codigo,
    CASE WHEN len(list_intersect(
           list_transform(string_split(coalesce(est.cnae_secundario, ''), ','),
                          x -> lpad(trim(x), 7, '0')),
           [{_ALD_SQL_LIST}])) > 0 THEN true ELSE false END           AS ald_secundario,
    est.situacao_especial                                             AS situacao_especial,
    nullif(trim(nat.descricao), 'nan')                                AS natureza_juridica,
    e.capital_social                                                  AS capital_social,
    CASE e.porte_empresa WHEN 1 THEN 'Microempresa (ME)' WHEN 3 THEN 'EPP'
         WHEN 5 THEN 'Demais' ELSE 'Não Informado' END                AS porte,
    nullif(trim(est.uf), 'nan')                                       AS uf
  FROM {_pq('empresas', sample)} e
  LEFT JOIN (
    SELECT lpad(regexp_replace(cnpj, '[./-]', '', 'g'), 8, '0')       AS cnpj_b,
           situacao, motivo_situacao,
           lpad(regexp_replace(cnae_fiscal, '[./-]', '', 'g'), 7, '0') AS cnae_fiscal,
           cnae_secundario,
           nullif(trim(situacao_especial), 'nan')                     AS situacao_especial, uf
    FROM {_pq('estabelecimentos', sample)}
    WHERE matriz_filial = 1
  ) est ON lpad(regexp_replace(e.cnpj_8, '[./-]', '', 'g'), 8, '0') = est.cnpj_b
  LEFT JOIN {_pq('cnaes', sample)}     cna ON est.cnae_fiscal     = lpad(cna.codigo, 7, '0')
  LEFT JOIN {_pq('motivos', sample)}   mot ON est.motivo_situacao = mot.codigo
  LEFT JOIN {_pq('naturezas', sample)} nat ON e.natureza_juridica = nat.codigo
) TO '{(DADOS_PROCESSADOS / 'nodes_empresas.csv').as_posix()}' (HEADER, DELIMITER ',');
"""


def _sql_edges(sample: bool) -> str:
    return f"""
COPY (
  SELECT
    lpad(regexp_replace(s.cnpj, '[./-]', '', 'g'), 8, '0')            AS cnpj_basico,
    regexp_replace(s.cpf_cnpj_socio, '[./-]', '', 'g')               AS cnpj_cpf_socio,
    nullif(trim(s.nome_socio), 'nan')                                AS nome_socio_razao_social,
    nullif(trim(q.descricao), 'nan')                                 AS qualificacao_do_socio,
    CASE s.identificador_socio WHEN 1 THEN 'PJ' WHEN 2 THEN 'PF'
         WHEN 3 THEN 'EXTERIOR' ELSE 'PF' END                        AS identificador_de_socio
  FROM {_pq('socios', sample)} s
  LEFT JOIN {_pq('qualificacoes', sample)} q ON s.qualificacao_socio = q.codigo
  WHERE s.cpf_cnpj_socio IS NOT NULL AND trim(s.cpf_cnpj_socio) <> 'nan'
) TO '{(DADOS_PROCESSADOS / 'edges_socios.csv').as_posix()}' (HEADER, DELIMITER ',');
"""


def build_csvs_duckdb(sample: bool, threads: int) -> None:
    """Gera os dois CSVs via DuckDB (join out-of-core, paralelo por PRAGMA threads)."""
    import duckdb

    con = duckdb.connect()
    con.execute("SET enable_progress_bar=false")
    con.execute(f"PRAGMA threads={threads}")
    print("  -> [duckdb] gerando nodes_empresas.csv ...")
    con.execute(_sql_nodes(sample))
    print("  -> [duckdb] gerando edges_socios.csv ...")
    con.execute(_sql_edges(sample))
    con.close()


def build_database() -> None:
    """Materializa nexus.duckdb a partir dos CSVs, com índices de grafo."""
    import duckdb

    db_path = DADOS_PROCESSADOS / "nexus.duckdb"
    if db_path.exists():
        db_path.unlink()

    nodes_csv = str(DADOS_PROCESSADOS / "nodes_empresas.csv")
    edges_csv = str(DADOS_PROCESSADOS / "edges_socios.csv")

    con = duckdb.connect(str(db_path))
    con.execute("SET enable_progress_bar=false")
    # Tipagem 100% textual nos identificadores (all_varchar) → integridade alfanumérica.
    # ORDER BY pela chave de consulta → clusteriza os dados e habilita o "zonemap
    # pruning" do DuckDB: filtros por cnpj passam a ler apenas o bloco relevante
    # (lookup de ~milissegundos, mesmo a frio), em vez de varrer a tabela inteira.
    # all_varchar preserva os identificadores como texto; mas ald_secundario é
    # booleano — castamos explicitamente (senão a string "false" seria truthy).
    con.execute(
        "CREATE TABLE nodes_empresas AS "
        "SELECT * REPLACE (lower(ald_secundario) = 'true' AS ald_secundario) "
        "FROM read_csv_auto(?, all_varchar=true) ORDER BY cnpj",
        [nodes_csv],
    )
    con.execute(
        "CREATE TABLE edges_socios AS "
        "SELECT * FROM read_csv_auto(?, all_varchar=true) ORDER BY cnpj_basico",
        [edges_csv],
    )
    con.execute("CREATE INDEX idx_nodes_cnpj ON nodes_empresas(cnpj)")
    con.execute("CREATE INDEX idx_edges_basico ON edges_socios(cnpj_basico)")
    con.execute("CREATE INDEX idx_edges_socio ON edges_socios(cnpj_cpf_socio)")
    n_nodes = con.execute("SELECT COUNT(*) FROM nodes_empresas").fetchone()[0]
    n_edges = con.execute("SELECT COUNT(*) FROM edges_socios").fetchone()[0]
    con.close()
    print(f"  [duckdb] nexus.duckdb  nodes={n_nodes:,}  edges={n_edges:,}")


def main() -> int:
    parser = argparse.ArgumentParser(description="NEXUS V2 — ETL (Fase 0)")
    parser.add_argument(
        "--sample", action="store_true",
        help="Lê apenas a 1ª partição de cada base (validação rápida).",
    )
    parser.add_argument(
        "--engine", choices=["duckdb", "polars"], default="duckdb",
        help="Motor dos joins: 'duckdb' (robusto, out-of-core; default) "
             "ou 'polars' (Lazy/streaming, conforme spec — ideal p/ amostra).",
    )
    parser.add_argument(
        "--threads", type=int, default=(os.cpu_count() or 4),
        help="Núcleos para o motor DuckDB (default: todos).",
    )
    parser.add_argument(
        "--skip-duckdb", action="store_true",
        help="Não materializa o nexus.duckdb (gera somente os CSVs).",
    )
    args = parser.parse_args()

    if not DADOS_BRUTOS.exists():
        print(f"ERRO: pasta de dados brutos não encontrada: {DADOS_BRUTOS}", file=sys.stderr)
        return 1

    DADOS_PROCESSADOS.mkdir(exist_ok=True)
    mode = "AMOSTRA (1 partição/base)" if args.sample else "COMPLETO (4,68 GB)"
    print(f"NEXUS V2 — ETL | modo: {mode} | motor: {args.engine}")

    t0 = time.perf_counter()
    if args.engine == "duckdb":
        build_csvs_duckdb(args.sample, args.threads)
    else:
        print("  -> [polars] gerando nodes_empresas.csv ...")
        build_nodes(args.sample).sink_csv(DADOS_PROCESSADOS / "nodes_empresas.csv")
        print("  -> [polars] gerando edges_socios.csv ...")
        build_edges(args.sample).sink_csv(DADOS_PROCESSADOS / "edges_socios.csv")
    print(f"  CSVs prontos em {time.perf_counter() - t0:.1f}s")

    if not args.skip_duckdb:
        build_database()

    print(f"OK — ETL concluído em {time.perf_counter() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
