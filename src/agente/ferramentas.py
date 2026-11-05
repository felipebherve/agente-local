"""Botões "Ligar ferramentas" e "Desligar ferramentas" do painel.

Liga, nesta ordem, só o que ainda não está rodando: Ollama com o Cérebro acordado, o ouvido
da voz, Docker Desktop, o Ubuntu (WSL) num terminal, o VS Code conectado ao Ubuntu e o
Claude Desktop. Cada passo é independente: se um falhar, os outros seguem. Cada passo sabe
dizer se está aberto agora (os checks do painel) e se fechar; desligar vai na ordem inversa.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from agente.config import Config

logger = logging.getLogger(__name__)

SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)
LOCAL = Path(os.environ.get("LOCALAPPDATA", ""))
DOCKER = (
    LOCAL / "Programs" / "DockerDesktop" / "Docker Desktop.exe",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    / "Docker"
    / "Docker"
    / "Docker Desktop.exe",
)
VSCODE = LOCAL / "Programs" / "Microsoft VS Code" / "bin" / "code.cmd"
CLAUDE_APP = r"shell:AppsFolder\Claude_pzs8sxrjxfjjc!Claude"


def _nada() -> None:
    return None


@dataclass(frozen=True)
class Passo:
    nome: str
    pronto: Callable[[], bool]  # está rodando agora?
    ligar: Callable[[], None]  # liga e espera ficar pronto (ou levanta erro)
    desligar: Callable[[], None] = _nada  # fecha


class ErroFerramenta(Exception):
    """Uma ferramenta não ligou a tempo."""


def _ok(comando: list[str], timeout: float = 15) -> bool:
    try:
        r = subprocess.run(comando, capture_output=True, timeout=timeout, creationflags=SEM_JANELA)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


def _abrir(comando: list[str]) -> None:
    subprocess.Popen(comando, creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))


def esperar(pronto: Callable[[], bool], segundos: float, nome: str, intervalo: float = 2) -> None:
    fim = time.monotonic() + segundos
    while time.monotonic() < fim:
        if pronto():
            return
        time.sleep(intervalo)
    raise ErroFerramenta(f"{nome} não ficou pronto em {segundos:.0f} s")


def _processo_rodando(nome_exe: str) -> bool:
    import psutil

    alvo = nome_exe.lower()
    for proc in psutil.process_iter(["name"]):
        try:
            if (proc.info["name"] or "").lower() == alvo:
                return True
        except psutil.Error:
            continue
    return False


def _fechar(*nomes_exe: str, espera_s: float = 6) -> None:
    """Pede para o programa fechar; se não fechar a tempo, encerra à força."""
    for nome in nomes_exe:
        _ok(["taskkill", "/IM", nome, "/T"], 15)
    fim = time.monotonic() + espera_s
    while time.monotonic() < fim and any(_processo_rodando(n) for n in nomes_exe):
        time.sleep(1)
    for nome in nomes_exe:
        if _processo_rodando(nome):
            _ok(["taskkill", "/F", "/IM", nome, "/T"], 15)


def distros_rodando() -> set[str]:
    """Distros do WSL ligadas agora (a saída do wsl.exe vem em UTF-16)."""
    try:
        bruto = subprocess.run(
            ["wsl", "--list", "--running", "--quiet"],
            capture_output=True,
            timeout=15,
            creationflags=SEM_JANELA,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return set()
    texto = bruto.decode("utf-16-le", "ignore") if b"\x00" in bruto else bruto.decode()
    return {linha.strip().lower() for linha in texto.splitlines() if linha.strip()}


def pasta_wsl(cfg: Config) -> str:
    """Pasta aberta no VS Code do Ubuntu: a do config ou a home do usuário do Ubuntu."""
    if cfg.ferramentas.pasta_wsl:
        return cfg.ferramentas.pasta_wsl
    try:
        home = subprocess.run(
            ["wsl", "-d", cfg.ferramentas.distro, "-e", "sh", "-c", "echo $HOME"],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=SEM_JANELA,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        home = ""
    return home or "/"


def passos(
    cfg: Config,
    acordar_cerebro: Callable[[], None],
    preparar_voz: Callable[[], None],
    voz_pronta: Callable[[], bool] | None = None,
    descarregar_voz: Callable[[], None] = _nada,
) -> list[Passo]:
    """Os passos na ordem: primeiro o que os agentes usam, depois as ferramentas do projeto."""
    from agente.llm import ClienteOllama, ErroOllama

    distro = cfg.ferramentas.distro
    rapido = ClienteOllama(cfg.ollama_url, 5, cfg.keep_alive)
    docker = next((p for p in DOCKER if p.exists()), DOCKER[0])
    estado = {"voz": False}

    def ollama_no_ar() -> bool:
        try:
            rapido.versao()
            return True
        except ErroOllama:
            return False

    def ligar_ollama() -> None:
        _abrir([str(LOCAL / "Programs" / "Ollama" / "ollama app.exe")])
        esperar(ollama_no_ar, 40, "Ollama")

    def cerebro_acordado() -> bool:
        try:
            return cfg.modelos.cerebro in rapido.modelos_carregados()
        except ErroOllama:
            return False

    def desligar_ollama() -> None:
        try:
            for modelo in rapido.modelos_carregados():
                rapido.dormir(modelo)
        except ErroOllama:
            pass
        _fechar("ollama app.exe", "ollama.exe")

    def desligar_cerebro() -> None:
        try:
            rapido.dormir(cfg.modelos.cerebro)
        except ErroOllama:
            pass

    def ligar_voz() -> None:
        preparar_voz()
        estado["voz"] = True

    def voz_ligada() -> bool:
        return voz_pronta() if voz_pronta is not None else estado["voz"]

    def desligar_voz() -> None:
        descarregar_voz()
        estado["voz"] = False

    def docker_aberto() -> bool:
        return _processo_rodando("Docker Desktop.exe")

    def desligar_docker() -> None:
        if not _ok(["docker", "desktop", "stop"], 60):
            _fechar("Docker Desktop.exe", "com.docker.backend.exe")

    def ligar_docker() -> None:
        if not docker.exists():
            raise ErroFerramenta("Docker Desktop não encontrado")
        _abrir([str(docker)])
        esperar(lambda: _ok(["docker", "info"]), 120, "Docker", 4)

    def ubuntu_no_ar() -> bool:
        return _ok(["wsl", "-d", distro, "-e", "true"], 60)

    def ubuntu_aberto() -> bool:
        return distro.lower() in distros_rodando()

    def ligar_ubuntu() -> None:
        terminal = shutil.which("wt")
        _abrir(
            [terminal, "-p", distro] if terminal else ["cmd", "/c", "start", "wsl", "-d", distro]
        )
        esperar(ubuntu_aberto, 60, "Ubuntu")

    def desligar_ubuntu() -> None:
        _ok(["wsl", "--terminate", distro], 30)  # o terminal do Ubuntu fecha junto

    def ligar_vscode() -> None:
        code = str(VSCODE) if VSCODE.exists() else (shutil.which("code") or "code")
        _abrir(["cmd", "/c", code, "--remote", f"wsl+{distro}", pasta_wsl(cfg)])
        esperar(lambda: _processo_rodando("Code.exe"), 30, "VS Code")

    def ligar_claude() -> None:
        _abrir(["explorer.exe", CLAUDE_APP])
        esperar(lambda: _processo_rodando("claude.exe"), 30, "Claude")

    lista = [
        Passo("Ollama", ollama_no_ar, ligar_ollama, desligar_ollama),
        Passo("Cérebro", cerebro_acordado, acordar_cerebro, desligar_cerebro),
    ]
    if cfg.ferramentas.voz:
        lista.append(Passo("Voz", voz_ligada, ligar_voz, desligar_voz))
    lista += [
        Passo("Docker", docker_aberto, ligar_docker, desligar_docker),
        Passo(f"Ubuntu ({distro})", ubuntu_aberto, ligar_ubuntu, desligar_ubuntu),
        Passo(
            "VS Code no Ubuntu",
            lambda: _processo_rodando("Code.exe"),
            ligar_vscode,
            lambda: _fechar("Code.exe"),
        ),
    ]
    if cfg.ferramentas.claude:
        lista.append(
            Passo(
                "Claude",
                lambda: _processo_rodando("claude.exe"),
                ligar_claude,
                lambda: _fechar("claude.exe"),
            )
        )
    return lista


def estados(lista: list[Passo]) -> list[tuple[str, bool]]:
    """(nome, aberto agora) de cada passo, para os checks do painel."""
    resultado = []
    for passo in lista:
        try:
            aberto = passo.pronto()
        except Exception:  # conferir nunca derruba o painel
            aberto = False
        resultado.append((passo.nome, aberto))
    return resultado


def desligar_tudo(
    lista: list[Passo],
    progresso: Callable[[int, int, str], None] = lambda _f, _t, _n: None,
) -> list[str]:
    """Fecha, na ordem inversa, cada passo que está aberto."""
    relatorio = []
    ordem = list(reversed(lista))
    for feitos, passo in enumerate(ordem):
        progresso(feitos, len(ordem), passo.nome)
        try:
            if not passo.pronto():
                continue
            passo.desligar()
            relatorio.append(f"{passo.nome}: fechado")
        except Exception as exc:
            logger.warning("não fechei %s: %s", passo.nome, exc)
            relatorio.append(f"{passo.nome}: FALHOU ({exc})")
    progresso(len(ordem), len(ordem), "")
    return relatorio


def ligar_tudo(
    lista: list[Passo],
    aviso: Callable[[str], None] = lambda _t: None,
    progresso: Callable[[int, int, str], None] = lambda _f, _t, _n: None,
) -> list[str]:
    """Roda cada passo que ainda não está pronto e devolve uma linha por passo.

    progresso(feitos, total, nome) alimenta a barra de carregamento do painel.
    """
    relatorio = []
    for feitos, passo in enumerate(lista):
        progresso(feitos, len(lista), passo.nome)
        try:
            if passo.pronto():
                relatorio.append(f"{passo.nome}: já estava ligado")
                continue
            aviso(f"Ligando {passo.nome}...")
            inicio = time.monotonic()
            passo.ligar()
            relatorio.append(f"{passo.nome}: ligado em {time.monotonic() - inicio:.0f} s")
        except Exception as exc:  # um passo ruim não impede os outros
            logger.warning("ferramenta %s falhou: %s", passo.nome, exc)
            relatorio.append(f"{passo.nome}: FALHOU ({exc})")
    progresso(len(lista), len(lista), "")
    return relatorio
