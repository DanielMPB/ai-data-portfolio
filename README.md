# NEXUS — Plataforma de Due Diligence Corporativa, Grafos Societários, Score de Risco e Terminal B3

Plataforma **Backend-First / API-First** de *due diligence* corporativa sobre a base pública da Receita Federal: grafos societários de 2º grau, score de risco determinístico com contágio de rede, calculadora de Relações com Investidores (RI) via LLM e terminal quantitativo da B3.

### Pilares acadêmicos demonstrados
- **Grafos / Graph Mining** — travessia de 2º grau (DuckDB CTE) + mineração estrutural com
  NetworkX (centralidade de grau, componentes conexos = grupo econômico, pontos de articulação).
  Ver [`graph_db.py`](app/services/graph_db.py) e [`graph_mining.py`](app/services/graph_mining.py).
- **Computação Paralela** — due diligence de portfólio distribuída por múltiplos núcleos
  (`ThreadPoolExecutor` sobre consultas DuckDB que liberam o GIL). Ver
  [`parallel.py`](app/services/parallel.py) e o benchmark
  [`benchmark_paralelo.py`](scripts/benchmark_paralelo.py) (speedup ~3x).
- **Computação em Nuvem** — *(adiada para o deploy)* a API é stateless e containerizável;
  a base DuckDB/CSVs vai para object storage e o serviço sobe atrás de um load balancer.

## Arquitetura

```
NEXUS 2.0/
├── Dados Brutos/            # Parquet bruto da Receita Federal (particionado)
├── dados_processados/       # gerado: nodes_empresas.csv, edges_socios.csv, nexus.duckdb
├── scripts/etl_nexus.py     # Fase 0 — ETL Polars (streaming)
├── app/
│   ├── main.py              # FastAPI
│   ├── core/                # config.py, validators.py
│   └── services/            # graph_db, risk_score, ir_agent, market_data, llm_client
├── frontend/                # Fase 5 — Vis.js
└── tests/
```

## Setup

```powershell
pip install -r requirements.txt
Copy-Item .env.example .env   # ajuste LLM_BASE_URL / LLM_MODEL conforme seu Gemma
```

## Fases (construção modular, validada uma a uma)

| Fase | Entrega | Validação |
|------|---------|-----------|
| 0 | ETL → CSVs + DuckDB | `python scripts/etl_nexus.py --sample` (amostra), depois full |
| 1 | Validador CNPJ + grafo 2º grau | `GET /api/v1/empresa/{cnpj}` → 200 |
| 2 | Score de risco + contágio | `pytest tests/test_risk_score.py` |
| 3 | Calculadora RI (LLM) | `POST /api/v1/calculator/ir` |
| 4 | Terminal B3 + advisor | `GET /api/v1/market/stock/{ticker}` |
| 5 | Frontend Vis.js | Swagger todas 200 → UI |

## Pipeline de dados (Fase 0)

```powershell
# Amostra (1 partição por base — rápido)
python scripts/etl_nexus.py --sample

# Completo (4,68 GB) — motor DuckDB out-of-core, paralelo (default)
python scripts/etl_nexus.py

# Variante Polars (Lazy/streaming, conforme spec) — recomendada para amostra
python scripts/etl_nexus.py --sample --engine polars
```

## Computação paralela — benchmark

```powershell
python scripts/benchmark_paralelo.py 48 8   # 48 CNPJs, 8 workers
# Endpoint equivalente: POST /api/v1/portfolio/risco {"cnpjs": [...], "workers": 8}
```

## API + Frontend

```powershell
uvicorn app.main:app --reload
# Interface (Vis.js, dark mode): http://127.0.0.1:8000/
# Swagger UI:                     http://127.0.0.1:8000/docs
```

O FastAPI serve a aplicação web (`frontend/`) na raiz `/` e a API em `/api/v1/*`.
Módulos da UI: Investigação de Vínculos (grafo + score + graph mining), Relações com
Investidores (IA), Radar de Mercado (B3) e Portfólio Paralelo (multi-core).

