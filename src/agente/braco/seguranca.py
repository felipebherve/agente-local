"""Travas do braço: parada de emergência e confirmação antes de ações que não se desfazem."""

from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path

from agente import atalho
from agente.executor import ConfirmacaoNecessaria, ErroExecucao

logger = logging.getLogger(__name__)

ATALHO_EMERGENCIA = "ctrl+alt+p"
ARRISCADO = re.compile(
    r"enviar|submit|comprar|pagar|pagamento|finalizar|confirmar|excluir|apagar|deletar|"
    r"remover|entrar|login|log in|sign in|assinar|transferir|publicar|postar|send|buy|pay|"
    r"checkout|delete|remove|purchase|order|pedido",
    re.IGNORECASE,
)

# Arquivo-sinal: o Claude Desktop e o Claude Code rodam cada um o seu servidor, mas só um
# consegue registrar o atalho; o arquivo faz a parada valer para todos.
SINAL_PARADA = Path(tempfile.gettempdir()) / "agente-local-PARADO"
_atalho_ativo = False


class ParadaDeEmergencia(ErroExecucao):
    """O usuário apertou a tecla de emergência."""


def parar() -> None:
    SINAL_PARADA.touch()
    logger.warning("PARADA DE EMERGÊNCIA acionada")


def liberar() -> None:
    SINAL_PARADA.unlink(missing_ok=True)
    logger.info("braço liberado após parada de emergência")


def ativar_atalho() -> bool:
    """Registra Ctrl+Alt+P como parada de emergência global. Devolve se conseguiu."""
    global _atalho_ativo
    if not _atalho_ativo:
        _atalho_ativo = atalho.registrar(ATALHO_EMERGENCIA, parar)
    return _atalho_ativo


def verificar() -> None:
    if SINAL_PARADA.exists():
        raise ParadaDeEmergencia(
            "parada de emergência ativa (Ctrl+Alt+P). Pergunte ao usuário e chame braco_liberar"
        )


def exigir_confirmacao(descricao: str, confirmado: bool, motivo: str = "") -> None:
    """Bloqueia ações cujo texto sugere enviar, logar, pagar ou apagar, sem o OK do usuário."""
    if confirmado:
        return
    if motivo or ARRISCADO.search(descricao):
        explicacao = motivo or "parece enviar, logar, pagar ou apagar algo"
        raise ConfirmacaoNecessaria(f"'{descricao[:80]}' {explicacao}")
