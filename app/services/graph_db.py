"""Engine analítica DuckDB — grafos relacionais societários de 2º grau.

Abandona a consulta simples de 1º grau e executa uma varredura bidirecional de
2º grau via Expressão de Tabela Comum (CTE): a partir da empresa-alvo, encontra
seus sócios e, através deles, todas as empresas-satélite associadas — desvelando
holdings e grupos econômicos ocultos.
"""
from __future__ import annotations

from typing import Any

import duckdb

from app.core.config import settings
from app.core.validators import raiz_cnpj

# Limite de satélites para proteger contra sócios "hub" (ex.: grandes holdings).
_LIMITE_VINCULOS = 800

# CTE homologada (2º grau): vínculos dos sócios da empresa-alvo.
# Otimização: a decoração com a razão social/situação das empresas-satélite é
# feita em uma 2ª etapa por *point-lookup* indexado (evita um hash-join sobre os
# ~19M nós a cada consulta — reduz a latência de segundos para milissegundos).
_SQL_GRAFO = """
WITH socios_da_empresa_alvo AS (
    SELECT DISTINCT cnpj_cpf_socio
    FROM edges_socios
    WHERE cnpj_basico = ?
)
SELECT
    e.cnpj_cpf_socio,
    e.nome_socio_razao_social,
    e.qualificacao_do_socio,
    e.identificador_de_socio,
    e.cnpj_basico
FROM edges_socios e
WHERE e.cnpj_cpf_socio IN (SELECT cnpj_cpf_socio FROM socios_da_empresa_alvo)
-- ORDER BY determinístico: garante que o truncamento (LIMIT) selecione sempre o
-- mesmo subconjunto → score 100% reproduzível, inclusive sob execução paralela.
ORDER BY e.cnpj_cpf_socio, e.cnpj_basico
LIMIT ?
"""

_SQL_EMPRESA = "SELECT * FROM nodes_empresas WHERE cnpj = ? LIMIT 1"


