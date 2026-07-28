"""Engine analítica DuckDB — grafos relacionais societários de 2º grau.

Abandona a consulta simples de 1º grau e executa uma varredura bidirecional de
2º grau via Expressão de Tabela Comum (CTE): a partir da empresa-alvo, encontra
seus sócios e, através deles, todas as empresas-satélite associadas — desvelando
holdings e grupos econômicos ocultos.
"""
from __future__ import annotations

import unicodedata
from datetime import date, timedelta
from typing import Any

import duckdb

from app.core.config import settings
from app.core.validators import raiz_cnpj

# Palavras a ignorar no casamento de nome de sócio PF (CPF é mascarado na base).
_STOP_NOME = {"DA", "DE", "DO", "DAS", "DOS", "E"}


def _tokens_nome(nome: Any) -> set[str]:
    """Tokens significativos de um nome (sem acento, maiúsculo, >=3 letras)."""
    s = unicodedata.normalize("NFKD", str(nome or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).upper()
    return {t for t in s.replace(".", " ").split() if len(t) >= 3 and t not in _STOP_NOME}


def _nome_casa(a: Any, b: Any) -> bool:
    """Heurística de mesma pessoa: >=2 tokens significativos em comum."""
    ta, tb = _tokens_nome(a), _tokens_nome(b)
    return len(ta & tb) >= 2

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
        # Ajuste opcional de recursos (só se configurado no .env). Vazio = default
        # do DuckDB, que é o adequado para um processo único.
        try:
            if settings.duckdb_memory_limit:
                self._con.execute(f"PRAGMA memory_limit='{settings.duckdb_memory_limit}'")
            if settings.duckdb_threads:
                self._con.execute(f"PRAGMA threads={settings.duckdb_threads}")
        except duckdb.Error:
            pass

        # Camada de sanções (CEIS/CNEP) — opcional e desacoplada (fail-soft):
        # se a base existir, é anexada; senão o score simplesmente ignora a camada.
        self.has_sancoes = self._anexar(settings.sancoes_db, "sanc", "sancoes")

        # Camada de endereços (cruzamento / "ninho de fachada") — também opcional.
        self.has_enderecos = self._anexar(settings.enderecos_db, "endr", "empresa_endereco")

        # Camada de Dívida Ativa da União (PGFN) — eixo financeiro, opcional.
        self.has_dividas = self._anexar(settings.dividas_db, "div", "dividas")

    def _anexar(self, caminho, alias: str, tabela_probe: str) -> bool:
        """ATTACH read-only de uma base opcional (sanções/endereços), sondando uma
        tabela para rejeitar arquivos parciais/corrompidos. Retorna True só se a
        base estiver utilizável — caso contrário a camada fica desligada."""
        if not caminho.exists():
            return False
        try:
            self._con.execute(f"ATTACH '{caminho.as_posix()}' AS {alias} (READ_ONLY)")
            self._con.execute(f"SELECT 1 FROM {alias}.{tabela_probe} LIMIT 1")
            return True
        except duckdb.Error:
            try:
                self._con.execute(f"DETACH {alias}")
            except duckdb.Error:
                pass
            return False

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

    # -- camada de sanções (CEIS/CNEP) -----------------------------------
    def _buscar_sancoes(
        self, raizes: set[str], docs_pf: set[str]
    ) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
        """Sanções VIGENTES por raiz (PJ, match exato) e por documento (PF, CPF mascarado)."""
        by_raiz: dict[str, list[dict[str, Any]]] = {}
        by_doc: dict[str, list[dict[str, Any]]] = {}
        if not self.has_sancoes:
            return by_raiz, by_doc
        cur = self._con.cursor()
        cols = "fonte, tipo_sancao, orgao, processo, nome, CAST(data_fim AS VARCHAR)"

        rs = sorted({r for r in raizes if r})
        if rs:
            ph = ",".join(["?"] * len(rs))
            cur.execute(
                f"SELECT raiz, {cols} FROM sanc.sancoes "
                f"WHERE vigente AND raiz IN ({ph})", rs)
            for raiz, fonte, tipo, orgao, proc, nome, dfim in cur.fetchall():
                by_raiz.setdefault(raiz, []).append({
                    "fonte": fonte, "tipo_sancao": tipo, "orgao": orgao,
                    "processo": proc, "nome": nome, "data_fim": dfim})

        ds = sorted({d for d in docs_pf if d})
        if ds:
            ph = ",".join(["?"] * len(ds))
            cur.execute(
                f"SELECT documento, {cols} FROM sanc.sancoes "
                f"WHERE vigente AND tipo_pessoa = 'PF' AND documento IN ({ph})", ds)
            for doc, fonte, tipo, orgao, proc, nome, dfim in cur.fetchall():
                by_doc.setdefault(doc, []).append({
                    "fonte": fonte, "tipo_sancao": tipo, "orgao": orgao,
                    "processo": proc, "nome": nome, "data_fim": dfim})
        return by_raiz, by_doc

    # -- camada de endereços (cruzamento) --------------------------------
    def _buscar_enderecos(self, raizes: set[str]) -> dict[str, dict[str, Any]]:
        """Endereço normalizado (key + texto) de cada raiz informada."""
        out: dict[str, dict[str, Any]] = {}
        if not self.has_enderecos:
            return out
        rs = sorted({r for r in raizes if r})
        if not rs:
            return out
        cur = self._con.cursor()
        ph = ",".join(["?"] * len(rs))
        cur.execute(
            f"SELECT raiz, endereco_key, endereco_fmt, situacao, inicio_atividade "
            f"FROM endr.empresa_endereco WHERE raiz IN ({ph})", rs)
        for raiz, key, fmt, sit, inicio in cur.fetchall():
            out[raiz] = {"endereco_key": key, "endereco_fmt": fmt,
                         "situacao": sit, "inicio": inicio}
        return out

    def _stats_endereco(self, endereco_key: str | None) -> dict[str, int]:
        """Quantas empresas (ativas / inaptas / baixadas) há no endereço."""
        vazio = {"total": 0, "ativas": 0, "inaptas": 0, "baixadas": 0}
        if not self.has_enderecos or not endereco_key:
            return vazio
        cur = self._con.cursor()
        row = cur.execute(
            "SELECT total, ativas, inaptas, baixadas FROM endr.endereco_stats "
            "WHERE endereco_key = ?", [endereco_key]).fetchone()
        if not row:
            return vazio
        return {"total": int(row[0]), "ativas": int(row[1]),
                "inaptas": int(row[2]), "baixadas": int(row[3])}

    # -- camada de dívida ativa (PGFN) -----------------------------------
    def _buscar_dividas(self, raizes: set[str]) -> dict[str, dict[str, Any]]:
        """Dívida ativa na União por raiz (valor consolidado, nº inscrições, ajuizadas)."""
        out: dict[str, dict[str, Any]] = {}
        if not self.has_dividas:
            return out
        rs = sorted({r for r in raizes if r})
        if not rs:
            return out
        cur = self._con.cursor()
        ph = ",".join(["?"] * len(rs))
        cur.execute(
            f"SELECT raiz, inscricoes, valor, ajuizadas FROM div.dividas "
            f"WHERE raiz IN ({ph})", rs)
        for raiz, insc, valor, aju in cur.fetchall():
            out[raiz] = {"inscricoes": int(insc or 0), "valor": float(valor or 0),
                         "ajuizadas": int(aju or 0)}
        return out

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

        # --- Camada de sanções (CEIS/CNEP): coleta as chaves e decora a teia ---
        raizes_consulta: set[str] = {raiz}
        docs_pf: set[str] = set()
        for v in vinculos:
            if v["cnpj_basico"]:
                raizes_consulta.add(v["cnpj_basico"])
            doc = v["cnpj_cpf_socio"]
            if v["identificador_de_socio"] == "PJ" and doc and "*" not in doc[:8]:
                raizes_consulta.add(doc[:8])  # sócio PJ → casa por raiz
            elif doc:
                docs_pf.add(doc)               # sócio PF → CPF mascarado
        by_raiz, by_doc = self._buscar_sancoes(raizes_consulta, docs_pf)

        # --- Camada de endereços (cruzamento / "ninho de fachada") ---
        enderecos = self._buscar_enderecos(raizes_consulta)
        alvo_key = (enderecos.get(raiz) or {}).get("endereco_key")
        alvo_fmt = (enderecos.get(raiz) or {}).get("endereco_fmt")
        end_stats = self._stats_endereco(alvo_key)
        # Empresas da própria teia (mesmos sócios) registradas no MESMO endereço do
        # alvo, classificadas por estado — pois INAPTA, BAIXADA e "ativa recém-aberta"
        # contam de formas diferentes no score.
        co_endereco: set[str] = set()
        co_inaptas = co_baixadas = co_ativas_recentes = 0
        if alvo_key:
            corte_recente = date.today() - timedelta(days=730)  # "recém-aberta": ≤ 2 anos
            rede_raizes: set[str] = set()
            for v in vinculos:
                rel = v["cnpj_basico"]
                if rel and rel != raiz:
                    rede_raizes.add(rel)
                d = v["cnpj_cpf_socio"]
                if v["identificador_de_socio"] == "PJ" and d and "*" not in d[:8] and d[:8] != raiz:
                    rede_raizes.add(d[:8])
            for r2 in rede_raizes:
                info = enderecos.get(r2)
                if not info or info.get("endereco_key") != alvo_key:
                    continue
                co_endereco.add(r2)
                sit = info.get("situacao")
                if sit == 4:
                    co_inaptas += 1
                elif sit == 8:
                    co_baixadas += 1
                elif sit == 2:
                    ini = info.get("inicio")
                    if ini and ini >= corte_recente:
                        co_ativas_recentes += 1

        # --- Dívida Ativa da União (PGFN): eixo financeiro ---
        dividas = self._buscar_dividas(raizes_consulta)
        dividas_rede = sum(1 for r in raizes_consulta if r != raiz and dividas.get(r))
        empresa_inicio = (enderecos.get(raiz) or {}).get("inicio")

        # Sócio PF: só conta a sanção se o nome também casa (CPF mascarado é ambíguo).
        def sancoes_do_socio(v: dict[str, Any]) -> list[dict[str, Any]]:
            doc = v["cnpj_cpf_socio"]
            if v["identificador_de_socio"] == "PJ" and doc and "*" not in doc[:8]:
                return by_raiz.get(doc[:8], [])
            return [s for s in by_doc.get(doc, [])
                    if _nome_casa(v["nome_socio_razao_social"], s.get("nome"))]

        principal["sancionada"] = bool(by_raiz.get(raiz))

        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        vistos: set[str] = set()

        # Nó alvo (Ciano Elétrico no frontend)
        nodes.append({
            "id": raiz,
            "label": principal["razao_social"] or raiz,
            "group": "Alvo",
            "sancionado": bool(by_raiz.get(raiz)),
        })
        vistos.add(raiz)

        for v in vinculos:
            doc_socio = v["cnpj_cpf_socio"]
            cnpj_rel = v["cnpj_basico"]
            grupo_socio = "SocioPJ" if v["identificador_de_socio"] == "PJ" else "SocioPF"

            # decora o vínculo com as sanções vigentes (consumido pelo risk_score)
            sanc_socio = sancoes_do_socio(v)
            sanc_satelite = by_raiz.get(cnpj_rel, []) if cnpj_rel != raiz else []
            v["sancoes_socio"] = sanc_socio
            v["sancoes_satelite"] = sanc_satelite

            # nó do sócio (conector)
            if doc_socio not in vistos:
                eh_pj = grupo_socio == "SocioPJ"
                socio_co = eh_pj and doc_socio[:8] in co_endereco
                nodes.append({
                    "id": doc_socio,
                    "label": v["nome_socio_razao_social"] or doc_socio,
                    "group": grupo_socio,
                    "sancionado": bool(sanc_socio),
                    "mesmo_endereco": socio_co,
                    "divida": eh_pj and doc_socio[:8] in dividas,
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
                        "sancionado": bool(sanc_satelite),
                        "mesmo_endereco": cnpj_rel in co_endereco,
                        "divida": cnpj_rel in dividas,
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
            "_sancoes_alvo": by_raiz.get(raiz, []),
            "_dividas_alvo": dividas.get(raiz),
            "_dividas_rede": dividas_rede,
            "_empresa_inicio": empresa_inicio,
            "_endereco": {
                "endereco_alvo": alvo_fmt,
                "total": end_stats["total"],
                "ativas": end_stats["ativas"],
                "inaptas": end_stats["inaptas"],
                "baixadas": end_stats["baixadas"],
                "rede_mesmo_endereco": len(co_endereco),
                "rede_inaptas": co_inaptas,
                "rede_baixadas": co_baixadas,
                "rede_ativas_recentes": co_ativas_recentes,
            },
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
