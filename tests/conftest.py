import subprocess
from pathlib import Path

import pytest

from agente.config import RAIZ, Config, carregar_config


def pytest_configure(config: pytest.Config) -> None:
    """Sem config.yaml (cópia nova do repositório, CI): usa um gerado do config.example.yaml."""
    import os
    import tempfile

    if (RAIZ / "config.yaml").exists() or os.environ.get("AGENTE_CONFIG"):
        return
    from agente import assistente

    pasta = Path(tempfile.mkdtemp(prefix="agente-teste-"))
    arq = pasta / "config.yaml"
    arq.write_text(
        assistente.montar_config(assistente.NIVEIS[0], [str(pasta)]), encoding="utf-8"
    )
    os.environ["AGENTE_CONFIG"] = str(arq)


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    """Config isolada: logs e pastas permitidas dentro do tmp_path.

    Isola também do HD externo de verdade (achar_hd -> None): sem isso, os testes
    ficam diferentes rodando numa máquina com o HD externo plugado.
    """
    from agente import config as config_mod

    monkeypatch.setattr(config_mod, "achar_hd", lambda: None)
    arq = tmp_path / "config.yaml"
    arq.write_text(
        "modelos: {cerebro: a, codigo: b, visao: c, embeddings: d}\n"
        f"pastas_permitidas: ['{tmp_path.as_posix()}']\n"
        "comandos_liberados: [git, python, gh, npm]\n",
        encoding="utf-8",
    )
    return carregar_config(arq)


def git(pasta: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=pasta, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Repositório git novo na branch main com um commit."""
    pasta = tmp_path / "repo"
    pasta.mkdir()
    git(pasta, "init", "-q", "-b", "main")
    git(pasta, "config", "user.email", "teste@exemplo.com")
    git(pasta, "config", "user.name", "Teste")
    (pasta / "a.txt").write_text("um\n", encoding="utf-8")
    git(pasta, "add", "-A")
    git(pasta, "commit", "-q", "-m", "inicio")
    return pasta
