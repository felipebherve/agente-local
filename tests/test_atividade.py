import time

from agente import atividade


def test_agente_aparece_enquanto_trabalha_e_some_depois(tmp_path):
    with atividade.trabalhando(tmp_path, "Braço"):
        assert atividade.ativos(tmp_path) == {"Braço"}
    assert atividade.ativos(tmp_path) == {"Braço"}  # fica um pouco depois do fim
    depois = time.time() + atividade.MOSTRAR_DEPOIS_S + 1
    assert atividade.ativos(tmp_path, depois) == set()


def test_dois_agentes_ao_mesmo_tempo(tmp_path):
    with atividade.trabalhando(tmp_path, "Cérebro"), atividade.trabalhando(tmp_path, "Voz"):
        assert atividade.ativos(tmp_path) == {"Cérebro", "Voz"}


def test_sem_pasta_ninguem_ativo(tmp_path):
    assert atividade.ativos(tmp_path / "nao-existe") == set()
