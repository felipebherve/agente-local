from types import SimpleNamespace

import pytest

from agente import git_ops, maestro
from agente.braco import ThreadUnica, janelas, navegador, seguranca
from agente.braco.navegador import _descrever
from agente.executor import ConfirmacaoNecessaria, ErroExecucao


@pytest.mark.parametrize("texto", ["Enviar cadastro", "Finalizar compra", "Sign in", "Excluir"])
def test_acoes_arriscadas_pedem_confirmacao(texto):
    with pytest.raises(ConfirmacaoNecessaria):
        seguranca.exigir_confirmacao(texto, confirmado=False)
    seguranca.exigir_confirmacao(texto, confirmado=True)


def test_acao_comum_passa_e_motivo_forca_confirmacao():
    seguranca.exigir_confirmacao("Pré-visualizar", confirmado=False)
    with pytest.raises(ConfirmacaoNecessaria, match="senha"):
        seguranca.exigir_confirmacao("Senha", confirmado=False, motivo="é um campo de senha")


def test_parada_de_emergencia_bloqueia_ate_liberar():
    seguranca.parar()
    try:
        with pytest.raises(seguranca.ParadaDeEmergencia):
            seguranca.verificar()
    finally:
        seguranca.liberar()
    seguranca.verificar()


def test_thread_unica_roda_sempre_na_mesma_thread():
    import threading

    unica = ThreadUnica("teste")
    nomes = {unica.rodar(lambda: threading.current_thread().name) for _ in range(3)}
    assert len(nomes) == 1


def test_descricao_de_elementos():
    campo = {"ref": 1, "tag": "input", "tipo": "email", "rotulo": "E-mail", "valor": "a@b.c"}
    botao = {"ref": 2, "tag": "input", "tipo": "submit", "rotulo": "Enviar", "valor": ""}
    link = {"ref": 3, "tag": "a", "tipo": "", "rotulo": "Ajuda", "valor": ""}
    assert _descrever(campo) == "[1] campo (email) \"E-mail\" = 'a@b.c'"
    assert _descrever(botao) == '[2] botão "Enviar"'
    assert _descrever(link) == '[3] link "Ajuda"'


class _NavegadorFalso:
    def __init__(self):
        self.urls: list[str] = []

    def abrir(self, url: str) -> str:
        self.urls.append(url)
        return url


def test_abrir_endereco_site_conhecido(monkeypatch):
    falso = _NavegadorFalso()
    monkeypatch.setattr(navegador, "navegador", lambda _cfg: falso)
    cfg = SimpleNamespace(sites_liberados={"youtube": "https://www.youtube.com/"})
    assert navegador.abrir_endereco(cfg, "YouTube") == "https://www.youtube.com/"


def test_abrir_endereco_dominio_direto(monkeypatch):
    falso = _NavegadorFalso()
    monkeypatch.setattr(navegador, "navegador", lambda _cfg: falso)
    cfg = SimpleNamespace(sites_liberados={})
    navegador.abrir_endereco(cfg, "exemplo.com.br")
    assert falso.urls == ["exemplo.com.br"]


def test_abrir_endereco_sem_dominio_busca_no_google(monkeypatch):
    falso = _NavegadorFalso()
    monkeypatch.setattr(navegador, "navegador", lambda _cfg: falso)
    cfg = SimpleNamespace(sites_liberados={})
    navegador.abrir_endereco(cfg, "qual o sentido da vida")
    assert falso.urls[0].startswith("https://www.google.com/search?q=")


def test_resolver_abrir_app_liberado(cfg, monkeypatch):
    chamadas = []
    monkeypatch.setattr(janelas, "abrir_app", lambda _c, nome: chamadas.append(nome) or "ok")
    assert navegador.resolver_abrir(cfg, "calculadora") == "ok"
    assert chamadas == ["calculadora"]


def _sem_app(*_a: object, **_k: object) -> str:
    raise ErroExecucao("app não liberado")


def test_resolver_abrir_arquivo_local_existente(cfg, tmp_path, monkeypatch):
    arquivo = tmp_path / "nota.txt"
    arquivo.write_text("x")
    monkeypatch.setattr(janelas, "abrir_app", _sem_app)
    chamadas: list[list[str]] = []
    monkeypatch.setattr(navegador.subprocess, "Popen", lambda args: chamadas.append(args))
    resposta = navegador.resolver_abrir(cfg, arquivo.name)
    assert chamadas == [["xdg-open", str(arquivo)]]
    assert str(arquivo) in resposta


def test_resolver_abrir_cai_no_site_quando_nao_e_app_nem_arquivo(cfg, monkeypatch):
    monkeypatch.setattr(janelas, "abrir_app", _sem_app)
    chamadas = []
    monkeypatch.setattr(
        navegador, "abrir_endereco", lambda _c, alvo: chamadas.append(alvo) or "ok"
    )
    assert navegador.resolver_abrir(cfg, "youtube") == "ok"
    assert chamadas == ["youtube"]


def test_resolver_abrir_projeto_no_git(cfg, repo, monkeypatch):
    monkeypatch.setattr(maestro, "achar_projeto", lambda _c, _frase: repo)
    monkeypatch.setattr(git_ops, "remoto_web", lambda _c, _pasta: "https://github.com/x/y")
    chamadas = []
    monkeypatch.setattr(
        navegador, "abrir_endereco", lambda _c, alvo: chamadas.append(alvo) or "ok"
    )
    resposta = navegador.resolver_abrir(cfg, "meu projeto falavado que esta no git")
    assert chamadas == ["https://github.com/x/y"]
    assert resposta == "ok"


def test_resolver_abrir_projeto_no_git_nao_achado(cfg, monkeypatch):
    monkeypatch.setattr(maestro, "achar_projeto", lambda _c, _frase: None)
    with pytest.raises(ErroExecucao):
        navegador.resolver_abrir(cfg, "projeto inexistente no git")
