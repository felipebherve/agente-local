import io
import json
import urllib.error

from agente import nuvem


class _RespostaFalsa(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _fingir_resposta(monkeypatch, corpo: dict, capturado: list):
    def urlopen(req, timeout):
        capturado.append(json.loads(req.data))
        return _RespostaFalsa(json.dumps(corpo).encode())

    monkeypatch.setattr(nuvem.urllib.request, "urlopen", urlopen)


def _fingir_erro(monkeypatch, excecao):
    def urlopen(req, timeout):
        raise excecao

    monkeypatch.setattr(nuvem.urllib.request, "urlopen", urlopen)


def test_pergunta_monta_corpo_com_modelo_auto(cfg, monkeypatch):
    enviado: list = []
    _fingir_resposta(
        monkeypatch,
        {"model": "gpt-4o-mini", "choices": [{"message": {"content": " Brasília. "}}]},
        enviado,
    )
    r = nuvem.perguntar(cfg, "qual a capital do Brasil?", "sistema x")
    assert r == nuvem.Resposta("gpt-4o-mini", "Brasília.", provedor="duckduckgo-web")
    assert enviado[0]["model"] == cfg.omniroute.modelos[0]
    assert enviado[0]["messages"] == [
        {"role": "system", "content": "sistema x"},
        {"role": "user", "content": "qual a capital do Brasil?"},
    ]


def test_omniroute_fora_do_ar_devolve_none(cfg, monkeypatch):
    _fingir_erro(monkeypatch, urllib.error.URLError("conexão recusada"))
    assert nuvem.perguntar(cfg, "oi", "sistema") is None


def test_resposta_vazia_devolve_none(cfg, monkeypatch):
    _fingir_resposta(monkeypatch, {"model": "x", "choices": [{"message": {"content": ""}}]}, [])
    assert nuvem.perguntar(cfg, "oi", "sistema") is None


def test_resposta_mal_formada_devolve_none(cfg, monkeypatch):
    _fingir_resposta(monkeypatch, {"choices": []}, [])
    assert nuvem.perguntar(cfg, "oi", "sistema") is None


def test_desligado_no_config_nao_chama_rede(cfg, monkeypatch):
    import dataclasses

    cfg_desligado = dataclasses.replace(
        cfg, omniroute=dataclasses.replace(cfg.omniroute, ligado=False)
    )

    def urlopen(*_a, **_k):
        raise AssertionError("não devia chamar a rede com omniroute desligado")

    monkeypatch.setattr(nuvem.urllib.request, "urlopen", urlopen)
    assert nuvem.perguntar(cfg_desligado, "oi", "sistema") is None


def test_pula_para_o_proximo_modelo_da_fila(cfg, monkeypatch):
    import dataclasses

    cfg_fila = dataclasses.replace(
        cfg,
        omniroute=dataclasses.replace(
            cfg.omniroute, modelos=("provedor-a/x", "provedor-b/y")
        ),
    )
    tentados: list = []

    def urlopen(req, timeout):
        corpo = json.loads(req.data)
        tentados.append(corpo["model"])
        if corpo["model"] == "provedor-a/x":
            raise urllib.error.URLError("fora do ar")
        return _RespostaFalsa(
            json.dumps(
                {"model": "y", "choices": [{"message": {"content": "respondeu o b"}}]}
            ).encode()
        )

    monkeypatch.setattr(nuvem.urllib.request, "urlopen", urlopen)
    r = nuvem.perguntar(cfg_fila, "oi", "sistema")
    assert r == nuvem.Resposta("y", "respondeu o b", provedor="provedor-b")
    assert tentados == ["provedor-a/x", "provedor-b/y"]


def test_captura_provedor_e_tokens_da_resposta(cfg, monkeypatch):
    _fingir_resposta(
        monkeypatch,
        {
            "model": "gpt-4o-mini",
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"total_tokens": 42},
        },
        [],
    )
    r = nuvem.perguntar(cfg, "oi", "sistema")
    assert r.provedor == "duckduckgo-web"
    assert r.tokens_total == 42
