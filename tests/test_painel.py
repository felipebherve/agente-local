from agente.bandeja import Bandeja, Estado
from agente.braco import seguranca
from agente.painel import (
    PADRAO,
    Agente,
    arquivo_icone,
    futuros,
    imagem_icone,
    ler_tema,
    proximo_tema,
)


def test_todos_os_agentes_ja_existem():
    assert futuros() == []


def test_bandeja_lista_os_agentes_sem_a_voz(cfg):
    bandeja = Bandeja(cfg, mostrar_painel=False)
    agentes = {a.nome: a for a in bandeja.interface.agentes}
    assert list(agentes)[:6] == [
        "Cérebro",
        "Braço",
        "Memória",
        "Porteiro",
        "Revisor",
        "Maestro",
    ]
    assert agentes["Revisor"].ligado() and agentes["Revisor"].uso() == "Nenhuma revisão ainda."
    assert agentes["Memória"].ligado() and agentes["Memória"].alternar is not None

    bandeja.estado = Estado(True, {"qwen3:8b": 5.2})
    assert agentes["Cérebro"].ligado()
    assert agentes["Cérebro"].uso() == "Placa de vídeo: 5.2 GB"
    bandeja.estado = Estado(True)
    assert not agentes["Cérebro"].ligado()
    assert agentes["Cérebro"].uso() == "Sem uso (dormindo)."


def test_botao_do_braco_usa_a_parada_de_emergencia(cfg):
    agentes = Bandeja(cfg, mostrar_painel=False).interface.agentes
    braco = next(a for a in agentes if a.nome == "Braço")
    try:
        braco.alternar(False)
        assert not braco.ligado()
        assert seguranca.SINAL_PARADA.exists()
    finally:
        braco.alternar(True)
    assert braco.ligado()


def test_tema_salvo_e_unico(tmp_path):
    arquivo = tmp_path / "tema.txt"
    assert ler_tema(arquivo) is PADRAO  # sem arquivo
    arquivo.write_text("lovecraft", encoding="utf-8")  # tema antigo, que saiu
    assert ler_tema(arquivo) is PADRAO
    assert proximo_tema(PADRAO) is PADRAO


def test_todo_agente_tem_icone():
    for icone in ["cerebro", "braco", "voz", "memoria", "porteiro", "revisor", "maestro"]:
        for ligado in (True, False):
            assert arquivo_icone(PADRAO, icone, ligado).exists(), icone


def test_nome_e_descricao_do_tema():
    braco = Agente("Braço", "padrão", "#fff", "braco")
    assert PADRAO.nome_de(braco) == "Braço"
    assert PADRAO.descricao_de(braco) == "padrão"


def test_imagem_do_icone_tem_o_tamanho_pedido():
    agente = Agente("Maestro", "Escolhe o agente.", "#3d8bff", "maestro")
    assert imagem_icone(agente, True, 56).size == (56, 56)
    assert imagem_icone(agente, False, 104).size == (104, 104)


def test_somas_do_grafico_de_economia():
    from agente.painel import nome_mes, por_dia, por_hora, por_mes

    pontos = [
        ("2026-09-30T23:10:00", 50),
        ("2026-10-26T09:05:00", 100),
        ("2026-10-26T09:40:00", 20),
        ("2026-10-26T18:00:00", 7),
        ("2026-10-27T08:00:00", 3),
    ]
    assert por_mes(pontos) == {"2026-09": 50, "2026-10": 130}
    assert por_dia(pontos, "2026-10") == {"2026-10-26": 127, "2026-10-27": 3}
    horas = por_hora(pontos, "2026-10-26")
    assert len(horas) == 24 and horas[9] == 120 and horas[18] == 7 and sum(horas) == 127
    assert nome_mes("2026-10") == "outubro de 2026"
    assert nome_mes("2026-03", curto=True) == "mar/26"


def test_icone_ia_verde_e_cinza():
    from agente.painel import imagem_ia

    ligado, desligado = imagem_ia(True, 32), imagem_ia(False, 32)
    assert ligado.size == (32, 32)
    meio_l, meio_d = ligado.getpixel((6, 16)), desligado.getpixel((6, 16))
    assert meio_l[1] > meio_l[0]  # verde
    assert abs(meio_d[0] - meio_d[1]) < 20  # cinza
