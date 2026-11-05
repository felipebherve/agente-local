"""Degrau do meio entre o Cérebro local e o Claude: IA grátis na nuvem via OmniRoute.

O OmniRoute (github.com/diegosouzapw/OmniRoute) roda local em dado endereço (padrão
127.0.0.1:20128) e expõe um endpoint compatível com a API da OpenAI, roteando cada
pedido para um provedor grátis conectado no painel dele. Sem o OmniRoute no ar, ou sem
nenhum provedor conectado, `perguntar` devolve None e quem chamou segue para o Claude —
nunca trava o Porteiro.

cfg.omniroute.modelos é uma fila: tenta cada "provedor/modelo" na ordem até um
responder. Veja o comentário ao lado dela em config.py para adicionar mais.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

from agente.config import Config

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Resposta:
    modelo: str
    texto: str
    provedor: str = ""
    tokens_total: int = 0


def _tentar(cfg: Config, modelo: str, pergunta: str, sistema: str) -> Resposta | None:
    corpo = {
        "model": modelo,
        "messages": [
            {"role": "system", "content": sistema},
            {"role": "user", "content": pergunta},
        ],
        "max_tokens": cfg.max_tokens,
    }
    req = urllib.request.Request(
        f"{cfg.omniroute.url}/chat/completions",
        data=json.dumps(corpo).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg.omniroute.timeout_s) as r:
            dados = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.info("omniroute (%s) indisponível: %s", modelo, exc)
        return None
    try:
        texto = str(dados["choices"][0]["message"]["content"]).strip()
        modelo_usado = str(dados.get("model", modelo))
    except (KeyError, IndexError, TypeError) as exc:
        logger.info("resposta inesperada do omniroute (%s): %s", modelo, exc)
        return None
    provedor = modelo.split("/", 1)[0]
    tokens_total = int(dados.get("usage", {}).get("total_tokens", 0) or 0)
    return Resposta(modelo_usado, texto, provedor, tokens_total) if texto else None


def perguntar(cfg: Config, pergunta: str, sistema: str) -> Resposta | None:
    """Tenta cada modelo de cfg.omniroute.modelos, na ordem, até um responder algo útil."""
    if not cfg.omniroute.ligado:
        return None
    for modelo in cfg.omniroute.modelos:
        resposta = _tentar(cfg, modelo, pergunta, sistema)
        if resposta is not None:
            return resposta
    return None
