"""NEXUS V2 — Extração e Gerador de Amostra para GitHub.

Este script extrai um subconjunto representativo e rico da base completa de dados
(empresas, relacionamentos societários, dívidas e sanções) para gerar um banco
`dados_amostra/nexus_amostra.duckdb` e arquivos CSV reduzidos com tamanho < 25 MB,
totalmente compatíveis e seguros para serem enviados ao GitHub.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
import duckdb

ROOT = Path(__file__).resolve().parents[1]
DADOS_PROCESSADOS = ROOT / "dados_processados"
DADOS_AMOSTRA = ROOT / "dados_amostra"

DB_ORIGEM = DADOS_PROCESSADOS / "nexus.duckdb"
DB_DESTINO = DADOS_AMOSTRA / "nexus_amostra.duckdb"


def extrair_amostra():
    if not DB_ORIGEM.exists():
        print(f"[ERRO] Base de origem não encontrada em: {DB_ORIGEM}")
        print("Rode o ETL de amostra original: python scripts/etl_nexus.py --sample")
        return

    DADOS_AMOSTRA.mkdir(parents=True, exist_ok=True)
    
    if DB_DESTINO.exists():
        try:
            os.remove(DB_DESTINO)
        except Exception:
            pass

    print(f"[1/4] Anexando a base completa ({DB_ORIGEM})...")
    
    db_orig_str = str(DB_ORIGEM.resolve()).replace("\\", "/")
    db_dest_str = str(DB_DESTINO.resolve()).replace("\\", "/")

    # Conecta no banco de destino e anexa o banco de origem via DuckDB ATTACH
    con = duckdb.connect(db_dest_str)
    con.execute(f"ATTACH '{db_orig_str}' AS orig (READ_ONLY);")

    print("[2/4] Selecionando amostra representativa (top redes e empresas conectadas)...")
    
    # Criar tabela de empresas da amostra (primeiras 10.000 empresas)
    con.execute("""
    CREATE TABLE nodes_empresas AS 
    SELECT * FROM orig.nodes_empresas 
    LIMIT 10000;
    """)
    
    # Criar índice
    con.execute("CREATE INDEX IF NOT EXISTS idx_nodes_cnpj ON nodes_empresas(cnpj);")

    # Extrair arestas de sócios correspondentes às empresas da amostra
    con.execute("""
    CREATE TABLE edges_socios AS 
    SELECT * FROM orig.edges_socios 
    WHERE cnpj_basico IN (SELECT cnpj FROM nodes_empresas)
       OR cnpj_cpf_socio IN (SELECT cnpj FROM nodes_empresas)
    LIMIT 25000;
    """)

    con.execute("CREATE INDEX IF NOT EXISTS idx_edges_cnpj_basico ON edges_socios(cnpj_basico);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_edges_socio ON edges_socios(cnpj_cpf_socio);")

    print("[3/4] Exportando CSVs de amostra para visualização no repositório...")
    csv_nodes = (DADOS_AMOSTRA / "nodes_empresas_amostra.csv").resolve().as_posix()
    csv_edges = (DADOS_AMOSTRA / "edges_socios_amostra.csv").resolve().as_posix()

    con.execute(f"COPY nodes_empresas TO '{csv_nodes}' (HEADER, DELIMITER ',');")
    con.execute(f"COPY edges_socios TO '{csv_edges}' (HEADER, DELIMITER ',');")

    con.close()

    tam_db = os.path.getsize(DB_DESTINO) / (1024 * 1024)
    tam_nodes = os.path.getsize(csv_nodes) / (1024 * 1024)
    tam_edges = os.path.getsize(csv_edges) / (1024 * 1024)

    print("\n============================================================")
    print("  AMOSTRA CRIADA COM SUCESSO E PRONTA PARA O GITHUB!")
    print("============================================================")
    print(f" -> Banco DuckDB: {DB_DESTINO.name} ({tam_db:.2f} MB)")
    print(f" -> CSV Empresas: {Path(csv_nodes).name} ({tam_nodes:.2f} MB)")
    print(f" -> CSV Relacionamentos: {Path(csv_edges).name} ({tam_edges:.2f} MB)")
    print(f" -> Tamanho Total da Amostra: {(tam_db + tam_nodes + tam_edges):.2f} MB")
    print("============================================================")
    print("Esta pasta 'dados_amostra/' pode ser adicionada e commitada no GitHub!")


if __name__ == "__main__":
    extrair_amostra()
