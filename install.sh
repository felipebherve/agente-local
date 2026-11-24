#!/usr/bin/env bash
# Instalador do agente-local para Linux.
#
#   git clone https://github.com/felipebherve/agente-local.git
#   cd agente-local && ./install.sh            # pergunta antes de cada passo opcional
#   ./install.sh --sim                         # aceita tudo sem perguntar
#   ./install.sh --voz                         # inclui a voz (atalho Ctrl+Alt+F)
#   ./install.sh --celular                     # deixa o painel sempre no ar para o celular
#   ./install.sh --barra                       # fixa o app na barra de tarefas (dock)
#   ./install.sh --sem-area-de-trabalho        # não cria o atalho na área de trabalho
#
# O que faz: confere Python e Git, instala o Ollama (se faltar), cria o ambiente do
# agente, instala o OmniRoute (opcional), roda "agente init" (modelos + config + Claude)
# e cria o atalho "Agente local" no menu de aplicativos.
set -euo pipefail

SIM=0
VOZ=0
CELULAR=0
BARRA=0
AREA=1
for arg in "$@"; do
    case "$arg" in
        --sim) SIM=1 ;;
        --voz) VOZ=1 ;;
        --celular) CELULAR=1 ;;
        --barra) BARRA=1 ;;
        --sem-area-de-trabalho) AREA=0 ;;
        -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    esac
done

PASTA="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"  # caminho real, sem links
cd "$PASTA"

azul() { printf '\n\033[1;34m== %s\033[0m\n' "$1"; }
aviso() { printf '\033[1;33m%s\033[0m\n' "$1"; }
perguntar() {  # perguntar "texto" -> 0 se sim
    [ "$SIM" = 1 ] && return 0
    read -r -p "$1 [S/n] " r
    [[ -z "$r" || "$r" =~ ^[sSyY] ]]
}

azul "1/6 Conferindo o básico"
command -v git >/dev/null || { aviso "Instale o git (ex.: sudo apt install git) e rode de novo."; exit 1; }
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$c" >/dev/null && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
        PY="$c"; break
    fi
done
[ -n "$PY" ] || { aviso "Precisa do Python 3.10 ou mais novo (ex.: sudo apt install python3 python3-venv)."; exit 1; }
"$PY" -c 'import venv' 2>/dev/null || { aviso "Falta o venv: sudo apt install python3-venv"; exit 1; }
echo "Python: $($PY --version)"

azul "2/6 Ollama (roda os modelos de IA no seu PC)"
if command -v ollama >/dev/null; then
    echo "Ollama já instalado."
elif perguntar "Instalar o Ollama agora (script oficial de ollama.com, pede sua senha)?"; then
    curl -fsSL https://ollama.com/install.sh | sh
else
    aviso "Sem o Ollama o agente não funciona. Instale depois em https://ollama.com"
fi

azul "3/6 Ambiente do agente"
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
EXTRAS=""
if [ "$VOZ" = 1 ]; then
    EXTRAS="[voz]"
    command -v notify-send >/dev/null || aviso "Dica: instale libnotify-bin para ver os avisos da voz."
fi
.venv/bin/python -m pip install -q -e ".$EXTRAS"
# Caminhos absolutos ficam gravados na .venv: se a pasta mudou de lugar, refaz a .venv.
if ! .venv/bin/agente --help >/dev/null 2>&1; then
    aviso "A pasta mudou de lugar: recriando o ambiente do agente."
    rm -rf .venv && "$PY" -m venv .venv
    .venv/bin/python -m pip install -q --upgrade pip
    .venv/bin/python -m pip install -q -e ".$EXTRAS"
fi
echo "Agente instalado em $PASTA/.venv"

azul "4/6 OmniRoute (opcional: IA grátis na nuvem entre o seu PC e o Claude)"
if command -v omniroute >/dev/null; then
    echo "OmniRoute já instalado."
elif command -v npm >/dev/null; then
    if perguntar "Instalar o OmniRoute (npm install -g omniroute)?"; then
        npm install -g omniroute || aviso "Não deu certo; veja https://github.com/diegosouzapw/OmniRoute"
    fi
else
    echo "Node.js não encontrado: pulei o OmniRoute (dá para instalar depois)."
fi

azul "5/6 Modelos, config e registro no Claude"
if [ "$SIM" = 1 ]; then .venv/bin/agente init --sim; else .venv/bin/agente init; fi

