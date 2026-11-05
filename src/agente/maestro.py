"""Maestro (Fase 10): lê o pedido e escolhe qual agente cuida dele.

A escolha é por regras, sem modelo: revisar, testar, ver o que mudou e achar algo num
projeto vão direto ao agente certo; o resto passa ao Porteiro, que resolve aqui ou manda
ao Claude.

Fluido: o Maestro liga o agente escolhido mesmo que esteja desligado no painel, tira da
memória os modelos que não servem para a tarefa (se a memória estiver no limite) e, no
fim, desliga o modelo que ele mesmo carregou depois de DESLIGAR_APOS sem uso.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agente import atividade
from agente.config import Config
from agente.voz.conversa import normalizar

logger = logging.getLogger(__name__)

REVISAR = re.compile(r"\b(revis\w*|confer\w*|chec\w*|lint|verifiqu\w*|verific\w*)\b")
TESTAR = re.compile(
    r"\b(rod\w*|execut\w*|pass\w*|quebr\w*|falh\w*)\b.*\btestes?\b"
    r"|\btestes?\b.*\b(rod\w*|pass\w*|quebr\w*|falh\w*)\b"
)
MUDOU = re.compile(
    r"\b(git status|status do git|o que (mudou|alterei|mexi)|"
    r"(arquivos|coisas) (alterad|mudad|modificad)\w*|alteracoes pendentes)\b"
)
ACHAR = re.compile(
    r"\b(onde (fica|esta|e feito|e feita|tem|mexe)|procur\w*|ach\w*|encontr\w*|"
    r"(qual|que|em que) arquivo|em qual arquivo)\b"
)
COMUNS = {"agente", "projeto", "sistema", "codigo"}  # palavras que não bastam como nome
# Pausa de cada agente no painel (arquivo em dados/).
PAUSAS = {
    "Revisor": "revisor-pausado",
    "Memória": "memoria-pausada",
    "Porteiro": "porteiro-pausado",
}
DESLIGAR_APOS = "2m"  # modelo que o Maestro carregou sai da placa depois disso sem uso


@dataclass(frozen=True)
class Rota:
    agente: str  # Revisor, Testes, Git, Memória ou Porteiro
    projeto: Path | None
    motivo: str


@dataclass(frozen=True)
class Resultado:
    agente: str
    destino: str  # "local", "nuvem" ou "claude"
    resposta: str


def modelos_do_agente(cfg: Config, agente: str) -> set[str]:
    """Modelos que o agente usa (o Revisor e o Git não precisam de nenhum)."""
    return {
        "Porteiro": {cfg.modelos.cerebro},
        "Memória": {cfg.modelos.embeddings},
        "Testes": {cfg.modelos.codigo},  # só para explicar falhas
    }.get(agente, set())


class Turno:
    """Liga o agente para um pedido e desliga o que foi ligado só por causa dele."""

    def __init__(self, cfg: Config, cliente: Any, agente: str) -> None:
        self.cfg, self.cliente, self.agente = cfg, cliente, agente
        self.precisa = modelos_do_agente(cfg, agente)
        self.ja_carregados: set[str] = set()
        self.estava_desligado = not _ligado(cfg, agente)

    def __enter__(self) -> Turno:
        from agente import recursos

        if self.cliente is not None:
            try:
                self.ja_carregados = set(self.cliente.modelos_carregados())
            except Exception:  # Ollama fora: o agente reclama sozinho se precisar
                self.ja_carregados = set()
            recursos.garantir_folga(
                self.cfg, liberar=lambda: recursos.liberar(self.cliente, self.precisa)
            )
        if self.estava_desligado:
            logger.info("maestro: ligando %s só para este pedido", self.agente)
        return self

    def __exit__(self, *_erro: object) -> None:
        if self.cliente is None:
            return
        for modelo in self.precisa - self.ja_carregados:
            try:  # carregado por este pedido: sai da placa sozinho depois de um tempo
                if modelo in self.cliente.modelos_carregados():
                    self.cliente.acordar(modelo, DESLIGAR_APOS)
            except Exception as exc:
                logger.warning("não marquei %s para desligar: %s", modelo, exc)

    def nota(self) -> str:
        return f" (liguei o {self.agente} só para isso)" if self.estava_desligado else ""


def achar_projeto(cfg: Config, frase: str) -> Path | None:
    """Projeto citado no pedido: pelo nome inteiro ou pela primeira palavra do nome."""
    from agente import memoria

    candidatos: list[tuple[int, Path]] = []
    for projeto in memoria.projetos(cfg):
        nome = normalizar(projeto.name.replace("_", " ").replace("-", " "))
        if not nome:
            continue
        if re.search(rf"\b{re.escape(nome)}\b", frase):
            candidatos.append((len(nome), projeto))
            continue
        primeira = nome.split()[0]
        if (
            len(primeira) >= 5
            and primeira not in COMUNS
            and re.search(rf"\b{re.escape(primeira)}\b", frase)
        ):
            candidatos.append((len(primeira), projeto))
    return max(candidatos, key=lambda c: c[0])[1] if candidatos else None


def _ligado(cfg: Config, agente: str) -> bool:
    pausa = PAUSAS.get(agente)
    return pausa is None or not (cfg.pasta_dados / pausa).exists()


def rotear(cfg: Config, pedido: str, pasta: str | Path | None = None) -> Rota:
    """Escolhe o agente. Sem projeto (citado ou passado em `pasta`), vai ao Porteiro."""
    frase = normalizar(pedido)
    projeto = achar_projeto(cfg, frase) or (Path(pasta) if pasta else None)
    longo = "```" in pedido or len(frase.split()) > 30
    if projeto is None or longo:
        return Rota("Porteiro", None, "sem projeto citado" if projeto is None else "pedido longo")
    regras = [
        ("Testes", TESTAR, "pede para rodar os testes"),
        ("Revisor", REVISAR, "pede revisão"),
        ("Git", MUDOU, "pergunta o que mudou"),
        ("Memória", ACHAR, "procura algo no projeto"),
    ]
    for agente, padrao, motivo in regras:
        if padrao.search(frase):  # desligado no painel? o Maestro liga só para o pedido
            return Rota(agente, projeto, motivo)
    return Rota("Porteiro", None, "nenhuma regra de projeto")


def _achar(cfg: Config, cliente: Any, projeto: Path, pedido: str) -> str:
    from agente import memoria

    memoria.indexar(cfg, cliente, projeto)  # só reprocessa o que mudou
    trechos = memoria.buscar(cfg, cliente, projeto, pedido, k=3)
    if not trechos:
        return f"Não achei nada parecido em {projeto.name}."
    locais = ", ".join(f"{t.caminho}:{t.inicio}-{t.fim}" for t in trechos)
    return f"Em {projeto.name}, o mais provável: {locais}."


def perguntar(
    cfg: Config,
    cliente: Any,
    pedido: str,
    pasta: str | Path | None = None,
    encaminhar: Callable[[str], str] | None = None,
) -> Resultado:
    """Ponto único pra perguntar ao agente: comando direto -> Porteiro (local, depois
    OmniRoute) -> Claude se sobrar, sempre roteado pelo Maestro e registrado no histórico.

    Usado pela CLI, pelo MCP e pelo atalho de voz, pra não duplicar essa ligação em cada um.
    encaminhar(pedido) decide o que fazer quando sobra pro Claude (padrão: só avisar).
    """
    from agente import comandos
    from agente import porteiro as porteiro_mod

    comando = comandos.padrao(cfg)
    encaminhar = encaminhar or (lambda _p: "PRECISA DO CLAUDE.")

    def ao_porteiro(texto: str) -> tuple[str, str]:
        r = porteiro_mod.resolver(
            cfg, cliente, texto, executar_comando=comando, encaminhar=encaminhar
        )
        return r.destino, r.resposta

    return conduzir(cfg, cliente, pedido, ao_porteiro, pasta)


def conduzir(
    cfg: Config,
    cliente: Any,
    pedido: str,
    porteiro: Callable[[str], tuple[str, str]],
    pasta: str | Path | None = None,
) -> Resultado:
    """Roteia e executa. porteiro(pedido) -> (destino, resposta) cuida do que sobra.

    Todo pedido fica no histórico (janela "Histórico de pedidos" do painel).
    """
    from agente import historico

    inicio = time.perf_counter()
    r = _conduzir(cfg, cliente, pedido, porteiro, pasta)
    historico.registrar(cfg, pedido, r.agente, r.destino, r.resposta, time.perf_counter() - inicio)
    return r


def _conduzir(
    cfg: Config,
    cliente: Any,
    pedido: str,
    porteiro: Callable[[str], tuple[str, str]],
    pasta: str | Path | None,
) -> Resultado:
    from agente import economia, git_ops, revisor, testes
    from agente.executor import ErroExecucao

    rota = rotear(cfg, pedido, pasta)
    logger.info("maestro: %s (%s)", rota.agente, rota.motivo)
    if rota.projeto is None:
        with Turno(cfg, cliente, "Porteiro") as turno:
            destino, resposta = porteiro(pedido)
        nota = turno.nota() if destino in ("local", "nuvem") else ""
        return Resultado("Porteiro", destino, resposta + nota)
    projeto = rota.projeto
    acoes: dict[str, Callable[[], str]] = {
        "Testes": lambda: testes.rodar_testes(cfg, cliente, projeto).texto(),
        "Revisor": lambda: revisor.revisar(cfg, cliente, projeto).texto(),
        "Git": lambda: git_ops.status(cfg, projeto),
        "Memória": lambda: _achar(cfg, cliente, projeto, pedido),
    }
    bolinha = {"Testes": "Cérebro", "Git": "Cérebro"}.get(rota.agente, rota.agente)
    try:
        with Turno(cfg, cliente, rota.agente) as turno:
            with atividade.trabalhando(cfg.pasta_dados, bolinha):
                resposta = acoes[rota.agente]() + turno.nota()
    except ErroExecucao as exc:
        return Resultado(rota.agente, "local", f"{rota.agente} não conseguiu: {exc}")
    # Sem o Maestro isso iria ao Claude: o pedido e a resposta ficaram de graça.
    economia.registrar(cfg, "maestro", len(pedido) + len(resposta), 0)
    return Resultado(rota.agente, "local", resposta)
