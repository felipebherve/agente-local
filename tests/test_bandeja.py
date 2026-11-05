import pytest

from agente import atalho, lancador
from agente.bandeja import Estado, ler_estado
from agente.llm import ErroOllama


def test_estado_por_situacao():
    assert Estado(False).nome == "fora"
    assert Estado(True).nome == "dormindo"
    acordado = Estado(True, {"qwen3:8b": 6.2})
    assert acordado.nome == "acordado"
    assert "qwen3:8b (6.2 GB)" in acordado.texto("10m")
    assert "10m" in acordado.texto("10m")


def test_ler_estado_com_ollama_fora():
    class Fora:
        def modelos_carregados(self):
            raise ErroOllama("fora do ar")

    assert ler_estado(Fora()) == Estado(False)


def test_ler_estado_com_modelo_carregado():
    class Ligado:
        def modelos_carregados(self):
            return {"qwen3:8b": 6.0}

    assert ler_estado(Ligado()).nome == "acordado"


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("ctrl+alt+a", (atalho.MOD_CONTROL | atalho.MOD_ALT | atalho.MOD_NOREPEAT, ord("A"))),
        (
            "Ctrl + Shift + 9",
            (atalho.MOD_CONTROL | atalho.MOD_SHIFT | atalho.MOD_NOREPEAT, ord("9")),
        ),
    ],
)
def test_traduz_atalho(texto, esperado):
    assert atalho.traduzir(texto) == esperado


@pytest.mark.parametrize("texto", ["", "ctrl+alt+f12", "win+a", "ctrl+alt+"])
def test_atalho_invalido(texto):
    with pytest.raises(ValueError):
        atalho.traduzir(texto)


@pytest.mark.parametrize("estado", ["acordado", "dormindo", "fora"])
def test_icone_tem_a_cor_do_estado(estado):
    imagem = lancador.desenhar_icone(estado, 64)
    assert imagem.size == (64, 64)
    assert imagem.getpixel((8, 32))[:3] == lancador.CORES[estado]


def test_salva_ico(cfg):
    caminho = lancador.salvar_ico(cfg)
    assert caminho.exists() and caminho.suffix == ".ico"
