"""Assistente de instalação (`agente init`) e diagnóstico (`agente doctor`).

init: vê a placa de vídeo, escolhe modelos que cabem nela, cria o config.yaml, baixa os
modelos no Ollama e registra o agente no Claude (Code e Desktop).
doctor: confere cada peça e diz em uma linha o que corrigir.

Os dois funcionam sem o config.yaml existir (por isso não recebem uma Config).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from agente.config import CAMINHO_PADRAO, RAIZ

EXEMPLO = RAIZ / "config.example.yaml"


@dataclass(frozen=True)
class Nivel:
    nome: str
    vram_min_gb: float
    cerebro: str
    codigo: str
    visao: str


# Do maior pro menor; o primeiro que couber na placa ganha.
NIVEIS = (
    Nivel("12 GB ou mais", 11.0, "qwen3:8b", "qwen2.5-coder:7b", "qwen2.5vl:7b"),
    Nivel("8 GB", 7.5, "qwen3:8b", "qwen2.5-coder:7b", ""),
    Nivel("6 GB", 5.5, "qwen3:4b", "qwen2.5-coder:3b", ""),
    Nivel("só processador", 0.0, "qwen3:1.7b", "qwen2.5-coder:1.5b", ""),
)
EMBEDDINGS = "nomic-embed-text"


def escolher_nivel(vram_gb: float) -> Nivel:
    for nivel in NIVEIS:
        if vram_gb >= nivel.vram_min_gb:
            return nivel
    return NIVEIS[-1]


def vram_total_gb() -> float:
    from agente import recursos

    return recursos._vram()[1]


def montar_config(
    nivel: Nivel, pastas: list[str], nome: str = "", omniroute: bool = False
) -> str:
    """Texto do config.yaml a partir do config.example.yaml, trocando só o necessário."""
    texto = EXEMPLO.read_text(encoding="utf-8")
    trocas = {
        "{CEREBRO}": nivel.cerebro,
        "{CODIGO}": nivel.codigo,
        "{VISAO}": nivel.visao or nivel.cerebro,
        "{EMBEDDINGS}": EMBEDDINGS,
        "{NOME}": json.dumps(nome, ensure_ascii=False),
        "{OMNIROUTE}": "true" if omniroute else "false",
        "{PASTAS}": "\n".join(f"  - {json.dumps(p, ensure_ascii=False)}" for p in pastas)
        or "  []",
    }
    for chave, valor in trocas.items():
        texto = texto.replace(chave, valor)
    return texto


def _perguntar(texto: str, padrao: str, sim: bool) -> str:
    if sim:
        return padrao
    resposta = input(f"{texto} [{padrao}]: ").strip()
    return resposta or padrao


def _ollama_no_ar(url: str = "http://localhost:11434") -> bool:
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=2):  # noqa: S310 - localhost
            return True
    except OSError:
        return False


def _omniroute_no_ar(url: str = "http://127.0.0.1:20128") -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2):  # noqa: S310 - localhost
            return True
    except urllib.error.HTTPError:
        return True
    except OSError:
        return False


def init(sim: bool = False, baixar: bool = True, caminho: Path = CAMINHO_PADRAO) -> int:
    """Cria o config.yaml, baixa os modelos e registra no Claude. sim=True aceita os padrões."""
    print("== Agente local: configuração ==")
    vram = vram_total_gb()
    nivel = escolher_nivel(vram)
    print(f"Placa de vídeo: {vram:.0f} GB -> modelos para '{nivel.nome}': "
          f"{nivel.cerebro}, {nivel.codigo}" + (f", {nivel.visao}" if nivel.visao else ""))

    escrever = not caminho.exists()
    if not escrever and not sim:
        escrever = _perguntar("Já existe um config.yaml. Substituir? (s/n)", "n", sim) == "s"
    if escrever:
        pasta_padrao = str(Path.home() / "projetos")
        pastas = _perguntar(
            "Pastas dos seus projetos que o agente pode usar (separe por ;)", pasta_padrao, sim
        )
        nome = _perguntar("Como o agente deve te chamar? (vazio = sem nome)", "", sim)
        if _omniroute_no_ar():
            print("OmniRoute encontrado. Para usar: conecte um provedor no painel dele "
                  "(http://localhost:20128), ponha o id em omniroute.modelos e ligado: true.")
        else:
            print("OmniRoute não encontrado (é opcional).")
        lista = [p.strip() for p in pastas.split(";") if p.strip()]
        caminho.write_text(montar_config(nivel, lista, nome, False), encoding="utf-8")
        print(f"Config criada: {caminho}")
    else:
        print("Mantive o config.yaml atual.")

    if baixar:
        if not shutil.which("ollama"):
            print("Ollama não encontrado. Instale em https://ollama.com e rode 'agente init'.")
            return 1
        for modelo in dict.fromkeys(m for m in (nivel.cerebro, nivel.codigo, nivel.visao,
                                                  EMBEDDINGS) if m):
            print(f"Baixando {modelo} (pode demorar na primeira vez)...")
            subprocess.run(["ollama", "pull", modelo], check=False)  # noqa: S603,S607

    from agente.instalar import instalar_no_claude

    try:
        print("\n".join(instalar_no_claude()))
    except FileNotFoundError as exc:
        print(f"Não registrei no Claude: {exc}")
        return 1
    print("\nPronto. Abra o Claude Code e peça algo: ele vai chamar o agente sozinho.")
    print("Painel: comando 'agente-painel' (abre no navegador).")
    return 0


@dataclass(frozen=True)
class Checagem:
    nome: str
    ok: bool
    dica: str


def doctor() -> list[Checagem]:
    """Confere as peças, sem mudar nada."""
    from agente.config import ErroConfig, carregar_config

    checagens: list[Checagem] = []
    try:
        cfg = carregar_config()
        checagens.append(Checagem("config.yaml", True, str(CAMINHO_PADRAO)))
    except ErroConfig as exc:
        cfg = None
        checagens.append(Checagem("config.yaml", False, f"{exc}. Rode: agente init"))

    url = cfg.ollama_url if cfg else "http://localhost:11434"
    ollama = _ollama_no_ar(url)
    checagens.append(Checagem("Ollama", ollama, url if ollama else
                              "Fora do ar. Abra o Ollama (https://ollama.com)."))
    if ollama and cfg:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=3) as r:  # noqa: S310
            baixados = {m["name"] for m in json.loads(r.read()).get("models", [])}
        for papel, modelo in (("cérebro", cfg.modelos.cerebro), ("código", cfg.modelos.codigo),
                              ("busca", cfg.modelos.embeddings)):
            tem = modelo in baixados or f"{modelo}:latest" in baixados
            checagens.append(Checagem(f"modelo {papel}", tem,
                                      modelo if tem else f"Falta: ollama pull {modelo}"))

    vram = vram_total_gb()
    checagens.append(Checagem("placa de vídeo", vram > 0, f"{vram:.0f} GB" if vram else
                              "NVIDIA não encontrada: vai rodar no processador (mais lento)."))
    if cfg and cfg.omniroute.ligado:
        base = cfg.omniroute.url.rsplit("/v1", 1)[0]
        omni = _omniroute_no_ar(base)
        checagens.append(Checagem("OmniRoute", omni, base if omni else
                                  "Ligado no config mas fora do ar. Rode: omniroute"))
    checagens.append(Checagem("GitHub (gh)", shutil.which("gh") is not None,
                              "ok" if shutil.which("gh") else
                              "Opcional, para PRs: instale o gh e rode 'gh auth login'."))
    claude = Path.home() / ".claude.json"
    registrado = claude.exists() and "agente-local" in claude.read_text(encoding="utf-8")
    checagens.append(Checagem("Claude Code", registrado, "agente registrado" if registrado else
                              "Agente não registrado. Rode: agente instalar-claude"))
    return checagens


def imprimir_doctor() -> int:
    falhas = 0
    for c in doctor():
        print(f"{'OK ' if c.ok else 'X  '} {c.nome}: {c.dica}")
        falhas += not c.ok
    return 1 if falhas else 0
