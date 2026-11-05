"""Print da tela descrito pelo modelo de visão local: o Claude recebe texto, nunca a imagem.

A visão de 7B descreve bem, mas erra a posição dos cliques (testado: 50 a 150 px fora),
então clicar fica com a acessibilidade do Windows (janelas.clicar_em_qualquer).
"""

from __future__ import annotations

import base64
import ctypes
import io
import logging
from dataclasses import dataclass

from agente.braco.seguranca import verificar
from agente.config import Config
from agente.economia import registrar
from agente.executor import ErroExecucao
from agente.llm import ClienteOllama

logger = logging.getLogger(__name__)

LARGURA_ENVIADA = 1288


def _dpi_real() -> None:
    """Faz o print usar pixels reais em telas com escala do Windows."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        pass


_dpi_real()


@dataclass(frozen=True)
class Captura:
    png_base64: str
    largura: int
    altura: int


def capturar() -> Captura:
    """Print do monitor principal, reduzido para LARGURA_ENVIADA (mais rápido para a visão)."""
    try:
        import mss
        from PIL import Image
    except ImportError as exc:
        raise ErroExecucao(f"falta biblioteca de captura: {exc}") from exc
    fabrica = getattr(mss, "MSS", None) or mss.mss
    with fabrica() as sct:
        # monitors[0] é a área de todos juntos; a ordem dos demais não garante o principal.
        monitor = next((m for m in sct.monitors[1:] if m.get("is_primary")), sct.monitors[1])
        bruto = sct.grab(monitor)
    imagem = Image.frombytes("RGB", bruto.size, bruto.bgra, "raw", "BGRX")
    if imagem.width > LARGURA_ENVIADA:
        altura = round(imagem.height * LARGURA_ENVIADA / imagem.width)
        imagem = imagem.resize((LARGURA_ENVIADA, altura))
    buffer = io.BytesIO()
    imagem.save(buffer, format="PNG")
    return Captura(base64.b64encode(buffer.getvalue()).decode("ascii"), imagem.width, imagem.height)


def descrever(cfg: Config, cliente: ClienteOllama, pergunta: str = "") -> str:
    """Descreve a tela em poucas linhas, sem mandar imagem nenhuma para o Claude."""
    verificar()
    cap = capturar()
    pedido = pergunta or "Descreva em até 5 linhas o que está na tela: app aberto, janela e ação."
    resposta = cliente.conversar(cfg.modelos.visao, pedido, imagens=[cap.png_base64]).texto
    registrar(cfg, "descrever tela", len(cap.png_base64) // 3, len(resposta))
    return resposta
