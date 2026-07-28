# GUIA DE LIMITES DO GITHUB E INCLUSÃO DE DADOS PARCIAIS (AMOSTRA)

Este guia explica os limites do GitHub para arquivos de dados e como incluir uma amostra parcial leve do banco de dados no seu repositório.

---

## 1. LIMITES DO GITHUB PARA ARQUIVOS E REPOSITÓRIOS

* **Limite Rígido por Arquivo:** **100 MB**
  * O GitHub rejeita qualquer `git push` que contenha um único arquivo acima de 100 MB.
  * A partir de **50 MB**, o GitHub exibe avisos (*warnings*) durante o push.
* **Tamanho Recomendado do Repositório:** **Menos de 1 GB**
  * Manter o repositório leve melhora o desempenho de `git clone` e `git pull`.
* **Por que a base completa do NEXUS não deve ir direto pro Git?**
  * A base completa `nexus.duckdb` possui **~6,7 GB** e os dados brutos/CSVs possuem **>14 GB**, excedendo os limites do Git.

---

## 2. ESTRATÉGIAS PARA ADICIONAR DADOS PARCIAIS NO GITHUB

### Estratégia 1: Criar uma Base de Amostra Leve (Recomendado — < 50 MB)

Você pode commitar apenas a versão de amostra do `nexus.duckdb` ou CSVs reduzidos.

1. **Gere a amostra reduzida:**
   ```powershell
   python scripts/etl_nexus.py --sample
   ```
   *(Isso gera um `dados_processados/nexus.duckdb` pequeno de apenas 1 partição).*

2. **Abra o arquivo `.gitignore` e permita a versão de amostra:**
   Atualmente o `.gitignore` ignora a pasta `dados_processados/` inteira:
   ```gitignore
   dados_processados/
   *.duckdb
   ```

   Para versionar **apenas** uma pasta de amostra (ex: `dados_amostra/`), crie a pasta `dados_amostra/`:
   ```powershell
   New-Item -ItemType Directory -Force -Path "dados_amostra"
   Copy-Item "dados_processados\nexus.duckdb" "dados_amostra\nexus_amostra.duckdb"
   ```

3. **Adicione a exceção no `.gitignore`:**
   Adicione as seguintes linhas no final do `.gitignore`:
   ```gitignore
   # Permitir apenas o banco de amostra
   !dados_amostra/
   !dados_amostra/*.duckdb
   ```

---

## 3. ESTRATÉGIA 2: UTILIZAR AS RELEASES DO GITHUB (Para arquivos > 100 MB até 2 GB)

Se você quiser disponibilizar o banco de dados completo ou uma amostra maior (ex: 500 MB a 2 GB) para quem baixar o projeto:

1. Faça o commit apenas do código-fonte para o GitHub.
2. No repositório do GitHub, vá em **Releases** $\rightarrow$ **Create a new release**.
3. Faça o upload do arquivo `nexus.duckdb` (ou zipado `.zip`/`.tar.gz`) como anexo binário da release.
4. No `COMO_RODAR.md`, adicione o link para o usuário baixar a base pronta da Release.

---

## 4. ESTRATÉGIA 3: GERAR LOCALMENTE VIA ETL (Prática recomendada para Big Data)

A abordagem standard em projetos de engenharia de dados é:
* **Não versionar os dados binários grandes no Git.**
* Versionar o script de download/ETL (`scripts/etl_nexus.py --sample`).
* Quem clonar o repositório apenas roda `python scripts/etl_nexus.py --sample` para criar a base local em 1 minuto.

---

## 5. RESUMO DE COMANDOS PARA INCLUIR A AMOSTRA NO GIT

```powershell
# 1. Gerar base amostral
python scripts/etl_nexus.py --sample

# 2. Criar pasta de amostra
New-Item -ItemType Directory -Force -Path "dados_amostra"
Copy-Item "dados_processados\nexus.duckdb" "dados_amostra\nexus_amostra.duckdb"

# 3. Adicionar ao Git
git add dados_amostra/
git commit -m "feat: adiciona base de dados amostral para testes"
git push origin main
```
