import http.client
import json
import threading
from dataclasses import replace
from http.server import ThreadingHTTPServer

import pytest

from agente import celular, painel_web
from agente.config import Celular

ENDERECO = "meu-pc.tail1234.ts.net"


@pytest.fixture(autouse=True)
def _sem_trava():
    celular._zerar_trava()
    yield
    celular._zerar_trava()


def _servidor(cfg):
    handler = type("H", (painel_web._Handler,), {"cfg": cfg})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _pedir(porta, metodo, caminho, corpo=None, remoto=True, host=ENDERECO, cookie=None):
    con = http.client.HTTPConnection("127.0.0.1", porta, timeout=5)
    cab = {"Host": host if remoto else f"127.0.0.1:{porta}"}
    if remoto:  # o que o tailscale serve acrescenta
        cab["X-Forwarded-For"] = "100.64.0.2"
        cab["Tailscale-User-Login"] = "eu@exemplo.com"
    if cookie:
        cab["Cookie"] = f"{celular.COOKIE}={cookie}"
    dados = None
    if corpo is not None:
        cab["Content-Type"] = "application/json"
        dados = json.dumps(corpo)
    con.request(metodo, caminho, body=dados, headers=cab)
    r = con.getresponse()
    return r.status, r.getheader("Set-Cookie") or "", r.read()


@pytest.fixture
def cfg_cel(cfg, monkeypatch):
    cfg_cel = replace(cfg, celular=Celular(ligado=True, endereco=ENDERECO))
    monkeypatch.setattr(painel_web, "_celular_atual", lambda _cfg: cfg_cel.celular)
    return cfg_cel


def test_celular_ligado_no_config_vale_sem_reabrir_o_painel(cfg, monkeypatch, tmp_path):
    arq = tmp_path / "config-celular.yaml"
    arq.write_text(
        "modelos: {cerebro: a, codigo: b, visao: c, embeddings: d}\n"
        f"celular: {{ligado: true, endereco: {ENDERECO}}}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTE_CONFIG", str(arq))
    assert painel_web._celular_atual(cfg) == Celular(ligado=True, endereco=ENDERECO)


def test_codigo_tem_8_letras_faceis_e_fica_guardado(cfg):
    dados = celular.ler(cfg)
    assert len(dados["codigo"]) == 8 and set(dados["codigo"]) <= set(celular.ALFABETO)
    assert celular.ler(cfg) == dados
    celular.novo_codigo(cfg)
    assert celular.ler(cfg)["sessao"] != dados["sessao"]


def test_parear_aceita_codigo_com_traco_e_trava_apos_erros(cfg):
    codigo = celular.ler(cfg)["codigo"]
    assert celular.parear(cfg, f"{codigo[:4]}-{codigo[4:]}".lower()) == celular.ler(cfg)["sessao"]
    for _ in range(celular.TENTATIVAS):
        assert celular.parear(cfg, "ERRADO00") is None
    assert celular.parear(cfg, codigo) is None  # travado mesmo com o código certo


def test_celular_desligado_nao_entra(cfg):
    srv = _servidor(cfg)
    try:
        status, _, _ = _pedir(srv.server_address[1], "GET", "/")
        assert status == 403
    finally:
        srv.shutdown()


def test_celular_sem_pareamento_ve_so_a_tela_do_codigo(cfg_cel):
    srv = _servidor(cfg_cel)
    porta = srv.server_address[1]
    try:
        status, _, corpo = _pedir(porta, "GET", "/")
        assert status == 200 and b"/api/parear" in corpo
        assert _pedir(porta, "GET", "/api/estado")[0] == 403
        assert _pedir(porta, "GET", "/manifest.webmanifest")[0] == 200
        assert _pedir(porta, "GET", "/icone-512.png")[0] == 200
        assert _pedir(porta, "GET", "/", host="outro.ts.net")[0] == 403
    finally:
        srv.shutdown()


def test_pareamento_da_cookie_seguro_e_libera_o_painel(cfg_cel):
    srv = _servidor(cfg_cel)
    porta = srv.server_address[1]
    try:
        assert _pedir(porta, "POST", "/api/parear", {"codigo": "ERRADO00"})[0] == 403
        codigo = celular.ler(cfg_cel)["codigo"]
        status, cookie, _ = _pedir(porta, "POST", "/api/parear", {"codigo": codigo})
        assert status == 200
        assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=Strict" in cookie
        sessao = cookie.split(";")[0].split("=", 1)[1]
        status, _, corpo = _pedir(porta, "GET", "/", cookie=sessao)
        assert status == 200 and b"btnInterruptor" in corpo
        assert _pedir(porta, "GET", "/api/projetos", cookie="falso")[0] == 403
        # pelo celular não muda pastas liberadas nem liga o microfone do PC
        assert _pedir(porta, "POST", "/api/config/pastas", {}, cookie=sessao)[0] == 403
        assert _pedir(porta, "POST", "/api/voz", {}, cookie=sessao)[0] == 403
    finally:
        srv.shutdown()


