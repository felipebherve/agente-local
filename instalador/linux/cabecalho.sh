#!/usr/bin/env bash
# Instalador do Agente Local para Linux.
#
#   ./AgenteLocal-Instalador-Linux.run                 # instala em Documentos/Agente Local
#   ./AgenteLocal-Instalador-Linux.run --pasta DIR     # instala em outra pasta
#   ./AgenteLocal-Instalador-Linux.run --celular       # já deixa o painel ligado p/ o celular
#
# Atualizar é rodar de novo: troca só os arquivos do programa. config.yaml, dados/ e
# logs/ (os seus dados) ficam como estão.
set -euo pipefail
DOCS="$(xdg-user-dir DOCUMENTS 2>/dev/null || true)"
[ -n "$DOCS" ] && [ "$DOCS" != "$HOME" ] || DOCS="$HOME/Documentos"
DESTINO="$DOCS/Agente Local"
OPCOES=(--sim)
while [ $# -gt 0 ]; do
    case "$1" in
        --pasta) DESTINO="$2"; shift ;;
        --celular) OPCOES+=(--celular) ;;
        --voz) OPCOES+=(--voz) ;;
        -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    esac
    shift
done
printf '\n\033[1;35m== Agente Local\033[0m\nInstalando em: %s\n' "$DESTINO"
if [[ " ${OPCOES[*]} " != *" --celular "* ]] && [ -t 0 ]; then
    read -r -p "Deixar o painel sempre ligado para usar pelo celular? [s/N] " r
    [[ "$r" =~ ^[sSyY] ]] && OPCOES+=(--celular)
fi
mkdir -p "$DESTINO"
LINHA=$(awk '/^__PACOTE_AGENTE__$/ { print NR + 1; exit 0 }' "$0")
tail -n +"$LINHA" "$0" | tar -xz -C "$DESTINO"
cd "$DESTINO"
chmod +x install.sh
./install.sh "${OPCOES[@]}"
exit 0
__PACOTE_AGENTE__
