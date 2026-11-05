"""Resumo local de textos e arquivos grandes, com registro da economia."""

from __future__ import annotations

from pathlib import Path

from agente.compactar import compactar
from agente.config import Config
from agente.economia import registrar
from agente.executor import ErroExecucao, validar_pasta
from agente.llm import ClienteOllama

SISTEMA = (
    "Você é um assistente técnico local. Responda em português do Brasil, "
    "direto ao ponto e no menor texto possível."
)
LIMITE_ENTRADA = 60_000


def resumir_texto(
    cfg: Config, cliente: ClienteOllama, texto: str, foco: str = "", tarefa: str = "resumo"
) -> str:
    pedido = (
        f"TEXTO:\n{compactar(texto)[-LIMITE_ENTRADA:]}\n\n---\n"
        f"Resuma o texto acima em no máximo 5 linhas{': ' + foco if foco else ''}."
    )
    resumo = cliente.conversar(cfg.modelos.codigo, pedido, sistema=SISTEMA).texto
    registrar(cfg, tarefa, len(texto), len(resumo))
    return resumo


def resumir_arquivo(
    cfg: Config, cliente: ClienteOllama, caminho: str | Path, foco: str = ""
) -> str:
    arquivo = validar_pasta(cfg, caminho)
    if not arquivo.is_file():
        raise ErroExecucao(f"não é um arquivo: {arquivo}")
    texto = arquivo.read_text(encoding="utf-8", errors="replace")
    return resumir_texto(cfg, cliente, texto, foco, "resumo de arquivo")