def test_cabecalho_do_tailscale_nunca_passa_como_pedido_local(cfg):
    """Mesmo com Host 127.0.0.1, quem chega pelo tailscale serve é tratado como celular."""
    srv = _servidor(cfg)
    porta = srv.server_address[1]
    try:
        assert _pedir(porta, "GET", "/api/projetos", host=f"127.0.0.1:{porta}")[0] == 403
        assert _pedir(porta, "GET", "/api/projetos", remoto=False)[0] == 200
    finally:
        srv.shutdown()


def test_botoes_acordar_e_desligar(cfg, tmp_path, monkeypatch):
    from agente import interruptor
    from agente.braco import seguranca

    monkeypatch.setattr(seguranca, "SINAL_PARADA", tmp_path / "PARADO")
    monkeypatch.setattr(interruptor, "ClienteOllama", type("X", (), {
        "de_config": staticmethod(lambda c: type("O", (), {
            "modelos_carregados": lambda self: {}, "dormir": lambda self, m: None})())}))
    srv = _servidor(cfg)
    porta = srv.server_address[1]
    try:
        assert json.loads(_pedir(porta, "POST", "/api/desligar", {}, remoto=False)[2]) == {
            "desligado": True}
        resp = json.loads(_pedir(porta, "POST", "/api/perguntar", {"mensagem": "oi"},
                                 remoto=False)[2])
        assert "desligado" in resp["resposta"]
        assert json.loads(_pedir(porta, "POST", "/api/acordar", {}, remoto=False)[2]) == {
            "desligado": False}
    finally:
        srv.shutdown()


def test_codigo_aparece_no_pc_e_nunca_pelo_celular(cfg_cel):
    srv = _servidor(cfg_cel)
    porta = srv.server_address[1]
    try:
        status, _, corpo = _pedir(porta, "GET", "/api/celular", remoto=False)
        assert status == 200 and json.loads(corpo)["codigo"] == celular.ler(cfg_cel)["codigo"]
        sessao = celular.ler(cfg_cel)["sessao"]
        assert _pedir(porta, "GET", "/api/celular", cookie=sessao)[0] == 403
    finally:
        srv.shutdown()


def test_celular_manda_fotos_e_audio(cfg_cel, monkeypatch, tmp_path):
    from agente import envios, interruptor
    from agente.braco import seguranca

    monkeypatch.setattr(seguranca, "SINAL_PARADA", tmp_path / "PARADO")
    monkeypatch.setattr(envios, "transcrever_envio", lambda c, o, arqs, foco: f"{len(arqs)} ok")
    monkeypatch.setattr(envios, "ouvir_envio", lambda c, audio, tipo: "oi agente")
    srv = _servidor(cfg_cel)
    porta = srv.server_address[1]
    sessao = celular.ler(cfg_cel)["sessao"]
    try:
        interruptor.acordar(cfg_cel)
        corpo = {"arquivos": [{"nome": "a.jpg", "dados": "eA=="}]}
        status, _, resp = _pedir(porta, "POST", "/api/transcrever", corpo, cookie=sessao)
        assert status == 200 and json.loads(resp)["texto"] == "1 ok"
        status, _, resp = _pedir(porta, "POST", "/api/ouvir", {"audio": "eA=="}, cookie=sessao)
        assert json.loads(resp)["texto"] == "oi agente"
        # o celular não liga o Tailscale do PC
        assert _pedir(porta, "POST", "/api/tailscale/ligar", {}, cookie=sessao)[0] == 403
        interruptor.desligar(cfg_cel, type("O", (), {"modelos_carregados": lambda s: {}})())
        assert _pedir(porta, "POST", "/api/transcrever", corpo, cookie=sessao)[0] == 409
        estado = json.loads(_pedir(porta, "GET", "/api/estado", cookie=sessao)[2])
        assert estado["remoto"] is True and estado["tailscale"] is None
    finally:
        srv.shutdown()
