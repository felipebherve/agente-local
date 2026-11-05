"""Roda os testes de um projeto e devolve só o essencial: contagem, falhas e causa provável."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from agente.compactar import compactar
from agente.config import Config
from agente.economia import registrar
from agente.executor import ErroExecucao, executar, validar_pasta
from agente.llm import ClienteOllama, ErroOllama

logger = logging.getLogger(__name__)

CONTAGEM = re.compile(r"(\d+)\s+(passed|failed|errors?)\b", re.IGNORECASE)
LINHA_FALHA = re.compile(r"^\s*(FAILED|ERROR|FAIL|●|×|✕)\s+(.+)$")
MAX_FALHAS = 10


@dataclass(frozen=True)
class RelatorioTestes:
    comando: str
    ok: bool
    passaram: int
    falharam: int
    segundos: float
    falhas: list[str] = field(default_factory=list)
    causa: str = ""

    def texto(self) -> str:
        situacao = "OK" if self.ok else "FALHOU"
        linhas = [
            f"{situacao}: {self.passaram} passaram, {self.falharam} falharam "
            f"({self.segundos:.0f}s) [{self.comando}]"
        ]
        linhas += [f"- {f}" for f in self.falhas]
        if self.causa:
            linhas.append(f"Causa provável: {self.causa}")
        return "\n".join(linhas)


def _python_do_projeto(pasta: Path) -> str:
    for venv in (".venv", "venv"):
        candidato = pasta / venv / "Scripts" / "python.exe"
        if candidato.exists():
            return str(candidato)
        candidato = pasta / venv / "bin" / "python"
        if candidato.exists():
            return str(candidato)
    return "python"


def detectar_comando(pasta: Path) -> list[str]:
    """Escolhe pytest ou o script de teste do package.json."""
    marcadores_py = ("pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini")
    if any((pasta / m).exists() for m in marcadores_py) or (pasta / "tests").is_dir():
        return [_python_do_projeto(pasta), "-m", "pytest", "-q", "-rfE", "--color=no"]
    pacote = pasta / "package.json"
    if pacote.exists():
        try:
            scripts = json.loads(pacote.read_text(encoding="utf-8")).get("scripts", {})
        except (json.JSONDecodeError, OSError) as exc:
            raise ErroExecucao(f"package.json ilegível: {exc}") from exc
        if "test" in scripts:
            return ["npm", "test", "--silent"]
    raise ErroExecucao(f"não achei testes em {pasta} (pytest ou script 'test' no package.json)")


def contar(saida: str) -> tuple[int, int]:
    """Lê passaram/falharam da última linha de resumo do pytest, jest ou vitest."""
    for linha in reversed(saida.splitlines()):
        achados = CONTAGEM.findall(linha)
        if achados:
            passaram = sum(int(n) for n, tipo in achados if tipo.lower() == "passed")
            falharam = sum(int(n) for n, tipo in achados if tipo.lower() != "passed")
            return passaram, falharam
    return 0, 0


def extrair_falhas(saida: str) -> list[str]:
    vistas: list[str] = []
    for linha in saida.splitlines():
        m = LINHA_FALHA.match(linha)
        if m and m.group(2).strip() not in vistas:
            vistas.append(m.group(2).strip()[:200])
        if len(vistas) >= MAX_FALHAS:
            break
    return vistas


def _explicar(cliente: ClienteOllama, modelo: str, saida: str) -> str:
    pedido = (
        f"SAÍDA DOS TESTES:\n{compactar(saida)}\n\n---\n"
        "Em no máximo 2 linhas, qual a causa provável das falhas? Cite arquivo e linha se houver."
    )
    try:
        return cliente.conversar(modelo, pedido).texto
    except ErroOllama as exc:
        logger.warning("sem explicação local das falhas: %s", exc)
        return ""


def rodar_testes(
    cfg: Config, cliente: ClienteOllama | None, pasta: str | Path, timeout_s: float = 900
) -> RelatorioTestes:
    raiz = validar_pasta(cfg, pasta)
    comando = detectar_comando(raiz)
    saida = executar(cfg, comando, raiz, timeout_s)
    passaram, falharam = contar(saida.texto)
    falhas = extrair_falhas(saida.texto) if not saida.ok else []
    causa = ""
    if not saida.ok and cliente is not None:
        causa = _explicar(cliente, cfg.modelos.codigo, saida.texto)
    rotulo = " ".join(Path(c).name if i == 0 else c for i, c in enumerate(comando))
    relatorio = RelatorioTestes(rotulo, saida.ok, passaram, falharam, saida.segundos, falhas, causa)
    registrar(cfg, "testes", len(saida.texto), len(relatorio.texto()))
    return relatorio
