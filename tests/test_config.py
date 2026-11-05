import os
from pathlib import Path

import pytest

from agente.config import ErroConfig, carregar_config

YAML_OK = """
ollama_url: http://localhost:11434/
modelos: {cerebro: a, codigo: b, visao: c, embeddings: d}
pensar: false
"""


def test_config_do_repositorio_carrega():
    cfg = carregar_config()
    assert cfg.modelos.cerebro
    assert "git" in cfg.comandos_liberados


def test_padroes_e_normalizacao(tmp_path: Path):
    arq = tmp_path / "config.yaml"
    arq.write_text(YAML_OK, encoding="utf-8")
    cfg = carregar_config(arq)
    assert cfg.ollama_url == "http://localhost:11434"
    assert cfg.pensar is False
    assert cfg.keep_alive == "10m"
    assert cfg.pasta_logs == tmp_path / "logs"


def test_modelos_incompletos(tmp_path: Path):
    arq = tmp_path / "config.yaml"
    arq.write_text("modelos: {cerebro: a}", encoding="utf-8")
    with pytest.raises(ErroConfig, match="modelos"):
        carregar_config(arq)


def test_arquivo_ausente(tmp_path: Path):
    with pytest.raises(ErroConfig, match="não encontrada"):
        carregar_config(tmp_path / "nada.yaml")


def test_omniroute_padrao_e_personalizado(tmp_path: Path, monkeypatch):
    from agente import config as config_mod

    monkeypatch.setattr(config_mod, "achar_hd", lambda: None)
    arq = tmp_path / "config.yaml"
    arq.write_text(YAML_OK, encoding="utf-8")
    cfg = carregar_config(arq)
    assert cfg.omniroute.ligado is True
    assert cfg.omniroute.url == "http://127.0.0.1:20128/v1"
    assert cfg.omniroute.modelos == ("duckduckgo-web/gpt-4o-mini",)

    arq.write_text(
        YAML_OK + "\nomniroute: {ligado: false, url: 'http://x:1/v1/', timeout_s: 9, "
        "modelos: [a/b, c/d]}\n",
        encoding="utf-8",
    )
    cfg2 = carregar_config(arq)
    assert cfg2.omniroute.ligado is False
    assert cfg2.omniroute.url == "http://x:1/v1"
    assert cfg2.omniroute.timeout_s == 9
    assert cfg2.omniroute.modelos == ("a/b", "c/d")


@pytest.mark.skipif(os.name == "nt", reason="no Windows o HD é achado pela letra do disco")
def test_achar_hd_encontra_pela_pasta_filha(tmp_path: Path, monkeypatch):
    from agente import config as config_mod

    montagem = tmp_path / "usuario"
    montagem.mkdir()
    (montagem / "Meu HD").mkdir()
    monkeypatch.setattr(config_mod, "RAIZES_LINUX", (tmp_path,))
    assert config_mod.achar_hd("Meu HD") == montagem / "Meu HD"
    assert config_mod.achar_hd("") is None


def test_achar_hd_nenhum_lugar_montado(tmp_path: Path, monkeypatch):
    from agente import config as config_mod

    monkeypatch.setattr(config_mod, "RAIZES_LINUX", (tmp_path / "nao-existe",))
    assert config_mod.achar_hd() is None


def test_omniroute_vem_do_hd_quando_tem_arquivo_compartilhado(tmp_path: Path, monkeypatch):
    from agente import config as config_mod

    hd = tmp_path / "hd"
    pasta_comp = hd / config_mod.CAMINHO_COMPARTILHADO.parent
    pasta_comp.mkdir(parents=True)
    (pasta_comp / "compartilhado.yaml").write_text(
        "omniroute: {modelos: [a/b, c/d]}\n", encoding="utf-8"
    )
    monkeypatch.setattr(config_mod, "achar_hd", lambda _nome="": hd)

    arq = tmp_path / "config.yaml"
    arq.write_text(
        YAML_OK + "\nomniroute: {modelos: [local-only/x]}\nhd_compartilhado: Meu HD\n",
        encoding="utf-8",
    )
    cfg = carregar_config(arq)
    assert cfg.omniroute.modelos == ("a/b", "c/d")


def test_omniroute_local_quando_hd_nao_tem_arquivo(tmp_path: Path, monkeypatch):
    from agente import config as config_mod

    monkeypatch.setattr(config_mod, "achar_hd", lambda: None)
    arq = tmp_path / "config.yaml"
    arq.write_text(
        YAML_OK + "\nomniroute: {modelos: [local-only/x]}\n",
        encoding="utf-8",
    )
    cfg = carregar_config(arq)
    assert cfg.omniroute.modelos == ("local-only/x",)
