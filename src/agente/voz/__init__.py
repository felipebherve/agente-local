"""Voz do agente: ouvir (faster-whisper), falar (Piper) e conversar, tudo no PC."""

from __future__ import annotations


class ErroVoz(Exception):
    """Microfone, alto-falante ou modelo de voz indisponível."""
