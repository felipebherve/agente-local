import pytest
import yaml

from agente import configuracoes as conf

CONFIG = """# topo
ollama_url: http://localhost:11434

# OmniRoute
omniroute:
  ligado: false   # comentário que some
  url: http://127.0.0.1:20128/v1
  modelos: []

# pastas
pastas_permitidas:
  - /tmp/x
voz:
  atalho: ""
"""


def test_trocar_bloco_mexe_so_no_bloco(tmp_path):
    arq = tmp_path / "config.yaml"
    arq.write_text(CONFIG, encoding="utf-8")
    destino = conf.salvar_omniroute(arq, True, ["groq/a", " ", "gemini/b "])
    assert destino == arq
    texto = arq.read_text(encoding="utf-8")
    dados = yaml.safe_load(texto)
    assert dados["omniroute"]["ligado"] is True
    assert dados["omniroute"]["modelos"] == ["groq/a", "gemini/b"]
    assert dados["pastas_permitidas"] == ["/tmp/x"]
    assert "# topo" in texto and "# pastas" in texto
    assert (tmp_path / "config.yaml.bak").exists()


def test_trocar_bloco_acrescenta_quando_nao_existe(tmp_path):
    arq = tmp_path / "config.yaml"
    arq.write_text("ollama_url: x\n", encoding="utf-8")
    conf.trocar_bloco(arq, "omniroute", {"ligado": True, "modelos": ["a/b"]})
    assert yaml.safe_load(arq.read_text(encoding="utf-8"))["omniroute"]["modelos"] == ["a/b"]


@pytest.mark.parametrize(
    ("entrada", "normal", "gnome", "windows"),
    [
        ("Ctrl+Alt+F", "ctrl+alt+f", "<Control><Alt>f", "Ctrl+Alt+F"),
        ("ctrl + shift + f9", "ctrl+shift+f9", "<Control><Shift>f9", "Ctrl+Shift+F9"),
        ("alt+ctrl+1", "ctrl+alt+1", "<Control><Alt>1", "Ctrl+Alt+1"),
    ],
)
def test_atalho_vira_formato_de_cada_sistema(entrada, normal, gnome, windows):
    assert conf.normalizar_atalho(entrada) == normal
    assert conf.para_gnome(normal) == gnome
    assert conf.para_windows(normal) == windows


@pytest.mark.parametrize("ruim", ["f", "ctrl+alt", "ctrl+alt+é", "ctrl+a+b"])
def test_atalho_invalido_e_recusado(ruim):
    with pytest.raises(ValueError):
        conf.normalizar_atalho(ruim)


def test_entrar_em_servico_desconhecido():
    with pytest.raises(KeyError):
        conf.entrar("netflix")


def test_salvar_pastas_valida_e_atualiza_a_memoria(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    arq = tmp_path / "config.yaml"
    arq.write_text(
        CONFIG + "memoria:\n  projetos:\n    - /velho\n  intervalo_min: 10\n", encoding="utf-8"
    )
    lista = conf.salvar_pastas(arq, [str(a), f"  {b}  ", str(a), ""])
    assert lista == [str(a), str(b)]
    dados = yaml.safe_load(arq.read_text(encoding="utf-8"))
    assert dados["pastas_permitidas"] == [str(a), str(b)]
    assert dados["memoria"] == {"projetos": [str(a), str(b)], "intervalo_min": 10}
    assert dados["omniroute"]["ligado"] is False  # resto intacto


@pytest.mark.parametrize("ruim", ["relativa/pasta", "/nao/existe/mesmo", "/"])
def test_pasta_invalida_e_recusada(ruim):
    with pytest.raises(ValueError):
        conf.validar_pastas([ruim])
