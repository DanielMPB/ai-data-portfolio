# Como rodar o NEXUS V2 no localhost

Guia passo a passo para subir o sistema na sua própria máquina. Os comandos estão
no formato **Windows / PowerShell** (ambiente do projeto), mas são equivalentes em
Linux/macOS.

> Todos os comandos abaixo devem ser executados **dentro da pasta do projeto**:
> `C:\Users\Davi\Desktop\NEXUS 2.0`

---

## Pré-requisitos

- **Python 3.10+** (o projeto foi desenvolvido em 3.14). Verifique:
  ```powershell
  python --version
  ```
- **~15 GB de disco livre** se for gerar a base processada do zero (o `nexus.duckdb`
  ocupa ~6,7 GB e os CSVs intermediários ~14 GB). Se a base já existe, não precisa.
- **Conexão de internet** para: instalar dependências, usar a IA (OpenAI) e o terminal
  de mercado (yfinance). A análise de grafos/score funciona 100% offline.

---

## Passo 1 — Instalar as dependências

```powershell
pip install -r requirements.txt
```

Isso instala Polars, DuckDB, FastAPI, Uvicorn, NetworkX, yfinance, OpenAI, etc.

---

## Passo 2 — Configurar a chave da IA (opcional, mas recomendado)

As análises de IA (Calculadora de RI, Advisor e Recomendação do dia) usam a API da
OpenAI. **O resto do sistema funciona sem isso** — sem a chave, essas rotas apenas
retornam um aviso (503).

1. Pegue uma chave em https://platform.openai.com/api-keys (começa com `sk-...`).
2. Abra o arquivo **`.env`** na raiz do projeto e cole na linha:
   ```
   LLM_API_KEY=sk-sua-chave-aqui
   ```
   (Se o arquivo `.env` não existir, copie o modelo: `Copy-Item .env.example .env`.)

> Para usar Gemma (Ollama local ou Google AI Studio) em vez da OpenAI, há blocos
> comentados no próprio `.env` — basta descomentar o desejado.

---

## Passo 3 — Garantir a base de dados

O sistema precisa do arquivo **`dados_processados/nexus.duckdb`**.

**Verifique se já existe:**
```powershell
Test-Path "dados_processados\nexus.duckdb"
```

- **Se retornar `True`** → a base já está pronta, **pule para o Passo 4**.
- **Se retornar `False`** → gere a base a partir dos Parquet em `Dados Brutos/`:

  ```powershell
  # Opção rápida (amostra — 1 partição por base, ~1-2 min, ideal para testar):
  python scripts/etl_nexus.py --sample

  # Opção completa (toda a base, 4,68 GB, ~6 min):
  python scripts/etl_nexus.py
  ```

  > O ETL lê os Parquet de `Dados Brutos/`, higieniza e gera os CSVs + o
  > `nexus.duckdb` indexado. Use `--sample` na primeira vez para validar rápido.

---

## Passo 4 — Subir o servidor

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Você verá algo como `Uvicorn running on http://127.0.0.1:8000`. **Deixe esse
terminal aberto** — ele é o servidor.

> Dica: adicione `--reload` durante o desenvolvimento para recarregar ao salvar
> arquivos do backend: `python -m uvicorn app.main:app --reload`

---

## Passo 5 — Acessar no navegador

| O quê | Endereço |
|---|---|
| **Interface (app web)** | http://127.0.0.1:8000/ |
| **Swagger (documentação da API)** | http://127.0.0.1:8000/docs |
| **Health check** | http://127.0.0.1:8000/health |

A interface tem as 3 seções: **Investigação de Vínculos**, **Relações com
Investidores** e **Radar de Mercado**.

**Para testar rapidamente** (Investigação de Vínculos), digite uma raiz de CNPJ:
`48847523` (HELPMED, rede grande), `07605410` (Inapta, alto risco) ou `03432472`
(ANADEM S.A.).

---

## Como parar o servidor

No terminal do servidor, pressione **`Ctrl + C`**.

---

## Solução de problemas

| Problema | Causa / Solução |
|---|---|
| `Base não encontrada: ...nexus.duckdb` (erro 503 nas rotas de empresa) | A base não foi gerada. Volte ao **Passo 3** e rode o ETL. |
| Rotas de IA retornam **503** | Sem `LLM_API_KEY` no `.env`, ou chave inválida/sem créditos. Veja o **Passo 2**. |
| Cotações/mercado vazios | Sem internet (yfinance) ou instabilidade do provedor. Tente de novo. |
| `Address already in use` / porta 8000 ocupada | Use outra porta: `--port 8001`, e acesse `http://127.0.0.1:8001`. |
| `uvicorn não é reconhecido` | Use `python -m uvicorn ...` (como no guia) em vez de só `uvicorn`. |
| Mudei o CSS/JS e não atualiza | O servidor já envia `no-cache`; basta **F5**. Se persistir, **Ctrl+F5**. |

---

## Resumo rápido (TL;DR)

```powershell
pip install -r requirements.txt
# (cole sua chave OpenAI em .env, se quiser as funções de IA)
python scripts/etl_nexus.py          # só se nexus.duckdb ainda não existir
python -m uvicorn app.main:app --port 8000
# abra http://127.0.0.1:8000/
```
