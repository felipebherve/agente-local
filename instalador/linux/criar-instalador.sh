#!/usr/bin/env bash
# Gera o instalador do Agente Local para Linux: dist/AgenteLocal-Instalador-Linux.run
#
#   instalador/linux/criar-instalador.sh
#
# O .run é um script só, com o agente dentro. Quem baixa roda:
#   chmod +x AgenteLocal-Instalador-Linux.run && ./AgenteLocal-Instalador-Linux.run
set -euo pipefail
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$RAIZ"
mkdir -p dist
SAIDA="dist/AgenteLocal-Instalador-Linux.run"
PACOTE="$(mktemp)"
trap 'rm -f "$PACOTE"' EXIT
tar --exclude='__pycache__' --exclude='*.pyc' --exclude='*.egg-info' -czf "$PACOTE" \
    src pyproject.toml install.sh config.example.yaml README.md README.pt-BR.md \
    LICENSE THIRD_PARTY_NOTICES.md CHANGELOG.md
cat instalador/linux/cabecalho.sh "$PACOTE" > "$SAIDA"
chmod +x "$SAIDA"
echo "Pronto: $SAIDA ($(du -h "$SAIDA" | cut -f1))"
