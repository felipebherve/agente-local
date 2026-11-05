"""Ouvir: grava do microfone até uma pausa e transcreve com o faster-whisper, localmente."""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

from agente.config import Config
from agente.voz import ErroVoz

logger = logging.getLogger(__name__)

TAXA = 16_000  # o Whisper trabalha em 16 kHz mono
BLOCO_S = 0.05
CALIBRAR_S = 0.3
DICA = "Comandos: acordar, dormir, status, economia, abrir, parar tudo, libera o braço."

_modelo: Any = None
_trava = threading.Lock()


def _libs_cuda() -> None:
    """No Windows, as DLLs da NVIDIA vêm em pacotes pip; o Python precisa saber onde estão."""
    if sys.platform != "win32":
        return
    import site

    for base in site.getsitepackages():
        for pasta in Path(base, "nvidia").glob("*/bin"):
            os.add_dll_directory(str(pasta))
            os.environ["PATH"] = f"{pasta}{os.pathsep}{os.environ.get('PATH', '')}"


def _carregar(cfg: Config) -> Any:
    global _modelo
    with _trava:
        if _modelo is not None:
            return _modelo
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise ErroVoz("faster-whisper não instalado") from exc
        _libs_cuda()
        try:
            try:  # offline primeiro: só vai à internet se o modelo ainda não foi baixado
                _modelo = WhisperModel(
                    cfg.voz.stt, device="cuda", compute_type="int8_float16", local_files_only=True
                )
            except (OSError, ValueError):
                _modelo = WhisperModel(cfg.voz.stt, device="cuda", compute_type="int8_float16")
            logger.info("whisper %s na placa de vídeo", cfg.voz.stt)
        except (RuntimeError, ValueError, OSError) as exc:
            logger.warning("whisper na placa de vídeo falhou (%s); usando CPU", exc)
            _modelo = WhisperModel(cfg.voz.stt_cpu, device="cpu", compute_type="int8")
        return _modelo


def carregado() -> bool:
    """O Whisper já está na memória (ocupa ~1 GB da placa de vídeo)?"""
    return _modelo is not None


def descarregar() -> None:
    """Tira o Whisper da memória (botão "Desligar ferramentas")."""
    global _modelo
    import gc

    with _trava:
        _modelo = None
    gc.collect()


def preparar(cfg: Config) -> None:
    """Carrega o modelo antes da primeira fala (leva alguns segundos)."""
    _carregar(cfg)


def nivel(bloco: Any) -> float:
    """Volume (RMS) de um bloco de áudio."""
    import numpy as np

    return float(np.sqrt(np.mean(np.square(bloco)))) if len(bloco) else 0.0


def gravar(cfg: Config, aviso: Any = None) -> Any:
    """Grava até uma pausa depois da fala (ou até max_s). Devolve o áudio em float32 16 kHz.

    O limiar de silêncio é calibrado no começo, com o barulho ambiente do momento.
    """
    try:
        import numpy as np
        import sounddevice as sd
    except ImportError as exc:
        raise ErroVoz("sounddevice/numpy não instalados") from exc
    tamanho = int(TAXA * BLOCO_S)
    blocos: list[Any] = []
    try:
        with sd.InputStream(samplerate=TAXA, channels=1, dtype="float32") as entrada:
            ruido = [
                nivel(entrada.read(tamanho)[0][:, 0]) for _ in range(int(CALIBRAR_S / BLOCO_S))
            ]
            limiar = max(0.01, float(np.median(ruido)) * 3)
            if aviso is not None:
                aviso()
            inicio = time.perf_counter()
            falou = False
            quieto_desde = time.perf_counter()
            while time.perf_counter() - inicio < cfg.voz.max_s:
                bloco = entrada.read(tamanho)[0][:, 0].copy()
                blocos.append(bloco)
                if nivel(bloco) > limiar:
                    falou = True
                    quieto_desde = time.perf_counter()
                elif falou and time.perf_counter() - quieto_desde > cfg.voz.silencio_s:
                    break
                elif not falou and time.perf_counter() - inicio > 6:
                    break  # ninguém falou em 6 s
    except sd.PortAudioError as exc:
        raise ErroVoz(f"microfone indisponível: {exc}") from exc
    if not falou:
        return np.zeros(0, dtype="float32")
    return np.concatenate(blocos)


def transcrever(cfg: Config, audio: Any) -> str:
    if len(audio) == 0:
        return ""
    modelo = _carregar(cfg)
    segmentos, _info = modelo.transcribe(
        audio, language="pt", vad_filter=True, beam_size=1, initial_prompt=DICA
    )
    texto = " ".join(s.text.strip() for s in segmentos).strip()
    logger.info("ouvi: %s", texto)
    return texto


def ouvir(cfg: Config, aviso: Any = None) -> str:
    """Grava uma fala e devolve o texto ('' se ninguém falou)."""
    return transcrever(cfg, gravar(cfg, aviso))
