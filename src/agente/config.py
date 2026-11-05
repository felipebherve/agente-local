"""Carrega e valida a configuração do agente a partir do config.yaml."""

from __future__ import annotations

import os
import string
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

RAIZ = Path(__file__).resolve().parents[2]
CAMINHO_PADRAO = RAIZ / "config.yaml"

# Config compartilhada entre os PCs (Linux e Windows) por um HD externo (opcional): hoje só
# os provedores do OmniRoute, pra não ter que repetir "ligar uma IA nova" em cada máquina.
# O nome da pasta do HD vem do config.yaml (hd_compartilhado); vazio = não usa.
NOME_HD = ""
CAMINHO_COMPARTILHADO = Path("Backup") / "Agente de Ia" / "compartilhado.yaml"
RAIZES_LINUX = (Path("/run/media"), Path("/media"), Path("/mnt"))


def achar_hd(nome: str = NOME_HD) -> Path | None:
    """Acha o HD externo nos lugares comuns do Linux e do Windows; None se não estiver ligado."""
    if not nome:
        return None
    if os.name == "nt":
        candidatos = [Path(f"{letra}:/") / nome for letra in string.ascii_uppercase]
    else:
        candidatos = []
        for raiz in RAIZES_LINUX:
            if raiz.is_dir():
                candidatos += sorted(raiz.glob(f"*/{nome}"))
    return next((c for c in candidatos if c.is_dir()), None)


