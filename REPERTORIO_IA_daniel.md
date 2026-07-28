# REPERTÓRIO TÉCNICO E ARQUITETURAL — NEXUS V2

Plataforma **Backend-First / API-First** de *due diligence* corporativa e análise de risco relacional baseada nos dados públicos da Receita Federal do Brasil (RFB), dados sancionatórios (CEIS/CNEP/Lista Suja), Dívida Ativa da PGFN e cotações da B3.

---

## 1. VISÃO GERAL DO PROJETO

* **Objetivo:** Fornecer suporte à tomada de decisão e due diligence automatizada através de grafos societários de 2º grau, score determinístico de risco com contágio em rede, mineração de grafos, auditoria de RI via IA e terminal quantitativo do mercado acionário.
* **Stack Tecnológico:**
  * **Linguagem:** Python 3.10+ (desenvolvido em 3.14).
  * **Backend & API:** FastAPI, Uvicorn, Pydantic.
  * **Banco de Dados & ETL:** DuckDB (consultas out-of-core com CTEs), Polars (streaming/lazy ETL em Parquet).
  * **Teoria dos Grafos & Mineração:** NetworkX (componentes conexos, centralidade, pontos de articulação).
  * **Computação Paralela:** `ThreadPoolExecutor` (multithreading liberando GIL durante consultas DuckDB).
  * **Inteligência Artificial (LLM):** Integrador com OpenAI (GPT-4o) / Gemma (Ollama/Google AI Studio).
  * **Frontend:** HTML5, CSS3 Vanilla (Dark Mode / Glassmorphism), JavaScript ES6+ com Vis.js Network.
  * **Mercado Financeiro:** Integrador `yfinance`.
  * **Testes:** Pytest.

---

## 2. ESTRUTURA DE PASTAS E ARQUIVOS ESSENCIAIS

```
NEXUS 2.0/
├── app/                        # Núcleo da Aplicação Backend (FastAPI)
│   ├── main.py                 # Ponto de entrada, configuração de rotas e static mount
│   ├── core/                   # Módulos fundamentais
│   │   ├── config.py           # Carregamento de variáveis de ambiente (.env)
│   │   ├── validators.py       # Validação e normalização de CNPJs (alfanumérico/matriz/filial)
│   │   └── ald.py              # Classificação de setores expostos a Lavagem de Dinheiro (ALD)
│   └── services/               # Motores de negócio e processamento
│       ├── graph_db.py         # Engine DuckDB, travessia SQL de 2º grau e construção da rede
│       ├── graph_mining.py     # Análise estrutural (NetworkX): centralidade, grupos e articulações
│       ├── risk_score.py       # Relational Trust Score (Erosão de confiança Noisy-OR + Contágio)
│       ├── parallel.py         # Processamento paralelo de portfólios multi-CNPJ
│       ├── ir_agent.py         # Auditoria de Relações com Investidores via LLM
│       ├── market_data.py      # Terminal de mercado B3 (yfinance + IA advisor)
│       └── llm_client.py       # Client resiliente para provedores de LLM
├── scripts/                    # Scripts de ETL, Benchmarks e Automações
│   ├── etl_nexus.py            # Pipeline ETL (Parquet → CSVs/DuckDB) via Polars/DuckDB
│   ├── etl_dividas.py          # ETL de Dívida Ativa da PGFN
│   ├── etl_sancoes.py           # ETL de Sanções (CEIS/CNEP/Trabalho Análogo à Escravidão)
│   ├── etl_enderecos.py        # ETL e padronização geométrica de endereços
│   ├── benchmark_paralelo.py   # Benchmark de escalabilidade paralela multi-core
│   ├── avaliar_score.py        # Avaliação de acurácia e calibração do modelo de risco
│   └── preparar_dataset_rotulado.py # Preparação de dados de treino/validação
├── frontend/                   # Dashboard Web Estático (SPA)
│   ├── index.html              # Estrutura da interface (Investigação, RI, Mercado, Portfólio)
│   ├── style.css               # Estilização CSS responsiva e temas visuais
│   └── app.js                  # Lógica de renderização de grafos (Vis.js) e consumo da API
├── tests/                      # Suíte de Testes Automatizados (Pytest)
│   ├── test_graph_mining.py
│   ├── test_ir_agent.py
│   ├── test_market_data.py
│   ├── test_parallel.py
│   ├── test_phase1_endpoint.py
│   ├── test_risk_score.py
│   └── test_validators.py
├── paper/                      # Artigo/Documentação Acadêmica (LaTeX)
│   └── avaliacao_resultados.tex
├── Dados Brutos/               # Arquivos Parquet brutos da Receita Federal (não versionados)
├── dados_processados/          # Banco DuckDB (nexus.duckdb) e CSVs extraídos
├── .env.example                # Modelo de configuração de variáveis de ambiente
├── requirements.txt            # Lista de dependências Python
├── COMO_RODAR.md               # Guia de execução local
└── README.md                   # Documentação geral do projeto
```

---

## 3. PIPELINE DE DADOS & ARMAZENAMENTO (ETL)

1. **Entrada de Dados:** Arquivos `.parquet` contendo dados da Receita Federal (Empresas, Sócios, Estabelecimentos).
2. **Processamento (ETL):** `scripts/etl_nexus.py`
   * Limpeza e higienização via Polars (modo streaming) ou DuckDB out-of-core.
   * Separação em nós (`nodes_empresas.csv`) e arestas de relacionamento (`edges_socios.csv`).
3. **Persistência Indexada:**
   * Arquivo final: `dados_processados/nexus.duckdb` (~6.7 GB full, ou amostra reduzida).
   * Tabelas indexadas por raiz de CNPJ (8 caracteres) e documento do sócio (CPF/CNPJ).

---

