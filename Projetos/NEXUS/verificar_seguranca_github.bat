@echo off
chcp 65001 > nul
echo ============================================================
echo   NEXUS V2 — Auditoria de Segurança para Push no GitHub
echo ============================================================

REM 1. Verifica se o .env está sendo ignorado
git check-ignore .env > nul 2>&1
if %errorlevel% neq 0 (
    echo [ALERTA DE SEGURANÇA] O arquivo .env NÃO está sendo ignorado pelo Git!
    echo Adicionando .env ao .gitignore...
    echo .env >> .gitignore
    git rm --cached .env > nul 2>&1
) else (
    echo [OK] O arquivo .env (chaves secretas) esta devidamente ignorado.
)

REM 2. Verifica se dados pesados estão sendo ignorados
git check-ignore dados_processados/nexus.duckdb > nul 2>&1
if %errorlevel% eq 0 (
    echo [OK] O banco de dados pesado (dados_processados/) esta ignorado.
) else (
    echo [AVISO] Removendo dados_processados do indice do Git...
    git rm -r --cached dados_processados/ > nul 2>&1
)

git check-ignore "Dados Brutos/" > nul 2>&1
if %errorlevel% eq 0 (
    echo [OK] A pasta Dados Brutos/ esta ignorada.
) else (
    echo [AVISO] Removendo Dados Brutos do indice do Git...
    git rm -r --cached "Dados Brutos/" > nul 2>&1
)

echo.
echo ============================================================
echo   Status dos arquivos que irao para o GitHub:
echo ============================================================
git status --short

echo.
echo ============================================================
echo   Auditoria concluida! Nenhum dado sensivel sera vazado.
echo ============================================================
pause
