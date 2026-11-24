from pathlib import Path

from agente import app


def test_modo_app_abre_janela_sem_abas_com_perfil_proprio(tmp_path):
    cmd = app.comando_modo_app("chrome", "http://127.0.0.1:8899", tmp_path)
    assert cmd[0] == "chrome"
    assert "--app=http://127.0.0.1:8899" in cmd
    assert f"--user-data-dir={tmp_path}" in cmd


def test_icone_do_app_existe():
    assert app.ICONE.exists()
    assert (Path(app.__file__).parent / "icones" / "app.ico").exists()


def test_so_abre_uma_copia_e_a_segunda_chama_a_primeira():
    import socket
    import threading

    chamou = threading.Event()
    with socket.socket() as s:  # porta livre qualquer
        s.bind(("127.0.0.1", 0))
        porta = s.getsockname()[1]
    primeira = app.ouvir_outras_copias(chamou.set, porta)
    try:
        assert primeira is not None
        assert app.ouvir_outras_copias(lambda: None, porta) is None  # segunda não pega
        assert app.avisar_aberto(porta)
        assert chamou.wait(5)
    finally:
        app.parar_de_ouvir(primeira)
    assert not app.avisar_aberto(porta)  # fechou: ninguém aberto
