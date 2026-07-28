"""NEXUS V2 — ETL de Sanções Oficiais (CEIS / CNEP — Portal da Transparência).

Ingere os CSVs de sanções que o usuário baixa do Portal da Transparência e
deposita em ``Dados Brutos/sancoes/`` e materializa
``dados_processados/sancoes.duckdb`` (tabela ``sancoes`` indexada por ``raiz`` e
``documento``, com a vigência da sanção pré-computada).

Por que uma base separada do ``nexus.duckdb``?
  * O ``nexus.duckdb`` (6,7 GB) é caro de reconstruir. As sanções mudam com
    frequência (atualização mensal/semestral) e são minúsculas em comparação —
    mantê-las à parte permite atualizar o sinal de risco sem reprocessar a base
    da Receita. O ``GraphDB`` faz ``ATTACH`` desta base se ela existir.

Aquisição dos dados (manual, uma vez):
  1. https://portaldatransparencia.gov.br/download-de-dados/ceis  → baixar o CSV
  2. https://portaldatransparencia.gov.br/download-de-dados/cnep  → baixar o CSV
  3. extrair os .csv para ``Dados Brutos/sancoes/`` (o nome do arquivo deve
     conter "ceis" ou "cnep" para identificar a fonte).

Uso:
    python scripts/etl_sancoes.py
"""
from __future__ import annotations

import csv
import sys
import unicodedata
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # permite importar o pacote `app`

from app.core.config import settings  # noqa: E402

# Campos da tabela final, na ordem de inserção.
_COLUNAS = (
    "documento", "raiz", "tipo_pessoa", "nome", "fonte",
    "tipo_sancao", "orgao", "processo", "data_inicio", "data_fim", "vigente",
)


def _norm_header(h: str) -> str:
    """Cabeçalho canônico: sem acento, maiúsculo, espaços colapsados."""
    s = unicodedata.normalize("NFKD", h or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.upper().split())


def _achar_coluna(headers: list[str], *chaves_por_prioridade: tuple[str, ...],
                  excluir: tuple[str, ...] = ()) -> int | None:
    """Localiza o índice da 1ª coluna cujo cabeçalho contém TODAS as palavras de
    algum dos grupos de chaves (testados em ordem de prioridade) e NENHUMA das
    palavras de `excluir` (evita falsos positivos — ex.: a coluna de NOME contém
    o texto 'ÓRGÃO SANCIONADOR')."""
    norm = [_norm_header(h) for h in headers]
    for chaves in chaves_por_prioridade:
        for i, h in enumerate(norm):
            if all(k in h for k in chaves) and not any(x in h for x in excluir):
                return i
    return None


def _norm_doc(doc: str) -> str:
    """Documento sem pontuação física, preservando máscara de CPF (``***`` e ``**``)."""
    return "".join(c for c in (doc or "").upper() if c.isalnum() or c == "*")


def _parse_data(s: str) -> date | None:
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _abrir(path: Path):
    """Abre o CSV detectando encoding (utf-8-sig → latin-1) e delimitador (; , \\t)."""
    for enc in ("utf-8-sig", "latin-1"):
        try:
            with path.open("r", encoding=enc, newline="") as fh:
                amostra = fh.read(8192)
            delim = ";"
            try:
                delim = csv.Sniffer().sniff(amostra, delimiters=";,\t").delimiter
            except csv.Error:
                pass
            return path.open("r", encoding=enc, newline=""), delim
        except UnicodeDecodeError:
            continue
    # Último recurso: latin-1 tolera qualquer byte.
    return path.open("r", encoding="latin-1", newline=""), ";"


def _fonte_de(path: Path) -> str:
    nome = path.name.lower()
    if "cnep" in nome:
        return "CNEP"
    if "ceis" in nome:
        return "CEIS"
    if "escravo" in nome or "suja" in nome or "trabalho" in nome:
        return "TRABALHO_ESCRAVO"
    return "SANÇÃO"  # genérico, se o nome não identificar


