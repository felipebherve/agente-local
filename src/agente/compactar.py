"""Compacta textos longos sem IA antes de mandar ao modelo local.

Modelos pequenos se perdem em logs repetitivos; filtrar primeiro deixa o resumo certo e rápido.
"""

from __future__ import annotations

import re
from collections import Counter

IMPORTANTE = re.compile(
    r"fail|error|erro|exception|traceback|assert|warn|panic|fatal|^E\s", re.IGNORECASE
)
CAUDA = 30


def _sem_repeticao(linhas: list[str]) -> list[str]:
    """Mantém a primeira ocorrência de cada linha e anota quantas vezes ela apareceu."""
    contagem = Counter(linha.strip() for linha in linhas)
    vistas: set[str] = set()
    saida: list[str] = []
    for linha in linhas:
        chave = linha.strip()
        if not chave or chave in vistas:
            continue
        vistas.add(chave)
        n = contagem[chave]
        saida.append(f"{linha.rstrip()}  (x{n})" if n > 1 else linha.rstrip())
    return saida


def compactar(texto: str, limite: int = 12_000) -> str:
    """Remove repetições e, se ainda for grande, fica com as linhas de erro e o final."""
    linhas = _sem_repeticao(texto.splitlines())
    resultado = "\n".join(linhas)
    if len(resultado) <= limite:
        return resultado
    importantes = [linha for linha in linhas[:-CAUDA] if IMPORTANTE.search(linha)]
    omitidas = len(linhas) - len(importantes) - CAUDA
    partes = [*importantes, f"[... {omitidas} linhas sem erro omitidas ...]", *linhas[-CAUDA:]]
    return "\n".join(partes)[-limite:]