class GraphDB:
    """Acesso somente-leitura ao `nexus.duckdb`, com cursores por consulta."""

    def __init__(self) -> None:
        if not settings.duckdb_path.exists():
            raise FileNotFoundError(
                f"Base não encontrada: {settings.duckdb_path}. "
                "Rode o ETL (Fase 0): python scripts/etl_nexus.py"
            )
        # Conexão única read-only; cada consulta usa um cursor independente.
        self._con = duckdb.connect(str(settings.duckdb_path), read_only=True)

    # -- amostragem aleatória --------------------------------------------
    def cnpjs_aleatorios(self, n: int = 5) -> list[str]:
        """Sorteia N raízes reais (empresas que possuem rede societária)."""
        cur = self._con.cursor()
        # amostra um excedente e deduplica (reservoir sample rápido sobre 24M arestas)
        cur.execute(f"SELECT cnpj_basico FROM edges_socios USING SAMPLE {int(n) * 4} ROWS")
        vistos: list[str] = []
        for (c,) in cur.fetchall():
            if c and c not in vistos:
                vistos.append(c)
        return vistos[:n]

    # -- consultas brutas -------------------------------------------------
    def empresa_principal(self, raiz: str) -> dict[str, Any] | None:
        cur = self._con.cursor()
        row = cur.execute(_SQL_EMPRESA, [raiz]).fetchone()
        if row is None:
            return None
        cols = [c[0] for c in cur.description]
        return dict(zip(cols, row))

    def _decorar_empresas(self, cnpjs: list[str]) -> dict[str, dict[str, Any]]:
        """Busca razão social/situação de um conjunto de CNPJs (point-lookup indexado)."""
        if not cnpjs:
            return {}
        placeholders = ",".join(["?"] * len(cnpjs))
        cur = self._con.cursor()
        cur.execute(
            f"SELECT cnpj, razao_social, situacao_cadastral, cnae_codigo, "
            f"situacao_especial, ald_secundario "
            f"FROM nodes_empresas WHERE cnpj IN ({placeholders})",
            cnpjs,
        )
        return {r[0]: {"razao_social_empresa": r[1], "situacao_cadastral": r[2],
                       "cnae_codigo": r[3], "situacao_especial": r[4],
                       "ald_secundario": r[5]}
                for r in cur.fetchall()}

    def vinculos_2grau(self, raiz: str, limite: int = _LIMITE_VINCULOS) -> list[dict[str, Any]]:
        cur = self._con.cursor()
        cur.execute(_SQL_GRAFO, [raiz, limite])
        cols = [c[0] for c in cur.description]
        vinculos = [dict(zip(cols, r)) for r in cur.fetchall()]

        # 2ª etapa: decora as empresas-satélite distintas via lookup indexado.
        cnpjs = sorted({v["cnpj_basico"] for v in vinculos if v["cnpj_basico"]})
        info = self._decorar_empresas(cnpjs)
        for v in vinculos:
            dados = info.get(v["cnpj_basico"], {})
            v["razao_social_empresa"] = dados.get("razao_social_empresa")
            v["situacao_cadastral"] = dados.get("situacao_cadastral")
            v["cnae_codigo"] = dados.get("cnae_codigo")
            v["situacao_especial"] = dados.get("situacao_especial")
            v["ald_secundario"] = dados.get("ald_secundario")
        return vinculos

    # -- contrato de dados homologado ------------------------------------
    def consultar(self, cnpj: str, limite: int = _LIMITE_VINCULOS) -> dict[str, Any]:
        """Monta o contrato GET /api/v1/empresa/{cnpj}: empresa_principal + grafo.

        Retorna também `_vinculos` (linhas brutas) para consumo do motor de risco.
        """
        raiz = raiz_cnpj(cnpj)
        empresa = self.empresa_principal(raiz)
        vinculos = self.vinculos_2grau(raiz, limite)

        principal = {
            "cnpj": raiz,
            "razao_social": (empresa or {}).get("razao_social"),
            "situacao": (empresa or {}).get("situacao_cadastral"),
        }

        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        vistos: set[str] = set()

        # Nó alvo (Ciano Elétrico no frontend)
        nodes.append({
            "id": raiz,
            "label": principal["razao_social"] or raiz,
            "group": "Alvo",
        })
        vistos.add(raiz)

        for v in vinculos:
            doc_socio = v["cnpj_cpf_socio"]
            cnpj_rel = v["cnpj_basico"]
            grupo_socio = "SocioPJ" if v["identificador_de_socio"] == "PJ" else "SocioPF"

            # nó do sócio (conector)
            if doc_socio not in vistos:
                nodes.append({
                    "id": doc_socio,
                    "label": v["nome_socio_razao_social"] or doc_socio,
                    "group": grupo_socio,
                })
                vistos.add(doc_socio)

            if cnpj_rel == raiz:
                # vínculo direto: sócio -> empresa-alvo
                edges.append({"from": doc_socio, "to": raiz, "label": "Sócio Direto"})
            else:
                # empresa-satélite (Grafite Escuro)
                if cnpj_rel not in vistos:
                    nodes.append({
                        "id": cnpj_rel,
                        "label": v["razao_social_empresa"] or cnpj_rel,
                        "group": "EmpresaRelacionada",
                    })
                    vistos.add(cnpj_rel)
                edges.append({
                    "from": doc_socio, "to": cnpj_rel, "label": "Participação Externa",
                })

        return {
            "empresa_principal": principal,
            "grafo": {"nodes": nodes, "edges": edges},
            "_vinculos": vinculos,
            "_empresa_raw": empresa,
        }

    def close(self) -> None:
        self._con.close()


# Singleton lazy — inicializado no startup da API.
_graph_db: GraphDB | None = None


def get_graph_db() -> GraphDB:
    global _graph_db
    if _graph_db is None:
        _graph_db = GraphDB()
    return _graph_db
