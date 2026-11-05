import pytest
from conftest import git

from agente import maestro


@pytest.fixture
def projetos(cfg, tmp_path):
    """Dois projetos em pastas_permitidas: falavado (git) e Site loja."""
    falavado = tmp_path / "falavado"
    falavado.mkdir()
    git(falavado, "init", "-q", "-b", "main")
    (falavado / "narracao.py").write_text("def narrar():\n    pass\n", encoding="utf-8")
    (tmp_path / "Site loja").mkdir()
    return falavado


def porteiro_falso(chamados):
    def porteiro(texto):
        chamados.append(texto)
        return "local", "resposta do porteiro"

    return porteiro


@pytest.mark.parametrize(
    ("pedido", "agente"),
    [
        ("revisa o falavado", "Revisor"),
        ("confere o código do falavado antes do commit", "Revisor"),
        ("roda os testes do falavado", "Testes"),
        ("os testes do falavado estão passando?", "Testes"),
        ("o que mudou no falavado?", "Git"),
        ("onde fica a narração no falavado", "Memória"),
        ("qual a capital da França?", "Porteiro"),
        ("revisa esse texto pra mim", "Porteiro"),  # sem projeto citado
        ("me explica o falavado", "Porteiro"),
    ],
)
def test_rotas(cfg, projetos, pedido, agente):
    assert maestro.rotear(cfg, pedido).agente == agente


def test_acha_projeto_com_espaco_e_pela_primeira_palavra(cfg, projetos, tmp_path):
    (tmp_path / "exemplo_services").mkdir()
    assert maestro.achar_projeto(cfg, "revisa o site loja").name == "Site loja"
    assert maestro.achar_projeto(cfg, "testes do exemplo").name == "exemplo_services"
    assert maestro.achar_projeto(cfg, "revisa o site") is None


def test_pasta_passada_vale_sem_citar(cfg, projetos):
    rota = maestro.rotear(cfg, "roda os testes", pasta=projetos)
    assert (rota.agente, rota.projeto) == ("Testes", projetos)


class OllamaFalso:
    def __init__(self, carregados=()):
        self.carregados = {m: 5.0 for m in carregados}
        self.acordados = []

    def modelos_carregados(self):
        return dict(self.carregados)

    def acordar(self, modelo, keep_alive=None):
        self.carregados[modelo] = 5.0
        self.acordados.append((modelo, keep_alive))

    def dormir(self, modelo):
        self.carregados.pop(modelo, None)


@pytest.fixture
def folga(monkeypatch):
    from agente import recursos

    monkeypatch.setattr(recursos, "medir", lambda: recursos.Uso(1, 12, 5, 16, 0))


def test_maestro_liga_agente_desligado_so_para_o_pedido(cfg, projetos, folga):
    cfg.pasta_dados.mkdir(parents=True, exist_ok=True)
    (cfg.pasta_dados / "porteiro-pausado").write_text("x", encoding="utf-8")
    (cfg.pasta_dados / "revisor-pausado").write_text("x", encoding="utf-8")
    assert maestro.rotear(cfg, "revisa o falavado").agente == "Revisor"
    r = maestro.conduzir(cfg, OllamaFalso(), "quem foi Pelé?", porteiro_falso([]))
    assert r.resposta.endswith("(liguei o Porteiro só para isso)")
    assert (cfg.pasta_dados / "porteiro-pausado").exists()  # continua desligado no painel


def test_desliga_o_modelo_que_ele_mesmo_carregou(cfg, projetos, folga):
    ollama = OllamaFalso()

    def porteiro(_texto):
        ollama.acordar("a")  # o Porteiro usou o Cérebro ("a" na config de teste)
        return "local", "ok"

    maestro.conduzir(cfg, ollama, "quem foi Pelé?", porteiro)
    assert ollama.acordados[-1] == ("a", maestro.DESLIGAR_APOS)

    ja_estava = OllamaFalso(["a"])
    maestro.conduzir(cfg, ja_estava, "quem foi Pelé?", lambda _t: ("local", "ok"))
    assert ja_estava.acordados == []  # acordado pelo usuário: não mexe


def test_libera_memoria_antes_de_recusar(cfg, monkeypatch):
    from agente import recursos

    usos = iter([95.0, 80.0])
    monkeypatch.setattr(recursos, "medir", lambda: recursos.Uso(0, 0, next(usos), 100, 0))
    monkeypatch.setattr(recursos.time, "sleep", lambda _s: None)
    ollama = OllamaFalso(["a", "b", "d"])
    recursos.garantir_folga(cfg, liberar=lambda: recursos.liberar(ollama, {"d"}))
    assert set(ollama.carregados) == {"d"}


def test_sem_folga_mesmo_liberando_recusa(cfg, monkeypatch):
    from agente import recursos
    from agente.executor import ErroExecucao

    monkeypatch.setattr(recursos, "medir", lambda: recursos.Uso(0, 0, 95, 100, 0))
    monkeypatch.setattr(recursos.time, "sleep", lambda _s: None)
    with pytest.raises(ErroExecucao):
        recursos.garantir_folga(cfg, liberar=lambda: recursos.liberar(OllamaFalso(["a"]), set()))


def test_conduzir_git_e_porteiro(cfg, projetos):
    chamados = []
    r = maestro.conduzir(cfg, None, "o que mudou no falavado?", porteiro_falso(chamados))
    assert (r.agente, r.destino) == ("Git", "local")
    assert "narracao.py" in r.resposta and chamados == []
    r = maestro.conduzir(cfg, None, "qual a capital da França?", porteiro_falso(chamados))
    assert r == maestro.Resultado("Porteiro", "local", "resposta do porteiro")
    assert (cfg.pasta_logs / "economia.jsonl").exists()


def test_erro_do_agente_vira_texto(cfg, projetos, tmp_path):
    r = maestro.conduzir(cfg, None, "o que mudou no site loja", porteiro_falso([]))
    assert r.agente == "Git" and "não conseguiu" in r.resposta


def test_perguntar_liga_comando_porteiro_e_historico(cfg):
    """perguntar() é o ponto único usado pela CLI, pelo MCP e pelo atalho de voz."""
    from agente import historico

    r = maestro.perguntar(cfg, None, "2 + 2")
    assert r.destino == "local" and "4" in r.resposta
    assert historico.ler(cfg)[0].pedido == "2 + 2"


def test_perguntar_usa_encaminhar_padrao_quando_cai_pro_claude(cfg):
    r = maestro.perguntar(cfg, None, "implemente uma função nova")
    assert r.destino == "claude"
    assert r.resposta == "PRECISA DO CLAUDE."


def test_perguntar_aceita_encaminhar_personalizado(cfg):
    r = maestro.perguntar(
        cfg, None, "implemente uma função nova", encaminhar=lambda _p: "abra o Claude Code"
    )
    assert r.resposta == "abra o Claude Code"
