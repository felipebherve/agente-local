"""Abre pull requests em rascunho com título e descrição gerados pelo modelo local."""

from __future__ import annotations

import logging
from pathlib import Path

from agente.config import Config
from agente.economia import registrar
from agente.executor import ErroExecucao, executar
from agente.git_ops import MAX_DIFF, _git, _git_ok, _repo, branch_atual, push
from agente.llm import ClienteOllama, ErroOllama

logger = logging.getLogger(__name__)


def _referencia_base(cfg: Config, repo: Path, base: str) -> str:
    remota = f"origin/{base}"
    if _git(cfg, repo, "rev-parse", "--verify", "--quiet", remota).ok:
        return remota
    if _git(cfg, repo, "rev-parse", "--verify", "--quiet", base).ok:
        return base
    raise ErroExecucao(f"branch base '{base}' não encontrada")


def gerar_texto_pr(
    cliente: ClienteOllama | None, modelo: str, commits: str, stat: str, diff: str
) -> tuple[str, str]:
    """Devolve (título, corpo). Sem modelo, monta a partir dos commits."""
    primeiro = commits.strip().splitlines()[0].removeprefix("- ") if commits.strip() else ""
    padrao = (primeiro or "Atualizações")[:70], f"## Mudanças\n\n{commits.strip()}\n\n{stat}"
    if cliente is None:
        return padrao
    pedido = (
        f"COMMITS:\n{commits}\n\nARQUIVOS:\n{stat}\n\nDIFF:\n{diff}\n\n---\n"
        "Escreva um pull request no idioma dos commits (português se não der para saber).\n"
        "Formato exato:\nTITULO: <até 70 caracteres>\nCORPO:\n## Resumo\n<2 a 4 linhas>\n"
        "## Mudanças\n- <item>\n## Como testar\n- <item>"
    )
    try:
        texto = cliente.conversar(modelo, pedido).texto
    except ErroOllama as exc:
        logger.warning("texto do PR local falhou: %s", exc)
        return padrao
    if "TITULO:" not in texto or "CORPO:" not in texto:
        return padrao
    titulo = texto.split("TITULO:", 1)[1].split("\n", 1)[0].strip().strip("`\"' ")[:70]
    corpo = texto.split("CORPO:", 1)[1].strip()
    return (titulo or padrao[0]), (corpo or padrao[1])


def abrir_pr(
    cfg: Config,
    cliente: ClienteOllama | None,
    pasta: str | Path,
    base: str = "main",
    simular: bool = False,
) -> str:
    """Envia a branch atual e abre um PR em rascunho. simular=True só mostra o texto."""
    repo = _repo(cfg, pasta)
    branch = branch_atual(cfg, repo)
    if branch == base:
        raise ErroExecucao(f"você está na {base}; crie uma branch antes de abrir PR")
    ref = _referencia_base(cfg, repo, base)
    commits = _git_ok(cfg, repo, "log", f"{ref}..HEAD", "--pretty=- %s").strip()
    if not commits:
        raise ErroExecucao(f"a branch {branch} não tem commits novos em relação a {base}")
    stat = _git_ok(cfg, repo, "diff", f"{ref}...HEAD", "--stat").strip()
    diff = _git_ok(cfg, repo, "diff", f"{ref}...HEAD", "--unified=1")
    titulo, corpo = gerar_texto_pr(cliente, cfg.modelos.codigo, commits, stat, diff[:MAX_DIFF])
    if simular:
        return f"[simulação] {branch} -> {base}\nTÍTULO: {titulo}\n\n{corpo}"
    push(cfg, repo)
    s = executar(
        cfg,
        [
            "gh",
            "pr",
            "create",
            "--draft",
            "--base",
            base,
            "--head",
            branch,
            "--title",
            titulo,
            "--body",
            corpo,
        ],
        repo,
        timeout_s=180,
    )
    if not s.ok:
        raise ErroExecucao(f"gh pr create falhou: {s.texto.strip()[-600:]}")
    url = s.texto.strip().splitlines()[-1]
    texto = f"PR em rascunho aberto: {url}\nTítulo: {titulo}"
    registrar(cfg, "pull request", len(diff) + len(commits), len(texto))
    return texto
