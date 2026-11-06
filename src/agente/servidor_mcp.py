"""Servidor MCP: expõe o agente local como ferramentas para o Claude (Desktop e Code)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from agente import atividade, economia, git_ops, pr, recursos, resumos, testes
from agente.config import Config, ErroConfig, carregar_config
from agente.executor import ConfirmacaoNecessaria, ErroExecucao
from agente.llm import ClienteOllama, ErroOllama
from agente.logs import configurar_logs
from agente.voz import ErroVoz

logger = logging.getLogger(__name__)
INSTRUCOES = (
    "Agente local gratuito no PC do usuário (Ollama na GPU dele). Em TODA conversa, chame "
    "pedir_ao_agente primeiro com o pedido do usuário (e a pasta do projeto, se houver): o "
    "Maestro liga o agente certo e só sobra para você o que voltar 'PRECISA DO CLAUDE'. "
    "Antes de criar um projeto ou pasta nova, chame projeto_parecido(nome) para não "
    "duplicar um que já existe. "
    "Para economizar tokens, "
    "use estas ferramentas sempre que a tarefa couber nelas, em vez de fazer você mesmo: "
    "rodar_testes no lugar de rodar testes e ler a saída; git_status, git_pull, "
    "git_criar_branch, git_commit (sem mensagem ele escreve), git_merge, git_push e abrir_pr "
    "para git e PRs; resumir_arquivo e resumir_texto antes de ler arquivos, logs ou saídas "
    "longas; contexto_projeto antes de explorar um projeto (traz só os trechos relevantes e "
    "as decisões já tomadas), ler_relevante no lugar de abrir arquivos grandes inteiros, e "
    "lembrar para guardar decisões e erros resolvidos; revisar_projeto antes de revisar "
    "código ou dar uma tarefa como pronta (lint, tipos, testes e senhas esquecidas); "
    "pedir_ao_agente quando não souber qual ferramenta usar (o Maestro escolhe); "
    "perguntar_local para rascunhos e dúvidas simples; segunda_opiniao para checar uma decisão, "
    "um trecho de código ou um plano com um modelo local antes de seguir (é só sugestão, "
    "confira antes de agir). Para mexer no computador: "
    "navegador_* para sites (lê a página como lista numerada, sem print), janela_* e "
    "abrir_app para apps do Windows, tela_descrever para saber o que está na tela sem "
    "receber imagem. falar(texto) lê em voz alta no PC quando o usuário pedir "
    "para ouvir a resposta. Se a resposta disser 'PRECISA DE CONFIRMAÇÃO', pergunte ao usuário "
    "antes de repetir com confirmado=true. Se disser 'ERRO no agente local', siga sem ele."
)
mcp = MCPServer("agente-local", instructions=INSTRUCOES)


def _preparar() -> tuple[Config, ClienteOllama]:
    cfg = carregar_config()
    return cfg, ClienteOllama.de_config(cfg)


def _seguro(acao: Callable[[Config, ClienteOllama], str], agente: str = "Cérebro") -> str:
    """Roda a ação e transforma qualquer erro conhecido em texto curto para o Claude.

    agente: quem aparece como "trabalhando" na bolinha da tela ('' = consulta rápida, sem
    bolinha e sem checar a memória do PC).
    """
    try:
        cfg, cliente = _preparar()
        if not agente:
            return acao(cfg, cliente)
        # memória no limite: tira da placa os modelos parados antes de recusar a tarefa
        recursos.garantir_folga(cfg, liberar=lambda: recursos.liberar(cliente, set()))
        with atividade.trabalhando(cfg.pasta_dados, agente):
            return acao(cfg, cliente)
    except ConfirmacaoNecessaria as exc:
        return (
            f"PRECISA DE CONFIRMAÇÃO: {exc}. Pergunte ao usuário e, se ele aprovar, "
            "chame de novo com confirmado=true."
        )
    except (ErroConfig, ErroOllama, ErroExecucao, ErroVoz) as exc:
        logger.error("ferramenta falhou: %s", exc)
        return f"ERRO no agente local: {exc}"


@mcp.tool()
def perguntar_local(pergunta: str, papel: str = "codigo") -> str:
    """Pergunta ao modelo local no PC do usuário (grátis, sem gastar tokens do Claude).

    Bom para: explicar um erro, rascunhar texto, gerar código simples.
    papel: 'codigo' (padrão) ou 'cerebro' (raciocínio geral).
    """

    def acao(cfg: Config, cliente: ClienteOllama) -> str:
        modelo = cfg.modelos.codigo if papel == "codigo" else cfg.modelos.cerebro
        pedido = pergunta[-resumos.LIMITE_ENTRADA :]
        return cliente.conversar(modelo, pedido, sistema=resumos.SISTEMA).texto

    return _seguro(acao)


SISTEMA_SEGUNDA_OPINIAO = (
    "Você é um revisor independente, local e gratuito (não é o Claude). Dê uma segunda opinião "
    "curta e direta (até 8 frases): riscos, bugs prováveis, pontos esquecidos ou alternativas. "
    "Se não achar nada de errado, diga isso em uma frase. Responda em português do Brasil."
)


@mcp.tool()
def segunda_opiniao(pergunta: str, contexto: str = "", papel: str = "codigo") -> str:
    """Pede uma segunda opinião a um modelo local (grátis), ao estilo do zen-mcp-server.

    Use para conferir uma decisão, um trecho de código ou um plano antes de seguir, sem gastar
    tokens do Claude. papel: 'codigo' (padrão, revisão técnica), 'cerebro' (raciocínio geral) ou
    'visao' (se contexto describer algo visual). contexto: código ou texto relevante (opcional).
    A resposta é de um modelo pequeno: confira antes de agir.
    """

    def acao(cfg: Config, cliente: ClienteOllama) -> str:
        modelo = {
            "codigo": cfg.modelos.codigo,
            "cerebro": cfg.modelos.cerebro,
            "visao": cfg.modelos.visao,
        }.get(papel, cfg.modelos.codigo)
        pedido = (contexto + "\n\n" + pergunta) if contexto else pergunta
        pedido = pedido[-resumos.LIMITE_ENTRADA :]
        resposta = cliente.conversar(
            modelo, pedido, sistema=SISTEMA_SEGUNDA_OPINIAO, temperatura=0.4
        ).texto
        economia.registrar(cfg, "segunda_opiniao", len(pedido), len(resposta))
        return resposta

    return _seguro(acao)


@mcp.tool()
def resumir_texto(texto: str, foco: str = "") -> str:
    """Resume um texto longo (log, saída de comando, diff) em poucas linhas, localmente.

    Prefira esta ferramenta a ler saídas grandes inteiras: só o resumo entra no contexto.
    foco: o que importa no resumo (ex.: 'quais testes falharam e por quê').
    """
    return _seguro(
        lambda cfg, cliente: resumos.resumir_texto(cfg, cliente, texto, foco, "resumo de texto")
    )


@mcp.tool()
def resumir_arquivo(caminho: str, foco: str = "") -> str:
    """Lê um arquivo grande no PC do usuário e devolve só um resumo (ex.: log, CSV, código).

    Use antes de abrir arquivos longos inteiros. foco: o que procurar no arquivo.
    """
    return _seguro(lambda cfg, cliente: resumos.resumir_arquivo(cfg, cliente, caminho, foco))


@mcp.tool()
def rodar_testes(pasta: str) -> str:
    """Roda os testes do projeto (pytest ou npm test) e devolve só contagem, falhas e causa.

    Use no lugar de rodar os testes no terminal e ler a saída inteira.
    pasta: raiz do projeto no PC do usuário.
    """
    return _seguro(lambda cfg, cliente: testes.rodar_testes(cfg, cliente, pasta).texto())


@mcp.tool()
def git_status(pasta: str) -> str:
    """Branch, situação com o remoto e arquivos alterados, em poucas linhas."""
    return _seguro(lambda cfg, _: git_ops.status(cfg, pasta))


@mcp.tool()
def git_pull(pasta: str) -> str:
    """Atualiza a branch atual (só fast-forward; nunca cria merge nem perde trabalho)."""
    return _seguro(lambda cfg, _: git_ops.pull(cfg, pasta))


@mcp.tool()
def git_criar_branch(pasta: str, nome: str) -> str:
    """Cria uma branch nova a partir da atual e muda para ela."""
    return _seguro(lambda cfg, _: git_ops.criar_branch(cfg, pasta, nome))


@mcp.tool()
def git_commit(pasta: str, mensagem: str = "") -> str:
    """Adiciona todas as mudanças e commita. Sem mensagem, o modelo local escreve uma.

    Arquivos sensíveis (.env, chaves) nunca são commitados.
    """
    return _seguro(lambda cfg, cliente: git_ops.commit(cfg, cliente, pasta, mensagem))


@mcp.tool()
def git_merge(pasta: str, origem: str, confirmado: bool = False) -> str:
    """Faz merge de 'origem' na branch atual. Em conflito, desfaz e lista os arquivos.

    Merge na main/master exige confirmado=true, que só deve ser passado com o OK do usuário.
    """
    return _seguro(lambda cfg, _: git_ops.merge(cfg, pasta, origem, confirmado))


@mcp.tool()
def git_push(pasta: str, confirmado: bool = False) -> str:
    """Envia a branch atual para o GitHub (nunca com força).

    Push direto na main/master exige confirmado=true, só com o OK do usuário.
    """
    return _seguro(lambda cfg, _: git_ops.push(cfg, pasta, confirmado))


@mcp.tool()
def abrir_pr(pasta: str, base: str = "main", simular: bool = False) -> str:
    """Envia a branch atual e abre um PR em rascunho com título e descrição gerados localmente.

    simular=true só mostra o texto que seria usado, sem enviar nada.
    """
    return _seguro(lambda cfg, cliente: pr.abrir_pr(cfg, cliente, pasta, base, simular))


@mcp.tool()
def relatorio_economia() -> str:
    """Quantos tokens o agente local já poupou (estimativa), por tipo de tarefa."""
    return _seguro(lambda cfg, _: economia.relatorio(cfg), "")


@mcp.tool()
def status_agente() -> str:
    """Mostra se o Ollama está no ar, os modelos instalados e quanto do PC está em uso."""

    def acao(_cfg: Config, cliente: ClienteOllama) -> str:
        instalados = cliente.modelos_instalados()
        return (
            f"Ollama {cliente.versao()} ok. Modelos: {', '.join(instalados) or 'nenhum'}. "
            f"{recursos.medir().texto()}."
        )

    return _seguro(acao, "")


# --- Braço: navegador, janelas do Windows e tela (Fase 3) ---
# Os módulos do braço são importados só quando usados: o servidor sobe rápido.


@mcp.tool()
def navegador_abrir(url: str) -> str:
    """Abre um site no navegador do agente e devolve o texto e a lista numerada de elementos.

    Use no lugar de prints: a página vem como texto curto. Logins ficam salvos no perfil.
    """
    from agente.braco.navegador import navegador

    return _seguro(lambda cfg, _: navegador(cfg).abrir(url), "Braço")


@mcp.tool()
def navegador_ler() -> str:
    """Lê de novo a página atual: título, texto e elementos numerados ([1], [2]...)."""
    from agente.braco.navegador import navegador

    return _seguro(lambda cfg, _: navegador(cfg).ler(), "Braço")


@mcp.tool()
def navegador_clicar(alvo: str, confirmado: bool = False) -> str:
    """Clica num elemento pelo número da leitura (ex.: '5') ou pelo texto (ex.: 'Entrar').

    Botões de enviar, logar, pagar ou apagar exigem confirmado=true, só com o OK do usuário.
    """
    from agente.braco.navegador import navegador

    return _seguro(lambda cfg, _: navegador(cfg).clicar(alvo, confirmado), "Braço")


@mcp.tool()
def navegador_preencher(alvo: str, valor: str, confirmado: bool = False) -> str:
    """Preenche um campo (número ou rótulo). Em listas, escolhe a opção pelo texto.

    Campos de senha exigem confirmado=true, só com o OK do usuário.
    """
    from agente.braco.navegador import navegador

    return _seguro(lambda cfg, _: navegador(cfg).preencher(alvo, valor, confirmado), "Braço")


@mcp.tool()
def navegador_tecla(tecla: str, confirmado: bool = False) -> str:
    """Aperta uma tecla na página (ex.: 'Enter', 'Tab', 'Escape', 'PageDown')."""
    from agente.braco.navegador import navegador

    return _seguro(lambda cfg, _: navegador(cfg).tecla(tecla, confirmado), "Braço")


@mcp.tool()
def navegador_fechar() -> str:
    """Fecha o navegador do agente."""
    from agente.braco.navegador import navegador

    return _seguro(lambda cfg, _: navegador(cfg).fechar(), "Braço")


@mcp.tool()
def janelas_listar() -> str:
    """Lista os títulos das janelas abertas no Windows."""
    from agente.braco import janelas

    return _seguro(lambda _cfg, _: janelas.listar(), "Braço")


@mcp.tool()
def janela_ler(titulo: str) -> str:
    """Lista os botões, campos e menus de uma janela (parte do título basta), numerados."""
    from agente.braco import janelas

    return _seguro(lambda _cfg, _: janelas.ler(titulo), "Braço")


@mcp.tool()
def janela_clicar(titulo: str, alvo: str, confirmado: bool = False) -> str:
    """Clica num controle da janela pelo número da leitura ou pelo nome (ex.: 'Salvar').

    Ações de enviar, apagar, pagar etc. exigem confirmado=true, só com o OK do usuário.
    """
    from agente.braco import janelas

    return _seguro(lambda _cfg, _: janelas.clicar(titulo, alvo, confirmado), "Braço")


@mcp.tool()
def janela_digitar(titulo: str, texto: str, alvo: str = "") -> str:
    """Digita texto na posição do cursor de um campo da janela (não apaga o que já existe).

    alvo: número ou nome do campo; vazio usa o campo principal.
    """
    from agente.braco import janelas

    return _seguro(lambda _cfg, _: janelas.digitar(titulo, texto, alvo), "Braço")


@mcp.tool()
def abrir_app(nome: str) -> str:
    """Abre um app liberado no config.yaml (ex.: 'bloco de notas', 'calculadora', 'vscode')."""
    from agente.braco import janelas

    return _seguro(lambda cfg, _: janelas.abrir_app(cfg, nome), "Braço")


@mcp.tool()
def tela_descrever(pergunta: str = "") -> str:
    """Tira um print e o modelo de visão local descreve em texto (nenhuma imagem para você).

    pergunta: o que você quer saber da tela (ex.: 'apareceu alguma mensagem de erro?').
    """
    from agente.braco import tela

    return _seguro(lambda cfg, cliente: tela.descrever(cfg, cliente, pergunta), "Braço")


@mcp.tool()
def tela_clicar(alvo: str, confirmado: bool = False) -> str:
    """Clica em qualquer botão visível pelo nome, procurando em todas as janelas e na barra
    de tarefas (ex.: 'Claude - 1 janela em execução'). Nome exato é bem mais rápido.
    """
    from agente.braco import janelas

    return _seguro(lambda _cfg, _: janelas.clicar_em_qualquer(alvo, confirmado), "Braço")


@mcp.tool()
def reiniciar_claude(confirmado: bool = False) -> str:
    """Fecha e reabre o Claude Desktop (para carregar ferramentas novas do agente).

    A conversa atual é interrompida por uns 10 s. Exige confirmado=true, só com o OK do usuário.
    """
    from agente import reiniciar

    if not confirmado:
        return (
            "PRECISA DE CONFIRMAÇÃO: reiniciar o Claude interrompe esta conversa por uns 10 s. "
            "Pergunte ao usuário e, se ele aprovar, chame de novo com confirmado=true."
        )
    return _seguro(lambda _cfg, _: reiniciar.reiniciar_claude(), "")


@mcp.tool()
def braco_liberar() -> str:
    """Libera o braço depois da parada de emergência (Ctrl+Alt+P). Só com o OK do usuário."""
    from agente.braco import seguranca

    seguranca.liberar()
    return "Braço liberado."


@mcp.tool()
def contexto_projeto(pasta: str, tarefa: str, quantos: int = 5) -> str:
    """Trechos do projeto mais relevantes para a tarefa, com arquivo e linhas.

    Use ANTES de abrir ou procurar arquivos num projeto: em vez de ler pastas inteiras, recebe
    só os trechos certos e as decisões e erros já resolvidos (guardados com `lembrar`).
    Atualiza o índice sozinho (só arquivos alterados). pasta: raiz do projeto.
    """
    from agente import memoria

    return _seguro(
        lambda cfg, cliente: memoria.contexto(
            cfg, cliente, pasta, tarefa, max(1, min(quantos, 12))
        ),
        "Memória",
    )


@mcp.tool()
def ler_relevante(arquivo: str, tarefa: str) -> str:
    """Lê um arquivo grande pela metade do custo: mapa das funções com linhas + só os trechos
    ligados à tarefa. Use no lugar de abrir o arquivo inteiro quando ele passar de ~150 linhas.
    """
    from agente import memoria

    return _seguro(
        lambda cfg, cliente: memoria.ler_relevante(cfg, cliente, arquivo, tarefa), "Memória"
    )


@mcp.tool()
def indexar_projeto(pasta: str) -> str:
    """Atualiza o índice de busca do projeto (só reprocessa arquivos alterados)."""
    from agente import memoria

    return _seguro(lambda cfg, cliente: memoria.indexar(cfg, cliente, pasta).texto(), "Memória")


@mcp.tool()
def lembrar(pasta: str, texto: str, tipo: str = "decisao") -> str:
    """Guarda uma decisão do projeto (tipo 'decisao') ou um erro e como foi resolvido ('erro').

    Volta junto em contexto_projeto quando a tarefa for parecida, para não repetir a conversa.
    Escreva curto e completo, ex.: 'erro: X falhava por Y; resolvido com Z'.
    """
    from agente import memoria

    return _seguro(
        lambda cfg, cliente: memoria.lembrar(cfg, cliente, pasta, texto, tipo), "Memória"
    )


@mcp.tool()
def revisar_projeto(pasta: str, testes: bool = True, opiniao: bool = False) -> str:
    """Revisão local antes da sua: lint, tipos, testes e o que há de suspeito nas alterações
    (senhas e chaves, marcas de conflito, depuração esquecida, arquivos grandes).

    Devolve só os problemas, com arquivo e linha. Use antes de revisar código ou de dar uma
    tarefa como pronta. testes=False pula os testes; opiniao=True pede ao modelo de código
    local uma leitura do diff (confira antes de agir).
    """
    from agente import revisor

    return _seguro(
        lambda cfg, cliente: revisor.revisar(cfg, cliente, pasta, testes, opiniao).texto(),
        "Revisor",
    )


@mcp.tool()
def organizar_pasta(pasta: str) -> str:
    """Levanta uma pasta (inventário, duplicados por hash, sugestão de estrutura via
    OmniRoute) e grava o relatório em JSON, Markdown e PDF em dados/organizador/.

    Só leitura: nunca move, renomeia ou apaga nada. Pasta grande (muitos GB) pode demorar
    — a duplicata só lê o arquivo inteiro quando o tamanho e um pedaço já bateram.
    """

    def acao(cfg: Config, _cliente: ClienteOllama) -> str:
        from agente import organizador

        destino, resumo = organizador.gerar_relatorio(cfg, Path(pasta))
        return (
            f"Relatório em {destino}: {resumo['total_arquivos']} arquivos, "
            f"{resumo['tamanho_total_gb']} GB, {resumo['grupos_duplicados']} grupos "
            f"duplicados ({resumo['espaco_duplicado_gb']} GB desperdiçados). "
            "Veja resumo.json, duplicados.md, sugestao.md e relatorio.pdf."
        )

    return _seguro(acao, "Maestro")


@mcp.tool()
def pedir_ao_agente(pedido: str, pasta: str = "") -> str:
    """Pedido em português; o Maestro local escolhe quem resolve (Revisor, testes, git,
    Memória ou o Cérebro para perguntas simples) e devolve a resposta curta.

    Chame em toda conversa, antes de trabalhar: o Maestro liga o agente certo (e desliga
    depois). pasta: projeto (opcional, se o pedido não citar o nome). Se voltar
    'PRECISA DO CLAUDE', faça você mesmo; resposta local é de modelo pequeno, confira fatos.
    """
    from agente import maestro

    def acao(cfg: Config, cliente: ClienteOllama) -> str:
        r = maestro.perguntar(
            cfg,
            cliente,
            pedido,
            pasta or None,
            encaminhar=lambda _p: "PRECISA DO CLAUDE: faça você mesmo.",
        )
        return f"[{r.agente}] {r.resposta}"

    return _seguro(acao, "Maestro")


# Vagas de emprego: só existem se o módulo agente.vagas estiver presente (fica fora da
# versão pública, porque raspar sites de emprego pode ir contra os termos deles).
try:
    from agente import vagas as _vagas  # type: ignore[attr-defined,unused-ignore]
except ImportError:
    _vagas = None  # type: ignore[assignment,unused-ignore]

if _vagas is not None:

    @mcp.tool()
    def ler_vaga(url: str) -> str:
        """Abre a página de uma vaga no navegador do agente (logins salvos) e devolve só a
        ficha: cargo, empresa, local, contrato, salário, requisitos, data, se encerrou e onde
        se candidata (até ~400 caracteres). Use no lugar de abrir ou ler a página inteira.
        """
        return _seguro(lambda cfg, cliente: _vagas.ler_vaga(cfg, cliente, url), "Braço")

    @mcp.tool()
    def buscar_vagas(url_da_busca: str, max: int = 10) -> str:
        """Abre uma página de resultados de busca de vagas e devolve só títulos e links das
        vagas (sem o resto da página). Depois use ler_vaga em cada link que interessar.
        """
        return _seguro(lambda cfg, _: _vagas.buscar_vagas(cfg, url_da_busca, max), "Braço")


@mcp.tool()
def projeto_parecido(nome: str) -> str:
    """Antes de criar um projeto ou pasta nova: diz se já existe um projeto com nome parecido
    nas pastas liberadas (ex.: 'Agente de IA' e 'agente-ia'), com pasta, % pronto e resumo.
    Só lê; não cria nada.
    """
    from agente import projetos_tdah

    return _seguro(lambda cfg, _: projetos_tdah.checar_nome(cfg, nome), "")


@mcp.tool()
def falar(texto: str) -> str:
    """Fala o texto em voz alta no alto-falante do PC (voz brasileira local, Piper).

    Use quando o usuário pedir para ouvir a resposta. Texto curto: markdown e código são
    tirados, e mais de ~1200 caracteres é cortado.
    """
    from agente.voz import boca

    return _seguro(lambda cfg, _: boca.falar(cfg, texto), "Voz")


def main() -> None:
    try:
        configurar_logs(carregar_config().pasta_logs)
    except (ErroConfig, RuntimeError) as exc:
        logger.error("logs indisponíveis: %s", exc)
    from agente.braco import seguranca

    if seguranca.ativar_atalho():
        logger.info("parada de emergência: %s", seguranca.ATALHO_EMERGENCIA)
    logger.info("servidor MCP iniciado em %s", Path.cwd())
    mcp.run()


if __name__ == "__main__":
    main()
