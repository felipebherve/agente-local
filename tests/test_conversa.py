import pytest

from agente.voz.conversa import Pedido, interpretar, normalizar


def test_normalizar_tira_acento_e_pontuacao():
    assert normalizar("  Acorde, Cérebro! ") == "acorde cerebro"


@pytest.mark.parametrize(
    ("frase", "acao"),
    [
        ("Acorda", "acordar"),
        ("acorde agente", "acordar"),
        ("Vai dormir.", "dormir"),
        ("libera a placa de vídeo", "dormir"),
        ("Status", "status"),
        ("como você está?", "status"),
        ("quanto de economia?", "economia"),
        ("Para tudo!", "parar"),
        ("libera o braço", "liberar"),
        ("", "nada"),
    ],
)
def test_comandos_por_regra(frase, acao):
    assert interpretar(frase).acao == acao


def test_abrir_app_pega_o_nome():
    assert interpretar("Abra o bloco de notas") == Pedido("abrir", "bloco de notas")
    assert interpretar("abrir Spotify") == Pedido("abrir", "spotify")


def test_abrir_site_pega_o_nome():
    assert interpretar("abre o youtube") == Pedido("abrir", "youtube")
    assert interpretar("abra meu projeto falavado que esta no git") == Pedido(
        "abrir", "meu projeto falavado que esta no git"
    )


@pytest.mark.parametrize(
    ("frase", "musica"),
    [
        ("Toque Legião Urbana Tempo Perdido no YouTube", "legiao urbana tempo perdido"),
        ("toca aquela música do Raul Seixas", "aquela musica do raul seixas"),
        ("coloca Tempo Perdido pra tocar", "tempo perdido"),
    ],
)
def test_tocar_pega_a_musica(frase, musica):
    assert interpretar(frase) == Pedido("tocar", musica)


def test_buscar_arquivo_pega_o_nome():
    # normalizar() tira a pontuação: "relatorio.pdf" chega como "relatorio pdf" (sem o ponto);
    # quem compara nome de arquivo (memoria.buscar_arquivos) tira os espaços de novo.
    assert interpretar("busca o arquivo relatorio.pdf") == Pedido("buscar", "relatorio pdf")
    assert interpretar("procura arquivos de currículo") == Pedido("buscar", "de curriculo")


def test_frase_longa_vira_pergunta_mesmo_com_palavra_de_comando():
    frase = "por que eu durmo mal quando tomo café depois das seis da tarde?"
    assert interpretar(frase) == Pedido("perguntar", frase)


def test_pergunta_comum():
    assert interpretar("Qual a capital da França?") == Pedido(
        "perguntar", "Qual a capital da França?"
    )
