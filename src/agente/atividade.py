"""Quem está trabalhando agora: cada servidor MCP marca o agente em uso num arquivo.

O Claude Desktop e o Claude Code rodam servidores separados; o arquivo deixa a bandeja ver
os dois. Um arquivo por chamada evita que duas ferramentas ao mesmo tempo se atropelem.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

MOSTRAR_DEPOIS_S = 3.0  # a bolinha fica um pouco depois do fim, senão pisca rápido demais
ABANDONADO_S = 600.0  # arquivo velho de um processo que morreu no meio


def pasta(dados: Path) -> Path:
    return dados / "atividade"


@contextmanager
def trabalhando(dados: Path, agente: str) -> Iterator[None]:
    """Marca o agente como em uso enquanto o bloco roda."""
    destino = pasta(dados) / f"{agente}.{os.getpid()}.{uuid.uuid4().hex[:8]}"
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text("rodando", encoding="utf-8")
    except OSError as exc:  # sem marcação a ferramenta ainda funciona
        logger.warning("não marquei atividade de %s: %s", agente, exc)
    try:
        yield
    finally:
        try:
            destino.write_text(f"fim {time.time():.3f}", encoding="utf-8")
        except OSError:
            pass


def ativos(dados: Path, agora: float | None = None) -> set[str]:
    """Agentes rodando agora ou que terminaram há menos de MOSTRAR_DEPOIS_S."""
    agora = time.time() if agora is None else agora
    resultado: set[str] = set()
    try:
        arquivos = list(pasta(dados).iterdir())
    except OSError:
        return resultado
    for arquivo in arquivos:
        agente = arquivo.name.split(".", 1)[0]
        try:
            conteudo = arquivo.read_text(encoding="utf-8")
            idade = agora - arquivo.stat().st_mtime
        except OSError:
            continue
        if conteudo == "rodando" and idade < ABANDONADO_S:
            resultado.add(agente)
        elif conteudo.startswith("fim ") and agora - float(conteudo[4:]) < MOSTRAR_DEPOIS_S:
            resultado.add(agente)
        elif idade > MOSTRAR_DEPOIS_S * 4:
            arquivo.unlink(missing_ok=True)  # limpeza
    return resultado
