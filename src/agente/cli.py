"""Linha de comando do agente local (use 'agente -h' para ver todos os comandos)."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from agente import economia, git_ops, pr, resumos, testes
from agente.bench import formatar, rodar_benchmark
from agente.config import Config, ErroConfig, carregar_config
from agente.executor import ConfirmacaoNecessaria, ErroExecucao
from agente.instalar import instalar_no_claude
from agente.llm import ClienteOllama, ErroOllama
from agente.logs import configurar_logs

logger = logging.getLogger("agente")


def _modelo(cfg: Config, papel: str) -> str:
    return str(getattr(cfg.modelos, papel))


def _ler_entrada_extra() -> str:
    """Se houver algo vindo por pipe (ex.: pytest | agente perguntar ...), anexa à pergunta."""
    if sys.stdin is None or sys.stdin.isatty():
        return ""
    return sys.stdin.read()


def cmd_perguntar(cfg: Config, cliente: ClienteOllama, args: argparse.Namespace) -> int:
    pergunta = " ".join(args.texto)
    extra = _ler_entrada_extra()
    if extra:
        pergunta = f"{pergunta}\n\n---\n{extra[-20000:]}"
    r = cliente.conversar(_modelo(cfg, args.modelo), pergunta, sistema=resumos.SISTEMA)
    print(r.texto)
    if args.detalhes:
        velocidade = f"{r.segundos:.1f}s | {r.tokens_por_s:.0f} tok/s"
        print(f"\n[{r.modelo} | {r.tokens_saida} tokens | {velocidade}]")
    return 0


def cmd_status(cfg: Config, cliente: ClienteOllama, _: argparse.Namespace) -> int:
    print(f"Ollama {cliente.versao()} em {cfg.ollama_url}")
    instalados = set(cliente.modelos_instalados())
    faltando = 0
    for papel in ("cerebro", "codigo", "visao", "embeddings"):
        nome = _modelo(cfg, papel)
        ok = nome in instalados or f"{nome}:latest" in instalados
        faltando += not ok
        print(f"  {papel:<11}{nome:<24}{'ok' if ok else 'FALTANDO (ollama pull ' + nome + ')'}")
    return 1 if faltando else 0


def cmd_acordar(cfg: Config, cliente: ClienteOllama, args: argparse.Namespace) -> int:
    cliente.acordar(_modelo(cfg, args.modelo))
    print(f"{_modelo(cfg, args.modelo)} pronto na GPU por {cfg.keep_alive}")
    return 0


def cmd_dormir(cfg: Config, cliente: ClienteOllama, _: argparse.Namespace) -> int:
    for papel in ("cerebro", "codigo", "visao"):
        cliente.dormir(_modelo(cfg, papel))
    print("Modelos fora da GPU; VRAM liberada.")
    return 0


def cmd_bench(cfg: Config, cliente: ClienteOllama, _: argparse.Namespace) -> int:
    resultados = rodar_benchmark(cfg, cliente)
    print(formatar(resultados))
    return 0 if all(r.ok for r in resultados) else 1


def cmd_instalar_claude(_cfg: Config, _cliente: ClienteOllama, _: argparse.Namespace) -> int:
    relatorio = instalar_no_claude()
    print("\n".join(relatorio))
    print("Reinicie o Claude Desktop para ele carregar o agente.")
    return 1 if any(linha.startswith("FALHOU") for linha in relatorio) else 0


def cmd_atalho(cfg: Config, _cliente: ClienteOllama, args: argparse.Namespace) -> int:
    from agente import lancador

    try:
        print(f"Atalho criado: {lancador.criar_atalho_area_de_trabalho(cfg)}")
        if args.iniciar_com_windows is not None:
            lancador.iniciar_com_windows(cfg, args.iniciar_com_windows == "sim")
            print(f"Iniciar com o Windows: {args.iniciar_com_windows}")
    except lancador.ErroLancador as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_reiniciar_claude(_cfg: Config, _cliente: ClienteOllama, _: argparse.Namespace) -> int:
    from agente.reiniciar import reiniciar_claude

    print(reiniciar_claude())
    return 0


def cmd_falar(cfg: Config, _cliente: ClienteOllama, args: argparse.Namespace) -> int:
    from agente.voz import ErroVoz, boca

    try:
        print(boca.falar(cfg, " ".join(args.texto) or _ler_entrada_extra()))
    except ErroVoz as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2
    return 0


def cmd_ouvir(cfg: Config, _cliente: ClienteOllama, _: argparse.Namespace) -> int:
    from agente.voz import ErroVoz, ouvido

    try:
        print(ouvido.ouvir(cfg, aviso=lambda: print("Pode falar...", file=sys.stderr)))
    except ErroVoz as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2
    return 0


def cmd_indexar(cfg: Config, cliente: ClienteOllama, args: argparse.Namespace) -> int:
    from agente import memoria

    print(memoria.indexar(cfg, cliente, args.pasta).texto())
    return 0


def cmd_contexto(cfg: Config, cliente: ClienteOllama, args: argparse.Namespace) -> int:
    from agente import memoria

    print(memoria.contexto(cfg, cliente, args.pasta, " ".join(args.tarefa), args.quantos))
    return 0


def cmd_ler_relevante(cfg: Config, cliente: ClienteOllama, args: argparse.Namespace) -> int:
    from agente import memoria

    print(memoria.ler_relevante(cfg, cliente, args.arquivo, " ".join(args.tarefa)))
    return 0


def cmd_pedir(cfg: Config, cliente: ClienteOllama, args: argparse.Namespace) -> int:
    from agente import maestro

    r = maestro.perguntar(
        cfg,
        cliente,
        " ".join(args.texto),
        args.pasta,
        encaminhar=lambda _p: "PRECISA DO CLAUDE: abra o Claude Code para isso.",
    )
    print(r.resposta)
    print(f"(Maestro: {r.agente})")
    return 0


def cmd_lembrar(cfg: Config, cliente: ClienteOllama, args: argparse.Namespace) -> int:
    from agente import memoria

    print(memoria.lembrar(cfg, cliente, args.pasta, " ".join(args.texto), args.tipo))
    return 0


def cmd_revisar(cfg: Config, cliente: ClienteOllama, args: argparse.Namespace) -> int:
    from agente import revisor

    r = revisor.revisar(cfg, cliente, args.pasta, not args.sem_testes, args.opiniao)
    print(r.texto())
    return 0 if r.problemas == 0 else 1


def cmd_testar(cfg: Config, cliente: ClienteOllama, args: argparse.Namespace) -> int:
    r = testes.rodar_testes(cfg, cliente, args.pasta)
    print(r.texto())
    return 0 if r.ok else 1


def cmd_git(cfg: Config, cliente: ClienteOllama, args: argparse.Namespace) -> int:
    pasta = args.pasta
    acoes = {
        "status": lambda: git_ops.status(cfg, pasta),
        "pull": lambda: git_ops.pull(cfg, pasta),
        "branch": lambda: git_ops.criar_branch(cfg, pasta, args.nome or ""),
        "commit": lambda: git_ops.commit(cfg, cliente, pasta, args.mensagem),
        "merge": lambda: git_ops.merge(cfg, pasta, args.nome or "", args.confirmar),
        "push": lambda: git_ops.push(cfg, pasta, args.confirmar),
    }
    if args.acao in ("branch", "merge") and not args.nome:
        print(f"Erro: 'agente git {args.acao}' precisa de um nome de branch", file=sys.stderr)
        return 2
    print(acoes[args.acao]())
    return 0


def cmd_pr(cfg: Config, cliente: ClienteOllama, args: argparse.Namespace) -> int:
    print(pr.abrir_pr(cfg, cliente, args.pasta, args.base, args.simular))
    return 0


def cmd_resumir(cfg: Config, cliente: ClienteOllama, args: argparse.Namespace) -> int:
    print(resumos.resumir_arquivo(cfg, cliente, Path(args.arquivo).resolve(), args.foco))
    return 0


def cmd_economia(cfg: Config, _cliente: ClienteOllama, _: argparse.Namespace) -> int:
    print(economia.relatorio(cfg))
    return 0


def criar_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agente", description="Agente de IA local e offline")
    sub = p.add_subparsers(dest="comando", required=True)
    papeis = ["cerebro", "codigo", "visao"]

    sp = sub.add_parser("perguntar", help="pergunta ao modelo local (aceita texto por pipe)")
    sp.add_argument("texto", nargs="+")
    sp.add_argument("-m", "--modelo", choices=papeis, default="cerebro")
    sp.add_argument("-d", "--detalhes", action="store_true", help="mostra tempo e tokens")
    sp.set_defaults(func=cmd_perguntar)

    sub.add_parser("status", help="confere Ollama e modelos").set_defaults(func=cmd_status)
    si = sub.add_parser("init", help="configura o agente: modelos, config.yaml e Claude")
    si.add_argument("--sim", action="store_true", help="aceita os padrões sem perguntar")
    si.add_argument("--sem-baixar", action="store_true", help="não baixa os modelos agora")
    sub.add_parser("doctor", help="confere se está tudo funcionando")

    sa = sub.add_parser("acordar", help="carrega um modelo na GPU")
    sa.add_argument("-m", "--modelo", choices=papeis, default="cerebro")
    sa.set_defaults(func=cmd_acordar)

    sub.add_parser("dormir", help="libera a VRAM").set_defaults(func=cmd_dormir)
    sub.add_parser("bench", help="mede os modelos no seu PC").set_defaults(func=cmd_bench)
    sub.add_parser(
        "instalar-claude", help="registra o agente no Claude Desktop e Code (global)"
    ).set_defaults(func=cmd_instalar_claude)
    sat = sub.add_parser("atalho", help='cria o atalho "Acordar Agente" na área de trabalho')
    sat.add_argument("--iniciar-com-windows", choices=["sim", "nao"])
    sat.set_defaults(func=cmd_atalho)
    sub.add_parser("reiniciar-claude", help="fecha e reabre o Claude Desktop").set_defaults(
        func=cmd_reiniciar_claude
    )

    sf = sub.add_parser("falar", help="fala o texto em voz alta (aceita texto por pipe)")
    sf.add_argument("texto", nargs="*")
    sf.set_defaults(func=cmd_falar)
    sub.add_parser("ouvir", help="grava uma fala e mostra o texto").set_defaults(func=cmd_ouvir)

    si = sub.add_parser("indexar", help="atualiza o índice de busca do projeto")
    si.add_argument("pasta", nargs="?", default=".")
    si.set_defaults(func=cmd_indexar)
    sc = sub.add_parser("contexto", help="trechos do projeto relevantes para uma tarefa")
    sc.add_argument("tarefa", nargs="+")
    sc.add_argument("-C", "--pasta", default=".")
    sc.add_argument("-k", "--quantos", type=int, default=5)
    sc.set_defaults(func=cmd_contexto)
    sr2 = sub.add_parser("ler-relevante", help="mapa do arquivo + só os trechos da tarefa")
    sr2.add_argument("arquivo")
    sr2.add_argument("tarefa", nargs="+")
    sr2.set_defaults(func=cmd_ler_relevante)
    sp2 = sub.add_parser("pedir", help="Maestro: escolhe o agente (ou o Claude) para o pedido")
    sp2.add_argument("texto", nargs="+")
    sp2.add_argument("-C", "--pasta", default=None, help="projeto, se o pedido não citar")
    sp2.set_defaults(func=cmd_pedir)
    sl = sub.add_parser("lembrar", help="guarda uma decisão ou erro resolvido do projeto")
    sl.add_argument("texto", nargs="+")
    sl.add_argument("-C", "--pasta", default=".")
    sl.add_argument("--tipo", choices=["decisao", "erro"], default="decisao")
    sl.set_defaults(func=cmd_lembrar)

    sv = sub.add_parser("revisar", help="Revisor: lint, tipos, testes e alterações suspeitas")
    sv.add_argument("pasta", nargs="?", default=".")
    sv.add_argument("--sem-testes", action="store_true")
    sv.add_argument("--opiniao", action="store_true", help="o modelo de código lê o diff")
    sv.set_defaults(func=cmd_revisar)

    st = sub.add_parser("testar", help="roda os testes e mostra só o resumo")
    st.add_argument("pasta", nargs="?", default=".")
    st.set_defaults(func=cmd_testar)

    sg = sub.add_parser("git", help="status, pull, branch, commit, merge, push")
    sg.add_argument("acao", choices=["status", "pull", "branch", "commit", "merge", "push"])
    sg.add_argument("nome", nargs="?", help="branch (para branch e merge)")
    sg.add_argument("-m", "--mensagem", default="", help="mensagem do commit (opcional)")
    sg.add_argument("-C", "--pasta", default=".")
    sg.add_argument("--confirmar", action="store_true", help="libera merge/push na main")
    sg.set_defaults(func=cmd_git)

    spr = sub.add_parser("pr", help="abre PR em rascunho com texto gerado localmente")
    spr.add_argument("-C", "--pasta", default=".")
    spr.add_argument("--base", default="main")
    spr.add_argument("--simular", action="store_true", help="só mostra o texto")
    spr.set_defaults(func=cmd_pr)

    sr = sub.add_parser("resumir", help="resume um arquivo grande")
    sr.add_argument("arquivo")
    sr.add_argument("--foco", default="")
    sr.set_defaults(func=cmd_resumir)

    sub.add_parser("economia", help="tokens poupados até agora").set_defaults(func=cmd_economia)
    return p


def main(argv: list[str] | None = None) -> int:
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8")
    args = criar_parser().parse_args(argv)
    if args.comando in ("init", "doctor"):  # funcionam sem config.yaml
        from agente import assistente

        if args.comando == "doctor":
            return assistente.imprimir_doctor()
        return assistente.init(sim=args.sim, baixar=not args.sem_baixar)
    try:
        cfg = carregar_config()
        configurar_logs(cfg.pasta_logs)
        cliente = ClienteOllama.de_config(cfg)
        codigo: int = args.func(cfg, cliente, args)
        return codigo
    except ConfirmacaoNecessaria as exc:
        print(f"Precisa de confirmação: {exc}. Repita com --confirmar.", file=sys.stderr)
        return 3
    except (ErroConfig, ErroOllama, ErroExecucao) as exc:
        logger.error("%s", exc)
        print(f"Erro: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrompido.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