## 4. MÓDULOS E ALGORITMOS NUCLEARES

### A. Travessia de Grafos & Mineração (`graph_db.py` e `graph_mining.py`)
* **Travessia de 2º Grau:** Executa SQL otimizado em DuckDB utilizando CTEs recursivas para mapear:
  * Empresa principal $\rightarrow$ Sócios diretos $\rightarrow$ Outras empresas dos mesmos sócios.
* **Graph Mining (NetworkX):**
  * **Centralidade de Grau (Degree Centrality):** Identifica os agentes mais conectados na rede.
  * **Grupos Econômicos (Connected Components):** Agrupa empresas/pessoas interligadas.
  * **Pontos de Articulação (Cut Vertices):** Identifica entidades críticas cuja remoção fragmentaria a rede.

### B. Motor de Risco determinístico (`risk_score.py`)
* **Modelo:** *NEXUS Relational Trust Score* baseado em **Erosão de Confiança Multiplicativa (Noisy-OR)**:
  $$\text{Confiança Final} = \prod (1 - w_i \cdot s_i) \quad \Longrightarrow \quad \text{Score} = 100 \cdot \text{Confiança Final}$$
  onde $w_i \in [0, 1]$ é o peso máximo do sinal e $s_i \in [0, 1]$ é a severidade do evento.
* **Camadas de Avaliação:**
  * **Layer A (Risco Direto):** Situação cadastral (Inapta, Baixada, Suspensa), motivos graves (fraude/simulação), CNAE exposto a Lavagem de Dinheiro (ALD), empresas de fachada (*shell companies*), sanções CEIS/CNEP e Dívida Ativa.
  * **Layer B (Contágio de Rede):** Propagação do risco de entidades conectadas no 1º e 2º grau com baselines da Receita Federal e suavização de Laplace.

### C. Execução Paralela (`parallel.py`)
* Avaliação em lote (*batch processing*) de carteiras de CNPJs.
* Utiliza `ThreadPoolExecutor` para distribuição multi-core sem bloqueio do event loop do FastAPI.

### D. Agente de IA para RI (`ir_agent.py`)
* Recebe dados cadastrais, financeiros e governança de empresas.
* Avalia a maturidade de Relações com Investidores, gerando um **Rating (A a D)** e um parecer detalhado formatado em Markdown via LLM.

### E. Terminal de Mercado B3 (`market_data.py`)
* Integração com a B3 via `yfinance`.
* Coleta dados de preço, séries históricas de 6 meses e indicadores fundamentalistas (P/L, DY, ROE, Margem Líquida).
* Gera recomendações diárias e relatórios de Valuation/Advisor alimentados por LLM.

---

## 5. CATÁLOGO DE ENDPOINTS DA API (`FastAPI`)

| Categoria | Método | Rota | Descrição |
| :--- | :---: | :--- | :--- |
| **Infra** | `GET` | `/health` | Verificação de status do serviço |
| **Due Diligence** | `GET` | `/api/v1/empresa/{cnpj}` | Grafo 2º grau + Score Risco + Graph Mining por CNPJ |
| **Due Diligence** | `GET` | `/api/v1/amostra/rede` | Grafo de amostra pré-processado para demonstração rápida |
| **Due Diligence** | `POST`| `/api/v1/portfolio/risco` | Análise paralela multi-core de lista de CNPJs |
| **Calculadora RI**| `POST`| `/api/v1/calculator/ir` | Auditoria de maturidade de RI via LLM |
| **Mercado B3** | `GET` | `/api/v1/market/overview` | Panorama do mercado (índices macro + watchlist) |
| **Mercado B3** | `GET` | `/api/v1/market/stock/{ticker}`| Múltiplos e histórico de 6 meses de uma ação |
| **Mercado B3** | `GET` | `/api/v1/market/recomendacao-dia` | Relatório diário da B3 via LLM |
| **Mercado B3** | `POST`| `/api/v1/market/analyze` | Veredito do Advisor IA (Strong Buy/Hold/Sell) |

---

## 6. ESTRUTURA DO FRONTEND

* **Arquitetura SPA (Single Page Application):** Estática, servida diretamente pelo FastAPI na raiz `/`.
* **Visualização de Redes:** Utiliza `Vis.js Network` para interatividade com o grafo societário (drag, zoom, destaque de relacionamentos e nós articuladores).
* **Módulos da Interface:**
  1. **Investigação de Vínculos:** Consulta por CNPJ, visualização do grafo, score de risco e métricas de mineração.
  2. **Relações com Investidores:** Formulário interativo de auditoria de RI.
  3. **Radar de Mercado:** Cotações, gráficos de ações da B3 e análises de IA.
  4. **Portfólio Paralelo:** Upload/entrada em lote de CNPJs para análise simultânea.

---

## 7. INSTRUÇÕES DE OPERAÇÃO

### Pré-requisitos
* Python 3.10 ou superior.
* ~15 GB de espaço livre em disco (caso precise rodar o ETL completo).
* Chave de API OpenAI configurada no `.env` (opcional, para funções de IA).

### Passos para Execução

1. **Instalar dependências:**
   ```powershell
   pip install -r requirements.txt
   ```

2. **Configurar variáveis de ambiente:**
   ```powershell
   Copy-Item .env.example .env
   # Adicionar LLM_API_KEY se desejar usar as funcionalidades de IA
   ```

3. **Gerar ou verificar base de dados DuckDB:**
   ```powershell
   # Rodar ETL amostral (rápido):
   python scripts/etl_nexus.py --sample
   ```

4. **Iniciar o Servidor Backend + Frontend:**
   ```powershell
   python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
   ```

5. **Acessos:**
   * **Interface Web:** `http://127.0.0.1:8000/`
   * **Swagger Docs:** `http://127.0.0.1:8000/docs`
