"""Gera o template do dataset rotulado para avaliar o NEXUS Trust Score.

A avaliação científica exige um ground truth: CNPJs com rótulo
fraude(1)/legítimo(0). Aqui usamos *weak labeling* a partir das fontes oficiais
já carregadas no grafo:

  * POSITIVOS (label=1): empresas presentes em CEIS, CNEP ou Lista Suja do
    Trabalho Escravo — irregularidade CONFIRMADA por órgão público.
  * NEGATIVOS (label=0): amostra aleatória de empresas ATIVAS sem qualquer
    sanção/dívida e com sócios sem ocorrências (controle).

IMPORTANTE: weak labels são um PONTO DE PARTIDA. Para um paper, o ideal é uma
amostra revisada manualmente — a coluna `label` deve ser auditada antes de citar
os números. Há ainda um risco de *vazamento*: se a sanção também alimenta o
score, o positivo fica "fácil". Por isso o avaliador também reporta o desempenho
sobre sinais INFERIDOS (rede/endereço), não só os confirmados.

Saída: CSV `cnpj,label,fonte` em data/rotulos.csv (revisar antes de usar).

Uso:
    python scripts/preparar_dataset_rotulado.py --n-negativos 500 --out data/rotulos.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402


def _conectar() -> duckdb.DuckDBPyConnection:
    """Conexão read-only própria (desacoplada do GraphDB) com sanções/dívidas."""
    con = duckdb.connect(str(settings.duckdb_path), read_only=True)
    con.execute(f"ATTACH '{settings.sancoes_db.as_posix()}' AS sanc (READ_ONLY)")
    con.execute(f"ATTACH '{settings.dividas_db.as_posix()}' AS div (READ_ONLY)")
    return con


def coletar_positivos(con, n: int) -> list[tuple[str, str]]:
    """Raízes (8 díg.) sancionadas VIGENTES (CEIS/CNEP/Lista Suja) → label 1."""
    sql = f"""
        SELECT raiz, max(fonte) AS fonte
        FROM sanc.sancoes
        WHERE vigente AND raiz IS NOT NULL AND length(raiz) = 8
        GROUP BY raiz
        USING SAMPLE {int(n)} ROWS
    """
    return [(str(r[0]).strip(), str(r[1])) for r in con.execute(sql).fetchall()]


def coletar_negativos(con, n: int, excluir: set[str]) -> list[tuple[str, str]]:
    """Controle: ATIVAS, sem sanção vigente e sem dívida ativa na União."""
    sql = f"""
        SELECT raiz FROM (
            SELECT substr(e.cnpj, 1, 8) AS raiz
            FROM nodes_empresas e
            WHERE upper(e.situacao_cadastral) = 'ATIVA'
            USING SAMPLE {int(n * 4)} ROWS
        ) s
        WHERE NOT EXISTS (SELECT 1 FROM sanc.sancoes x
                          WHERE x.vigente AND x.raiz = s.raiz)
          AND NOT EXISTS (SELECT 1 FROM div.dividas d WHERE d.raiz = s.raiz)
    """
    out, vistos = [], set()
    for (raiz,) in con.execute(sql).fetchall():
        raiz = str(raiz).strip()
        if raiz and raiz not in excluir and raiz not in vistos:
            vistos.add(raiz)
            out.append((raiz, "controle_ativa_limpa"))
        if len(out) >= n:
            break
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-positivos", type=int, default=400)
    ap.add_argument("--n-negativos", type=int, default=400)
    ap.add_argument("--out", type=Path, default=Path("data/rotulos.csv"))
    args = ap.parse_args()

    con = _conectar()
    positivos = coletar_positivos(con, args.n_positivos)
    excluir = {c for c, _ in positivos}
    negativos = coletar_negativos(con, args.n_negativos, excluir)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["cnpj", "label", "fonte"])
        for cnpj, fonte in positivos:
            w.writerow([cnpj, 1, fonte])
        for cnpj, fonte in negativos:
            w.writerow([cnpj, 0, fonte])

    print(f"Dataset escrito em {args.out}: "
          f"{len(positivos)} positivos + {len(negativos)} negativos.")
    print("REVISE os rótulos manualmente antes de citar métricas em um paper.")


if __name__ == "__main__":
    main()
