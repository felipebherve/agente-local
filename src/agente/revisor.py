"""Revisor (Fase 9): roda as checagens locais antes de o Claude revisar o código.

O Claude recebe só os problemas: avisos de lint e de tipos com arquivo e linha, testes que
falharam e coisas suspeitas nas alterações (senhas, marcas de conflito, depuração esquecida).
Tudo roda no PC; o modelo de código só opina sobre o diff se for pedido.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agente.compactar import compactar
from agente.config import Config
from agente.economia import registrar
from agente.executor import ErroExecucao, executar, validar_pasta

logger = logging.getLogger(__name__)

MAX_ITENS = 10
GRANDE_BYTES = 1_000_000
LOCAL = re.compile(r"^\s*([\w./\\-]+\.\w+)[:(](\d+)")  # caminho:linha de lint, tipos e testes
SEGREDO = re.compile(
    r"(AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|xox[baprs]-[\w-]{10,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|(?i:\b(senha|password|passwd|secret|token|api_?key)\b\s*[:=]\s*['\"][^'\"\s]{6,}['\"]))"
)
CONFLITO = re.compile(r"^(<<<<<<< |>>>>>>> |=======$)")
DEPURACAO = re.compile(r"(\bbreakpoint\(\)|\bpdb\.set_trace\(|\bdebugger;|\bconsole\.log\()")
PENDENCIA = re.compile(r"\b(TODO|FIXME|XXX)\b")
OPINIAO = (
    "Você revisa um diff. Liste até 5 bugs PROVÁVEIS e concretos (não estilo), um por linha, "
    "no formato arquivo:linha - problema. Se não houver nada sério, responda só NADA."
)


@dataclass(frozen=True)
class Checagem:
    nome: str
    ok: bool
    resumo: str
    itens: list[str] = field(default_factory=list)
    aviso: bool = False  # só informativo: não conta como problema

    def texto(self) -> str:
        marca = "·" if self.aviso else ("✓" if self.ok else "✗")
        linhas = [f"{marca} {self.nome}: {self.resumo}"]
        linhas += [f"  - {item}" for item in self.itens[:MAX_ITENS]]
        if len(self.itens) > MAX_ITENS:
            linhas.append(f"  ... e mais {len(self.itens) - MAX_ITENS}")
        return "\n".join(linhas)


@dataclass(frozen=True)
class Revisao:
    projeto: str
    checagens: list[Checagem]
    segundos: float

    @property
    def problemas(self) -> int:
        return sum(1 for c in self.checagens if not c.ok and not c.aviso)

    def texto(self) -> str:
        if not self.checagens:
            return f"Revisor ({self.projeto}): não achei lint, tipos nem testes para rodar."
        cabeca = (
            f"Revisor ({self.projeto}): {self.problemas} com problema em "
            f"{len(self.checagens)} checagens ({self.segundos:.0f} s)."
        )
        return "\n".join([cabeca, *(c.texto() for c in self.checagens)])


# --- lint, tipos e testes ------------------------------------------------------------------


def _locais(saida: str) -> list[str]:
    """Linhas com arquivo:linha (o que importa na saída de lint e de tipos)."""
    vistas: list[str] = []
    for linha in saida.splitlines():
        if LOCAL.match(linha) and linha.strip() not in vistas:
            vistas.append(linha.strip()[:220])
    return vistas


def _rodar(cfg: Config, nome: str, comando: list[str], raiz: Path, brutos: list[int]) -> Checagem:
    try:
        saida = executar(cfg, comando, raiz, timeout_s=600)
    except ErroExecucao as exc:
        return Checagem(nome, False, f"não rodou ({exc})")
    brutos.append(len(saida.texto))
    if saida.ok:
        return Checagem(nome, True, "ok")
    itens = _locais(saida.texto)
    if not itens:  # sem arquivo:linha: mostra o fim da saída, que costuma dizer o motivo
        itens = [linha.strip()[:220] for linha in saida.texto.strip().splitlines()[-5:]]
    return Checagem(nome, False, f"{len(_locais(saida.texto)) or 'com'} problemas", itens)


def _tem_modulo(cfg: Config, python: str, modulo: str, raiz: Path) -> bool:
    try:
        return executar(cfg, [python, "-m", modulo, "--version"], raiz, timeout_s=60).ok
    except ErroExecucao:
        return False


def _config_python(raiz: Path) -> str:
    textos = []
    for nome in ("pyproject.toml", "setup.cfg", "mypy.ini", ".mypy.ini", "ruff.toml", ".ruff.toml"):
        try:
            textos.append(f"[{nome}]\n" + (raiz / nome).read_text(encoding="utf-8"))
        except OSError:
            continue
    return "\n".join(textos)


def checagens_python(cfg: Config, raiz: Path, brutos: list[int]) -> list[Checagem]:
    from agente.testes import _python_do_projeto

    config = _config_python(raiz)
    if not config and not any(raiz.glob("*.py")):
        return []
    python = _python_do_projeto(raiz)
    resultado = []
    if _tem_modulo(cfg, python, "ruff", raiz):
        comando = [python, "-m", "ruff", "check", "--output-format", "concise", "."]
        resultado.append(_rodar(cfg, "lint (ruff)", comando, raiz, brutos))
    tem_mypy = "[tool.mypy]" in config or "[mypy]" in config or "[mypy.ini]" in config
    if tem_mypy and _tem_modulo(cfg, python, "mypy", raiz):
        resultado.append(_rodar(cfg, "tipos (mypy)", [python, "-m", "mypy"], raiz, brutos))
    return resultado


def checagens_js(cfg: Config, raiz: Path, brutos: list[int]) -> list[Checagem]:
    try:
        scripts: dict[str, Any] = json.loads(
            (raiz / "package.json").read_text(encoding="utf-8")
        ).get("scripts", {})
    except (OSError, json.JSONDecodeError):
        return []
    resultado = []
    if "lint" in scripts:
        resultado.append(
            _rodar(cfg, "lint (npm)", ["npm", "run", "lint", "--silent"], raiz, brutos)
        )
    tipos = next((s for s in ("typecheck", "type-check", "tsc", "types") if s in scripts), None)
    if tipos:
        resultado.append(
            _rodar(cfg, "tipos (npm)", ["npm", "run", tipos, "--silent"], raiz, brutos)
        )
    elif (raiz / "tsconfig.json").exists() and (raiz / "node_modules" / ".bin").is_dir():
        resultado.append(_rodar(cfg, "tipos (tsc)", ["npx", "tsc", "--noEmit"], raiz, brutos))
    return resultado


def checagem_testes(cfg: Config, cliente: Any, raiz: Path) -> list[Checagem]:
    from agente import testes

    try:
        testes.detectar_comando(raiz)
    except ErroExecucao:
        return []
    try:
        r = testes.rodar_testes(cfg, cliente, raiz)
    except ErroExecucao as exc:
        return [Checagem("testes", False, f"não rodaram ({exc})")]
    if r.ok:
        return [Checagem("testes", True, f"{r.passaram} passaram")]
    itens = list(r.falhas) + ([f"causa provável: {r.causa}"] if r.causa else [])
    return [Checagem("testes", False, f"{r.falharam} falharam, {r.passaram} passaram", itens)]


# --- alterações (git) ----------------------------------------------------------------------


@dataclass(frozen=True)
class Achado:
    tipo: str  # segredo, conflito, depuracao, pendencia, grande
    onde: str
    trecho: str

    def texto(self) -> str:
        return f"{self.onde} {self.tipo}: {self.trecho}"


def achados_no_diff(diff: str) -> list[Achado]:
    """Procura nas linhas adicionadas: segredos, conflitos, depuração e pendências."""
    achados: list[Achado] = []
    arquivo, linha = "?", 0
    for bruta in diff.splitlines():
        if bruta.startswith("+++ "):
            arquivo = bruta[4:].removeprefix("b/").strip()
            continue
        cabeca = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)", bruta)
        if cabeca:
            linha = int(cabeca.group(1))
            continue
        if bruta.startswith("+") and not bruta.startswith("+++"):
            conteudo = bruta[1:]
            onde = f"{arquivo}:{linha}"
            if SEGREDO.search(conteudo):
                trecho = SEGREDO.sub(lambda m: m.group(0)[:6] + "…", conteudo.strip())
                achados.append(Achado("possível segredo", onde, trecho[:120]))
            if CONFLITO.match(conteudo):
                achados.append(Achado("marca de conflito", onde, conteudo.strip()[:40]))
            if DEPURACAO.search(conteudo):
                achados.append(Achado("depuração esquecida", onde, conteudo.strip()[:120]))
            if PENDENCIA.search(conteudo):
                achados.append(Achado("pendência", onde, conteudo.strip()[:120]))
            linha += 1
        elif not bruta.startswith("-"):
            linha += 1
    return achados


def _git(cfg: Config, raiz: Path, *args: str) -> str:
    saida = executar(cfg, ["git", *args], raiz, timeout_s=120)
    return saida.texto if saida.ok else ""


def diff_atual(cfg: Config, raiz: Path, preparado: bool = False) -> tuple[str, list[str]]:
    """Diff das alterações (com arquivos novos) e a lista de arquivos alterados."""
    if preparado:
        nomes = _git(cfg, raiz, "diff", "--cached", "--name-only").splitlines()
        return _git(cfg, raiz, "diff", "--cached"), nomes
    diff = _git(cfg, raiz, "diff", "HEAD")
    nomes = _git(cfg, raiz, "diff", "HEAD", "--name-only").splitlines()
    for novo in _git(cfg, raiz, "ls-files", "--others", "--exclude-standard").splitlines():
        nomes.append(novo)
        try:
            texto = (raiz / novo).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        linhas = texto.splitlines()
        corpo = "\n".join(f"+{linha}" for linha in linhas)
        diff += f"\n+++ b/{novo}\n@@ -0,0 +1,{len(linhas)} @@\n{corpo}\n"
    # avisos do git (fim de linha CRLF) chegam misturados na saída
    return diff, [n for n in nomes if n.strip() and not n.startswith(("warning:", "aviso:"))]


def checagem_alteracoes(cfg: Config, raiz: Path, brutos: list[int]) -> tuple[list[Checagem], str]:
    if not (raiz / ".git").exists():
        return [], ""
    diff, nomes = diff_atual(cfg, raiz)
    brutos.append(len(diff))
    if not nomes:
        return [Checagem("alterações", True, "nada alterado desde o último commit")], ""
    achados = achados_no_diff(diff)
    grandes = [
        n for n in nomes if (raiz / n).is_file() and (raiz / n).stat().st_size > GRANDE_BYTES
    ]
    graves = [a for a in achados if a.tipo != "pendência"]
    itens = [a.texto() for a in graves] + [f"{n}: arquivo grande (mais de 1 MB)" for n in grandes]
    resumo = f"{len(nomes)} arquivos alterados" + (f", {len(itens)} suspeitas" if itens else "")
    resultado = [Checagem("alterações", not itens, resumo, itens)]
    pendencias = [a.texto() for a in achados if a.tipo == "pendência"]
    if pendencias:
        resultado.append(
            Checagem("pendências novas", True, f"{len(pendencias)} TODO/FIXME", pendencias, True)
        )
    return resultado, diff


def bloqueios_do_commit(cfg: Config, raiz: Path) -> list[str]:
    """Antes do commit (com o Revisor ligado): segredos e conflitos no que vai ser commitado."""
    diff, _ = diff_atual(cfg, raiz, preparado=True)
    return [
        a.texto()
        for a in achados_no_diff(diff)
        if a.tipo in ("possível segredo", "marca de conflito")
    ]


# --- revisão completa ----------------------------------------------------------------------


def _opiniao(cfg: Config, cliente: Any, diff: str) -> Checagem:
    if not diff.strip():
        return Checagem("opinião do modelo", True, "sem alterações para ler", aviso=True)
    try:
        r = cliente.conversar(cfg.modelos.codigo, compactar(diff)[:14000], sistema=OPINIAO)
    except Exception as exc:  # opinião é extra: falhar não estraga a revisão
        return Checagem("opinião do modelo", True, f"indisponível ({exc})", aviso=True)
    texto = str(getattr(r, "texto", "")).strip()
    if not texto or texto.upper().startswith("NADA"):
        return Checagem("opinião do modelo", True, "nada sério no diff", aviso=True)
    itens = [linha.strip("-• ").strip() for linha in texto.splitlines() if linha.strip()][:5]
    return Checagem("opinião do modelo (confira antes de agir)", True, "pontos", itens, True)


def revisar(
    cfg: Config,
    cliente: Any,
    pasta: str | Path,
    testes: bool = True,
    opiniao: bool = False,
) -> Revisao:
    raiz = validar_pasta(cfg, pasta)
    inicio = time.perf_counter()
    brutos: list[int] = []
    checagens = checagens_python(cfg, raiz, brutos) + checagens_js(cfg, raiz, brutos)
    if testes:
        checagens += checagem_testes(cfg, cliente, raiz)
    alteracoes, diff = checagem_alteracoes(cfg, raiz, brutos)
    checagens += alteracoes
    if opiniao and cliente is not None:
        checagens.append(_opiniao(cfg, cliente, diff))
    revisao = Revisao(raiz.name, checagens, time.perf_counter() - inicio)
    texto = revisao.texto()
    registrar(cfg, "revisor", sum(brutos), len(texto))
    try:
        cfg.pasta_dados.mkdir(parents=True, exist_ok=True)
        (cfg.pasta_dados / "revisor-ultima.txt").write_text(
            f"{raiz.name}: {revisao.problemas} com problema", encoding="utf-8"
        )
    except OSError:
        pass
    return revisao
