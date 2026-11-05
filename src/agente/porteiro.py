"""Porteiro (Fase 8): recebe o pedido primeiro e decide quem resolve.

- Simples (pergunta curta, conta, tradução, resumo, comando do agente): resolve aqui, de graça.
- Precisa do Claude (código, projeto, análise longa): copia o pedido, abre o Claude e avisa.

A decisão é por regras; o Cérebro só é consultado quando as regras não bastam.
"""

from __future__ import annotations

import ast
import logging
import operator
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from agente.config import Config
from agente.voz.conversa import normalizar

if TYPE_CHECKING:
    from agente.nuvem import Resposta as NuvemResposta

logger = logging.getLogger(__name__)

SISTEMA_LOCAL = (
    "Você é o assistente local{de_quem}, em português do Brasil. Responda direto e curto "
    "(até 8 frases), sem enrolação. Responda tudo que você souber com certeza, mesmo que seja "
    "só parte do pedido. NUNCA chute ou invente um fato que você não tem como saber (nome de "
    "arquivo, detalhe de um projeto específico, API usada, etc.): nesses casos diga 'não sei, "
    "{vocativo}' em vez de adivinhar. Se uma parte exigir ler arquivos, código de um "
    "projeto ou informação que você não tem, responda a parte que sabe e, numa linha separada "
    "no final, escreva: 'PRECISA DO CLAUDE PARA: ' seguido do que falta, em uma frase curta. "
    "Só escreva 'PRECISA DO CLAUDE' sem mais nada se você não souber responder absolutamente "
    "nada."
)
SISTEMA_NUVEM = (
    "Você é um modelo de IA grátis na nuvem, chamado pelo agente local{de_quem} "
    "(via OmniRoute) quando o modelo local não soube responder sozinho. Responda em "
    "português do Brasil, direto e completo. Você não tem acesso a arquivos, código ou "
    "projetos da pessoa: se o pedido depender disso, responda a parte que der e termine, "
    "numa linha separada, com 'PRECISA DO CLAUDE PARA: ' seguido do que falta, em uma "
    "frase curta."
)


def sistema(modelo: str, cfg: Config) -> str:
    """Preenche o prompt com o nome de quem usa (config nome_usuario), se houver."""
    nome = cfg.nome_usuario.strip()
    return modelo.format(
        de_quem=f" de {nome}" if nome else "",
        vocativo=f"não sei, meu nobre {nome}" if nome else "não sei",
    )


SISTEMA_TRIAGEM = (
    "Classifique o pedido. Responda só LOCAL ou CLAUDE. LOCAL: pergunta curta de conhecimento "
    "geral, definição, tradução, conta, resumo ou correção de um texto curto colado. CLAUDE: "
    "escrever ou mudar código, mexer num projeto ou arquivos, planejar, analisar algo longo."
)
PRECISA = "PRECISA DO CLAUDE"

# Trabalho do Claude mesmo em frase curta: fazer, mudar ou investigar algo.
FORTE = re.compile(
    r"\b(implement\w*|refator\w*|bug|debug\w*|commit|pull request|deploy|"
    r"crie|criar|construa|construir|desenvolv\w*|integr\w*|configur\w*|instal\w*|"
    r"planej\w*|estrategi\w*|analis\w*|compar\w*|revis\w*|pesquis\w*|"
    r"erro no|erro na|nao funciona|quebrou)\b"
)
# Assuntos do Claude, a menos que seja só uma pergunta de definição ("o que é uma API?").
ASSUNTO = re.compile(
    r"\b(codigo|programa\w*|funcao|classe|script|repositorio|repo|api|banco de dados|sql|"
    r"projeto|arquivo|pasta|site|app|aplicativo|tela de|layout|arquitetura)\b"
)
# Sinais de pergunta simples que o modelo local responde bem.
LOCAL = re.compile(
    r"^(o que (e|sao|significa)|quem (e|foi|sao)|quanto (e|sao|custa|tempo)|qual (e|a|o)|"
    r"quando|onde fica|como se (diz|escreve|fala)|traduz\w*|resum\w*|corrij\w*|"
    r"conver\w*|calcul\w*|defin\w*|sinonimo|explique (rapid|em uma|curto)|me diga)\b"
)
# Subconjunto de LOCAL que é claramente uma pergunta de conhecimento geral (não uma ação
# sobre código/projeto do usuário): tem prioridade até sobre o FORTE, por isso não inclui
# "corrija", "resuma" etc. (que também combinam com "corrija o bug", "resuma esse código").
PERGUNTA_DE_DEFINICAO = re.compile(
    r"^(o que (e|sao|significa)|quem (e|foi|sao)|quanto (e|sao|custa|tempo)|qual (e|a|o)|"
    r"quando|onde fica|como se (diz|escreve|fala))\b"
)
CONTA = re.compile(r"^[\d\s+\-*/().,^%x]+$")


