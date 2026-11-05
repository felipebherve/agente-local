# Instalador do agente-local para Windows 10/11 (PowerShell).
#
#   git clone https://github.com/felipebherve/agente-local.git
#   cd agente-local
#   powershell -ExecutionPolicy Bypass -File .\install.ps1          # pergunta antes
#   powershell -ExecutionPolicy Bypass -File .\install.ps1 -Sim     # aceita tudo
#   powershell -ExecutionPolicy Bypass -File .\install.ps1 -Voz     # inclui a voz (Ctrl+Alt+F)
#
# O que faz: instala pelo winget o que faltar (Python, Git, Ollama e, se quiser, Node.js),
# cria o ambiente do agente, instala o OmniRoute (opcional), roda "agente init" e cria os
# atalhos "Agente local" na área de trabalho e no menu Iniciar.
param([switch]$Sim, [switch]$Voz)
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Titulo($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Aviso($t) { Write-Host $t -ForegroundColor Yellow }
function Perguntar($t) {
    if ($Sim) { return $true }
    $r = Read-Host "$t [S/n]"
    return ($r -eq "" -or $r -match "^[sSyY]")
}
function Tem($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Recarregar-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}
function Instalar-Winget($id, $nome) {
    if (-not (Tem "winget")) { Aviso "Sem o winget: instale $nome à mão."; return }
    if (Perguntar "Instalar $nome pelo winget?") {
        winget install --id $id -e --accept-source-agreements --accept-package-agreements
        Recarregar-Path
    }
}

Titulo "1/6 Conferindo o básico"
if (-not (Tem "git")) { Instalar-Winget "Git.Git" "Git" }
function Py-Ok($cmd) {
    $resto = @($cmd | Select-Object -Skip 1)
    try {
        & $cmd[0] @resto -c "import sys; sys.exit(sys.version_info < (3, 10))" 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}
$py = $null
foreach ($c in @(@("py", "-3.12"), @("py", "-3.13"), @("py", "-3.11"), @("py", "-3.10"), @("python"))) {
    if (Py-Ok $c) { $py = $c; break }
}
if (-not $py) {
    Instalar-Winget "Python.Python.3.12" "Python 3.12"
    $py = @("py", "-3.12")
}
$pyResto = @($py | Select-Object -Skip 1)
Write-Host "Python: $(& $py[0] @pyResto --version)"

Titulo "2/6 Ollama (roda os modelos de IA no seu PC)"
if (Tem "ollama") { Write-Host "Ollama já instalado." } else { Instalar-Winget "Ollama.Ollama" "Ollama" }

Titulo "3/6 Ambiente do agente"
if (-not (Test-Path ".venv")) { & $py[0] @pyResto -m venv .venv }
$vpy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $vpy -m pip install -q --upgrade pip
$extras = ""
if ($Voz) { $extras = "[voz]" }
& $vpy -m pip install -q -e ".$extras"
Write-Host "Agente instalado em $PSScriptRoot\.venv"

Titulo "4/6 OmniRoute (opcional: IA grátis na nuvem entre o seu PC e o Claude)"
if (Tem "omniroute") {
    Write-Host "OmniRoute já instalado."
} elseif (Perguntar "Instalar o OmniRoute (precisa do Node.js)?") {
    if (-not (Tem "npm")) { Instalar-Winget "OpenJS.NodeJS.LTS" "Node.js" }
    if (Tem "npm") { npm install -g omniroute } else { Aviso "Sem Node.js: pulei o OmniRoute." }
}

Titulo "5/6 Modelos, config e registro no Claude"
$agente = Join-Path $PSScriptRoot ".venv\Scripts\agente.exe"
if ($Sim) { & $agente init --sim } else { & $agente init }

Titulo "6/6 Atalhos"
$shell = New-Object -ComObject WScript.Shell
$painel = Join-Path $PSScriptRoot ".venv\Scripts\agente-painel.exe"
$destinos = @(
    [Environment]::GetFolderPath("Desktop"),
    (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs")
)
foreach ($pasta in $destinos) {
    $lnk = $shell.CreateShortcut((Join-Path $pasta "Agente local.lnk"))
    $lnk.TargetPath = $painel
    $lnk.WorkingDirectory = $PSScriptRoot
    $lnk.Description = "Abre o painel do agente no navegador"
    $lnk.Save()
}
Write-Host "Atalho 'Agente local' criado na área de trabalho e no menu Iniciar."

if ($Voz) {
    # Atalho de teclado do Windows: um .lnk no menu Iniciar com tecla de atalho.
    $vpyw = Join-Path $PSScriptRoot ".venv\Scripts\pythonw.exe"
    $lnk = $shell.CreateShortcut((Join-Path $destinos[1] "Agente local - falar.lnk"))
    $lnk.TargetPath = $vpyw
    $lnk.Arguments = "-m agente.voz.atalho_voz"
    $lnk.WorkingDirectory = $PSScriptRoot
    $lnk.Hotkey = "Ctrl+Alt+F"
    $lnk.Save()
    Write-Host "Voz: Ctrl+Alt+F para começar a falar, Ctrl+Alt+F de novo para mandar."
    Write-Host "A resposta aparece no painel (aba Histórico)."
}

Titulo "Pronto"
Write-Host "- Abra o Claude Code: ele já chama o agente sozinho."
Write-Host "- Painel: atalho 'Agente local' na área de trabalho."
Write-Host "- Algo estranho? Rode: .venv\Scripts\agente.exe doctor"
Write-Host "- Desinstalar: apague esta pasta e os atalhos 'Agente local', e tire o bloco"
Write-Host "  'agente-local' de %USERPROFILE%\.claude.json e de %USERPROFILE%\.claude\CLAUDE.md."
