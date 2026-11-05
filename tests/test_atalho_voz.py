import os

from agente.voz import atalho_voz


def test_sem_gravacao_quando_nao_ha_arquivo(tmp_path, monkeypatch):
    monkeypatch.setattr(atalho_voz, "ARQUIVO_PID", tmp_path / "voz.pid")
    assert atalho_voz.gravando_agora() is None


def test_reconhece_gravacao_viva_e_limpa_a_morta(tmp_path, monkeypatch):
    arquivo = tmp_path / "voz.pid"
    monkeypatch.setattr(atalho_voz, "ARQUIVO_PID", arquivo)
    arquivo.write_text(str(os.getpid()))
    assert atalho_voz.gravando_agora() == os.getpid()
    arquivo.write_text("999999999")  # processo que não existe
    assert atalho_voz.gravando_agora() is None
    assert not arquivo.exists()


def test_pedir_para_parar_cria_o_arquivo(tmp_path, monkeypatch):
    monkeypatch.setattr(atalho_voz, "ARQUIVO_PARAR", tmp_path / "parar")
    assert not atalho_voz._deve_parar()
    atalho_voz.pedir_para_parar(123)
    assert atalho_voz._deve_parar()


def test_segundo_aperto_so_manda_parar(tmp_path, monkeypatch):
    arquivo = tmp_path / "voz.pid"
    monkeypatch.setattr(atalho_voz, "ARQUIVO_PID", arquivo)
    arquivo.write_text(str(os.getpid()))
    chamados = []
    monkeypatch.setattr(atalho_voz, "pedir_para_parar", chamados.append)
    monkeypatch.setattr(atalho_voz, "gravar", lambda cfg: (_ for _ in ()).throw(AssertionError))
    atalho_voz.main()
    assert chamados == [os.getpid()]