class Conversador(Protocol):
    def conversar(
        self, modelo: str, pergunta: str, sistema: str | None = None, temperatura: float = 0.2
    ) -> object: ...


@dataclass(frozen=True)
class Decisao:
    destino: str  # "local", "conta", "comando" ou "claude"
    motivo: str


@dataclass(frozen=True)
class Resultado:
    destino: str  # "local", "nuvem" ou "claude"
    resposta: str  # texto para mostrar (ou o aviso de que foi ao Claude)


def calcular(expressao: str) -> float:
    """Conta simples, sem eval: só números e + - * / ^ %."""
    texto = expressao.replace("x", "*").replace("^", "**").replace(",", ".")
    operacoes: dict[type, Callable[..., float]] = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.Mod: operator.mod,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }

    def avaliar(no: ast.AST) -> float:
        if isinstance(no, ast.Expression):
            return avaliar(no.body)
        if isinstance(no, ast.Constant) and isinstance(no.value, int | float):
            return float(no.value)
        if isinstance(no, ast.BinOp) and type(no.op) in operacoes:
            if isinstance(no.op, ast.Pow) and abs(avaliar(no.right)) > 100:
                raise ValueError("expoente grande demais")
            return operacoes[type(no.op)](avaliar(no.left), avaliar(no.right))
        if isinstance(no, ast.UnaryOp) and type(no.op) in operacoes:
            return operacoes[type(no.op)](avaliar(no.operand))
        raise ValueError("só contas simples")

    return avaliar(ast.parse(texto, mode="eval"))


def triar(pedido: str, perguntar_ao_cerebro: Callable[[str], str] | None = None) -> Decisao:
    """Decide quem resolve o pedido. Regras primeiro; o Cérebro só desempata."""
    from agente.voz.conversa import interpretar

    frase = normalizar(pedido)
    if not frase:
        return Decisao("local", "vazio")
    if CONTA.match(pedido.strip()) and re.search(r"\d", pedido):
        return Decisao("conta", "conta simples")
    if interpretar(pedido).acao not in ("perguntar", "nada"):
        return Decisao("comando", "comando do agente")
    linhas = pedido.strip().count("\n") + 1
    if "```" in pedido or linhas > 8 or len(pedido) > 600:
        # texto longo colado só para resumir ou traduzir ainda é local
        if LOCAL.match(frase) and "```" not in pedido:
            return Decisao("local", "resumo ou tradução de texto colado")
        return Decisao("claude", "pedido longo ou com código")
    curta = len(frase.split()) <= 25
    if PERGUNTA_DE_DEFINICAO.match(frase) and curta:
        # pergunta de conhecimento geral: resolve local mesmo citando uma palavra
        # do FORTE ou do ASSUNTO (ex.: "o que é configurar uma rede?")
        return Decisao("local", "pergunta de definição")
    if FORTE.search(frase):
        return Decisao("claude", "pede para fazer ou investigar algo")
    if LOCAL.match(frase) and curta:
        return Decisao("local", "pergunta curta")
    if ASSUNTO.search(frase):
        return Decisao("claude", "fala de código ou de projeto")
    if len(frase.split()) <= 12:
        return Decisao("local", "pergunta curta")
    if perguntar_ao_cerebro is not None:
        try:
            veredito = perguntar_ao_cerebro(pedido).strip().upper()
        except Exception as exc:  # sem modelo, na dúvida vai ao Claude
            logger.warning("triagem pelo Cérebro falhou: %s", exc)
            return Decisao("claude", "na dúvida")
        if veredito.startswith("LOCAL"):
            return Decisao("local", "o Cérebro achou simples")
        return Decisao("claude", "o Cérebro achou que precisa do Claude")
    return Decisao("claude", "na dúvida")


