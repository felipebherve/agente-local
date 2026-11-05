import sys

import pytest
from conftest import git

from agente import git_ops, revisor
from agente.executor import ErroExecucao

CHAVE = "sk-" + "a1B2c3D4e5F6g7H8i9J0kLmN"
Q = '"'  # aspas montadas: o próprio Revisor não acusa este arquivo
PARADA = "breakpoint" + "()"

DIFF = f"""diff --git a/app.py b/app.py
+++ b/app.py
@@ -10,2 +10,6 @@ def x():
 contexto
+API_KEY = {Q}{CHAVE}{Q}
-removida
+    {PARADA}
+# TODO arrumar depois
+<<<<<<< HEAD
"""


def test_achados_no_diff_com_linha():
    achados = {a.tipo: a for a in revisor.achados_no_diff(DIFF)}
    assert achados["possível segredo"].onde == "app.py:11"
    assert CHAVE not in achados["possível segredo"].trecho  # não repete a chave inteira
    assert achados["depuração esquecida"].onde == "app.py:12"
    assert achados["pendência"].onde == "app.py:13"
    assert achados["marca de conflito"].onde == "app.py:14"


def test_texto_limpo_nao_acusa():
    assert revisor.achados_no_diff("+++ b/a.py\n@@ -0,0 +1 @@\n+senha = input()\n") == []


def test_texto_da_revisao():
    r = revisor.Revisao(
        "loja",
        [
            revisor.Checagem("lint", False, "2 problemas", [f"a.py:{i}: E1" for i in range(12)]),
            revisor.Checagem("testes", True, "3 passaram"),
            revisor.Checagem("pendências", True, "1 TODO", ["x"], aviso=True),
        ],
        4.0,
    )
    assert r.problemas == 1
    texto = r.texto()
    assert texto.startswith("Revisor (loja): 1 com problema em 3 checagens")
    assert "✗ lint" in texto and "✓ testes" in texto and "e mais 2" in texto


@pytest.fixture
def cfg_py(cfg, monkeypatch):
    """Usa o python do ambiente de teste (que tem ruff e pytest) no projeto de exemplo."""
    from agente import testes

    monkeypatch.setattr(testes, "_python_do_projeto", lambda _pasta: sys.executable)
    return cfg


def test_revisar_projeto_python(cfg_py, repo):
    (repo / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_a.py").write_text("def test_a():\n    assert 1\n", encoding="utf-8")
    (repo / "ruim.py").write_text("import os\n", encoding="utf-8")
    (repo / "config.py").write_text(f"token = {Q}{CHAVE}{Q}\n", encoding="utf-8")
    r = revisor.revisar(cfg_py, None, repo)
    por_nome = {c.nome: c for c in r.checagens}
    assert not por_nome["lint (ruff)"].ok
    assert any("ruim.py:1" in i for i in por_nome["lint (ruff)"].itens)
    assert por_nome["testes"].ok
    assert not por_nome["alterações"].ok
    assert any("config.py:1" in i for i in por_nome["alterações"].itens)
    assert "repo: 2 com problema" in (cfg_py.pasta_dados / "revisor-ultima.txt").read_text(
        encoding="utf-8"
    )


def test_projeto_sem_nada_para_rodar(cfg, tmp_path):
    vazio = tmp_path / "vazio"
    vazio.mkdir()
    assert "não achei" in revisor.revisar(cfg, None, vazio, testes=False).texto()


def test_commit_travado_por_segredo(cfg, repo):
    (repo / "b.py").write_text(f"senha = {Q}{CHAVE}{Q}\n", encoding="utf-8")
    with pytest.raises(ErroExecucao, match="Revisor travou"):
        git_ops.commit(cfg, None, repo, "com senha")
    assert "com senha" not in git(repo, "log", "--oneline")
    (cfg.pasta_dados / "revisor-pausado").parent.mkdir(parents=True, exist_ok=True)
    (cfg.pasta_dados / "revisor-pausado").write_text("x", encoding="utf-8")
    assert "com senha" in git_ops.commit(cfg, None, repo, "com senha")
