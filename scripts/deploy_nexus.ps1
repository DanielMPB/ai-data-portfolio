<#
.SYNOPSIS
    Deploy/manutencao do NEXUS V2 num servidor Linux (Ubuntu/Debian) ja com os
    arquivos enviados. Roda da sua maquina Windows via SSH e, no servidor:
      1. Limpa todos os __pycache__ / *.pyc / *.pyo
      2. Organiza o ambiente: cria venv isolada e instala requirements.txt
      3. Sobe o sistema 24/7 como servico systemd (Restart=always, liga no boot)
      4. Libera a porta no firewall (ufw) e faz health-check

.NOTES
    Pre-requisitos:
      - OpenSSH client no Windows (ja vem no Win10/11: 'ssh' e 'scp').
      - Acesso SSH ao servidor (chave .pem/.key ou senha).
      - sudo SEM senha para o usuario (padrao em VMs de nuvem Ubuntu/AWS/Oracle).
      - IMPORTANTE: alem do firewall do host (ufw), libere a porta tambem no
        painel da nuvem (Security Group / Network ACL / Regras de entrada).
#>

# ======================= CONFIG — PREENCHA AQUI =======================
$VPS_HOST   = "SEU_IP_OU_HOSTNAME"          # ex: 203.0.113.45  ou  meuapp.exemplo.com
$VPS_USER   = "ubuntu"                       # usuario SSH (ubuntu / opc / root / ...)
$SSH_KEY    = "$HOME\.ssh\minha_chave.pem"   # caminho da chave privada; deixe "" p/ usar senha
$REMOTE_DIR = "/home/$VPS_USER/nexus"        # pasta no servidor onde voce subiu os arquivos
$APP_PORT   = 8000                            # porta da API
$SERVICE    = "nexus"                         # nome do servico systemd
# ======================================================================

$ErrorActionPreference = "Stop"

# ---- Preflight: ssh disponivel? ----
if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    Write-Host "ERRO: 'ssh' nao encontrado. Instale o OpenSSH Client (Configuracoes > Apps > Recursos opcionais)." -ForegroundColor Red
    exit 1
}
if ($VPS_HOST -eq "SEU_IP_OU_HOSTNAME") {
    Write-Host "ERRO: edite o bloco CONFIG no topo do script (VPS_HOST, etc.) antes de rodar." -ForegroundColor Red
    exit 1
}

# ---- Monta os argumentos do SSH ----
$sshArgs = @('-o','StrictHostKeyChecking=accept-new','-o','ConnectTimeout=12')
if ($SSH_KEY -and (Test-Path $SSH_KEY)) {
    $sshArgs += @('-i', $SSH_KEY)
    Write-Host "Usando chave: $SSH_KEY" -ForegroundColor DarkGray
} elseif ($SSH_KEY) {
    Write-Host "AVISO: chave '$SSH_KEY' nao encontrada — vai pedir senha." -ForegroundColor Yellow
}
$target = "$VPS_USER@$VPS_HOST"

# ---- Script remoto (bash) — recebe config via argumentos posicionais ----
$remoteScript = @'
#!/usr/bin/env bash
set -euo pipefail
REMOTE_DIR="$1"; PORT="$2"; SERVICE="$3"; SVC_USER="$4"

echo "==> Projeto: $REMOTE_DIR"
if [ ! -d "$REMOTE_DIR" ]; then
  echo "ERRO: pasta '$REMOTE_DIR' nao existe no servidor. Ajuste REMOTE_DIR no script."; exit 1
fi
cd "$REMOTE_DIR"

echo "==> [1/4] Limpando __pycache__ / *.pyc / *.pyo ..."
find . -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
find . -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete 2>/dev/null || true
echo "    limpo."

echo "==> [2/4] Organizando ambiente (Python + venv + dependencias) ..."
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3 python3-venv python3-pip >/dev/null
if [ ! -d .venv ]; then python3 -m venv .venv; fi
./.venv/bin/python -m pip install --upgrade pip -q
./.venv/bin/pip install -r requirements.txt -q
echo "    venv pronta em $REMOTE_DIR/.venv"

echo "==> Verificando base de dados ..."
if [ -f dados_processados/nexus.duckdb ]; then
  echo "    base OK ($(du -h dados_processados/nexus.duckdb | cut -f1))"
else
  echo "    AVISO: dados_processados/nexus.duckdb ausente — rotas de base retornarao 503."
fi

echo "==> [3/4] Criando servico systemd '$SERVICE' (24/7, Restart=always) ..."
sudo tee /etc/systemd/system/$SERVICE.service >/dev/null <<UNIT
[Unit]
Description=NEXUS V2 API (FastAPI/uvicorn)
After=network.target

[Service]
Type=simple
User=$SVC_USER
WorkingDirectory=$REMOTE_DIR
ExecStart=$REMOTE_DIR/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT
Restart=always
RestartSec=3
StandardOutput=append:/var/log/$SERVICE.log
StandardError=append:/var/log/$SERVICE.log

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable $SERVICE >/dev/null 2>&1 || true
sudo systemctl restart $SERVICE
sleep 4

echo "==> [4/4] Liberando porta $PORT no firewall do host (ufw, se ativo) ..."
if command -v ufw >/dev/null 2>&1 && sudo ufw status | grep -q 'Status: active'; then
  sudo ufw allow ${PORT}/tcp >/dev/null 2>&1 || true
  echo "    ufw: porta ${PORT}/tcp liberada."
else
  echo "    ufw inativo/ausente — nada a fazer no host."
fi

echo ""
echo "==================== STATUS ===================="
sudo systemctl --no-pager --full status $SERVICE | head -n 12 || true
echo "------------------------------------------------"
printf "Health local: "
curl -s -o /dev/null -w 'HTTP=%{http_code}\n' --max-time 8 http://127.0.0.1:$PORT/health || echo "sem resposta"
echo "================================================"
'@

# Normaliza fim de linha p/ LF (bash nao gosta de CRLF)
$remoteScript = $remoteScript -replace "`r`n", "`n"

# Comando remoto: roda bash lendo o script via stdin, passando a config como args
$remoteCmd = "bash -s -- '$REMOTE_DIR' '$APP_PORT' '$SERVICE' '$VPS_USER'"

Write-Host ""
Write-Host "==> Conectando em $target e executando o deploy..." -ForegroundColor Cyan
Write-Host ""

$remoteScript | ssh @sshArgs $target $remoteCmd

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "OK! NEXUS V2 no ar 24/7 em http://${VPS_HOST}:${APP_PORT}/" -ForegroundColor Green
    Write-Host "Swagger: http://${VPS_HOST}:${APP_PORT}/docs" -ForegroundColor Green
    Write-Host ""
    Write-Host "Comandos uteis no servidor (via SSH):" -ForegroundColor DarkGray
    Write-Host "  sudo systemctl status $SERVICE     # ver estado" -ForegroundColor DarkGray
    Write-Host "  sudo systemctl restart $SERVICE    # reiniciar" -ForegroundColor DarkGray
    Write-Host "  sudo journalctl -u $SERVICE -f     # logs ao vivo" -ForegroundColor DarkGray
    Write-Host "  tail -f /var/log/$SERVICE.log      # log do app" -ForegroundColor DarkGray
} else {
    Write-Host ""
    Write-Host "Falhou (exit $LASTEXITCODE). Veja a saida acima." -ForegroundColor Red
    Write-Host "Lembre: libere a porta $APP_PORT tambem no painel da nuvem (Security Group)." -ForegroundColor Yellow
}