def _ler_compartilhado(hd: Path | None) -> dict[str, Any]:
    if hd is None:
        return {}
    arq = hd / CAMINHO_COMPARTILHADO
    if not arq.exists():
        return {}
    try:
        dados = yaml.safe_load(arq.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return dados if isinstance(dados, dict) else {}


class ErroConfig(Exception):
    """Config ausente, ilegível ou incompleta."""


@dataclass(frozen=True)
class Modelos:
    cerebro: str
    codigo: str
    visao: str
    embeddings: str


@dataclass(frozen=True)
class Config:
    ollama_url: str
    timeout_s: float
    keep_alive: str
    pensar: bool | None
    max_tokens: int
    modelos: Modelos
    pasta_logs: Path
    pastas_permitidas: tuple[Path, ...]
    comandos_liberados: tuple[str, ...]
    navegador: str
    apps_liberados: dict[str, str]
    sites_liberados: dict[str, str]
    pasta_dados: Path
    atalho_acordar: str = "ctrl+alt+a"
    voz: Voz = field(default_factory=lambda: Voz())
    nome_usuario: str = ""  # como o agente chama você nas respostas ("" = sem nome)
    limites: Limites = field(default_factory=lambda: Limites())
    ferramentas: Ferramentas = field(default_factory=lambda: Ferramentas())
    memoria: Memoria = field(default_factory=lambda: Memoria())
    omniroute: Omniroute = field(default_factory=lambda: Omniroute())


@dataclass(frozen=True)
class Omniroute:
    """Degrau do meio entre o Cérebro local e o Claude: IA grátis na nuvem.

    Servidor local do OmniRoute (github.com/diegosouzapw/OmniRoute); sem ele no ar, ou
    sem provedor conectado no painel dele, o Porteiro simplesmente pula para o Claude.
    """

    ligado: bool = True
    url: str = "http://127.0.0.1:20128/v1"
    timeout_s: float = 25.0
    # "auto" do OmniRoute pode cair em provedor não conectado/quebrado; por isso é uma
    # fila fixa (na ordem) dos provedores já testados, não "auto". Pra adicionar um
    # provedor novo: conecte ele no painel (localhost:20128 -> Providers) e acrescente
    # "provedor/modelo" aqui (docs/reference/PROVIDER_REFERENCE.md no repositório do
    # OmniRoute tem o id de cada um).
    modelos: tuple[str, ...] = ("duckduckgo-web/gpt-4o-mini",)


@dataclass(frozen=True)
class Limites:
    """Teto de uso do PC: acima disso o agente recusa a tarefa em vez de travar o computador."""

    ram_pct: float = 90.0
    vram_pct: float = 95.0


@dataclass(frozen=True)
class Memoria:
    """Agente Memória: quais projetos ele mantém indexados e o que ignora."""

    projetos: tuple[Path, ...] = ()  # cada subpasta destas pastas é um projeto
    intervalo_min: float = 10.0  # de quanto em quanto tempo confere arquivos alterados
    ignorar: tuple[str, ...] = ("*backup*", "*-antiga*", "*_old", "old_*", "*.bak")


def _ler_memoria(bruto: Any, pastas_permitidas: tuple[Path, ...]) -> Memoria:
    bruto = bruto if isinstance(bruto, dict) else {}
    padrao = Memoria()
    return Memoria(
        projetos=tuple(Path(p) for p in bruto.get("projetos") or pastas_permitidas),
        intervalo_min=float(bruto.get("intervalo_min", padrao.intervalo_min)),
        ignorar=tuple(str(g) for g in bruto.get("ignorar") or padrao.ignorar),
    )


@dataclass(frozen=True)
class Ferramentas:
    """O que o botão "Ligar ferramentas" abre além do Ollama, Docker e Ubuntu."""

    distro: str = "Ubuntu"  # distro do WSL usada no terminal e no VS Code
    pasta_wsl: str = ""  # pasta aberta no VS Code ('' = home do Ubuntu)
    voz: bool = True  # já carrega o ouvido (Whisper) na placa de vídeo
    claude: bool = True  # abre o Claude Desktop se estiver fechado


def _ler_ferramentas(bruto: Any) -> Ferramentas:
    if not isinstance(bruto, dict):
        return Ferramentas()
    padrao = Ferramentas()
    return Ferramentas(
        distro=str(bruto.get("distro", padrao.distro)),
        pasta_wsl=str(bruto.get("pasta_wsl") or ""),
        voz=bool(bruto.get("voz", padrao.voz)),
        claude=bool(bruto.get("claude", padrao.claude)),
    )


@dataclass(frozen=True)
class Voz:
    stt: str = "large-v3-turbo"  # modelo do faster-whisper na placa de vídeo
    stt_cpu: str = "small"  # usado se a placa de vídeo não estiver disponível
    tts: str = "pt_BR-faber-medium"  # voz do Piper
    atalho: str = "ctrl+alt+v"
    silencio_s: float = 1.2  # pausa que encerra a gravação
    max_s: float = 30.0
    falar_respostas: bool = False  # ler as respostas em voz alta (o "narrador")
    microfone: str = ""  # trecho do nome do microfone; "" = o padrão do sistema


def _ler_voz(bruto: Any) -> Voz:
    if not isinstance(bruto, dict):
        return Voz()
    padrao = Voz()
    return Voz(
        stt=str(bruto.get("stt", padrao.stt)),
        stt_cpu=str(bruto.get("stt_cpu", padrao.stt_cpu)),
        tts=str(bruto.get("tts", padrao.tts)),
        atalho=str(bruto.get("atalho", padrao.atalho)),
        silencio_s=float(bruto.get("silencio_s", padrao.silencio_s)),
        max_s=float(bruto.get("max_s", padrao.max_s)),
        falar_respostas=bool(bruto.get("falar_respostas", padrao.falar_respostas)),
        microfone=str(bruto.get("microfone", padrao.microfone) or ""),
    )


def _ler_omniroute(bruto: Any) -> Omniroute:
    if not isinstance(bruto, dict):
        return Omniroute()
    padrao = Omniroute()
    brutos_modelos = bruto.get("modelos")
    if brutos_modelos is None:
        modelos = padrao.modelos
    elif isinstance(brutos_modelos, list):
        modelos = tuple(str(m) for m in brutos_modelos)
    else:
        modelos = (str(brutos_modelos),)
    return Omniroute(
        ligado=bool(bruto.get("ligado", padrao.ligado)),
        url=str(bruto.get("url", padrao.url)).rstrip("/"),
        timeout_s=float(bruto.get("timeout_s", padrao.timeout_s)),
        modelos=modelos,
    )


def _ler_yaml(caminho: Path) -> dict[str, Any]:
    try:
        bruto = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ErroConfig(f"config não encontrada: {caminho}") from exc
    except yaml.YAMLError as exc:
        raise ErroConfig(f"config.yaml inválido: {exc}") from exc
    if not isinstance(bruto, dict):
        raise ErroConfig("config.yaml precisa ser um mapa de chaves e valores")
    return bruto


def caminho_config() -> Path:
    """config.yaml do agente; a variável AGENTE_CONFIG troca o caminho (testes, outra máquina)."""
    return Path(os.environ.get("AGENTE_CONFIG") or CAMINHO_PADRAO)


def carregar_config(caminho: Path | None = None) -> Config:
    """Lê o config.yaml e devolve uma Config validada."""
    caminho = caminho or caminho_config()
    bruto = _ler_yaml(caminho)
    try:
        m = bruto["modelos"]
        modelos = Modelos(
            cerebro=str(m["cerebro"]),
            codigo=str(m["codigo"]),
            visao=str(m["visao"]),
            embeddings=str(m["embeddings"]),
        )
    except (KeyError, TypeError) as exc:
        raise ErroConfig(f"bloco 'modelos' incompleto no config.yaml: {exc}") from exc
    pensar = bruto.get("pensar")
    pastas_permitidas = tuple(Path(p) for p in bruto.get("pastas_permitidas", []))
    hd = str(bruto.get("hd_compartilhado") or "")
    compartilhado = _ler_compartilhado(achar_hd(hd) if hd else None)
    return Config(
        ollama_url=str(bruto.get("ollama_url", "http://localhost:11434")).rstrip("/"),
        timeout_s=float(bruto.get("timeout_s", 180)),
        keep_alive=str(bruto.get("keep_alive", "10m")),
        pensar=None if pensar is None else bool(pensar),
        max_tokens=int(bruto.get("max_tokens", 1024)),
        modelos=modelos,
        pasta_logs=caminho.parent / str(bruto.get("pasta_logs", "logs")),
        pastas_permitidas=pastas_permitidas,
        comandos_liberados=tuple(str(c) for c in bruto.get("comandos_liberados", [])),
        navegador=str(bruto.get("navegador", "msedge")),
        apps_liberados={
            str(k).lower(): str(v) for k, v in (bruto.get("apps_liberados") or {}).items()
        },
        sites_liberados={
            str(k).lower(): str(v) for k, v in (bruto.get("sites_liberados") or {}).items()
        },
        pasta_dados=caminho.parent / str(bruto.get("pasta_dados", "dados")),
        nome_usuario=str(bruto.get("nome_usuario") or ""),
        atalho_acordar=str(bruto.get("atalho_acordar", "ctrl+alt+a")),
        voz=_ler_voz(bruto.get("voz")),
        ferramentas=_ler_ferramentas(bruto.get("ferramentas")),
        memoria=_ler_memoria(bruto.get("memoria"), pastas_permitidas),
        omniroute=_ler_omniroute(compartilhado.get("omniroute", bruto.get("omniroute"))),
        limites=Limites(
            ram_pct=float((bruto.get("limites") or {}).get("ram_pct", 90)),
            vram_pct=float((bruto.get("limites") or {}).get("vram_pct", 95)),
        ),
    )
