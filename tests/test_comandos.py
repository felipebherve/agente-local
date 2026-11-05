from agente import comandos
from agente.braco import janelas


def test_comando_desconhecido_pede_claude(cfg):
    comando = comandos.padrao(cfg)
    assert comando("qual a capital da frança") == "PRECISA DO CLAUDE: faça você mesmo."


def test_comando_buscar_usa_memoria(cfg, tmp_path):
    (tmp_path / "relatorio.pdf").write_text("x")
    comando = comandos.padrao(cfg)
    assert comando("busca o arquivo relatorio.pdf").endswith("relatorio.pdf")


def test_comando_abrir_usa_resolver_abrir(cfg, monkeypatch):
    chamadas = []
    monkeypatch.setattr(janelas, "abrir_app", lambda _c, nome: chamadas.append(nome) or "ok")
    comando = comandos.padrao(cfg)
    assert comando("abra a calculadora") == "ok"
    assert chamadas == ["calculadora"]
