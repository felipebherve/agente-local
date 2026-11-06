"""Aba Configurações do painel: contas (Claude, GitHub, OmniRoute) e atalho de voz.

Nada de senha passa por aqui. Para entrar numa conta, o painel abre um terminal com o
comando oficial de login (claude auth login, gh auth login), e o login fica guardado
pelo próprio programa. As IAs grátis são ligadas no painel do OmniRoute (no navegador);
aqui só se escolhe a fila de modelos e se liga ou desliga o degrau.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

ATALHO_SUGERIDO = "ctrl+alt+f"
MODIFICADORES = ("ctrl", "alt", "shift", "super")
NOME_ATALHO_GNOME = "Agente local: falar"
NOME_LNK_WINDOWS = "Agente local - falar.lnk"
GNOME_LISTA = "org.gnome.settings-daemon.plugins.media-keys"
GNOME_ITEM = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
GNOME_BASE = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"


def _rodar(cmd: list[str], timeout: float = 10) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(  # noqa: S603 - comandos fixos, sem shell
            cmd, capture_output=True, text=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


# --- contas -----------------------------------------------------------------------------


def status_claude() -> dict[str, Any]:
    """Claude Code instalado, logado e com o agente registrado."""
    instalado = shutil.which("claude") is not None
    conectado, email, plano = False, "", ""
    if instalado:
        r = _rodar(["claude", "auth", "status"])
        if r is not None:
            try:
                dados = json.loads(r.stdout)
                conectado = bool(dados.get("loggedIn"))
                email = str(dados.get("email") or "")
                plano = str(dados.get("subscriptionType") or dados.get("authMethod") or "")
            except json.JSONDecodeError:
                pass
    arquivo = Path.home() / ".claude.json"
    try:
        registrado = "agente-local" in json.loads(arquivo.read_text(encoding="utf-8")).get(
            "mcpServers", {}
        )
    except (OSError, json.JSONDecodeError, AttributeError):
        registrado = False
    return {
        "instalado": instalado,
        "conectado": conectado,
        "conta": email,
        "plano": plano,
        "agente_registrado": registrado,
    }


def status_github() -> dict[str, Any]:
    instalado = shutil.which("gh") is not None
    conta = ""
    if instalado:
        r = _rodar(["gh", "auth", "status", "-h", "github.com"])
        if r is not None:
            achado = re.search(r"account (\S+)", r.stdout + r.stderr)
            conta = achado.group(1) if achado else ""
    return {"instalado": instalado, "conectado": bool(conta), "conta": conta}


COMANDOS_LOGIN = {
    "claude": ["claude", "auth", "login"],
    "github": ["gh", "auth", "login", "--web", "--git-protocol", "https"],
}


def abrir_terminal(cmd: list[str]) -> bool:
    """Abre uma janela de terminal rodando o comando (o login pede coisas na tela)."""
    texto = " ".join(cmd)
    if os.name == "nt":
        try:
            subprocess.Popen(["cmd", "/c", "start", "Login", "cmd", "/k", texto])  # noqa: S603,S607
            return True
        except OSError:
            return False
    espera = f"{texto}; echo; read -p 'Pronto. Aperte Enter para fechar.'"
    opcoes = [
        ["ptyxis", "--new-window", "-x", f"bash -lc \"{espera}\""],
        ["gnome-terminal", "--", "bash", "-lc", espera],
        ["konsole", "-e", "bash", "-lc", espera],
        ["x-terminal-emulator", "-e", "bash", "-lc", espera],
        ["xterm", "-e", "bash", "-lc", espera],
    ]
    for opcao in opcoes:
        if shutil.which(opcao[0]):
            try:
                subprocess.Popen(opcao, start_new_session=True)  # noqa: S603
                return True
            except OSError:
                continue
    return False


def entrar(servico: str) -> bool:
    if servico not in COMANDOS_LOGIN:
        raise KeyError(servico)
    return abrir_terminal(COMANDOS_LOGIN[servico])


def registrar_no_claude() -> list[str]:
    from agente.instalar import instalar_no_claude

    return instalar_no_claude()


# --- editar o config.yaml sem perder o resto -----------------------------------------------


def _bloco(texto: str, chave: str) -> tuple[int, int] | None:
    """Início e fim (posições) do bloco de primeiro nível `chave:` no texto."""
    achado = re.search(rf"^{re.escape(chave)}:.*$", texto, flags=re.M)
    if not achado:
        return None
    proximo = re.search(r"^[^\s#]", texto[achado.end() + 1 :], flags=re.M)
    fim = achado.end() + 1 + proximo.start() if proximo else len(texto)
    # comentários e linhas vazias logo antes da próxima chave pertencem a ela
    linhas = texto[achado.end() + 1 : fim].splitlines(keepends=True)
    while linhas and (not linhas[-1].strip() or linhas[-1].lstrip().startswith("#")) \
            and not linhas[-1].startswith((" ", "\t")):
        fim -= len(linhas.pop())
    return achado.start(), fim


def trocar_bloco(caminho: Path, chave: str, valor: Any) -> None:  # noqa: ANN401 - qualquer YAML
    """Reescreve só o bloco `chave:` do config.yaml (o resto e os comentários ficam)."""
    texto = caminho.read_text(encoding="utf-8")
    novo = yaml.safe_dump({chave: valor}, allow_unicode=True, sort_keys=False)
    faixa = _bloco(texto, chave)
    if faixa is None:
        texto = texto.rstrip("\n") + "\n\n" + novo
    else:
        texto = texto[: faixa[0]] + novo + "\n" + texto[faixa[1] :].lstrip("\n")
    yaml.safe_load(texto)  # não grava nada quebrado
    caminho.with_suffix(".yaml.bak").write_text(caminho.read_text(encoding="utf-8"), "utf-8")
    caminho.write_text(texto, encoding="utf-8")


def ler_bloco(caminho: Path, chave: str) -> dict[str, Any]:
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    bloco = dados.get(chave) or {}
    return dict(bloco) if isinstance(bloco, dict) else {}


def arquivo_omniroute(caminho: Path) -> Path:
    """Onde a fila do OmniRoute mora: no HD compartilhado (se ligado e com o bloco) ou no
    próprio config.yaml. Gravar no lugar errado faria a mudança "sumir"."""
    from agente.config import CAMINHO_COMPARTILHADO, achar_hd

    nome = str((yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}).get(
        "hd_compartilhado") or "")
    hd = achar_hd(nome) if nome else None
    if hd is not None:
        compartilhado = hd / CAMINHO_COMPARTILHADO
        if compartilhado.exists() and ler_bloco(compartilhado, "omniroute"):
            return compartilhado
    return caminho


def salvar_omniroute(caminho: Path, ligado: bool, modelos: list[str]) -> Path:
    """Grava a fila de modelos e o liga/desliga. Devolve o arquivo que mudou."""
    caminho = arquivo_omniroute(caminho)
    bloco = ler_bloco(caminho, "omniroute")
    bloco.setdefault("url", "http://127.0.0.1:20128/v1")
    bloco.setdefault("timeout_s", 25)
    bloco["ligado"] = bool(ligado)
    bloco["modelos"] = [m.strip() for m in modelos if m.strip()]
    trocar_bloco(caminho, "omniroute", bloco)
    return caminho


# --- pastas liberadas ----------------------------------------------------------------------


def validar_pastas(pastas: list[str]) -> list[str]:
    """Caminhos completos de pastas que existem, sem repetir. Levanta ValueError no erro."""
    resultado: list[str] = []
    for bruta in pastas:
        texto = bruta.strip().strip('"')
        if not texto:
            continue
        pasta = Path(os.path.expandvars(texto)).expanduser()
        if not pasta.is_absolute():
            raise ValueError(f"use o caminho completo: {texto}")
        if not pasta.is_dir():
            raise ValueError(f"pasta não existe: {texto}")
        if pasta == Path(pasta.anchor):
            raise ValueError(f"não libere a raiz do disco inteira: {texto}")
        if str(pasta) not in resultado:
            resultado.append(str(pasta))
    return resultado


def salvar_pastas(caminho: Path, pastas: list[str]) -> list[str]:
    """Grava pastas_permitidas (e a lista da Memória, se ela tiver uma própria)."""
    lista = validar_pastas(pastas)
    trocar_bloco(caminho, "pastas_permitidas", lista)
    memoria = ler_bloco(caminho, "memoria")
    if "projetos" in memoria:
        memoria["projetos"] = lista
        trocar_bloco(caminho, "memoria", memoria)
    return lista


def escolher_pasta() -> str:
    """Abre a janela do sistema para escolher uma pasta. "" se cancelou ou não deu."""
    if os.name == "nt":
        script = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            "$d=New-Object System.Windows.Forms.FolderBrowserDialog;"
            "$d.Description='Pasta que o agente pode usar';"
            "if($d.ShowDialog() -eq 'OK'){$d.SelectedPath}"
        )
        r = _rodar(["powershell", "-NoProfile", "-STA", "-Command", script], timeout=600)
    elif shutil.which("zenity"):
        r = _rodar(["zenity", "--file-selection", "--directory",
                    "--title=Pasta que o agente pode usar"], timeout=600)
    elif shutil.which("kdialog"):
        r = _rodar(["kdialog", "--getexistingdirectory", str(Path.home())], timeout=600)
    else:
        return ""
    return r.stdout.strip() if r is not None and r.returncode == 0 else ""


# --- atalho de voz --------------------------------------------------------------------------


def normalizar_atalho(texto: str) -> str:
    """'Ctrl + Alt + F' -> 'ctrl+alt+f'. Exige pelo menos um modificador e uma tecla."""
    partes = [p.strip().lower() for p in texto.replace(" ", "").split("+") if p.strip()]
    partes = ["ctrl" if p == "control" else "super" if p in ("win", "meta") else p for p in partes]
    mods = [m for m in MODIFICADORES if m in partes]
    teclas = [p for p in partes if p not in MODIFICADORES]
    valida = len(teclas) == 1 and re.fullmatch(r"[a-z0-9]|f([1-9]|1[0-2])|space", teclas[0])
    if not mods or not valida:
        raise ValueError("use um ou mais de Ctrl, Alt, Shift, Super e uma letra, número ou F1-F12")
    return "+".join([*mods, teclas[0]])


def para_gnome(atalho: str) -> str:
    nomes = {"ctrl": "<Control>", "alt": "<Alt>", "shift": "<Shift>", "super": "<Super>"}
    *mods, tecla = atalho.split("+")
    return "".join(nomes[m] for m in mods) + tecla


def para_windows(atalho: str) -> str:
    nomes = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "super": "Win"}
    *mods, tecla = atalho.split("+")
    return "+".join([*(nomes[m] for m in mods), tecla.upper()])


def _gnome_itens() -> list[str]:
    r = _rodar(["gsettings", "get", GNOME_LISTA, "custom-keybindings"])
    if r is None or r.returncode != 0:
        return []
    return re.findall(r"'([^']+)'", r.stdout)


def _gnome_ler(caminho: str, campo: str) -> str:
    r = _rodar(["gsettings", "get", f"{GNOME_ITEM}:{caminho}", campo])
    return r.stdout.strip().strip("'") if r is not None else ""


def _gnome_voz() -> str | None:
    """Caminho do atalho do GNOME que chama a voz do agente, se existir."""
    for item in _gnome_itens():
        comando = _gnome_ler(item, "command")
        if "atalho_voz" in comando or "agente-voz" in comando:
            return item
    return None


def comando_voz() -> str:
    return f'"{sys.executable}" -m agente.voz.atalho_voz'


def atalho_atual(caminho: Path | None = None) -> dict[str, str]:
    """O atalho de voz que o sistema está usando agora."""
    if os.name == "nt":
        # No Windows quem escuta o atalho é o próprio painel (RegisterHotKey), lendo o config.
        atalho = str(ler_bloco(caminho, "voz").get("atalho") or "") if caminho else ""
        return {"atalho": atalho, "sistema": "windows"}
    if shutil.which("gsettings"):
        item = _gnome_voz()
        if item:
            bruto = _gnome_ler(item, "binding")
            texto = bruto.replace("<Control>", "ctrl+").replace("<Primary>", "ctrl+")
            texto = texto.replace("<Alt>", "alt+").replace("<Shift>", "shift+")
            texto = texto.replace("<Super>", "super+")
            return {"atalho": texto.lower(), "sistema": "gnome"}
        return {"atalho": "", "sistema": "gnome"}
    return {"atalho": "", "sistema": "outro"}


def _lnk_windows() -> Path:
    return (Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu"
            / "Programs" / NOME_LNK_WINDOWS)


def aplicar_atalho(atalho: str, caminho: Path | None = None) -> str:
    """Grava o atalho de voz no sistema. Devolve o atalho normalizado."""
    atalho = normalizar_atalho(atalho)
    if os.name == "nt":
        # A tecla de atalho de um .lnk só funciona às vezes (o Explorer precisa recarregar e
        # jogos ou apps em foco engolem a tecla). O painel registra o atalho sozinho; aqui só
        # fica gravado no config.yaml e o .lnk antigo sai para não brigar pela mesma tecla.
        from agente import atalho as atalho_win

        atalho_win.traduzir(atalho)  # o Windows só aceita letra ou número no fim
        if caminho is None:
            raise RuntimeError("falta o caminho do config.yaml")
        voz = ler_bloco(caminho, "voz")
        voz["atalho"] = atalho
        trocar_bloco(caminho, "voz", voz)
        _lnk_windows().unlink(missing_ok=True)
        return atalho
    if not shutil.which("gsettings"):
        raise RuntimeError("só sei mudar o atalho no GNOME (Ubuntu) e no Windows")
    item = _gnome_voz()
    if item is None:
        item = f"{GNOME_BASE}/agente-voz/"
        lista = _gnome_itens()
        if item not in lista:
            lista.append(item)
            valor = "[" + ", ".join(f"'{i}'" for i in lista) + "]"
            _rodar(["gsettings", "set", GNOME_LISTA, "custom-keybindings", valor])
        _rodar(["gsettings", "set", f"{GNOME_ITEM}:{item}", "name", NOME_ATALHO_GNOME])
        _rodar(["gsettings", "set", f"{GNOME_ITEM}:{item}", "command", comando_voz()])
    r = _rodar(["gsettings", "set", f"{GNOME_ITEM}:{item}", "binding", para_gnome(atalho)])
    if r is None or r.returncode != 0:
        raise RuntimeError("o GNOME recusou o atalho")
    return atalho