azul "6/6 Atalhos"
mkdir -p "$HOME/.local/share/applications" "$HOME/.local/share/icons"
cp src/agente/icones/app-512.png "$HOME/.local/share/icons/agente-local.png"
rm -f "$HOME/.local/share/icons/agente-local.svg"
cat > "$HOME/.local/share/applications/agente-local.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Agente Local
Comment=App do agente: Acordar e Desligar Agente, conversa e economia
Exec="$PASTA/.venv/bin/agente-app"
Icon=$HOME/.local/share/icons/agente-local.png
StartupWMClass=agente-local
Terminal=false
Categories=Development;Utility;
EOF
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
if [ "$AREA" = 1 ] && [ -d "$DESKTOP_DIR" ]; then
    cp "$HOME/.local/share/applications/agente-local.desktop" "$DESKTOP_DIR/agente-local.desktop"
    chmod +x "$DESKTOP_DIR/agente-local.desktop"
    gio set "$DESKTOP_DIR/agente-local.desktop" metadata::trusted true 2>/dev/null || true
fi
echo "Atalho 'Agente Local' criado no menu de aplicativos."
[ "$AREA" = 1 ] && [ -d "$DESKTOP_DIR" ] && echo "Atalho criado na área de trabalho."
if [ "$BARRA" = 1 ]; then
    # GNOME (Ubuntu): a barra de tarefas é a lista de favoritos do dock
    if command -v gsettings >/dev/null && FAVS=$(gsettings get org.gnome.shell favorite-apps 2>/dev/null); then
        if [[ "$FAVS" != *"agente-local.desktop"* ]]; then
            if [[ "$FAVS" == "@as []" || "$FAVS" == "[]" ]]; then NOVA="['agente-local.desktop']"
            else NOVA="${FAVS%]}, 'agente-local.desktop']"; fi
            gsettings set org.gnome.shell favorite-apps "$NOVA"
        fi
        echo "Agente Local fixado na barra de tarefas."
    else
        aviso "Não achei o dock do GNOME: abra o app e use 'Fixar no dock/painel' com o botão direito."
    fi
fi

if [ "$CELULAR" = 1 ] && command -v systemctl >/dev/null; then
    # Painel sempre no ar (leve, o agente começa desligado) para o celular poder acordar.
    mkdir -p "$HOME/.config/systemd/user"
    cat > "$HOME/.config/systemd/user/agente-painel.service" <<EOF
[Unit]
Description=Painel do Agente Local (acesso pelo celular)
After=network-online.target

[Service]
ExecStart="$PASTA/.venv/bin/agente-painel" --sem-navegador
# always: se o app estiver com a porta, tenta de novo até ela ficar livre
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now agente-painel.service
    echo "Painel sempre no ar para o celular. Passo a passo: .venv/bin/agente celular"
fi

if [ "$VOZ" = 1 ] && command -v gsettings >/dev/null \
    && gsettings list-schemas | grep -q org.gnome.settings-daemon.plugins.media-keys; then
    BASE=/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings
    LISTA=$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings)
    CAM="$BASE/agente-voz/"
    if [[ "$LISTA" != *"$CAM"* ]]; then
        if [[ "$LISTA" == "@as []" || "$LISTA" == "[]" ]]; then NOVA="['$CAM']"; else NOVA="${LISTA%]}, '$CAM']"; fi
        gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "$NOVA"
    fi
    CHAVE="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$CAM"
    gsettings set "$CHAVE" name "Agente local: falar"
    gsettings set "$CHAVE" command "\"$PASTA/.venv/bin/python\" -m agente.voz.atalho_voz"
    gsettings set "$CHAVE" binding "<Control><Alt>f"
    echo "Voz: Ctrl+Alt+F para começar a falar, Ctrl+Alt+F de novo para mandar."
fi

azul "Pronto"
cat <<EOF
- Abra o Claude Code: ele já chama o agente sozinho.
- App: menu de aplicativos > "Agente Local" (ou o comando: .venv/bin/agente-app).
  Ele abre com o agente desligado: clique em "Acordar Agente".
- Celular: rode .venv/bin/agente celular e siga o passo a passo.
- Algo estranho? Rode: .venv/bin/agente doctor
- Desinstalar: apague esta pasta, ~/.local/share/applications/agente-local.desktop e
  (se usou --celular) rode systemctl --user disable --now agente-painel;
  e tire o bloco "agente-local" de ~/.claude.json e de ~/.claude/CLAUDE.md.
EOF
