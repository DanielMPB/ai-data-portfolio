# NEXUS V2 — Relatório de Testes e Avaliação Experimental

Documento de apoio ao artigo. Reúne resultados da suíte de testes automatizados,
benchmarks de desempenho (com expectativa × realidade), métricas de escala e as
decisões de engenharia mais relevantes.

---

## 1. Ambiente experimental

| Item | Valor |
|---|---|
| Sistema operacional | Windows |
| Linguagem | Python 3.14.5 |
| Núcleos lógicos | 24 |
| Framework de testes | pytest 9.0.3 |
| Engine de dados | DuckDB ≥1.0, Polars ≥1.0 |
| Grafos | NetworkX 3.6 |
| API | FastAPI / Uvicorn |
| LLM | OpenAI `gpt-4o-mini` (provedor ativo); fallback `gpt-4o`; suporte a Gemma via Ollama/Google |
| Base de dados | Receita Federal (CNPJ) — **4,68 GB** de Parquet bruto |
| Base processada | **59.616.977** empresas (nós) · **24.670.519** vínculos societários (arestas) |

**Tamanho dos artefatos:** `nexus.duckdb` 6,72 GB · `nodes_empresas.csv` 12,05 GB ·
`edges_socios.csv` 1,66 GB.
**Base de código:** `app/` 1.524 linhas · `scripts/` 429 · `tests/` 593 (≈ 2.546 LOC).

---

## 2. Suíte de testes automatizados

**Resultado global:** `56 coletados · 55 aprovados · 1 ignorado (skip) · 0 falhas`
em **43,34 s** (execução completa, incluindo testes que abrem a base DuckDB de 60M
de registros e testes de paralelismo real).

O único teste *skipped* (`test_obter_acao_rede_real`) é um teste de rede real
(yfinance), desativado por padrão para não depender de conectividade externa na CI.

### 2.1. Cobertura por módulo

| Módulo de teste | Testes | O que valida (expectativa) | Resultado |
|---|---:|---|---|
| `test_validators.py` | 7 | CNPJ alfanumérico — Módulo 11 estendido (padrão Julho/2026) | ✅ 7/7 |
| `test_phase1_endpoint.py` | 6 | Contrato do grafo de 2º grau, validação de entrada (422/404), endpoint de amostra | ✅ 6/6 |
| `test_risk_score.py` | 20 | Score determinístico — todas as camadas A/B, contágio, ALD, situação especial | ✅ 20/20 |
| `test_graph_mining.py` | 5 | Centralidade, grupo econômico (componentes conexos), pontos de articulação | ✅ 5/5 |
| `test_parallel.py` | 3 | Paridade determinística sequencial × paralelo, uso de múltiplas threads | ✅ 3/3 |
| `test_ir_agent.py` | 8 | Calculadora de RI: parsing de rating, limpeza de raciocínio, contrato, 503/422 | ✅ 8/8 |
| `test_market_data.py` | 7 | Terminal B3: normalização de ticker, parsing de veredito, contratos (1 skip de rede) | ✅ 6/6 (+1 skip) |
| **Total** | **56** | | **55 ✅ · 1 skip** |

### 2.2. Testes mais custosos (tempo de execução)

| Tempo | Teste | Natureza |
|---:|---|---|
| 12,58 s | `test_paralelo_paridade_com_sequencial` | Paralelismo real sobre a base de 60M |
| 10,62 s | `test_sequencial_avalia_todos` | Linha de base sequencial |
| 6,99 s | `test_paralelo_usa_multiplas_threads` | Verifica execução multi-thread |
| 2,36 s | `test_contrato_grafo` | Consulta de grafo end-to-end na base real |
| 2,09 s | `test_endpoint_stock_ok` | Endpoint de cotação (mock yfinance) |
| 1,50 s | `test_amostra_rede` | Grafo combinado de amostra |
| < 0,1 s | (demais 49 testes) | Lógica pura / contratos mockados |

Observa-se a separação clara entre **testes de lógica pura** (determinísticos,
sub-milissegundo, ex.: validador e score) e **testes de integração** que exercitam a
base DuckDB real ou o paralelismo (segundos).

