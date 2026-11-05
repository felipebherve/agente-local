"""Operações de git com resposta curta e trava nas ações que não se desfazem fácil."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from agente.config import Config
from agente.economia import registrar
from agente.executor import ConfirmacaoNecessaria, ErroExecucao, Saida, executar, validar_pasta
from agente.llm import ClienteOllama, ErroOllama

logger = logging.getLogger(__name__)

PROTEGIDAS = frozenset({"main", "master"})
SENSIVEIS = re.compile(r"(^|/)\.env($|\.)|\.pem$|\.key$|id_rsa|credentials|secrets?\.", re.I)
MAX_DIFF = 12_000


def _git(cfg: Config, pasta: Path, *args: str, timeout_s: float = 180) -> Saida:
    return executar(cfg, ["git", *args], pasta, timeout_s)


def _git_ok(cfg: Config, pasta: Path, *args: str, timeout_s: float = 180) -> str:
    s = _git(cfg, pasta, *args, timeout_s=timeout_s)
    if not s.ok:
        raise ErroExecucao(f"git {args[0]} falhou: {s.texto.strip()[-800:]}")
    return s.texto


def _repo(cfg: Config, pasta: str | Path) -> Path:
    raiz = validar_pasta(cfg, pasta)
    topo = _git_ok(cfg, raiz, "rev-parse", "--show-toplevel").strip()
    return validar_pasta(cfg, topo)


def branch_atual(cfg: Config, pasta: Path) -> str:
    return _git_ok(cfg, pasta, "rev-parse", "--abbrev-ref", "HEAD").strip()


def _remoto_para_web(url: str) -> str:
    """git@host:dono/repo.git ou https://host/dono/repo.git -> https://host/dono/repo"""
    url = url.strip().removesuffix(".git")
    if url.startswith("git@"):
        host, _, caminho = url.removeprefix("git@").partition(":")
        return f"https://{host}/{caminho}"
    return url


def remoto_web(cfg: Config, pasta: str | Path) -> str:
    """Endereço do remoto 'origin' do projeto, convertido para um link que abre no navegador."""
    repo = _repo(cfg, pasta)
    bruto = _git_ok(cfg, repo, "remote", "get-url", "origin")
    return _remoto_para_web(bruto)


def status(cfg: Config, pasta: str | Path) -> str:
    repo = _repo(cfg, pasta)
    bruto = _git_ok(cfg, repo, "status", "--porcelain=v1", "--branch")
    linhas = bruto.splitlines()
    cabecalho = linhas[0].removeprefix("## ") if linhas else "?"
    arquivos = linhas[1:]
    preparados = sum(1 for linha in arquivos if linha[:1] not in (" ", "?"))
    novos = sum(1 for linha in arquivos if linha.startswith("??"))
    modificados = len(arquivos) - novos
    resumo = [f"{cabecalho} | {modificados} alterados ({preparados} preparados), {novos} novos"]
    resumo += [f"  {linha}" for linha in arquivos[:15]]
    if len(arquivos) > 15:
        resumo.append(f"  ... e mais {len(arquivos) - 15}")
    texto = "\n".join(resumo)
    registrar(cfg, "git status", len(bruto), len(texto))
    return texto


def pull(cfg: Config, pasta: str | Path) -> str:
    repo = _repo(cfg, pasta)
    s = _git(cfg, repo, "pull", "--ff-only")
    if not s.ok:
        return f"Pull não aplicado (histórico divergiu ou conflito): {s.texto.strip()[-400:]}"
    ultima = s.texto.strip().splitlines()[-1] if s.texto.strip() else "ok"
    return f"Pull ok em {branch_atual(cfg, repo)}: {ultima}"


def criar_branch(cfg: Config, pasta: str | Path, nome: str) -> str:
    repo = _repo(cfg, pasta)
    _git_ok(cfg, repo, "check-ref-format", "--branch", nome)
    _git_ok(cfg, repo, "switch", "-c", nome)
    return f"Branch {nome} criada e ativa."


def _tirar_sensiveis(cfg: Config, repo: Path) -> list[str]:
    nomes = _git_ok(cfg, repo, "diff", "--cached", "--name-only").splitlines()
    sensiveis = [n for n in nomes if SENSIVEIS.search(n)]
    for nome in sensiveis:
        _git_ok(cfg, repo, "reset", "-q", "--", nome)
    return sensiveis


