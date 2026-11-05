import io
import json
import urllib.error

import pytest

from agente import llm
from agente.llm import ClienteOllama, ErroOllama


class _RespostaFalsa(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _fingir(monkeypatch, corpo: dict, capturado: list):
    def urlopen(req, timeout):
        capturado.append(json.loads(req.data) if req.data else None)
        return _RespostaFalsa(json.dumps(corpo).encode())

    monkeypatch.setattr(llm.urllib.request, "urlopen", urlopen)


def test_conversar_monta_corpo_e_le_metricas(monkeypatch):
    enviado: list = []
    _fingir(
        monkeypatch,
        {
            "message": {"content": " oi "},
            "eval_count": 50,
            "eval_duration": 1e9,
            "prompt_eval_count": 10,
        },
        enviado,
    )
    r = ClienteOllama("http://x", 5, pensar=False).conversar("m", "pergunta", sistema="sis")
    assert r.texto == "oi"
    assert r.tokens_por_s == pytest.approx(50)
    assert enviado[0]["think"] is False
    assert enviado[0]["options"]["num_predict"] == 1024
    assert enviado[0]["messages"][0]["role"] == "system"


def test_sem_pensar_nao_envia_think(monkeypatch):
    enviado: list = []
    _fingir(monkeypatch, {"message": {"content": "x"}}, enviado)
    ClienteOllama("http://x", 5).conversar("m", "p")
    assert "think" not in enviado[0]


def test_ollama_fora_do_ar(monkeypatch):
    def urlopen(req, timeout):
        raise urllib.error.URLError("recusado")

    monkeypatch.setattr(llm.urllib.request, "urlopen", urlopen)
    with pytest.raises(ErroOllama, match="fora do ar"):
        ClienteOllama("http://x", 5).versao()
