from agente import reiniciar, servidor_mcp


def test_reiniciar_sem_confirmacao_nao_faz_nada(monkeypatch):
    chamado = []
    monkeypatch.setattr(reiniciar, "reiniciar_claude", lambda *a: chamado.append(1) or "ok")
    resposta = servidor_mcp.reiniciar_claude()
    assert resposta.startswith("PRECISA DE CONFIRMAÇÃO")
    assert not chamado


def test_reiniciar_confirmado_agenda(monkeypatch):
    monkeypatch.setattr(reiniciar, "reiniciar_claude", lambda *a: "agendado")
    assert servidor_mcp.reiniciar_claude(confirmado=True) == "agendado"


def test_comando_fecha_espera_e_reabre():
    import base64

    cmd = reiniciar.comando(5)
    assert "'" not in cmd  # vai dentro de aspas simples no Invoke-CimMethod
    script = base64.b64decode(cmd.split()[-1]).decode("utf-16-le")
    assert "Start-Sleep -Seconds 5" in script
    assert "Stop-Process -Force" in script
    assert "shell:AppsFolder" in script
    assert reiniciar.APP_ID_PADRAO in script
