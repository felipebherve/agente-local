"""Conversa por voz: entende comandos simples por regra e manda o resto ao Cérebro local.

Comandos de regra respondem na hora, sem gastar placa de vídeo; o resto vira uma pergunta ao
modelo local com instrução de responder curto, porque a resposta vai ser falada.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

SISTEMA_FALADO = (
    "Você é um agente local, respondendo por voz em português do Brasil. "
    "Responda em no máximo três frases curtas, sem listas, sem markdown e sem código. "
    "Se não souber, diga que não sabe."
)


@dataclass(frozen=True)
class Pedido:
    # acordar, dormir, status, economia, parar, liberar, abrir, tocar, buscar, perguntar, nada
    acao: str
    alvo: str = ""


def normalizar(texto: str) -> str:
    """minúsculas, sem acento e sem pontuação: 'Acorde, agente!' -> 'acorde agente'"""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", sem_acento.lower())).strip()


# A ordem importa: "para de dormir" não deve cair em dormir antes de parar, etc.
REGRAS: tuple[tuple[str, str], ...] = (
    ("parar", r"\b(para tudo|parar tudo|pare tudo|emergencia|desliga o braco|para o braco)\b"),
    ("liberar", r"\b(libera o braco|liga o braco|religa o braco)\b"),
    ("dormir", r"\b(dorm\w*|libera\w* a placa)\b"),
    ("acordar", r"\b(acord\w*|desperta\w*)\b"),
    ("status", r"^(status|como (voce )?(esta|ta)|tudo bem)\b"),
    ("economia", r"\b(economi\w*|tokens? poupad\w*)\b"),
)
ABRIR = re.compile(
    r"^(abr[ae]|abrir|abre ai|inicia|iniciar|execut[ae])\s+(o |a |os |as )?(?P<alvo>.+)$"
)
# "no youtube"/"pra tocar" no final é só reforço: tanto faz dizer ou não.
TOCAR = re.compile(
    r"^(toque|toca|tocar|coloca|colocar|bota)\s+"
    r"(?P<musica>.+?)(?:\s+(no youtube|pra tocar|para tocar))?$"
)
BUSCAR = re.compile(
    r"^(busca|buscar|procura|procurar|ach[ae]|achar|encontr[ae]|encontrar)\s+"
    r"(o |a |os |as |um |uma )?arquivos?\s+(?P<nome>.+)$"
)


def interpretar(texto: str) -> Pedido:
    frase = normalizar(texto)
    if not frase:
        return Pedido("nada")
    aberto = ABRIR.match(frase)
    if aberto:
        return Pedido("abrir", aberto.group("alvo"))
    tocar = TOCAR.match(frase)
    if tocar:
        return Pedido("tocar", tocar.group("musica"))
    buscar = BUSCAR.match(frase)
    if buscar:
        return Pedido("buscar", buscar.group("nome"))
    curta = len(frase.split()) <= 6  # comandos são curtos; frase longa é pergunta
    for acao, padrao in REGRAS:
        if curta and re.search(padrao, frase):
            return Pedido(acao)
    return Pedido("perguntar", texto.strip())