def _ler_arquivo(path: Path, hoje: date) -> list[tuple]:
    fonte = _fonte_de(path)
    fh, delim = _abrir(path)
    linhas: list[tuple] = []
    with fh:
        leitor = csv.reader(fh, delimiter=delim)
        try:
            headers = next(leitor)
        except StopIteration:
            return linhas

        i_doc = _achar_coluna(headers, ("CPF", "CNPJ"), ("CNPJ",), ("CPF",))
        i_tipo_pessoa = _achar_coluna(headers, ("TIPO", "PESSOA",))
        i_nome = _achar_coluna(headers, ("NOME", "SANCIONAD"), ("RAZAO", "SOCIAL"),
                               ("NOME", "INFORMADO"), ("NOME",))
        i_sancao = _achar_coluna(headers, ("CATEGORIA", "SANCAO"), ("TIPO", "SANCAO"),
                                 ("SANCAO",))
        i_orgao = _achar_coluna(headers, ("ORGAO", "SANCIONADOR"), ("ORGAO",),
                                excluir=("NOME",))
        i_proc = _achar_coluna(headers, ("NUMERO", "PROCESSO"), ("PROCESSO",))
        i_ini = _achar_coluna(headers, ("DATA", "INICIO", "SANCAO"), ("DATA", "INICIO"))
        i_fim = _achar_coluna(headers, ("DATA", "FINAL", "SANCAO"), ("DATA", "FIM"),
                              ("DATA", "FINAL"))

        if i_doc is None:
            print(f"  ! {path.name}: coluna de CPF/CNPJ não localizada — pulando.")
            return linhas

        def cel(row: list[str], idx: int | None) -> str:
            return row[idx].strip() if idx is not None and idx < len(row) else ""

        for row in leitor:
            if not row:
                continue
            doc = _norm_doc(cel(row, i_doc))
            if not doc:
                continue
            tp_raw = _norm_header(cel(row, i_tipo_pessoa))
            if "J" in tp_raw and "F" not in tp_raw:
                tipo = "PJ"
            elif "F" in tp_raw:
                tipo = "PF"
            else:  # inferência pelo formato do documento
                tipo = "PJ" if (len(doc) == 14 and "*" not in doc) else "PF"
            raiz = doc[:8] if (tipo == "PJ" and len(doc) >= 8 and "*" not in doc[:8]) else None
            d_ini = _parse_data(cel(row, i_ini))
            d_fim = _parse_data(cel(row, i_fim))
            vigente = (d_ini is None or d_ini <= hoje) and (d_fim is None or d_fim >= hoje)
            tipo_sancao = cel(row, i_sancao) or None
            if fonte == "TRABALHO_ESCRAVO":
                # A "Lista Suja" publicada contém apenas os empregadores vigentes
                # (janela de 2 anos) — todas as linhas contam como vigentes.
                vigente = True
                tipo_sancao = tipo_sancao or "Trabalho análogo à escravidão (Lista Suja)"
            linhas.append((
                doc, raiz, tipo, cel(row, i_nome) or None, fonte,
                tipo_sancao, cel(row, i_orgao) or None,
                cel(row, i_proc) or None, d_ini, d_fim, vigente,
            ))
    print(f"  -> {path.name}: {len(linhas):,} sanções ({fonte})")
    return linhas


def main() -> int:
    src = settings.sancoes_brutos
    if not src.exists():
        print(f"ERRO: pasta de sanções não encontrada: {src}", file=sys.stderr)
        print("Crie a pasta e deposite os CSVs do CEIS/CNEP "
              "(https://portaldatransparencia.gov.br/download-de-dados).", file=sys.stderr)
        return 1

    # rglob: aceita os CSVs soltos na pasta OU dentro das subpastas que o ZIP do
    # Portal cria ao ser extraído (ex.: sancoes/20260612_CEIS/20260612_CEIS.csv).
    arquivos = sorted(p for p in src.rglob("*.csv"))
    if not arquivos:
        print(f"ERRO: nenhum .csv em {src}", file=sys.stderr)
        return 1

    hoje = date.today()
    print(f"NEXUS V2 — ETL de Sanções | {len(arquivos)} arquivo(s) | hoje={hoje}")
    todas: list[tuple] = []
    for p in arquivos:
        todas.extend(_ler_arquivo(p, hoje))

    if not todas:
        print("ERRO: nenhuma sanção lida (verifique o layout dos arquivos).", file=sys.stderr)
        return 1

    import duckdb

    settings.dados_processados.mkdir(parents=True, exist_ok=True)
    db_path = settings.sancoes_db
    if db_path.exists():
        db_path.unlink()
    con = duckdb.connect(str(db_path))
    con.execute(
        "CREATE TABLE sancoes ("
        "documento VARCHAR, raiz VARCHAR, tipo_pessoa VARCHAR, nome VARCHAR, "
        "fonte VARCHAR, tipo_sancao VARCHAR, orgao VARCHAR, processo VARCHAR, "
        "data_inicio DATE, data_fim DATE, vigente BOOLEAN)"
    )
    con.executemany(
        f"INSERT INTO sancoes ({', '.join(_COLUNAS)}) "
        f"VALUES ({', '.join(['?'] * len(_COLUNAS))})",
        todas,
    )
    con.execute("CREATE INDEX idx_sanc_raiz ON sancoes(raiz)")
    con.execute("CREATE INDEX idx_sanc_doc ON sancoes(documento)")
    total = con.execute("SELECT COUNT(*) FROM sancoes").fetchone()[0]
    vig = con.execute("SELECT COUNT(*) FROM sancoes WHERE vigente").fetchone()[0]
    con.close()
    print(f"OK - sancoes.duckdb: {total:,} sancoes ({vig:,} vigentes) -> {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
