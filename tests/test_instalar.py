import json

import pytest

from agente.instalar import FIM, INICIO, NOME_SERVIDOR, registrar_instrucoes, registrar_servidor


def test_registra_sem_apagar_o_resto(tmp_path):
    arq = tmp_path / "config.json"
    arq.write_text(json.dumps({"tema": "escuro", "mcpServers": {"outro": {"command": "x"}}}))
    assert registrar_servidor(arq, "C:/agente-mcp.exe") is True
    dados = json.loads(arq.read_text(encoding="utf-8"))
    assert dados["tema"] == "escuro"
    assert "outro" in dados["mcpServers"]
    assert dados["mcpServers"][NOME_SERVIDOR]["command"] == "C:/agente-mcp.exe"
    assert list(tmp_path.glob("config.json.bak-*"))


def test_idempotente(tmp_path):
    arq = tmp_path / "config.json"
    registrar_servidor(arq, "a")
    assert registrar_servidor(arq, "a") is False


def test_json_quebrado_nao_e_tocado(tmp_path):
    arq = tmp_path / "config.json"
    arq.write_text("{quebrado")
    with pytest.raises(ValueError):
        registrar_servidor(arq, "a")
    assert arq.read_text() == "{quebrado"


def test_instrucoes_atualizam_no_lugar(tmp_path):
    arq = tmp_path / "CLAUDE.md"
    arq.write_text(
        f"# Minhas regras\n\n{INICIO}\nvelho\n{FIM}\n\nfim do arquivo\n", encoding="utf-8"
    )
    assert registrar_instrucoes(arq) is True
    texto = arq.read_text(encoding="utf-8")
    assert "velho" not in texto
    assert texto.count(INICIO) == 1
    assert texto.startswith("# Minhas regras") and texto.rstrip().endswith("fim do arquivo")
    assert registrar_instrucoes(arq) is False
