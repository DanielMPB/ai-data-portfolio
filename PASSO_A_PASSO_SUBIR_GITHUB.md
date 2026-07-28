# PASSO A PASSO COMPLETO PARA SUBIR O NEXUS V2 NO GITHUB

Este guia cobre desde a criação do repositório no site do GitHub até o envio seguro (`push`) do projeto com a amostra de dados e a proteção de chaves de API.

---

## FASE 1 — No Site do GitHub (github.com)

1. Acesse **[github.com](https://github.com/)** e faça login na sua conta.
2. No canto superior direito, clique no botão **`+`** e selecione **"New repository"** (Novo repositório).
3. Preencha os campos:
   * **Repository name:** `NEXUS_2_daniel` (ou o nome de sua preferência).
   * **Description:** `Plataforma de Due Diligence Corporativa, Grafos Societários, Score de Risco e Terminal B3.`
   * **Visibilidade:** Escolha **Public** ou **Private**.
   * ⚠️ **IMPORTANTE (ATENÇÃO):** **NÃO marque** nenhuma das caixas:
     * ❌ *Add a README file* (já temos no projeto)
     * ❌ *Add .gitignore* (já temos configurado no projeto)
     * ❌ *Choose a license*
4. Clique no botão verde **"Create repository"**.
5. Na página que abrir, **copie a URL HTTPS** do seu repositório. Ela será parecida com:
   `https://github.com/SEU-USUARIO/NEXUS_2_daniel.git`

---

## FASE 2 — No Terminal / PowerShell da sua Máquina

Abra o terminal do VS Code ou o PowerShell na pasta do projeto (`C:\Users\Daniel Mont\Desktop\NEXUS_2_daniel`) e execute os comandos na ordem abaixo:

### Passo 1: Gerar a Amostra Leve de Dados (< 25 MB)
```powershell
python scripts/gerar_amostra_github.py
```
*(Isso cria a pasta `dados_amostra/` com o `nexus_amostra.duckdb` e os CSVs leveis).*

### Passo 2: Executar a Auditoria de Segurança Local
```powershell
.\verificar_seguranca_github.bat
```
*(Garante que o `.env` com a sua chave da OpenAI e as pastas gigantes de 32 GB estão 100% bloqueadas).*

### Passo 3: Inicializar o Git (caso ainda não tenha inicializado)
```powershell
git init
```

### Passo 4: Adicionar todos os arquivos do projeto ao Git
```powershell
git add .
```

### Passo 5: Criar o Primeiro Commit
```powershell
git commit -m "feat: commit inicial da plataforma NEXUS V2 com amostragem de dados"
```

### Passo 6: Renomear a Branch para `main`
```powershell
git branch -M main
```

### Passo 7: Conectar com o Repositório do GitHub
*(Substitua a URL abaixo pela URL que você copiou na FASE 1)*
```powershell
git remote add origin https://github.com/SEU-USUARIO/NEXUS_2_daniel.git
```

### Passo 8: Enviar os arquivos para o GitHub (`Push`)
```powershell
git push -u origin main
```

---

## FASE 3 — Como Disponibilizar a Base Completa (Opcional)

Se futuramente você quiser compartilhar a base completa de 6,7 GB (`nexus.duckdb`) com a comunidade ou equipe sem travar o repositório Git:

1. Compacte o arquivo em `.zip`: `nexus_completo.zip`.
2. No seu repositório no GitHub, clique em **Releases** (na barra lateral direita) $\rightarrow$ **Create a new release**.
3. Faça o upload do arquivo `.zip` nos anexos da Release.
4. O repositório permanecerá leve e qualquer pessoa poderá baixar a base completa pela Release.
