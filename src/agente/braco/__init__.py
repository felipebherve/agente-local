"""O braço: controle do navegador, das janelas do Windows e, em último caso, do mouse."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as TempoEsgotado
from typing import TypeVar

from agente.executor import ErroExecucao

T = TypeVar("T")


class ThreadUnica:
    """Roda tudo numa mesma thread: Playwright síncrono e COM do Windows exigem isso."""

    def __init__(self, nome: str) -> None:
        self._exec = ThreadPoolExecutor(max_workers=1, thread_name_prefix=nome)

    def rodar(self, fn: Callable[[], T], timeout_s: float = 120) -> T:
        futuro = self._exec.submit(fn)
        try:
            return futuro.result(timeout=timeout_s)
        except TempoEsgotado as exc:
            raise ErroExecucao(f"a ação passou de {timeout_s:.0f}s") from exc
