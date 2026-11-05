"""Comando padrão (abrir, tocar, buscar) do Porteiro para quem não é a bandeja: o
terminal (`agente pedir`) e a ferramenta MCP do Claude (`pedir_ao_agente`).

A bandeja tem o próprio dispatch em bandeja.py (fala em voz, controla acordar/dormir
etc.); aqui é só o que faz sentido fora dela.
"""

from __future__ import annotations

from collections.abc import Callable

from agente.config import Config


def padrao(cfg: Config) -> Callable[[str], str]:
    """Fecha sobre `cfg` um `executar_comando` para passar a `porteiro.resolver`."""
    from agente import memoria
    from agente.braco import navegador
    from agente.voz.conversa import interpretar

    def comando(texto: str) -> str:
        pedido = interpretar(texto)
        if pedido.acao == "abrir":
            return navegador.resolver_abrir(cfg, pedido.alvo)
        if pedido.acao == "tocar":
            return navegador.navegador(cfg).tocar(pedido.alvo)
        if pedido.acao == "buscar":
            achados = memoria.buscar_arquivos(cfg, pedido.alvo)
            if not achados:
                return f"Não achei nenhum arquivo com '{pedido.alvo}'."
            return "\n".join(str(p) for p in achados)
        return "PRECISA DO CLAUDE: faça você mesmo."

    return comando
