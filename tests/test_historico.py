from agente import economia, historico


def test_registra_e_le_os_pedidos_mais_novos_primeiro(cfg):
    historico.registrar(cfg, "revisa o agente", "Revisor", "local", "0 problemas " * 40, 3.21)
    historico.registrar(cfg, "escreva um poema", "Porteiro", "claude", "mandei ao Claude", 0.4)
    registros = historico.ler(cfg)
    assert [r.agente for r in registros] == ["Porteiro", "Revisor"]
    revisor = registros[1]
    assert revisor.tokens_poupados == revisor.tokens_locais > 0
    assert revisor.resumo.endswith("…") and len(revisor.resumo) <= historico.RESUMO_MAX
    assert revisor.resposta_completa == "0 problemas " * 40  # sem truncar, pro painel mostrar
    assert revisor.segundos == 3.2
    assert registros[0].tokens_poupados == 0  # foi ao Claude: nada poupado


def test_historico_vazio_e_linhas_quebradas(cfg):
    assert historico.ler(cfg) == []
    historico.registrar(cfg, "oi", "Porteiro", "local", "olá", 0.1)
    with (cfg.pasta_dados / "historico.jsonl").open("a", encoding="utf-8") as f:
        f.write("lixo\n")
    assert len(historico.ler(cfg)) == 1


def test_pontos_da_economia_para_o_grafico(cfg):
    assert economia.pontos(cfg) == []
    economia.registrar(cfg, "maestro", 4000, 0)
    ((quando, tokens),) = economia.pontos(cfg)
    assert tokens == 1000 and quando[:4].isdigit()
