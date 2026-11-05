from agente import ferramentas
from agente.config import carregar_config
from agente.ferramentas import ErroFerramenta, Passo, ligar_tudo


def test_liga_so_o_que_falta_e_segue_depois_de_falha():
    ligados = []

    def falhar():
        raise ErroFerramenta("Docker não ficou pronto em 120 s")

    lista = [
        Passo("Ollama", lambda: True, lambda: ligados.append("Ollama")),
        Passo("Docker", lambda: False, falhar),
        Passo("VS Code", lambda: False, lambda: ligados.append("VS Code")),
    ]
    avisos = []
    relatorio = ligar_tudo(lista, avisos.append)
    assert ligados == ["VS Code"]
    assert relatorio[0] == "Ollama: já estava ligado"
    assert relatorio[1].startswith("Docker: FALHOU")
    assert relatorio[2].startswith("VS Code: ligado")
    assert avisos == ["Ligando Docker...", "Ligando VS Code..."]


def test_desliga_na_ordem_inversa_so_o_que_esta_aberto():
    fechados = []
    lista = [
        Passo("Ollama", lambda: True, lambda: None, lambda: fechados.append("Ollama")),
        Passo("Docker", lambda: False, lambda: None, lambda: fechados.append("Docker")),
        Passo("Claude", lambda: True, lambda: None, lambda: fechados.append("Claude")),
    ]
    relatorio = ferramentas.desligar_tudo(lista)
    assert fechados == ["Claude", "Ollama"]
    assert relatorio == ["Claude: fechado", "Ollama: fechado"]


def test_estados_para_os_checks():
    def quebrado():
        raise OSError("sem wsl")

    lista = [Passo("A", lambda: True, lambda: None), Passo("B", quebrado, lambda: None)]
    assert ferramentas.estados(lista) == [("A", True), ("B", False)]


def test_ordem_dos_passos_agentes_primeiro(cfg):
    nomes = [p.nome for p in ferramentas.passos(cfg, lambda: None, lambda: None)]
    assert nomes[:3] == ["Ollama", "Cérebro", "Voz"]
    assert nomes[3:] == ["Docker", "Ubuntu (Ubuntu)", "VS Code no Ubuntu", "Claude"]


def test_config_de_ferramentas(tmp_path):
    from agente.config import caminho_config

    base = caminho_config().read_text(encoding="utf-8")
    arquivo = tmp_path / "config.yaml"
    arquivo.write_text(
        base.split("\nferramentas:")[0]
        + "\nferramentas:\n  distro: Debian\n  pasta_wsl: /home/x/proj\n  claude: false\n",
        encoding="utf-8",
    )
    cfg = carregar_config(arquivo)
    assert cfg.ferramentas.distro == "Debian"
    assert ferramentas.pasta_wsl(cfg) == "/home/x/proj"
    assert not cfg.ferramentas.claude
    assert cfg.ferramentas.voz