---

## 3. Expectativa × Realidade (validações-chave)

| Validação | Expectativa | Realidade medida |
|---|---|---|
| **Validador CNPJ alfanumérico** | DV correto para o exemplo oficial RFB `12.ABC.345/01DE-35` | DV calculado = `35` ✅ (e numérico `11.222.333/0001-81` → `81` ✅) |
| **Reprodutibilidade do score** | Mesmo CNPJ → mesmo score, inclusive sob paralelismo | Paridade exata sequencial × paralelo ✅ (após `ORDER BY` determinístico no truncamento) |
| **Diluição por diversificação** | Empresa com muitos sócios diretos e 1 "maçã podre" → impacto ~0 | 10 sócios, 1 com 1 empresa baixada → score **100** ✅ |
| **Fraude concentrada** | Rede pequena 100% inapta → score baixo | 2 sócios, todas satélites inaptas → **Risco Moderado** ✅ |
| **Falso positivo ALD** | "Aluguel de jóias" / "obras de arte" (engenharia) **não** são ALD | Lista curada por código → 49.674 empresas (0,083%) vs 98.918 (0,166%) por texto ❌→✅ |
| **Boolean via `all_varchar`** | String `"false"` **não** deve disparar contágio | Regressão coberta (`_truthy`): `"false"`→0, `"true"`→−20 ✅ |

---

## 4. Benchmarks de desempenho

### 4.1. Pipeline ETL (Fase 0)

| Cenário | Expectativa | Realidade |
|---|---|---|
| Polars `sink_csv` streaming (4,68 GB) | Processar sem estouro de memória | **Falhou (segfault, exit 139)** no join global de ~30M+ linhas |
| **Motor DuckDB out-of-core** (correção) | Processar 4,68 GB com spill em disco | **OK**: CSVs em **29,8 s**; pipeline completo (+ DuckDB indexado/ordenado) em **~364 s** (~6 min) |

**Resultado:** 59,6M nós + 24,7M arestas materializados a partir de 4,68 GB de
Parquet bruto, com qualidade 100% (situação cadastral, CNAE, natureza jurídica
todas decodificadas; CNPJ sempre 8 caracteres com zeros à esquerda preservados).

### 4.2. Otimização de latência de consulta

| Estado | Expectativa | Realidade |
|---|---|---|
| Tabela não ordenada (full scan) | Lookup rápido por índice ART | **~1,8 s** por consulta (DuckDB ignora ART, faz full scan de 24M) |
| **Tabela ordenada por chave** (zonemap pruning) | Ler só o bloco relevante | Lookup **~2 ms** (warm); `consultar()` end-to-end **~0,08–0,4 s** |
| Impacto agregado (60 CNPJs hubs) | — | Sequencial **176 s → 10,3 s** (~**17×**) só com a ordenação |

### 4.3. Computação paralela (`ThreadPoolExecutor` + DuckDB)

Três cenários medidos — o resultado **depende do peso da carga**, pois o DuckDB já
paraleliza internamente cada consulta entre os núcleos:

| Carga de trabalho | Sequencial | Paralelo | Speedup |
|---|---:|---:|---:|
| Amostra leve (6,5M arestas, queries cacheadas) | 10,3 s | 3,3 s (8 threads) | **3,09×** |
| **Carga típica** (80 empresas aleatórias, base 60M) | 23,6 s | 9,5 s (8 threads) | **2,47×** |
| Carga típica (4 threads) | 23,6 s | 9,8 s | 2,40× |
| Pior caso (60 mega-hubs, queries pesadas) | 84,6 s | 62,2 s (8 threads) | 1,36× |

