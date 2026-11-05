"""Benchmark rápido dos modelos configurados no hardware local."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from agente.config import Config
from agente.llm import ClienteOllama, ErroOllama

logger = logging.getLogger(__name__)

PERGUNTA = (
    "Resuma em 2 linhas, em português: o teste test_login falhou com "
    "AssertionError: esperado status 200, recebido 401, após trocar a chave JWT."
)


@dataclass(frozen=True)
class Resultado:
    papel: str
    modelo: str
    ok: bool
    segundos: float
    tokens_por_s: float
    amostra: str


def _testar_chat(cliente: ClienteOllama, papel: str, modelo: str) -> Resultado:
    try:
        cliente.acordar(modelo)
        r = cliente.conversar(modelo, PERGUNTA)
        return Resultado(papel, modelo, True, r.segundos, r.tokens_por_s, r.texto[:160])
    except ErroOllama as exc:
        logger.error("benchmark %s falhou: %s", modelo, exc)
        return Resultado(papel, modelo, False, 0.0, 0.0, str(exc)[:160])


def _testar_embeddings(cliente: ClienteOllama, modelo: str) -> Resultado:
    try:
        inicio = time.perf_counter()
        vetores = cliente.embutir(modelo, [PERGUNTA] * 8)
        segundos = time.perf_counter() - inicio
        return Resultado(
            "embeddings", modelo, bool(vetores), segundos, 0.0, f"{len(vetores)} vetores"
        )
    except ErroOllama as exc:
        logger.error("benchmark %s falhou: %s", modelo, exc)
        return Resultado("embeddings", modelo, False, 0.0, 0.0, str(exc)[:160])


def rodar_benchmark(cfg: Config, cliente: ClienteOllama) -> list[Resultado]:
    """Mede cada modelo e descarrega da GPU ao terminar, para não acumular VRAM."""
    m = cfg.modelos
    resultados: list[Resultado] = []
    for papel, modelo in (("cerebro", m.cerebro), ("codigo", m.codigo), ("visao", m.visao)):
        resultados.append(_testar_chat(cliente, papel, modelo))
        try:
            cliente.dormir(modelo)
        except ErroOllama as exc:
            logger.warning("não consegui descarregar %s: %s", modelo, exc)
    resultados.append(_testar_embeddings(cliente, m.embeddings))
    return resultados


def formatar(resultados: list[Resultado]) -> str:
    linhas = [f"{'papel':<11}{'modelo':<22}{'ok':<4}{'tempo':>8}{'tok/s':>8}"]
    for r in resultados:
        linhas.append(
            f"{r.papel:<11}{r.modelo:<22}{'sim' if r.ok else 'NAO':<4}"
            f"{r.segundos:>7.1f}s{r.tokens_por_s:>8.1f}"
        )
    linhas.append("")
    linhas += [f"[{r.papel}] {r.amostra}" for r in resultados]
    return "\n".join(linhas)
