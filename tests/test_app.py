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
