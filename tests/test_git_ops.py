import pytest
from conftest import git

from agente import git_ops, pr
from agente.economia import relatorio
from agente.executor import ConfirmacaoNecessaria, ErroExecucao


def test_status_resumido(cfg, repo):
    (repo / "b.txt").write_text("novo")
    texto = git_ops.status(cfg, repo)
    assert texto.startswith("main")
    assert "1 novos" in texto


def test_commit_com_mensagem_e_sem_sensiveis(cfg, repo):
    (repo / "b.txt").write_text("novo")
    (repo / "secrets.json").write_text('{"senha": "123"}')
    texto = git_ops.commit(cfg, None, repo, "adiciona b")
    assert "adiciona b" in texto
    assert "secrets.json" in texto
    assert "secrets.json" not in git(repo, "show", "--name-only", "--pretty=")
    assert "commit" in relatorio(cfg)


def test_commit_sem_mudancas(cfg, repo):
    assert git_ops.commit(cfg, None, repo) == "Nada para commitar."


def test_merge_e_push_na_main_pedem_confirmacao(cfg, repo):
    git_ops.criar_branch(cfg, repo, "feat")
    (repo / "c.txt").write_text("c")
    git_ops.commit(cfg, None, repo, "adiciona c")
    git(repo, "switch", "-q", "main")
    with pytest.raises(ConfirmacaoNecessaria):
        git_ops.merge(cfg, repo, "feat")
    with pytest.raises(ConfirmacaoNecessaria):
        git_ops.push(cfg, repo)
    assert "ok" in git_ops.merge(cfg, repo, "feat", confirmado=True)
    assert (repo / "c.txt").exists()


def test_merge_com_conflito_e_desfeito(cfg, repo):
    git_ops.criar_branch(cfg, repo, "outra")
    (repo / "a.txt").write_text("versao outra\n")
    git_ops.commit(cfg, None, repo, "muda a na outra")
    git(repo, "switch", "-q", "main")
    git_ops.criar_branch(cfg, repo, "minha")
    (repo / "a.txt").write_text("versao minha\n")
    git_ops.commit(cfg, None, repo, "muda a na minha")
    texto = git_ops.merge(cfg, repo, "outra")
    assert "Conflito em a.txt" in texto
    assert (repo / "a.txt").read_text() == "versao minha\n"


def test_pr_simulado(cfg, repo):
    git_ops.criar_branch(cfg, repo, "feat")
    (repo / "d.txt").write_text("d")
    git_ops.commit(cfg, None, repo, "adiciona d")
    texto = pr.abrir_pr(cfg, None, repo, base="main", simular=True)
    assert texto.startswith("[simulação] feat -> main")
    assert "adiciona d" in texto


def test_mensagem_longa_corta_em_palavra():
    longa = "Adiciona comandos para testar, gerenciar git, abrir PRs e resumir arquivos grandes"
    curta = git_ops._primeira_linha(f"`{longa}`\n\nexplicação extra")
    assert len(curta) <= 72
    assert curta.endswith("resumir")


@pytest.mark.parametrize(
    ("bruto", "web"),
    [
        ("git@github.com:exemplo/projeto.git", "https://github.com/exemplo/projeto"),
        ("https://github.com/exemplo/projeto.git", "https://github.com/exemplo/projeto"),
        ("https://github.com/exemplo/projeto", "https://github.com/exemplo/projeto"),
    ],
)
def test_remoto_para_web(bruto, web):
    assert git_ops._remoto_para_web(bruto) == web


def test_remoto_web_le_o_origin_do_repo(cfg, repo):
    git(repo, "remote", "add", "origin", "git@github.com:exemplo/projeto.git")
    assert git_ops.remoto_web(cfg, repo) == "https://github.com/exemplo/projeto"


def test_remoto_web_sem_origin_da_erro(cfg, repo):
    with pytest.raises(ErroExecucao):
        git_ops.remoto_web(cfg, repo)


def test_texto_pr_do_modelo():
    class Falso:
        def conversar(self, *_a, **_k):
            class R:
                texto = "TITULO: Adiciona login\nCORPO:\n## Resumo\nFaz login."

            return R()

    titulo, corpo = pr.gerar_texto_pr(Falso(), "m", "- x", "1 file", "diff")
    assert titulo == "Adiciona login"
    assert corpo.startswith("## Resumo")
