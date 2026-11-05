"""Registra quanto texto o agente deixou de mandar ao Claude (estimativa de tokens poupados)."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from agente.config import Config

logger = logging.getLogger(__name__)

CARACTERES_POR_TOKEN = 4


def _arquivo(cfg: Config) -> Path:
    return cfg.pasta_logs / "economia.jsonl"


def registrar(cfg: Config, tarefa: str, chars_brutos: int, chars_resumo: int) -> int:
    """Anota uma tarefa delegada e devolve os tokens poupados estimados."""
    poupados = max(0, (chars_brutos - chars_resumo) // CARACTERES_POR_TOKEN)
    linha = {
        "quando": datetime.now().isoformat(timespec="seconds"),
        "tarefa": tarefa,
        "chars_brutos": chars_brutos,
        "chars_resumo": chars_resumo,
        "tokens_poupados": poupados,
    }
    try:
        cfg.pasta_logs.mkdir(parents=True, exist_ok=True)
        with _arquivo(cfg).open("a", encoding="utf-8") as f:
            f.write(json.dumps(linha, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("não consegui registrar economia: %s", exc)
    return poupados


def total(cfg: Config) -> int:
    """Tokens poupados somados desde o começo."""
    try:
        linhas = _arquivo(cfg).read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    soma = 0
    for bruto in linhas:
        try:
            soma += int(json.loads(bruto)["tokens_poupados"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    return soma


def pontos(cfg: Config) -> list[tuple[str, int]]:
    """(quando ISO, tokens poupados) de cada tarefa, para o gráfico do painel."""
    try:
        linhas = _arquivo(cfg).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    resultado = []
    for bruto in linhas:
        try:
            item = json.loads(bruto)
            resultado.append((str(item["quando"]), int(item["tokens_poupados"])))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    return resultado


def relatorio(cfg: Config) -> str:
    """Resumo da economia acumulada, por tipo de tarefa."""
    arquivo = _arquivo(cfg)
    if not arquivo.exists():
        return "Nenhuma tarefa registrada ainda."
    por_tarefa: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for bruto in arquivo.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(bruto)
        except json.JSONDecodeError:
            continue
        por_tarefa[item["tarefa"]][0] += 1
        por_tarefa[item["tarefa"]][1] += int(item["tokens_poupados"])
    total = sum(t for _, t in por_tarefa.values())
    vezes = sum(n for n, _ in por_tarefa.values())
    linhas = [f"Tokens poupados (estimativa): {total:,} em {vezes} tarefas".replace(",", ".")]
    for tarefa, (n, tokens) in sorted(por_tarefa.items(), key=lambda kv: -kv[1][1]):
        linhas.append(f"- {tarefa}: {tokens:,} tokens em {n}x".replace(",", "."))
    return "\n".join(linhas)