def _primeira_linha(texto: str, limite: int = 72) -> str:
    """Primeira linha não vazia, cortada em palavra inteira se passar do limite."""
    for linha in texto.strip().splitlines():
        limpa = linha.strip().strip("`\"' ")
        if not limpa:
            continue
        if len(limpa) <= limite:
            return limpa
        return limpa[:limite].rsplit(" ", 1)[0].rstrip(",;:")
    return ""


def gerar_mensagem_commit(cfg: Config, cliente: ClienteOllama | None, repo: Path) -> str:
    stat = _git_ok(cfg, repo, "diff", "--cached", "--stat").strip()
    padrao = f"Atualiza {stat.splitlines()[-1].strip()}" if stat else "Atualiza arquivos"
    if cliente is None:
        return padrao[:72]
    estilo = _git(cfg, repo, "log", "-5", "--pretty=%s").texto.strip()
    diff = _git_ok(cfg, repo, "diff", "--cached", "--unified=1")[:MAX_DIFF]
    pedido = (
        f"DIFF:\n{diff}\n\n---\nCommits recentes do projeto:\n{estilo or '(nenhum)'}\n\n"
        "Escreva UMA linha curta de mensagem de commit (até 60 caracteres) para o diff acima, "
        "no mesmo idioma e estilo dos commits recentes (português se não houver). "
        "Responda só com a mensagem."
    )
    try:
        return _primeira_linha(cliente.conversar(cfg.modelos.codigo, pedido).texto) or padrao
    except ErroOllama as exc:
        logger.warning("mensagem de commit local falhou: %s", exc)
        return padrao[:72]


def commit(
    cfg: Config, cliente: ClienteOllama | None, pasta: str | Path, mensagem: str = ""
) -> str:
    repo = _repo(cfg, pasta)
    _git_ok(cfg, repo, "add", "-A")
    retirados = _tirar_sensiveis(cfg, repo)
    stat = _git_ok(cfg, repo, "diff", "--cached", "--stat").strip()
    if not stat:
        return "Nada para commitar." + (f" (retirei: {', '.join(retirados)})" if retirados else "")
    if not (cfg.pasta_dados / "revisor-pausado").exists():
        from agente.revisor import bloqueios_do_commit

        bloqueios = bloqueios_do_commit(cfg, repo)
        if bloqueios:
            _git_ok(cfg, repo, "reset", "-q")
            lista = "\n".join(f"- {b}" for b in bloqueios[:10])
            raise ErroExecucao(f"Revisor travou o commit (nada foi commitado):\n{lista}")
    diff_tamanho = len(_git_ok(cfg, repo, "diff", "--cached"))
    mensagem = mensagem.strip() or gerar_mensagem_commit(cfg, cliente, repo)
    _git_ok(cfg, repo, "commit", "-q", "-m", mensagem)
    curto = _git_ok(cfg, repo, "rev-parse", "--short", "HEAD").strip()
    texto = f"Commit {curto} em {branch_atual(cfg, repo)}: {mensagem}\n{stat.splitlines()[-1]}"
    if retirados:
        texto += f"\nNão commitei arquivos sensíveis: {', '.join(retirados)}"
    registrar(cfg, "commit", diff_tamanho, len(texto))
    return texto


def merge(cfg: Config, pasta: str | Path, origem: str, confirmado: bool = False) -> str:
    repo = _repo(cfg, pasta)
    destino = branch_atual(cfg, repo)
    if destino in PROTEGIDAS and not confirmado:
        raise ConfirmacaoNecessaria(f"merge de {origem} em {destino} precisa do OK do usuário")
    s = _git(cfg, repo, "merge", "--no-edit", origem)
    if s.ok:
        return f"Merge de {origem} em {destino} ok."
    conflitos = _git(cfg, repo, "diff", "--name-only", "--diff-filter=U").texto.split()
    _git(cfg, repo, "merge", "--abort")
    if conflitos:
        return f"Conflito em {', '.join(conflitos[:10])}. Merge desfeito; nada mudou."
    raise ErroExecucao(f"merge falhou: {s.texto.strip()[-400:]}")


def push(cfg: Config, pasta: str | Path, confirmado: bool = False) -> str:
    repo = _repo(cfg, pasta)
    branch = branch_atual(cfg, repo)
    if branch in PROTEGIDAS and not confirmado:
        raise ConfirmacaoNecessaria(f"push direto na {branch} precisa do OK do usuário")
    _git_ok(cfg, repo, "push", "-u", "origin", branch, timeout_s=300)
    return f"Push de {branch} ok."
