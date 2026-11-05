import asyncio
import importlib.util

from agente import servidor_mcp
from agente.llm import ErroOllama


def test_ferramentas_registradas():
    nomes = {f.name for f in asyncio.run(servidor_mcp.mcp.list_tools())}
    esperadas = {
        "perguntar_local",
        "resumir_texto",
        "resumir_arquivo",
        "rodar_testes",
        "git_status",
        "git_pull",
        "git_criar_branch",
        "git_commit",
        "git_merge",
        "git_push",
        "abrir_pr",
        "relatorio_economia",
        "status_agente",
        "navegador_abrir",
        "navegador_ler",
        "navegador_clicar",
        "navegador_preencher",
        "navegador_tecla",
        "navegador_fechar",
        "janelas_listar",
        "janela_ler",
        "janela_clicar",
        "janela_digitar",
        "abrir_app",
        "tela_descrever",
        "tela_clicar",
        "braco_liberar",
        "reiniciar_claude",
        "revisar_projeto",
        "pedir_ao_agente",
    }
    if importlib.util.find_spec("agente.vagas"):
        esperadas |= {"ler_vaga", "buscar_vagas"}
    assert esperadas <= nomes


def test_erro_vira_texto_legivel(monkeypatch):
    class ClienteQuebrado:
        def conversar(self, *a, **k):
            raise ErroOllama("fora do ar")

    cfg, _ = servidor_mcp._preparar()
    monkeypatch.setattr(servidor_mcp, "_preparar", lambda: (cfg, ClienteQuebrado()))
    assert servidor_mcp.resumir_texto("log").startswith("ERRO no agente local")
