"""Atalhos de teclado globais pelo RegisterHotKey do Windows.

Só o atalho registrado chega ao programa: nada do resto do teclado é escutado.
"""

from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x4000
WM_HOTKEY = 0x0312
_MODS = {"ctrl": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT}


def traduzir(atalho: str) -> tuple[int, int]:
    """'ctrl+alt+p' -> (modificadores, código da tecla). Só letras e números na tecla final."""
    partes = [p.strip().lower() for p in atalho.split("+") if p.strip()]
    if not partes or len(partes[-1]) != 1 or not partes[-1].isalnum():
        raise ValueError(f"atalho inválido: '{atalho}' (use algo como ctrl+alt+a)")
    mods = MOD_NOREPEAT
    for parte in partes[:-1]:
        if parte not in _MODS:
            raise ValueError(f"modificador desconhecido '{parte}' em '{atalho}'")
        mods |= _MODS[parte]
    return mods, ord(partes[-1].upper())


def _escutar(
    mods: int, tecla: int, acao: Callable[[], None], pronto: threading.Event, ok: list[int]
) -> None:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined,unused-ignore]  # só Windows
    ok.append(bool(user32.RegisterHotKey(None, 1, mods, tecla)))
    ok.append(threading.get_native_id())  # para cancelar() achar a thread
    pronto.set()
    if not ok[0]:
        return
    msg = wintypes.MSG()
    try:
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                try:
                    acao()
                except Exception:  # o atalho não pode morrer por causa de uma ação que falhou
                    logger.exception("ação do atalho falhou")
    finally:
        user32.UnregisterHotKey(None, 1)


_ativos: dict[str, int] = {}  # atalho -> id da thread que o escuta


def registrar(atalho: str, acao: Callable[[], None]) -> bool:
    """Registra o atalho numa thread própria. Devolve False se outro programa já o usa."""
    if sys.platform != "win32":
        return False
    mods, tecla = traduzir(atalho)
    pronto = threading.Event()
    ok: list[int] = []
    threading.Thread(
        target=_escutar, args=(mods, tecla, acao, pronto, ok), name=f"atalho {atalho}", daemon=True
    ).start()
    pronto.wait(5)
    registrado = bool(ok and ok[0])
    if registrado:
        _ativos[atalho] = int(ok[1])
    else:
        logger.warning("atalho %s indisponível (outro programa já usa?)", atalho)
    return registrado


def cancelar(atalho: str) -> None:
    """Solta um atalho registrado por registrar() (para trocar de tecla sem reiniciar)."""
    thread = _ativos.pop(atalho, None)
    if thread is not None and sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.PostThreadMessageW(thread, 0x0012, 0, 0)  # WM_QUIT
