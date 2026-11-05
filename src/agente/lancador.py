"""Ícone do agente e atalhos do Windows (área de trabalho e inicialização automática)."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from agente.config import Config

if TYPE_CHECKING:
    from PIL.Image import Image

logger = logging.getLogger(__name__)

NOME_ATALHO = "Acordar Agente.lnk"
CORES = {
    "acordado": (34, 170, 90),  # verde: modelo na placa de vídeo, resposta imediata
    "dormindo": (110, 110, 120),  # cinza: placa de vídeo livre
    "fora": (200, 60, 50),  # vermelho: Ollama fora do ar
}


class ErroLancador(Exception):
    """Não deu para criar ou remover um atalho do Windows."""


def desenhar_icone(estado: str = "acordado", tamanho: int = 64) -> Image:
    """Círculo colorido com 'IA' no meio; a cor mostra o estado do agente."""
    from PIL import Image, ImageDraw, ImageFont

    imagem = Image.new("RGBA", (tamanho, tamanho), (0, 0, 0, 0))
    desenho = ImageDraw.Draw(imagem)
    margem = tamanho // 16
    desenho.ellipse(
        (margem, margem, tamanho - margem, tamanho - margem), fill=CORES.get(estado, CORES["fora"])
    )
    try:
        fonte: ImageFont.FreeTypeFont | ImageFont.ImageFont = ImageFont.truetype(
            "arialbd.ttf", tamanho // 2
        )
    except OSError:
        fonte = ImageFont.load_default()
    desenho.text((tamanho / 2, tamanho / 2), "IA", fill="white", font=fonte, anchor="mm")
    return imagem


def salvar_ico(cfg: Config) -> Path:
    destino = cfg.pasta_dados / "agente.ico"
    destino.parent.mkdir(parents=True, exist_ok=True)
    desenhar_icone("acordado", 256).save(destino, sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
    return destino


def executavel_bandeja() -> Path:
    """O .exe sem janela de console que o pip cria no venv (gui-script)."""
    exe = Path(sys.executable).parent / "agente-bandeja.exe"
    if not exe.exists():
        raise ErroLancador(f"{exe} não existe; rode 'pip install -e .' no venv do agente")
    return exe


def _pasta_especial(nome: str) -> Path:
    import win32com.client

    shell = win32com.client.Dispatch("WScript.Shell")
    return Path(str(shell.SpecialFolders(nome)))


def _criar_lnk(
    destino: Path, alvo: Path, icone: Path, descricao: str, argumentos: str = ""
) -> None:
    import win32com.client

    shell = win32com.client.Dispatch("WScript.Shell")
    atalho = shell.CreateShortcut(str(destino))
    atalho.TargetPath = str(alvo)
    atalho.Arguments = argumentos
    atalho.WorkingDirectory = str(alvo.parent)
    atalho.IconLocation = f"{icone},0"
    atalho.Description = descricao
    atalho.Save()


def criar_atalho_area_de_trabalho(cfg: Config) -> Path:
    destino = _pasta_especial("Desktop") / NOME_ATALHO
    try:
        _criar_lnk(destino, executavel_bandeja(), salvar_ico(cfg), "Acorda o agente local de IA")
    except OSError as exc:
        raise ErroLancador(f"não consegui criar {destino}: {exc}") from exc
    logger.info("atalho criado: %s", destino)
    return destino


def _lnk_inicializar() -> Path:
    return _pasta_especial("Startup") / NOME_ATALHO


def inicia_com_windows() -> bool:
    return sys.platform == "win32" and _lnk_inicializar().exists()


def iniciar_com_windows(cfg: Config, ligar: bool) -> None:
    """Liga ou desliga o agente na inicialização (atalho na pasta Inicializar do usuário)."""
    destino = _lnk_inicializar()
    try:
        if ligar:
            # Na inicialização só o ícone aparece, sem abrir o painel.
            _criar_lnk(
                destino, executavel_bandeja(), salvar_ico(cfg), "Agente local de IA", "--sem-painel"
            )
        else:
            destino.unlink(missing_ok=True)
    except OSError as exc:
        raise ErroLancador(f"não consegui mudar {destino}: {exc}") from exc
    logger.info("iniciar com o Windows: %s", ligar)


def abrir(caminho: Path) -> None:
    """Abre uma pasta ou arquivo com o programa padrão do Windows."""
    os.startfile(caminho)  # só existe no Windows
