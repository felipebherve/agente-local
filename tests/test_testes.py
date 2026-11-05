import json
import sys

from agente import testes
from agente.testes import contar, detectar_comando, extrair_falhas, rodar_testes

PYTEST = """\
..F.
FAILED tests/test_login.py::test_login - AssertionError: 401 != 200
ERROR tests/test_db.py::test_conexao - ConnectionError
1 failed, 3 passed, 1 error in 0.52s
"""
JEST = """\
 FAIL  src/soma.test.js
  ● soma › soma dois números
Tests:       1 failed, 5 passed, 6 total
"""
VITEST = " Tests  2 failed | 7 passed (9)\n"


def test_contagens():
    assert contar(PYTEST) == (3, 2)
    assert contar(JEST) == (5, 1)
    assert contar(VITEST) == (7, 2)
    assert contar("nada aqui") == (0, 0)


def test_falhas_extraidas():
    falhas = extrair_falhas(PYTEST)
    assert falhas[0].startswith("tests/test_login.py::test_login")
    assert len(falhas) == 2
    assert "soma › soma dois números" in extrair_falhas(JEST)


def test_detecta_pytest_e_npm(tmp_path):
    (tmp_path / "pyproject.toml").write_text("")
    assert detectar_comando(tmp_path)[1:3] == ["-m", "pytest"]
    js = tmp_path / "js"
    js.mkdir()
    (js / "package.json").write_text(json.dumps({"scripts": {"test": "jest"}}))
    assert detectar_comando(js)[:2] == ["npm", "test"]


def test_roda_pytest_de_verdade(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(testes, "_python_do_projeto", lambda _pasta: sys.executable)
    projeto = tmp_path / "proj"
    (projeto / "tests").mkdir(parents=True)
    (projeto / "tests" / "test_x.py").write_text(
        "def test_ok():\n    assert 1\n\ndef test_ruim():\n    assert 1 == 2\n"
    )
    cfg_py = cfg.__class__(**{**cfg.__dict__, "comandos_liberados": ("python",)})
    r = rodar_testes(cfg_py, None, projeto)
    assert not r.ok
    assert (r.passaram, r.falharam) == (1, 1)
    assert any("test_ruim" in f for f in r.falhas)
    assert "1 passaram, 1 falharam" in r.texto()
