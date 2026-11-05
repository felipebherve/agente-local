"""Cliente mínimo da API local do Ollama, só com a biblioteca padrão."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from agente.config import Config

logger = logging.getLogger(__name__)


class ErroOllama(Exception):
    """Ollama fora do ar, lento demais ou com resposta inválida."""


@dataclass(frozen=True)
class Resposta:
    texto: str
    modelo: str
    tokens_entrada: int
    tokens_saida: int
    segundos: float
    tokens_por_s: float


class ClienteOllama:
    def __init__(
        self,
        url: str,
        timeout_s: float,
        keep_alive: str = "10m",
        pensar: bool | None = None,
        max_tokens: int = 1024,
    ) -> None:
        self.url = url.rstrip("/")
        self.timeout_s = timeout_s
        self.keep_alive = keep_alive
        self.pensar = pensar
        self.max_tokens = max_tokens

    @classmethod
    def de_config(cls, cfg: Config) -> ClienteOllama:
        return cls(cfg.ollama_url, cfg.timeout_s, cfg.keep_alive, cfg.pensar, cfg.max_tokens)

    def _requisitar(self, rota: str, corpo: dict[str, Any] | None = None) -> dict[str, Any]:
        dados = None if corpo is None else json.dumps(corpo).encode("utf-8")
        req = urllib.request.Request(
            f"{self.url}{rota}", data=dados, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                resultado: dict[str, Any] = json.loads(r.read().decode("utf-8"))
                return resultado
        except urllib.error.HTTPError as exc:
            detalhe = exc.read().decode("utf-8", "replace")
            raise ErroOllama(f"Ollama respondeu {exc.code} em {rota}: {detalhe}") from exc
        except urllib.error.URLError as exc:
            raise ErroOllama(
                f"Ollama fora do ar em {self.url} ({exc.reason}). Abra o Ollama e tente de novo."
            ) from exc
        except TimeoutError as exc:
            raise ErroOllama(f"Ollama não respondeu em {self.timeout_s:.0f}s ({rota})") from exc
        except json.JSONDecodeError as exc:
            raise ErroOllama(f"resposta inválida do Ollama em {rota}: {exc}") from exc

    def versao(self) -> str:
        return str(self._requisitar("/api/version").get("version", "?"))

    def modelos_instalados(self) -> list[str]:
        return [str(m["name"]) for m in self._requisitar("/api/tags").get("models", [])]

    def conversar(
        self,
        modelo: str,
        pergunta: str,
        sistema: str | None = None,
        temperatura: float = 0.2,
        imagens: list[str] | None = None,
    ) -> Resposta:
        """Envia uma pergunta (com imagens em base64, opcional) e devolve a resposta completa."""
        mensagens: list[dict[str, Any]] = (
            [{"role": "system", "content": sistema}] if sistema else []
        )
        usuario: dict[str, Any] = {"role": "user", "content": pergunta}
        if imagens:
            usuario["images"] = imagens
        mensagens.append(usuario)
        corpo: dict[str, Any] = {
            "model": modelo,
            "messages": mensagens,
            "stream": False,
            "keep_alive": self.keep_alive,
            # num_predict evita que um modelo entre em loop e prenda a GPU
            "options": {"temperature": temperatura, "num_predict": self.max_tokens},
        }
        if self.pensar is not None:
            corpo["think"] = self.pensar
        inicio = time.perf_counter()
        dados = self._requisitar("/api/chat", corpo)
        segundos = time.perf_counter() - inicio
        saida = int(dados.get("eval_count", 0))
        duracao_ns = int(dados.get("eval_duration", 0))
        logger.info("chat %s: %d tokens em %.1fs", modelo, saida, segundos)
        return Resposta(
            texto=str(dados.get("message", {}).get("content", "")).strip(),
            modelo=modelo,
            tokens_entrada=int(dados.get("prompt_eval_count", 0)),
            tokens_saida=saida,
            segundos=segundos,
            tokens_por_s=saida / (duracao_ns / 1e9) if duracao_ns else 0.0,
        )

    def embutir(self, modelo: str, textos: list[str]) -> list[list[float]]:
        """Gera embeddings para busca semântica."""
        dados = self._requisitar("/api/embed", {"model": modelo, "input": textos})
        return [list(map(float, v)) for v in dados.get("embeddings", [])]

    def modelos_carregados(self) -> dict[str, float]:
        """Modelos na memória agora e quantos GB de VRAM cada um ocupa."""
        return {
            str(m["name"]): int(m.get("size_vram", 0)) / 1024**3
            for m in self._requisitar("/api/ps").get("models", [])
        }

    def acordar(self, modelo: str, keep_alive: str | int | None = None) -> None:
        """Carrega o modelo na GPU para a primeira resposta sair rápida.

        keep_alive=-1 deixa o modelo carregado até alguém mandar dormir.
        """
        validade = self.keep_alive if keep_alive is None else keep_alive
        self._requisitar("/api/generate", {"model": modelo, "keep_alive": validade})
        logger.info("modelo %s carregado", modelo)

    def dormir(self, modelo: str) -> None:
        """Tira o modelo da GPU e libera a VRAM (para jogos, por exemplo)."""
        self._requisitar("/api/generate", {"model": modelo, "keep_alive": 0})
        logger.info("modelo %s descarregado", modelo)
