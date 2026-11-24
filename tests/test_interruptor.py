from agente import interruptor


class _Ollama:
    def __init__(self, carregados=("qwen3:8b",), quebrado=False):
        self.carregados = list(carregados)
        self.dormiu = []
        self.quebrado = quebrado

    def modelos_carregados(self):
        if self.quebrado:
            raise OSError("Ollama fora do ar")
        return {m: 5.0 for m in self.carregados}

    def dormir(self, modelo):
        self.dormiu.append(modelo)


def test_desligar_pausa_tudo_e_libera_a_placa(cfg, tmp_path, monkeypatch):
    from agente.braco import seguranca

    monkeypatch.setattr(seguranca, "SINAL_PARADA", tmp_path / "PARADO")
    ollama = _Ollama()
    interruptor.desligar(cfg, ollama)
    assert interruptor.desligado(cfg)
    assert all((cfg.pasta_dados / p).exists() for p in interruptor.PAUSAS)
    assert seguranca.SINAL_PARADA.exists()
    assert ollama.dormiu == ["qwen3:8b"]

    interruptor.acordar(cfg)
    assert not interruptor.desligado(cfg)
    assert not any((cfg.pasta_dados / p).exists() for p in interruptor.PAUSAS)
    assert not seguranca.SINAL_PARADA.exists()


def test_desligar_funciona_com_ollama_fechado(cfg, tmp_path, monkeypatch):
    from agente.braco import seguranca

    monkeypatch.setattr(seguranca, "SINAL_PARADA", tmp_path / "PARADO")
    interruptor.desligar(cfg, _Ollama(quebrado=True))
    assert interruptor.desligado(cfg)


def test_ferramentas_do_claude_respeitam_o_desligado(cfg, tmp_path, monkeypatch):
    from agente import servidor_mcp
    from agente.braco import seguranca

    monkeypatch.setattr(seguranca, "SINAL_PARADA", tmp_path / "PARADO")
    monkeypatch.setattr(servidor_mcp, "_preparar", lambda: (cfg, _Ollama()))
    interruptor.desligar(cfg, _Ollama())
    assert servidor_mcp._seguro(lambda c, o: "rodou") == interruptor.AVISO_MCP
    interruptor.acordar(cfg)
    monkeypatch.setattr(servidor_mcp.recursos, "garantir_folga", lambda *a, **k: None)
    assert servidor_mcp._seguro(lambda c, o: "rodou") == "rodou"