**Interpretação (importante para o artigo):** o ganho do paralelismo a nível de
aplicação **satura** quando cada tarefa já é pesada o suficiente para o DuckDB
ocupar todos os núcleos sozinho (mega-hubs → 1,36×). Em cargas típicas/leves, onde
cada consulta não satura o engine, o ThreadPool entrega **2,4×–3,1×**. O platô entre
4 e 8 threads (2,40× → 2,47×) confirma a saturação de núcleos. A escolha de
**threads** (não processos) é justificada por: (i) o DuckDB libera o GIL na execução
nativa; (ii) tentativas com `ProcessPoolExecutor` resultaram em `BrokenProcessPool`
(instabilidade da lib nativa cruzando processos no Windows/Py 3.14).

### 4.4. Latência da IA (LLM) e de mercado

| Operação | Expectativa | Realidade |
|---|---|---|
| Relatório de RI (OpenAI `gpt-4o-mini`) | Resposta em segundos | **~15 s** (5 seções + rating A–D) |
| Relatório de RI (Gemma 4 31B, comparativo) | — | ~46 s (modelo com raciocínio; bloco `<thought>` removido) |
| Advisor de mercado (veredito + tese) | Segundos | ~26 s (Gemma) / mais rápido no OpenAI |
| Panorama de mercado (`/market/overview`) | Tempo real | **~1,4–2,9 s** (download em lote, 24 tickers); **~3 ms** cacheado (TTL 300 s) |
| Recomendação do dia (34 ações + LLM) | Dezenas de segundos | **~14,7 s**; cacheado (TTL 600 s) |

Resiliência: o cliente LLM faz **retry com backoff** em erros transitórios (503/429)
e **fallback automático de modelo** — validado contra o "high demand" (503) do
provedor.

---

## 5. Pilares acadêmicos demonstrados

| Pilar | Evidência objetiva |
|---|---|
| **Grafos / Graph Mining** | Travessia de 2º grau via CTE no DuckDB + mineração com NetworkX (centralidade de grau, componentes conexos = grupo econômico, pontos de articulação). Ex. real: grupo de 801 nós, 119 empresas, 682 sócios, 106 pontos de articulação. |
| **Computação Paralela** | `ThreadPoolExecutor` sobre consultas DuckDB (GIL liberado) + benchmark reprodutível (`scripts/benchmark_paralelo.py`); speedup de 2,4–3,1× em carga típica; paralelismo de dados no ETL via `PRAGMA threads`. |
| **Computação em Nuvem** | API stateless e containerizável; base (DuckDB/CSVs) destinada a object storage; preparada para deploy atrás de load balancer (adiada para a etapa de implantação). |

---

## 6. Bugs encontrados e corrigidos (engenharia rigorosa)

1. **Segfault do Polars streaming** no ETL completo → substituído por motor DuckDB
   out-of-core (robusto, com spill em disco).
2. **Score "preso em 2"** — gatilhos fixos de contágio colapsavam por causa da alta
   taxa-base de empresas baixadas/inaptas no Brasil (~61%). Corrigido com modelo
   **proporcional, diluído por diversificação e com baseline empírico**.
3. **Não-determinismo do score** sob `LIMIT` sem `ORDER BY` → corrigido (truncamento
   determinístico), garantindo reprodutibilidade (coberto por teste).
4. **`ald_secundario` como string** (`all_varchar` do DuckDB) tornava `"false"`
   *truthy* em Python, marcando contágio ALD em **todas** as empresas → corrigido
   (cast booleano + coerção defensiva + teste de regressão).
5. **Falsos positivos de CNAE ALD** por busca textual ("jóias", "obras de arte") →
   substituído por **lista curada de 11 códigos** oficiais.

---

## 7. Reprodutibilidade

```bash
# Suíte completa (verbosa, com tempos)
python -m pytest -v --durations=0

# Benchmark de computação paralela
python scripts/benchmark_paralelo.py 80 8

# Pipeline de dados (Fase 0)
python scripts/etl_nexus.py --sample      # amostra (validação rápida)
python scripts/etl_nexus.py               # completo (4,68 GB, motor DuckDB)
```

**Resumo executivo:** 55/56 testes aprovados (1 skip de rede) em 43,3 s; pipeline de
60M empresas em ~6 min; consultas de grafo em milissegundos (após otimização de
zonemap); speedup paralelo de 2,4–3,1× em carga típica; IA integrada e resiliente.
