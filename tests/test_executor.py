import pytest

from agente.executor import ErroExecucao, executar, validar_pasta


def test_comando_nao_liberado(cfg, tmp_path):
    with pytest.raises(ErroExecucao, match="não liberado"):
        executar(cfg, ["powershell", "-c", "echo oi"], tmp_path)


def test_pasta_fora_das_permitidas(cfg, tmp_path):
    with pytest.raises(ErroExecucao, match="fora das pastas permitidas"):
        validar_pasta(cfg, tmp_path.parent)


def test_executa_e_junta_saida(cfg, tmp_path):
    s = executar(cfg, ["git", "--version"], tmp_path)
    assert s.ok
    assert "git version" in s.texto
