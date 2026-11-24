"""O que o app manda para o PC: fotos para transcrever, áudio do microfone e o Tailscale.

As fotos e o áudio chegam em base64 pelo painel, vão para uma pasta temporária, são lidos
pelo modelo local e apagados logo depois: documentos de clientes não ficam guardados.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from agente.config import Config
from agente.executor import ErroExecucao
from agente.llm import ClienteOllama

logger = logging.getLogger(__name__)

MAX_IMAGENS = 20
MAX_BYTES_IMAGEM = 15 * 1024 * 1024
MAX_BYTES_AUDIO = 15 * 1024 * 1024
EXT_AUDIO = {".webm", ".ogg", ".mp4", ".m4a", ".wav", ".mp3", ".aac"}


def _decodificar(dados: str, limite: int) -> bytes:
    if "," in dados[:100] and dados.startswith("data:"):
        dados = dados.split(",", 1)[1]  # "data:image/png;base64,...."
    try:
        bruto = base64.b64decode(dados, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ErroExecucao("arquivo corrompido no envio") from exc
    if len(bruto) > limite:
        raise ErroExecucao(f"arquivo grande demais (limite {limite // 1024 // 1024} MB)")
    return bruto


def _nome_seguro(nome: str, i: int, padrao: str) -> str:
    sufixo = Path(nome).suffix.lower()
    base = re.sub(r"[^\w.-]+", "_", Path(nome).stem)[:60] or "arquivo"
    return f"{i:02d}-{base}{sufixo or padrao}"


def transcrever_envio(
    cfg: Config, cliente: ClienteOllama, arquivos: list[dict[str, Any]], foco: str = ""
) -> str:
    """Transcreve as imagens mandadas pelo app (uma ou várias) e apaga as cópias."""
    from agente import documentos

    if not arquivos:
        raise ErroExecucao("nenhuma imagem enviada")
    if len(arquivos) > MAX_IMAGENS:
        raise ErroExecucao(f"{len(arquivos)} imagens; o limite por vez é {MAX_IMAGENS}")
    with tempfile.TemporaryDirectory(prefix="agente-envio-") as pasta:
        caminhos: list[Path] = []
        for i, arq in enumerate(arquivos, 1):
            nome = _nome_seguro(str(arq.get("nome", "")), i, ".jpg")
            if Path(nome).suffix not in documentos.EXT_IMAGEM:
                raise ErroExecucao(f"tipo de arquivo não suportado: {arq.get('nome', '')}")
            destino = Path(pasta) / nome
            destino.write_bytes(_decodificar(str(arq.get("dados", "")), MAX_BYTES_IMAGEM))
            caminhos.append(destino)
        return documentos.transcrever_arquivos(cfg, cliente, caminhos, foco)


def ouvir_envio(cfg: Config, dados: str, tipo: str = "") -> str:
    """Transcreve o áudio gravado no microfone do celular com o Whisper do PC."""
    try:
        from agente.voz import ouvido
    except ImportError as exc:
        raise ErroExecucao(
            "a voz não está instalada no PC: rode o instalador com a opção de voz"
        ) from exc
    extensao = {"audio/webm": ".webm", "audio/ogg": ".ogg", "audio/mp4": ".mp4"}.get(
        tipo.split(";")[0].strip(), ".webm"
    )
    with tempfile.TemporaryDirectory(prefix="agente-audio-") as pasta:
        arquivo = Path(pasta) / f"fala{extensao}"
        arquivo.write_bytes(_decodificar(dados, MAX_BYTES_AUDIO))
        try:
            return str(ouvido.transcrever(cfg, str(arquivo)))
        except ImportError as exc:  # faster-whisper ausente
            raise ErroExecucao(
                "a voz não está instalada no PC: rode o instalador com a opção de voz"
            ) from exc


# --- Tailscale -------------------------------------------------------------------------

_cache: dict[str, Any] = {"quando": 0.0, "estado": None}
CACHE_S = 15


def _tailscale() -> str | None:
    achado = shutil.which("tailscale")
    if achado:
        return achado
    if sys.platform == "win32":
        padrao = Path(r"C:\Program Files\Tailscale\tailscale.exe")
        return str(padrao) if padrao.exists() else None
    return None


def _rodar(args: list[str], timeout: float = 10) -> subprocess.CompletedProcess[str] | None:
    exe = _tailscale()
    if not exe:
        return None
    try:
        return subprocess.run(  # noqa: S603 - binário do Tailscale, argumentos fixos
            [exe, *args], capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.info("tailscale %s: %s", args[0], exc)
        return None


def estado_tailscale(porta: int, usar_cache: bool = True) -> dict[str, Any]:
    """instalado / conectado (logado e rodando) / servindo (o painel está no serve)."""
    agora = time.monotonic()
    if usar_cache and _cache["estado"] is not None and agora - _cache["quando"] < CACHE_S:
        return dict(_cache["estado"])
    estado = {"instalado": _tailscale() is not None, "conectado": False, "servindo": False}
    r = _rodar(["status", "--json"])
    if r and r.returncode == 0:
        try:
            estado["conectado"] = json.loads(r.stdout).get("BackendState") == "Running"
        except ValueError:
            pass
    r = _rodar(["serve", "status", "--json"])
    if r and r.returncode == 0:
        estado["servindo"] = f"127.0.0.1:{porta}" in r.stdout
    _cache.update(quando=agora, estado=estado)
    return dict(estado)


def ligar_tailscale(porta: int) -> dict[str, Any]:
    """Liga o Tailscale e o serve do painel. Se precisar entrar na conta, devolve o link."""
    if not _tailscale():
        return {"ok": False, "aviso": "Instale o Tailscale: https://tailscale.com/download"}
    r = _rodar(["up", "--timeout=15s"], timeout=25)
    saida = (r.stdout + r.stderr) if r else ""
    link = re.search(r"https://login\.tailscale\.com/\S+", saida)
    if link:
        _cache["estado"] = None
        return {"ok": False, "link": link.group(0), "aviso": "Entre na sua conta pelo link."}
    if r is not None and r.returncode != 0 and "Access denied" in saida:
        return {
            "ok": False,
            "aviso": "Falta permissão: rode uma vez no terminal "
            "'sudo tailscale set --operator=$USER' e tente de novo.",
        }
    r = _rodar(["serve", "--bg", str(porta)], timeout=20)
    saida = (r.stdout + r.stderr) if r else ""
    link = re.search(r"https://login\.tailscale\.com/\S+", saida)
    _cache["estado"] = None
    if link:  # HTTPS ainda não ativado na conta
        return {"ok": False, "link": link.group(0), "aviso": "Ative o HTTPS pelo link."}
    ok = bool(r and r.returncode == 0)
    return {"ok": ok, "aviso": "" if ok else (saida.strip()[-300:] or "não deu certo")}
