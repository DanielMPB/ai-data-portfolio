@echo off
chcp 65001 > nul
echo ============================================================
echo   NEXUS V2 — Configuração de Ambiente Seguro (.env)
echo ============================================================

REM 1. Verifica se .env já existe
if exist ".env" (
    echo [INFO] O arquivo .env ja existe na sua maquina local.
) else (
    echo [CRIANDO] Copiando .env.example para .env...
    copy .env.example .env
    echo [SUCESSO] Arquivo .env criado localmente!
)

REM 2. Garante que o .gitignore contém .env
findstr /C:".env" .gitignore > nul
if %errorlevel% neq 0 (
    echo .env >> .gitignore
    echo [PROTEÇÃO] Regra .env adicionada ao .gitignore!
)

REM 3. Remove .env do índice do Git se tiver sido adicionado acidentalmente
git rm --cached .env > nul 2>&1
git rm --cached dados_processados/* > nul 2>&1
git rm --cached "Dados Brutos/*" > nul 2>&1

echo.
echo ============================================================
echo   [OK] Seu ambiente local esta seguro!
echo   Chaves de API e arquivos pesados NAO serao enviados ao GitHub.
echo ============================================================
pause
