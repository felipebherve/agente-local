"""Histórico dos pedidos feitos ao agente (caixa do painel, voz, Claude e terminal).

Cada pedido vira uma linha em dados/historico.jsonl: quando, o pedido, quem resolveu, um
resumo da resposta e os tokens (gastos aqui, de graça, e poupados do Claude).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from agente.config import Config
from agente.economia import CARACTERES_POR_TOKEN

logger = logging.getLogger(__name__)

RESUMO_MAX = 160


@dataclass(frozen=True)
class Registro:
    quando: str  # 2026-10-26 18:24:31
    pedido: str
    agente: str
    destino: str  # "local", "nuvem" ou "claude"
    resumo: str
    tokens_locais: int  # processados no PC (de graça)
    tokens_poupados: int  # que o Claude deixou de gastar
    segundos: float
    resposta_completa: str = ""  # texto inteiro, pro painel mostrar (resumo é só pra lista)


def _arquivo(cfg: Config) -> Path:
    return cfg.pasta_dados / "historico.jsonl"


def resumir(texto: str, limite: int = RESUMO_MAX) -> str:
    linha = " ".join(texto.split())
    return linha if len(linha) <= limite else linha[: limite - 1].rstrip() + "…"


def registrar(
    cfg: Config, pedido: str, agente: str, destino: str, resposta: str, segundos: float
) -> Registro:
    tokens = (len(pedido) + len(resposta)) // CARACTERES_POR_TOKEN
    registro = Registro(
        quando=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        pedido=resumir(pedido, 200),
        agente=agente,
        destino=destino,
        resumo=resumir(resposta),
        tokens_locais=tokens,
        tokens_poupados=tokens if destino in ("local", "nuvem") else 0,
        segundos=round(segundos, 1),
        resposta_completa=resposta,
    )
    try:
        cfg.pasta_dados.mkdir(parents=True, exist_ok=True)
        with _arquivo(cfg).open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(registro), ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("não registrei o pedido no histórico: %s", exc)
    return registro


def ler(cfg: Config, limite: int = 500) -> list[Registro]:
    """Os pedidos mais recentes primeiro."""
    try:
        linhas = _arquivo(cfg).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    registros = []
    for bruta in reversed(linhas[-limite:]):
        try:
            registros.append(Registro(**json.loads(bruta)))
        except (json.JSONDecodeError, TypeError):
            continue
    return registros
