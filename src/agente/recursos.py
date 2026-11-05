"""Quanto do PC o agente usa, e a trava que impede passar do limite e travar o computador."""

from __future__ import annotations

import logging
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agente.config import Config
from agente.executor import ErroExecucao

logger = logging.getLogger(__name__)

GB = 1024**3


@dataclass(frozen=True)
class Uso:
    vram_usada_gb: float
    vram_total_gb: float
    ram_usada_gb: float
    ram_total_gb: float
    cpu_pct: float

    @property
    def vram_pct(self) -> float:
        return 100 * self.vram_usada_gb / self.vram_total_gb if self.vram_total_gb else 0.0

    @property
    def ram_pct(self) -> float:
        return 100 * self.ram_usada_gb / self.ram_total_gb if self.ram_total_gb else 0.0

    def texto(self) -> str:
        return (
            f"Placa de vídeo {self.vram_usada_gb:.1f} de {self.vram_total_gb:.0f} GB · "
            f"Memória {self.ram_usada_gb:.1f} de {self.ram_total_gb:.0f} GB · "
            f"Processador {self.cpu_pct:.0f}%"
        )


def _vram() -> tuple[float, float]:
    try:
        saida = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
        usada, total = (float(x) for x in saida.splitlines()[0].split(","))
        return usada / 1024, total / 1024
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return 0.0, 0.0


def medir() -> Uso:
    import psutil

    memoria = psutil.virtual_memory()
    vram_usada, vram_total = _vram()
    return Uso(
        vram_usada,
        vram_total,
        (memoria.total - memoria.available) / GB,
        memoria.total / GB,
        psutil.cpu_percent(interval=None),
    )


def ram_do_navegador_gb(cfg: Config) -> float:
    """Memória das janelas do navegador do agente (perfil próprio em dados/navegador)."""
    import psutil

    perfil = str(cfg.pasta_dados / "navegador").lower()
    total = 0
    for proc in psutil.process_iter(["name", "cmdline", "memory_info"]):
        try:
            nome = (proc.info["name"] or "").lower()
            if (
                nome.startswith(("msedge", "chrome"))
                and perfil in " ".join(proc.info["cmdline"] or []).lower()
            ):
                total += proc.info["memory_info"].rss
        except (psutil.Error, TypeError, AttributeError):
            continue
    return total / GB


def liberar(cliente: Any, manter: set[str]) -> list[str]:
    """Tira da placa e da memória os modelos do Ollama que não estão em `manter`."""
    tirados: list[str] = []
    try:
        carregados = list(cliente.modelos_carregados())
    except Exception as exc:  # Ollama fora: nada a liberar
        logger.warning("não consegui ver os modelos carregados: %s", exc)
        return tirados
    for modelo in carregados:
        if modelo in manter or modelo.removesuffix(":latest") in manter:
            continue
        try:
            cliente.dormir(modelo)
            tirados.append(modelo)
        except Exception as exc:
            logger.warning("não consegui descarregar %s: %s", modelo, exc)
    if tirados:
        logger.info("memória no limite: descarreguei %s", ", ".join(tirados))
    return tirados


def garantir_folga(
    cfg: Config,
    precisa_vram_gb: float = 0.0,
    liberar: Callable[[], list[str]] | None = None,
) -> None:
    """Recusa a ação se ela levaria a memória ou a placa de vídeo além do limite do config.

    liberar: chamado antes de recusar (ex.: descarregar modelos parados); depois mede de novo.
    """
    uso = medir()
    if liberar is not None and (
        uso.ram_pct > cfg.limites.ram_pct
        or (
            uso.vram_total_gb
            and 100 * (uso.vram_usada_gb + precisa_vram_gb) / uso.vram_total_gb
            > cfg.limites.vram_pct
        )
    ):
        if liberar():
            time.sleep(1.0)  # o Windows demora um pouco para devolver a memória
            uso = medir()
    if uso.ram_pct > cfg.limites.ram_pct:
        raise ErroExecucao(
            f"memória do PC em {uso.ram_pct:.0f}% (limite {cfg.limites.ram_pct:.0f}%); "
            "feche algum programa e tente de novo"
        )
    if uso.vram_total_gb and precisa_vram_gb:
        depois = 100 * (uso.vram_usada_gb + precisa_vram_gb) / uso.vram_total_gb
        if depois > cfg.limites.vram_pct:
            raise ErroExecucao(
                f"a placa de vídeo ficaria em {depois:.0f}% (limite {cfg.limites.vram_pct:.0f}%); "
                "ponha o agente para dormir ou feche jogos e tente de novo"
            )
