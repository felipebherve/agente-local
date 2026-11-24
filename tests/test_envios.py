import base64
import json
import subprocess
from pathlib import Path

import pytest

from agente import envios
from agente.executor import ErroExecucao

PNG_1PX = base64.b64encode(
    bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
    )
).decode()


def test_fotos_do_app_sao_lidas_e_apagadas(cfg, monkeypatch):
    from agente import documentos

    vistos: list[Path] = []

    def falso(_cfg, _cliente, arquivos, foco):
        vistos.extend(arquivos)
        assert all(a.exists() for a in arquivos)
        return f"{len(arquivos)} lidas, foco={foco}"

    monkeypatch.setattr(documentos, "transcrever_arquivos", falso)
    texto = envios.transcrever_envio(
        cfg, None,
        [{"nome": "rg frente.png", "dados": "data:image/png;base64," + PNG_1PX},
         {"nome": "../../etc/x.jpg", "dados": PNG_1PX}],
        "nome e CPF",
    )
    assert texto == "2 lidas, foco=nome e CPF"
    assert [a.name for a in vistos] == ["01-rg_frente.png", "02-x.jpg"]  # sem sair da pasta
    assert not any(a.exists() for a in vistos)  # nada fica guardado


def test_envio_recusa_tipo_estranho_e_base64_quebrado(cfg):
    with pytest.raises(ErroExecucao, match="não suportado"):
        envios.transcrever_envio(cfg, None, [{"nome": "virus.exe", "dados": PNG_1PX}])
    with pytest.raises(ErroExecucao, match="corrompido"):
        envios.transcrever_envio(cfg, None, [{"nome": "a.png", "dados": "@@@"}])
    with pytest.raises(ErroExecucao, match="nenhuma"):
        envios.transcrever_envio(cfg, None, [])


def test_tailscale_estado_e_link_de_login(monkeypatch):
    respostas = {
        "status": subprocess.CompletedProcess(
            [], 0, json.dumps({"BackendState": "NeedsLogin"}), ""),
        "serve": subprocess.CompletedProcess([], 0, "{}", ""),
        "up": subprocess.CompletedProcess(
            [], 1, "", "To authenticate, visit:\n\n\thttps://login.tailscale.com/a/abc123\n"),
    }
    monkeypatch.setattr(envios, "_tailscale", lambda: "/usr/bin/tailscale")
    monkeypatch.setattr(envios, "_rodar", lambda args, timeout=10: respostas[args[0]])
    estado = envios.estado_tailscale(8899, usar_cache=False)
    assert estado == {"instalado": True, "conectado": False, "servindo": False}
    r = envios.ligar_tailscale(8899)
    assert r["link"] == "https://login.tailscale.com/a/abc123" and not r["ok"]


def test_tailscale_ausente(monkeypatch):
    monkeypatch.setattr(envios, "_tailscale", lambda: None)
    assert envios.estado_tailscale(8899, usar_cache=False)["instalado"] is False
    assert "tailscale.com/download" in envios.ligar_tailscale(8899)["aviso"]
