"""Execução segura de comandos: só programas liberados e só dentro das pastas permitidas."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from agente.config import Config

logger = logging.getLogger(__name__)


class ErroExecucao(Exception):
    """Comando bloqueado, inexistente, lento demais ou que falhou."""


class ConfirmacaoNecessaria(ErroExecucao):
    """Ação que não se desfaz fácil e precisa do OK do usuário."""


@dataclass(frozen=True)
class Saida:
    comando: str
    codigo: int
    texto: str
    segundos: float

    @property
    def ok(self) -> bool:
        return self.codigo == 0


def validar_pasta(cfg: Config, pasta: str | Path) -> Path:
    """Devolve a pasta resolvida se ela estiver dentro de uma das pastas permitidas."""
    p = Path(pasta).expanduser().resolve()
    if not p.exists():
        raise ErroExecucao(f"caminho não existe: {p}")
    for permitida in cfg.pastas_permitidas:
        if p.is_relative_to(permitida.expanduser().resolve()):
            return p
    raise ErroExecucao(f"caminho fora das pastas permitidas no config.yaml: {p}")


def _resolver_programa(cfg: Config, programa: str) -> str:
    nome = Path(programa).stem.lower() if Path(programa).is_absolute() else programa
    if nome not in cfg.comandos_liberados:
        raise ErroExecucao(f"comando não liberado no config.yaml: {nome}")
    if Path(programa).is_absolute():
        return programa
    caminho = shutil.which(programa)
    if caminho is None:
        raise ErroExecucao(f"{programa} não encontrado no PATH")
    return caminho


def executar(cfg: Config, args: list[str], pasta: Path, timeout_s: float = 600) -> Saida:
    """Roda um comando sem shell e junta stdout e stderr num texto só."""
    caminho = _resolver_programa(cfg, args[0])
    ambiente = {**os.environ, "PYTHONIOENCODING": "utf-8", "NO_COLOR": "1", "CI": "1"}
    ambiente.pop("FORCE_COLOR", None)
    rotulo = " ".join(args)
    inicio = time.perf_counter()
    try:
        proc = subprocess.run(
            [caminho, *args[1:]],
            cwd=pasta,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            env=ambiente,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        raise ErroExecucao(f"'{rotulo}' passou de {timeout_s:.0f}s e foi interrompido") from exc
    except OSError as exc:
        raise ErroExecucao(f"não consegui rodar '{rotulo}': {exc}") from exc
    segundos = time.perf_counter() - inicio
    logger.info("exec %s -> %d em %.1fs (%s)", rotulo, proc.returncode, segundos, pasta)
    return Saida(rotulo, proc.returncode, (proc.stdout or "") + (proc.stderr or ""), segundos)
