"""Falar: transforma texto em voz com o Piper (voz brasileira, roda na CPU) e toca."""

from __future__ import annotations

import logging
import re
import threading
import urllib.request
from pathlib import Path
from typing import Any

from agente.config import Config
from agente.voz import ErroVoz

logger = logging.getLogger(__name__)

URL_VOZES = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
MAX_CARACTERES = 1200  # fala longa demais cansa; o resto vai por escrito

_vozes: dict[str, Any] = {}
_trava = threading.Lock()


def _url(nome: str, extensao: str) -> str:
    """pt_BR-faber-medium -> .../pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx"""
    try:
        local, voz, qualidade = nome.split("-")
    except ValueError as exc:
        raise ErroVoz(f"nome de voz inválido: '{nome}' (ex.: pt_BR-faber-medium)") from exc
    idioma = local.split("_")[0]
    return f"{URL_VOZES}/{idioma}/{local}/{voz}/{qualidade}/{nome}{extensao}"


def baixar_voz(cfg: Config) -> Path:
    """Baixa a voz do Piper uma vez para dados/vozes (cerca de 60 MB)."""
    pasta = cfg.pasta_dados / "vozes"
    pasta.mkdir(parents=True, exist_ok=True)
    modelo = pasta / f"{cfg.voz.tts}.onnx"
    for extensao in (".onnx", ".onnx.json"):
        destino = pasta / f"{cfg.voz.tts}{extensao}"
        if destino.exists():
            continue
        logger.info("baixando voz %s%s", cfg.voz.tts, extensao)
        temporario = destino.with_suffix(destino.suffix + ".parcial")
        try:
            urllib.request.urlretrieve(_url(cfg.voz.tts, extensao), temporario)
        except OSError as exc:
            temporario.unlink(missing_ok=True)
            raise ErroVoz(f"não consegui baixar a voz {cfg.voz.tts}: {exc}") from exc
        temporario.replace(destino)
    return modelo


def _voz(cfg: Config) -> Any:
    with _trava:
        if cfg.voz.tts not in _vozes:
            try:
                from piper import PiperVoice
            except ImportError as exc:
                raise ErroVoz("piper-tts não instalado") from exc
            _vozes[cfg.voz.tts] = PiperVoice.load(str(baixar_voz(cfg)))
        return _vozes[cfg.voz.tts]


def limpar(texto: str) -> str:
    """Tira o que soa mal em voz alta: markdown, links, blocos de código.

    Tira também a etiqueta de origem no começo ("[Ollama local · qwen3:8b] ...",
    "[OmniRoute · modelo] ..."): faz sentido ler na tela, não faz sentido falado.
    """
    texto = re.sub(r"^\[[^\]]+\]\s*", "", texto)
    texto = re.sub(r"```.*?```", " (trecho de código) ", texto, flags=re.DOTALL)
    texto = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", texto)
    texto = re.sub(r"https?://\S+", "link", texto)
    texto = re.sub(r"[*_`#>|]+", "", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    if len(texto) > MAX_CARACTERES:
        corte = texto.rfind(".", 0, MAX_CARACTERES)
        texto = texto[: corte + 1 if corte > 0 else MAX_CARACTERES]
    return texto


def sintetizar(cfg: Config, texto: str) -> tuple[Any, int]:
    """Devolve (áudio int16, taxa de amostragem)."""
    import numpy as np

    voz = _voz(cfg)
    partes = [p.audio_int16_array for p in voz.synthesize(texto)]
    audio = np.concatenate(partes) if partes else np.zeros(0, dtype="int16")
    return audio, int(voz.config.sample_rate)


def falar(cfg: Config, texto: str) -> str:
    """Fala o texto no alto-falante padrão e espera terminar."""
    limpo = limpar(texto)
    if not limpo:
        return "Nada para falar."
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise ErroVoz("sounddevice não instalado") from exc
    audio, taxa = sintetizar(cfg, limpo)
    try:
        sd.play(audio, taxa)
        sd.wait()
    except sd.PortAudioError as exc:
        raise ErroVoz(f"alto-falante indisponível: {exc}") from exc
    logger.info("falei %d caracteres", len(limpo))
    return f"Falei em voz alta ({len(audio) / taxa:.0f} s)."
