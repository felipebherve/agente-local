from agente import painel_web


def test_uso_comeca_vazio(cfg):
    assert painel_web.ler_uso(cfg) == {}


def test_registrar_uso_soma_por_provedor(cfg):
    painel_web.registrar_uso(cfg, "groq", 10)
    painel_web.registrar_uso(cfg, "groq", 5)
    painel_web.registrar_uso(cfg, "nvidia", 7)
    assert painel_web.ler_uso(cfg) == {"groq": 15, "nvidia": 7}


def test_registrar_uso_ignora_provedor_vazio_ou_zero(cfg):
    painel_web.registrar_uso(cfg, "", 10)
    painel_web.registrar_uso(cfg, "groq", 0)
    assert painel_web.ler_uso(cfg) == {}


def test_provedores_configurados_sem_repetir(cfg):
    import dataclasses

    cfg2 = dataclasses.replace(
        cfg,
        omniroute=dataclasses.replace(
            cfg.omniroute,
            modelos=("groq/a", "groq/b", "nvidia/c"),
        ),
    )
    assert painel_web.provedores_configurados(cfg2) == ["groq", "nvidia"]


def test_alternar_agente_cria_e_apaga_a_pausa(cfg):
    assert painel_web.agente_ligado(cfg, "Revisor")
    painel_web.alternar_agente(cfg, "Revisor", False)
    assert (cfg.pasta_dados / "revisor-pausado").exists()
    assert not painel_web.agente_ligado(cfg, "Revisor")
    painel_web.alternar_agente(cfg, "Revisor", True)
    assert painel_web.agente_ligado(cfg, "Revisor")


def test_agente_desconhecido(cfg):
    import pytest

    with pytest.raises(KeyError):
        painel_web.alternar_agente(cfg, "Ninguém", True)


def test_resumo_economia_tem_30_dias_e_soma_por_tipo(cfg):
    import json
    from datetime import datetime

    cfg.pasta_logs.mkdir(parents=True, exist_ok=True)
    linhas = [
        {"quando": "2026-11-05T10:00:00", "tarefa": "commit", "tokens_poupados": 100},
        {"quando": "2026-11-05T11:00:00", "tarefa": "commit", "tokens_poupados": 50},
        {"quando": "2026-11-01T11:00:00", "tarefa": "testes", "tokens_poupados": 7},
    ]
    (cfg.pasta_logs / "economia.jsonl").write_text(
        "\n".join(json.dumps(x) for x in linhas), encoding="utf-8"
    )
    r = painel_web.resumo_economia(cfg, hoje=datetime(2026, 11, 5))
    assert len(r["dias"]) == 30
    assert r["dias"][-1] == {"dia": "2026-11-05", "tokens": 150}
    assert r["por_tipo"][0] == {"tipo": "commit", "tokens": 150}
    assert r["total"] == 157


def test_projetos_sao_as_pastas_dentro_das_liberadas(tmp_path, cfg):
    from dataclasses import replace

    (tmp_path / "proj-a" / ".git").mkdir(parents=True)
    (tmp_path / ".escondida").mkdir()
    projetos = painel_web.listar_projetos(replace(cfg, pastas_permitidas=(tmp_path,)))
    nomes = [p["nome"] for p in projetos]
    assert "proj-a" in nomes and ".escondida" not in nomes
    assert next(p for p in projetos if p["nome"] == "proj-a")["git"] == "sim"


def _servidor(cfg):
    import threading
    from http.server import ThreadingHTTPServer

    handler = type("H", (painel_web._Handler,), {"cfg": cfg})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _post(porta, host=None, origem=None, tipo="application/json"):
    import http.client

    con = http.client.HTTPConnection("127.0.0.1", porta, timeout=5)
    cab = {"Content-Type": tipo, "Host": host or f"127.0.0.1:{porta}"}
    if origem:
        cab["Origin"] = origem
    con.request("POST", "/api/rota-que-nao-existe", body="{}", headers=cab)
    return con.getresponse().status


def test_painel_recusa_pedido_de_outro_site(cfg):
    srv = _servidor(cfg)
    porta = srv.server_address[1]
    try:
        assert _post(porta) == 404  # do próprio painel: passa (e a rota não existe)
        assert _post(porta, origem=f"http://localhost:{porta}") == 404
        assert _post(porta, origem="https://site-mal.com") == 403
        assert _post(porta, host="site-mal.com") == 403  # DNS rebinding
        assert _post(porta, tipo="text/plain") == 403  # formulário de outro site
    finally:
        srv.shutdown()
        srv.server_close()