def dica_de_projeto(cfg: Config, pedido: str) -> str:
    """Se o pedido cita um projeto conhecido, diz ao Claude onde ele está (sem colar código)."""
    from agente import memoria

    frase = normalizar(pedido)
    for projeto in memoria.projetos(cfg):
        nome = normalizar(projeto.name)
        if nome and re.search(rf"\b{re.escape(nome)}\b", frase):
            return (
                f"\n\n(Projeto: {projeto}. Use contexto_projeto do agente local antes de abrir "
                "arquivos.)"
            )
    return ""


def copiar(texto: str) -> None:
    import win32clipboard

    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, texto)
    finally:
        win32clipboard.CloseClipboard()


def abrir_claude() -> None:
    from agente.ferramentas import CLAUDE_APP

    subprocess.Popen(["explorer.exe", CLAUDE_APP])


def mandar_ao_claude(
    cfg: Config,
    pedido: str,
    copiar_: Callable[[str], None] = copiar,
    abrir: Callable[[], None] = abrir_claude,
) -> str:
    """Copia o pedido (com a dica do projeto) e abre o Claude; a pessoa só cola e envia."""
    copiar_(pedido.strip() + dica_de_projeto(cfg, pedido))
    abrir()
    return "Precisa do Claude: copiei o pedido e abri o Claude. É só colar (Ctrl+V) e enviar."


def resolver(
    cfg: Config,
    cliente: Conversador,
    pedido: str,
    executar_comando: Callable[[str], str] | None = None,
    encaminhar: Callable[[str], str] | None = None,
    perguntar_nuvem: Callable[[str], NuvemResposta | None] | None = None,
) -> Resultado:
    """Triagem + resposta. encaminhar(pedido) manda ao Claude (padrão: copiar e abrir o app).

    Se o modelo local não souber responder, tenta o degrau do meio (perguntar_nuvem,
    padrão: OmniRoute) antes de subir pro Claude.
    """
    from agente import economia, nuvem

    encaminhar = encaminhar or (lambda p: mandar_ao_claude(cfg, p))
    sistema_nuvem = sistema(SISTEMA_NUVEM, cfg)
    perguntar_nuvem = perguntar_nuvem or (lambda p: nuvem.perguntar(cfg, p, sistema_nuvem))

    def perguntar_ao_cerebro(texto: str) -> str:
        r = cliente.conversar(cfg.modelos.cerebro, texto, sistema=SISTEMA_TRIAGEM, temperatura=0)
        return str(getattr(r, "texto", ""))

    decisao = triar(pedido, perguntar_ao_cerebro)
    logger.info("porteiro: %s (%s)", decisao.destino, decisao.motivo)
    if decisao.destino == "claude":
        return Resultado("claude", encaminhar(pedido))
    if decisao.destino == "conta":
        try:
            valor = calcular(pedido)
            texto = f"{valor:g}".replace(".", ",")
            return Resultado("local", f"{pedido.strip()} = {texto}")
        except (ValueError, SyntaxError, ZeroDivisionError, OverflowError) as exc:
            return Resultado("local", f"Não consegui fazer essa conta: {exc}")
    if decisao.destino == "comando" and executar_comando is not None:
        return Resultado("local", executar_comando(pedido))
    r = cliente.conversar(
        cfg.modelos.cerebro, pedido, sistema=sistema(SISTEMA_LOCAL, cfg), temperatura=0.3
    )
    resposta = str(getattr(r, "texto", "")).strip()
    if not resposta or _sem_conteudo_util(resposta):
        nuvem_resp = perguntar_nuvem(pedido)
        if nuvem_resp is not None:
            texto = f"[OmniRoute · {nuvem_resp.modelo}] {nuvem_resp.texto}"
            economia.registrar(cfg, "omniroute", len(pedido) + len(texto), 0)
            return Resultado("nuvem", texto)
        return Resultado("claude", encaminhar(pedido))
    # O Claude teria lido o pedido e escrito a resposta (ou o resto dela): é isso que
    # ficou de graça, mesmo quando a resposta termina com "PRECISA DO CLAUDE PARA: ...".
    economia.registrar(cfg, "porteiro", len(pedido) + len(resposta), 0)
    return Resultado("local", f"[Ollama local · {cfg.modelos.cerebro}] {resposta}")


def _sem_conteudo_util(resposta: str) -> bool:
    """True só quando o modelo não respondeu nada de fato, além do aviso PRECISA DO CLAUDE."""
    pos = resposta.upper().find(PRECISA)
    if pos == -1:
        return False
    return len(resposta[:pos].strip()) < 10
