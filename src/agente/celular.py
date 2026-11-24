"""App do celular: pareamento por código e o passo a passo do Tailscale.

O painel continua ouvindo só em 127.0.0.1. O celular chega nele pelo `tailscale serve`,
que leva o HTTPS da rede privada do Tailscale (só os seus aparelhos) até o painel. Na
primeira vez o celular digita o código de pareamento; depois disso fica um cookie
seguro nele. `agente celular --novo-codigo` troca o código e desconecta os celulares.

O código e a sessão ficam em dados/celular.json (fora do git, só leitura do dono).
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import threading
import time
from pathlib import Path

from agente.config import Config

ARQUIVO = "celular.json"
COOKIE = "agente_celular"
ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sem 0/O e 1/I, para digitar fácil
TENTATIVAS = 10  # erros seguidos antes de travar o pareamento
TRAVA_S = 15 * 60

_trava = threading.Lock()
_erros = 0
_travado_ate = 0.0


def _arquivo(cfg: Config) -> Path:
    return cfg.pasta_dados / ARQUIVO


def _novo() -> dict[str, str]:
    codigo = "".join(secrets.choice(ALFABETO) for _ in range(8))
    return {"codigo": codigo, "sessao": secrets.token_urlsafe(32)}


def _salvar(cfg: Config, dados: dict[str, str]) -> None:
    arq = _arquivo(cfg)
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(dados), encoding="utf-8")
    try:
        os.chmod(arq, 0o600)
    except OSError:  # Windows: a pasta do usuário já é só dele
        pass


def ler(cfg: Config) -> dict[str, str]:
    """Código e sessão atuais (cria na primeira vez)."""
    try:
        dados = json.loads(_arquivo(cfg).read_text(encoding="utf-8"))
        if isinstance(dados, dict) and dados.get("codigo") and dados.get("sessao"):
            return {"codigo": str(dados["codigo"]), "sessao": str(dados["sessao"])}
    except (OSError, ValueError):
        pass
    dados = _novo()
    _salvar(cfg, dados)
    return dados


def novo_codigo(cfg: Config) -> str:
    dados = _novo()
    _salvar(cfg, dados)
    return dados["codigo"]


def parear(cfg: Config, codigo: str) -> str | None:
    """Devolve a sessão (valor do cookie) se o código bate; trava após muitos erros."""
    global _erros, _travado_ate
    with _trava:
        if time.monotonic() < _travado_ate:
            return None
        dados = ler(cfg)
        digitado = "".join(codigo.split()).upper().replace("-", "")
        if secrets.compare_digest(digitado.encode(), dados["codigo"].encode()):
            _erros = 0
            return dados["sessao"]
        _erros += 1
        if _erros >= TENTATIVAS:
            _erros = 0
            _travado_ate = time.monotonic() + TRAVA_S
        return None


def sessao_valida(cfg: Config, valor: str) -> bool:
    certa = ler(cfg).get("sessao", "")
    return bool(valor) and secrets.compare_digest(valor.encode(), certa.encode())


def _zerar_trava() -> None:  # para os testes
    global _erros, _travado_ate
    with _trava:
        _erros, _travado_ate = 0, 0.0


def passo_a_passo(cfg: Config, porta: int) -> str:
    """Texto do comando `agente celular`."""
    tem_tailscale = shutil.which("tailscale") is not None
    codigo = ler(cfg)["codigo"]
    linhas = ["App do Agente Local no celular", ""]
    if not tem_tailscale:
        linhas += [
            "1. Instale o Tailscale (grátis) neste PC: https://tailscale.com/download",
            "   e entre com a mesma conta no app do Tailscale do celular.",
        ]
    else:
        linhas.append("1. Tailscale encontrado neste PC. Entre com a mesma conta no celular.")
    linhas += [
        f"2. Rode uma vez: tailscale serve --bg {porta}",
        "   (o Tailscale mostra o endereço, algo como https://seu-pc.tail1234.ts.net)",
        "3. Rode: agente celular --ligar seu-pc.tail1234.ts.net",
        "4. No celular, abra esse endereço, digite o código abaixo e use",
        '   "Adicionar à tela inicial" (Android: "Instalar app").',
        "",
        f"Código de pareamento: {codigo[:4]}-{codigo[4:]}",
        "",
        "Situação agora: "
        + (
            f"ligado para {cfg.celular.endereco}"
            if cfg.celular.ligado and cfg.celular.endereco
            else "desligado (o painel só abre neste PC)"
        ),
    ]
    return "\n".join(linhas)
