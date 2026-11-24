"""Botões "Acordar Agente" e "Desligar Agente" do app.

Desligado, o agente inteiro para: os agentes ficam pausados (os mesmos arquivos de pausa
que o painel e a bandeja usam), o Braço fica com a parada de emergência ligada, os
modelos saem da placa de vídeo e as ferramentas do Claude respondem que o agente está
desligado. O painel continua no ar, bem leve, para dar para acordar pelo celular.
"""

from __future__ import annotations

import logging
from pathlib import Path

from agente.config import Config
from agente.llm import ClienteOllama, ErroOllama

logger = logging.getLogger(__name__)

ARQUIVO = "agente-desligado"
PAUSAS = ("maestro-pausado", "porteiro-pausado", "memoria-pausada", "revisor-pausado")
AVISO_MCP = (
    "AGENTE DESLIGADO: o usuário desligou o agente local no app (botão 'Acordar Agente' "
    "liga de novo). Faça você mesmo, sem chamar as ferramentas do agente."
)


def _sinal(cfg: Config) -> Path:
    return cfg.pasta_dados / ARQUIVO


def desligado(cfg: Config) -> bool:
    return _sinal(cfg).exists()


def desligar(cfg: Config, cliente: ClienteOllama | None = None) -> None:
    """Desliga tudo. Nunca falha por causa do Ollama fora do ar."""
    from agente.braco import seguranca

    cfg.pasta_dados.mkdir(parents=True, exist_ok=True)
    _sinal(cfg).write_text("desligado", encoding="utf-8")
    for nome in PAUSAS:
        (cfg.pasta_dados / nome).write_text("pausado", encoding="utf-8")
    seguranca.parar()
    cliente = cliente or ClienteOllama.de_config(cfg)
    try:
        for modelo in cliente.modelos_carregados():
            cliente.dormir(modelo)
    except (ErroOllama, OSError) as exc:  # Ollama fechado: já não tem nada na placa
        logger.info("não deu para tirar os modelos da placa: %s", exc)
    logger.info("agente desligado")


def acordar(cfg: Config) -> None:
    from agente.braco import seguranca

    _sinal(cfg).unlink(missing_ok=True)
    for nome in PAUSAS:
        (cfg.pasta_dados / nome).unlink(missing_ok=True)
    seguranca.liberar()
    logger.info("agente acordado")
