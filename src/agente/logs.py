"""Logs do agente: tudo em arquivo, avisos e erros também no terminal."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

FORMATO = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configurar_logs(pasta: Path, nivel: int = logging.INFO) -> Path:
    """Liga os logs uma única vez e devolve o caminho do arquivo de log."""
    arquivo = pasta / "agente.log"
    raiz = logging.getLogger()
    if any(isinstance(h, RotatingFileHandler) for h in raiz.handlers):
        return arquivo
    try:
        pasta.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(f"não foi possível criar a pasta de logs {pasta}: {exc}") from exc
    formato = logging.Formatter(FORMATO)
    em_arquivo = RotatingFileHandler(arquivo, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    em_arquivo.setFormatter(formato)
    no_terminal = logging.StreamHandler()
    no_terminal.setLevel(logging.WARNING)
    no_terminal.setFormatter(formato)
    raiz.setLevel(nivel)
    raiz.addHandler(em_arquivo)
    raiz.addHandler(no_terminal)
    return arquivo
