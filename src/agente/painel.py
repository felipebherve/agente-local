"""Painel de Agentes e bolinhas flutuantes (tkinter, já vem com o Python).

- Painel: um ícone por agente, colorido e com brilho quando ligado, apagado quando
  desligado; embaixo, quanto do PC cada um usa. O tema é um só
  (Padrão), visual sóbrio; o painel principal agora é o painel web (painel_web.py).
- Bolinhas: no canto superior direito da tela principal aparecem só os agentes que estão
  trabalhando agora (quando o Claude chama uma ferramenta deles).

Tudo do Tk roda numa única thread ("interface"); as outras threads só pedem coisas pela fila.
"""

from __future__ import annotations

import functools
import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ICONES = Path(__file__).parent / "icones"
CHAVE_TRANSPARENTE = "#010203"  # cor que vira transparente na janela das bolinhas
TAM_ICONE = 104
TAM_BOLINHA = 56
ATUALIZAR_MS = 1000
BOLINHAS_MS = 400
PROGRESSO_MS = 200
APP_ID = "AgenteLocal.Painel"  # o Windows agrupa a janela com o ícone IA, não com o do Python
VERDE_IA, CINZA_IA = "#2ecc71", "#8a8f98"


@dataclass(frozen=True)
class Tema:
    chave: str
    nome: str  # aparece no botão de trocar
    janela: str
    titulo: str
    subtitulo: str
    fundo: str
    cartao: str  # fundo das placas de texto
    borda: str  # moldura das placas ("" = sem moldura)
    texto: str
    apagado: str
    cor_ligado: str
    cor_desligado: str
    cor_breve: str
    fonte: str
    fonte_titulo: str
    pasta: str = ""  # subpasta de icones/ ("" = ícones padrão)
    palavras: tuple[str, str, str] = ("Ligado.", "Desligado.", "Em breve.")
    texto_ferramentas: str = "⚡ Ligar ferramentas"
    nomes: dict[str, str] = field(default_factory=dict)  # nome do agente -> nome no tema
    descricoes: dict[str, str] = field(default_factory=dict)

    def nome_de(self, agente: Agente) -> str:
        return self.nomes.get(agente.nome, agente.nome)

    def descricao_de(self, agente: Agente) -> str:
        return self.descricoes.get(agente.nome, agente.descricao)


PADRAO = Tema(
    chave="padrao",
    nome="Padrão",
    janela="Painel de Agentes",
    titulo="Painel de Agentes",
    subtitulo="Clique em um ícone para ativar ou desativar o agente",
    fundo="#5a606a",
    cartao="#6b727d",
    borda="#868e9a",
    texto="#f4f5f7",
    apagado="#d6d9de",
    cor_ligado="#3ccf6e",
    cor_desligado="#c9ccd1",
    cor_breve="#f2c230",
    fonte="Segoe UI",
    fonte_titulo="Segoe UI Semibold",
)

TEMAS = (PADRAO,)


def ler_tema(arquivo: Path | None) -> Tema:
    if arquivo is not None:
        try:
            chave = arquivo.read_text(encoding="utf-8").strip()
        except OSError:
            chave = ""
        for tema in TEMAS:
            if tema.chave == chave:
                return tema
    return PADRAO


def salvar_tema(arquivo: Path | None, tema: Tema) -> None:
    if arquivo is None:
        return
    try:
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_text(tema.chave, encoding="utf-8")
    except OSError as exc:
        logger.warning("não salvei o tema: %s", exc)


def proximo_tema(tema: Tema) -> Tema:
    return TEMAS[(TEMAS.index(tema) + 1) % len(TEMAS)]


@dataclass(frozen=True)
class Agente:
    nome: str
    descricao: str
    cor: str  # cor do brilho quando ligado
    icone: str  # nome base dos arquivos em icones/ (<icone>_on.png e <icone>_off.png)
    ligado: Callable[[], bool] | None = None  # None = ainda não existe ("em breve")
    alternar: Callable[[bool], None] | None = None  # recebe o novo estado
    uso: Callable[[], str] | None = None  # quanto do PC usa agora, em texto curto


def futuros() -> list[Agente]:
    """Agentes do plano ainda não construídos (todos já existem desde a Fase 10)."""
    return []


def arquivo_icone(tema: Tema, icone: str, ligado: bool) -> Path:
    """Ícone do tema; se o tema não tem esse agente, usa o ícone padrão."""
    nome = f"{icone}_{'on' if ligado else 'off'}.png"
    proprio = ICONES / tema.pasta / nome
    return proprio if tema.pasta and proprio.exists() else ICONES / nome


def imagem_icone(agente: Agente, ligado: bool, tamanho: int, tema: Tema = PADRAO) -> Any:
    """Ícone do agente; ligado ganha um anel de brilho na cor dele."""
    from PIL import Image, ImageDraw, ImageFilter

    try:
        base = Image.open(arquivo_icone(tema, agente.icone, ligado)).convert("RGBA")
        base = base.resize((256, 256), Image.Resampling.LANCZOS)
    except OSError:
        base = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        ImageDraw.Draw(base).ellipse((10, 10, 246, 246), fill=agente.cor if ligado else "#444")
    margem = 18
    lado = 256 + 2 * margem
    tela = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    if ligado:
        brilho = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
        ImageDraw.Draw(brilho).ellipse(
            (margem - 6, margem - 6, lado - margem + 6, lado - margem + 6),
            outline=agente.cor,
            width=14,
        )
        tela.alpha_composite(brilho.filter(ImageFilter.GaussianBlur(9)))
    tela.alpha_composite(base, (margem, margem))
    return tela.resize((tamanho, tamanho), Image.Resampling.LANCZOS)


def _milhar(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _curto(n: int) -> str:
    return f"{n / 1000:.1f}k".replace(".0k", "k") if n >= 1000 else str(n)


MESES = (
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)


def nome_mes(chave: str, curto: bool = False) -> str:
    """'2026-10' -> 'outubro de 2026' (ou 'out/26')."""
    ano, mes = chave.split("-")
    nome = MESES[int(mes) - 1]
    return f"{nome[:3]}/{ano[2:]}" if curto else f"{nome} de {ano}"


def por_mes(pontos: list[tuple[str, int]]) -> dict[str, int]:
    """pontos: (quando ISO, tokens poupados). Soma por mês 'AAAA-MM'."""
    soma: dict[str, int] = {}
    for quando, tokens in pontos:
        soma[quando[:7]] = soma.get(quando[:7], 0) + tokens
    return soma


def por_dia(pontos: list[tuple[str, int]], mes: str) -> dict[str, int]:
    soma: dict[str, int] = {}
    for quando, tokens in pontos:
        if quando.startswith(mes):
            soma[quando[:10]] = soma.get(quando[:10], 0) + tokens
    return soma


def por_hora(pontos: list[tuple[str, int]], dia: str) -> list[int]:
    horas = [0] * 24
    for quando, tokens in pontos:
        if dia and quando.startswith(dia) and len(quando) >= 13:
            horas[int(quando[11:13])] += tokens
    return horas


def imagem_ia(ligado: bool, tamanho: int = 64) -> Any:
    """Botão redondo "IA": verde com o agente ligado, cinza desligado (ícone da barra)."""
    from PIL import Image, ImageDraw, ImageFont

    escala = 4  # desenha grande e reduz: borda lisa
    lado = tamanho * escala
    tela = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    desenho = ImageDraw.Draw(tela)
    cor = VERDE_IA if ligado else CINZA_IA
    desenho.ellipse((2, 2, lado - 3, lado - 3), fill=cor, outline="#ffffff", width=lado // 22)
    try:
        fonte: Any = ImageFont.truetype("segoeuib.ttf", int(lado * 0.42))
    except OSError:
        fonte = ImageFont.load_default()
    desenho.text((lado / 2, lado / 2), "IA", fill="#ffffff", font=fonte, anchor="mm")
    return tela.resize((tamanho, tamanho), Image.Resampling.LANCZOS)


class Interface:
    """Dona da thread do Tk: painel sob demanda e bolinhas sempre prontas."""

    def __init__(
        self,
        agentes: list[Agente],
        ativos: Callable[[], set[str]],
        uso_total: Callable[[], str],
        arquivo_tema: Path | None = None,
        ligar_ferramentas: Callable[[], None] | None = None,
        pedir: Callable[[str], tuple[str, str]] | None = None,
        mandar_ao_claude: Callable[[str], str] | None = None,
        historico: Callable[[], list[Any]] | None = None,
        economia: Callable[[], list[tuple[str, int]]] | None = None,
        ferramentas_estado: Callable[[], list[tuple[str, bool]]] | None = None,
        ligar_uma: Callable[[str], None] | None = None,
        desligar_ferramentas: Callable[[], None] | None = None,
    ) -> None:
        self.agentes = agentes
        self.historico = historico  # registros do agente.historico, mais novos primeiro
        self.economia = economia  # (quando ISO, tokens poupados) de cada tarefa
        self.ferramentas_estado = ferramentas_estado
        self.ligar_uma = ligar_uma
        self.desligar_ferramentas = desligar_ferramentas
        self._ferramentas: list[tuple[str, bool]] = []  # checks: (nome, aberto agora)
        self._verbo = "Abrindo"
        self._icone_ligado: bool | None = None
        self._principal: Any = None  # página principal do painel
        self._pagina_aberta: Any = None  # aba aberta por cima dela (histórico, economia)
        self.ligar_ferramentas = ligar_ferramentas
        self.pedir = pedir  # Porteiro: devolve (destino, resposta)
        self.mandar_ao_claude = mandar_ao_claude
        self._respostas: queue.Queue[str] = queue.Queue()
        self._caixa: Any = None
        self._ultimo_pedido = ""
        self.ativos = ativos
        self.uso_total = uso_total
        self.arquivo_tema = arquivo_tema
        self.tema = ler_tema(arquivo_tema)
        self._pedidos: queue.Queue[str] = queue.Queue()
        self._thread: threading.Thread | None = None
        # Medições que custam (psutil, nvidia-smi) rodam fora da thread do Tk.
        self._usos: dict[str, str] = {}
        self._total = ""
        self._progresso: tuple[int, int, str] | None = None  # barra do "Ligar ferramentas"
        self._mostrando: tuple[str, ...] = ()  # agentes nas bolinhas agora

    def iniciar(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._rodar, name="interface", daemon=True)
            self._thread.start()
            threading.Thread(target=self._medir, name="medir uso", daemon=True).start()

    def abrir_painel(self) -> None:
        self.iniciar()
        self._pedidos.put("painel")

    def mostrar_progresso(self, feitos: int, total: int, nome: str, verbo: str = "Abrindo") -> None:
        """Atualiza a barra de carregamento (pode ser chamada de qualquer thread)."""
        self._verbo = verbo
        self._progresso = (feitos, total, nome)
        if feitos >= total:
            threading.Timer(6, lambda: setattr(self, "_progresso", None)).start()

    def trocar_tema(self) -> Tema:
        self.tema = proximo_tema(self.tema)
        salvar_tema(self.arquivo_tema, self.tema)
        self._pedidos.put("tema")
        return self.tema

    # --- medições (thread própria) ---------------------------------------------------------

    def _medir(self) -> None:
        while True:
            for agente in self.agentes:
                if agente.uso is not None:
                    try:
                        self._usos[agente.nome] = agente.uso()
                    except Exception:  # medir nunca derruba o painel
                        logger.exception("uso de %s", agente.nome)
            try:
                self._total = self.uso_total()
            except Exception:
                logger.exception("uso total")
            if self.ferramentas_estado is not None:
                try:
                    self._ferramentas = self.ferramentas_estado()
                except Exception:
                    logger.exception("estado das ferramentas")
            time.sleep(3)

    # --- thread do Tk ----------------------------------------------------------------------

    def _rodar(self) -> None:
        import tkinter as tk

        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)  # type: ignore[attr-defined,unused-ignore]  # só Windows
        except (AttributeError, OSError):
            pass
        self.raiz = tk.Tk()
        self.raiz.withdraw()
        self._fotos: dict[tuple[str, str, bool, int], Any] = {}
        self._painel: Any = None
        self._fotos_ia: list[Any] = []
        self._pintar_icone()
        self._criar_bolinhas()
        self._processar_pedidos()
        self.raiz.mainloop()

    def _foto(self, agente: Agente, ligado: bool, tamanho: int) -> Any:
        from PIL import ImageTk

        chave = (self.tema.chave, agente.icone, ligado, tamanho)
        if chave not in self._fotos:
            imagem = imagem_icone(agente, ligado, tamanho, self.tema)
            self._fotos[chave] = ImageTk.PhotoImage(imagem)
        return self._fotos[chave]

    def _pintar_icone(self) -> None:
        """Ícone da barra de tarefas: verde se alguma ferramenta está aberta, senão cinza."""
        from PIL import ImageTk

        ligado = any(aberto for _, aberto in self._ferramentas)
        if ligado != self._icone_ligado:
            self._icone_ligado = ligado
            self._fotos_ia = [ImageTk.PhotoImage(imagem_ia(ligado, t)) for t in (64, 32)]
            self.raiz.iconphoto(True, *self._fotos_ia)
            if self._painel is not None and self._painel.winfo_exists():
                self._painel.iconphoto(False, *self._fotos_ia)
        self.raiz.after(1000, self._pintar_icone)

    def _processar_pedidos(self) -> None:
        while not self._pedidos.empty():
            pedido = self._pedidos.get_nowait()
            if pedido == "painel":
                self._mostrar_painel()
            elif pedido == "tema":
                self._aplicar_tema()
            elif pedido == "historico":
                self._abrir_historico()
            elif pedido == "economia":
                self._abrir_economia()
            elif pedido == "voltar":
                self._fechar_pagina()
        while not self._respostas.empty():
            self._escrever_resposta(self._respostas.get_nowait())
        self.raiz.after(150, self._processar_pedidos)

    def _aplicar_tema(self) -> None:
        """Refaz o painel (se aberto) e as bolinhas com o tema novo."""
        if self._painel is not None and self._painel.winfo_exists():
            x, y = self._painel.winfo_x(), self._painel.winfo_y()
            self._painel.destroy()
            self._painel = None
            self._mostrar_painel()
            self._painel.geometry(f"+{x}+{y}")
        self._mostrando = ()  # força redesenhar as bolinhas

    def _placa(self, pai: Any, **opcoes: Any) -> Any:
        """Quadro com o fundo e a moldura das placas do tema."""
        import tkinter as tk

        tema = self.tema
        moldura: dict[str, Any] = (
            {"highlightthickness": 2, "highlightbackground": tema.borda} if tema.borda else {}
        )
        return tk.Frame(pai, bg=tema.cartao, **moldura, **opcoes)

    def _mostrar_painel(self) -> None:
        import tkinter as tk

        if self._painel is not None and self._painel.winfo_exists():
            self._painel.deiconify()
            self._painel.lift()
            return
        tema = self.tema
        janela = tk.Toplevel(self.raiz, bg=tema.fundo)
        janela.title(tema.janela)
        janela.resizable(False, False)
        if self._fotos_ia:
            janela.iconphoto(False, *self._fotos_ia)
        janela.configure(padx=22, pady=18)
        # Página principal num quadro: as abas (histórico, economia) trocam com ele.
        principal = tk.Frame(janela, bg=tema.fundo)
        principal.grid(row=0, column=0, sticky="nsew")
        self._principal = principal

        topo = self._placa(principal, padx=16, pady=10)
        topo.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        topo.columnconfigure(0, weight=1)
        tk.Label(
            topo, text=tema.titulo, bg=tema.cartao, fg=tema.texto, font=(tema.fonte_titulo, 20)
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            topo, text=tema.subtitulo, bg=tema.cartao, fg=tema.apagado, font=(tema.fonte, 11)
        ).grid(row=1, column=0, sticky="w")
        total = tk.Label(topo, text="", bg=tema.cartao, fg=tema.apagado, font=(tema.fonte, 9))
        total.grid(row=2, column=0, sticky="w", pady=(4, 0))
        botao_tema = tk.Label(
            topo,
            text=f"Tema: {tema.nome}  ⟳",
            bg=tema.fundo,
            fg="#ffffff" if tema is not PADRAO else tema.texto,
            font=(tema.fonte, 10),
            padx=10,
            pady=4,
            cursor="hand2",
            relief="ridge",
            bd=1,
        )
        botao_tema.grid(row=0, column=1, sticky="ne", padx=(16, 0))
        botao_tema.bind("<Button-1>", lambda _e: self.trocar_tema())
        if self.ligar_ferramentas is not None:
            ligar = self.ligar_ferramentas
            botao_ferramentas = tk.Label(
                topo,
                text=tema.texto_ferramentas,
                bg=tema.cor_ligado,
                fg="#ffffff",
                font=(tema.fonte_titulo, 11, "bold"),
                padx=12,
                pady=6,
                cursor="hand2",
                relief="raised",
                bd=2,
            )
            botao_ferramentas.grid(row=1, column=1, sticky="se", padx=(16, 0), pady=(4, 0))
            botao_ferramentas.bind("<Button-1>", lambda _e: ligar())
        if self.desligar_ferramentas is not None:
            desligar = self.desligar_ferramentas
            botao_desligar = tk.Label(
                topo,
                text="⏻ Desligar ferramentas",
                bg="#c0392b",
                fg="#ffffff",
                font=(tema.fonte_titulo, 10, "bold"),
                padx=12,
                pady=4,
                cursor="hand2",
                relief="raised",
                bd=2,
            )
            botao_desligar.grid(row=2, column=1, sticky="se", padx=(16, 0), pady=(6, 0))
            botao_desligar.bind("<Button-1>", lambda _e: desligar())
        checks = tk.Frame(topo, bg=tema.cartao)
        checks.grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        rotulos: dict[str, Any] = {}

        def _clique(nome: str, _evento: Any) -> None:
            clicar_check(nome)

        aviso_desligado = tk.Label(
            checks, text="", bg=tema.cartao, fg="#e74c3c", font=(tema.fonte_titulo, 10, "bold")
        )

        def clicar_check(nome: str) -> None:
            aberto = dict(self._ferramentas).get(nome, False)
            if not aberto and self.ligar_uma is not None and self._progresso is None:
                self.ligar_uma(nome)

        def pintar_checks() -> None:
            ocupado = self._progresso[2] if self._progresso else ""
            for i, (nome, aberto) in enumerate(self._ferramentas):
                rotulo = rotulos.get(nome)
                if rotulo is None:
                    rotulo = tk.Label(checks, bg=tema.cartao, font=(tema.fonte, 9), padx=4)
                    rotulo.grid(row=i // 4, column=i % 4, sticky="w", padx=(0, 14))
                    rotulo.bind("<Button-1>", functools.partial(_clique, nome))
                    rotulos[nome] = rotulo
                if nome == ocupado:
                    texto, cor, cursor = f"⏳ {nome}", tema.texto, "watch"
                elif aberto:
                    texto, cor, cursor = f"☑ {nome}", tema.cor_ligado, "arrow"
                else:
                    texto, cor, cursor = f"☐ {nome}", tema.apagado, "hand2"
                rotulo.configure(text=texto, fg=cor, cursor=cursor)
            linhas = (len(self._ferramentas) + 3) // 4
            if self._ferramentas and not any(a for _, a in self._ferramentas) and not ocupado:
                aviso_desligado.configure(text="Agentes desligados")
                aviso_desligado.grid(row=linhas, column=0, columnspan=4, sticky="w", pady=(4, 0))
            else:
                aviso_desligado.grid_remove()

        barra = tk.Canvas(topo, height=22, bg=tema.cartao, highlightthickness=0)

        def pintar_barra() -> None:
            if not barra.winfo_exists():
                return
            pintar_checks()
            if self._progresso is None:
                barra.grid_remove()
            else:
                feitos, total, nome = self._progresso
                barra.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))
                largura = max(barra.winfo_width(), 1)
                barra.delete("all")
                barra.create_rectangle(0, 4, largura, 18, fill=tema.fundo, outline=tema.borda)
                fracao = feitos / total if total else 1
                barra.create_rectangle(0, 4, largura * fracao, 18, fill=tema.cor_ligado, outline="")
                pronto = "Tudo pronto!" if self._verbo == "Abrindo" else "Agentes desligados"
                texto = f"{self._verbo} {nome}... ({feitos}/{total})" if nome else pronto
                barra.create_text(
                    largura / 2, 11, text=texto, fill="#ffffff", font=(tema.fonte, 8, "bold")
                )
            barra.after(PROGRESSO_MS, pintar_barra)

        pintar_barra()

        if self.pedir is not None:
            self._caixa_porteiro(principal)
        cartoes = [
            self._cartao(principal, agente, 2 + i // 3, i % 3)
            for i, agente in enumerate(self.agentes)
        ]

        def atualizar() -> None:
            if not janela.winfo_exists():
                return
            total.configure(text=self._total)
            for cartao in cartoes:
                self._pintar(*cartao)
            janela.after(ATUALIZAR_MS, atualizar)

        atualizar()
        self._painel = janela

    # --- Porteiro: caixa de pedidos --------------------------------------------------------

    def _caixa_porteiro(self, janela: Any) -> None:
        import tkinter as tk

        tema = self.tema
        placa = self._placa(janela, padx=14, pady=10)
        placa.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        placa.columnconfigure(0, weight=1)
        tk.Label(
            placa,
            text="Peça aqui: o Maestro liga o agente certo; o que não der vai ao Claude",
            bg=tema.cartao,
            fg=tema.apagado,
            font=(tema.fonte, 9),
        ).grid(row=0, column=0, columnspan=3, sticky="w")
        entrada = tk.Entry(placa, font=(tema.fonte, 11), relief="solid", bd=1)
        entrada.grid(row=1, column=0, sticky="ew", pady=(4, 6), ipady=4)
        botao = tk.Label(
            placa,
            text="Pedir",
            bg=tema.cor_ligado,
            fg="#ffffff",
            font=(tema.fonte_titulo, 10, "bold"),
            padx=14,
            pady=4,
            cursor="hand2",
        )
        botao.grid(row=1, column=1, padx=(8, 0), pady=(4, 6))
        claude = tk.Label(
            placa,
            text="Mandar ao Claude",
            bg=tema.fundo,
            fg="#ffffff",
            font=(tema.fonte, 10),
            padx=10,
            pady=4,
            cursor="hand2",
        )
        claude.grid(row=1, column=2, padx=(8, 0), pady=(4, 6))
        caixa = tk.Text(
            placa,
            height=4,
            wrap="word",
            font=(tema.fonte, 10),
            bg=tema.cartao,
            fg=tema.texto,
            relief="flat",
            state="disabled",
        )
        caixa.grid(row=2, column=0, columnspan=3, sticky="ew")
        self._caixa = caixa
        if self.historico is not None:
            link = tk.Label(
                placa,
                text="📜 Histórico de pedidos  ›",
                bg=tema.cartao,
                fg=tema.cor_ligado,
                font=(tema.fonte_titulo, 10, "bold", "underline"),
                cursor="hand2",
            )
            link.grid(row=3, column=0, sticky="w", pady=(6, 0))
            link.bind("<Button-1>", lambda _e: self._abrir_historico())
        if self.economia is not None:
            grafico = tk.Label(
                placa,
                text="📈 Economia de tokens  ›",
                bg=tema.cartao,
                fg=tema.cor_ligado,
                font=(tema.fonte_titulo, 10, "bold", "underline"),
                cursor="hand2",
            )
            grafico.grid(row=3, column=1, columnspan=2, sticky="e", pady=(6, 0))
            grafico.bind("<Button-1>", lambda _e: self._abrir_economia())

        def pedir(_evento: Any = None) -> None:
            texto = entrada.get().strip()
            if not texto or self.pedir is None:
                return
            self._ultimo_pedido = texto
            self._escrever_resposta("Pensando...")
            pedir_ = self.pedir

            def rodar() -> None:
                try:
                    destino, resposta = pedir_(texto)
                    prefixo = "" if destino == "local" else "➜ "
                    self._respostas.put(prefixo + resposta)
                except Exception as exc:  # erro vira texto na caixa, não fecha o painel
                    logger.exception("porteiro")
                    self._respostas.put(f"Não consegui: {exc}")

            threading.Thread(target=rodar, name="porteiro", daemon=True).start()

        def mandar(_evento: Any = None) -> None:
            texto = entrada.get().strip() or self._ultimo_pedido
            if texto and self.mandar_ao_claude is not None:
                self._escrever_resposta(self.mandar_ao_claude(texto))

        entrada.bind("<Return>", pedir)
        botao.bind("<Button-1>", pedir)
        claude.bind("<Button-1>", mandar)

    def _abrir_pagina(self, titulo: str) -> Any:
        """Troca a página principal por uma aba com o botão de voltar; devolve o quadro dela."""
        import tkinter as tk

        tema = self.tema
        self._fechar_pagina()
        # A aba cobre a página principal (mesmo tamanho); voltar só a destrói.
        pagina = tk.Frame(self._painel, bg=tema.fundo)
        pagina.place(in_=self._principal, x=0, y=0, relwidth=1, relheight=1)
        pagina.lift()
        barra = tk.Frame(pagina, bg=tema.fundo)
        barra.pack(fill="x")
        voltar = tk.Label(
            barra,
            text="←  Voltar ao painel",
            bg=tema.cor_ligado,
            fg="#ffffff",
            font=(tema.fonte_titulo, 10, "bold"),
            padx=12,
            pady=5,
            cursor="hand2",
        )
        voltar.pack(side="left")
        voltar.bind("<Button-1>", lambda _e: self._fechar_pagina())
        tk.Label(
            barra, text=titulo, bg=tema.fundo, fg="#ffffff", font=(tema.fonte_titulo, 16)
        ).pack(side="left", padx=(16, 0))
        self._pagina_aberta = pagina
        return pagina

    def _fechar_pagina(self) -> None:
        pagina = getattr(self, "_pagina_aberta", None)
        if pagina is not None and pagina.winfo_exists():
            pagina.destroy()
        self._pagina_aberta = None

    def _abrir_historico(self) -> None:
        """Aba com todos os pedidos: data e hora, quem resolveu, resumo e tokens."""
        import tkinter as tk
        from tkinter import ttk

        if self.historico is None:
            return
        tema = self.tema
        pagina = self._abrir_pagina("Histórico de pedidos")
        cabeca = tk.Label(pagina, bg=tema.fundo, fg="#ffffff", font=(tema.fonte, 10), anchor="w")
        cabeca.pack(fill="x", pady=(10, 0))
        colunas = ("quando", "pedido", "agente", "resumo", "locais", "poupados")
        titulos = (
            "Data e hora",
            "Pedido",
            "Quem fez",
            "Resumo do que foi feito",
            "Tokens gastos (PC)",
            "Poupados do Claude",
        )
        larguras = (125, 190, 90, 330, 110, 115)
        estilo = ttk.Style(pagina)
        estilo.configure("Historico.Treeview", rowheight=26, font=(tema.fonte, 9))
        estilo.configure("Historico.Treeview.Heading", font=(tema.fonte, 9, "bold"))
        quadro = tk.Frame(pagina, bg=tema.fundo)
        quadro.pack(fill="both", expand=True, pady=(8, 0))
        tabela = ttk.Treeview(quadro, columns=colunas, show="headings", style="Historico.Treeview")
        for coluna, titulo, largura in zip(colunas, titulos, larguras, strict=True):
            tabela.heading(coluna, text=titulo)
            alinhar: Any = "e" if coluna in ("locais", "poupados") else "w"
            tabela.column(coluna, width=largura, anchor=alinhar, stretch=coluna == "resumo")
        rolagem = ttk.Scrollbar(quadro, orient="vertical", command=tabela.yview)
        tabela.configure(yscrollcommand=rolagem.set)
        tabela.pack(side="left", fill="both", expand=True)
        rolagem.pack(side="right", fill="y")
        detalhe = tk.Label(
            pagina,
            bg=tema.fundo,
            fg="#ffffff",
            font=(tema.fonte, 9),
            anchor="w",
            justify="left",
            wraplength=940,
        )
        detalhe.pack(fill="x", pady=(8, 0))
        registros: dict[str, Any] = {}

        def carregar() -> None:
            if not pagina.winfo_exists():
                return
            lista = self.historico() if self.historico is not None else []
            selecionado = tabela.focus()
            tabela.delete(*tabela.get_children())
            registros.clear()
            for r in lista:
                quem = r.agente + (" → Claude" if r.destino == "claude" else "")
                item = tabela.insert(
                    "",
                    "end",
                    values=(
                        f"{r.quando[8:10]}/{r.quando[5:7]}/{r.quando[:4]} {r.quando[11:16]}",
                        r.pedido,
                        quem,
                        r.resumo,
                        _milhar(r.tokens_locais),
                        _milhar(r.tokens_poupados),
                    ),
                )
                registros[item] = r
            if selecionado in registros:
                tabela.focus(selecionado)
            locais = sum(r.tokens_locais for r in lista)
            poupados = sum(r.tokens_poupados for r in lista)
            cabeca.configure(
                text=f"{len(lista)} pedidos · {_milhar(locais)} tokens gastos aqui no PC "
                f"(de graça) · {_milhar(poupados)} poupados do Claude. "
                "Clique num pedido para ver o resumo inteiro."
            )
            pagina.after(5000, carregar)  # pedidos novos aparecem sozinhos

        def mostrar(_evento: Any = None) -> None:
            r = registros.get(tabela.focus())
            if r is not None:
                detalhe.configure(
                    text=f"{r.quando} · {r.agente} · {r.segundos:.0f} s\n"
                    f"Pedido: {r.pedido}\nResposta: {r.resumo}"
                )

        tabela.bind("<<TreeviewSelect>>", mostrar)
        carregar()

    def _abrir_economia(self) -> None:
        """Aba com os gráficos de tokens poupados: meses, dias do mês e horas do dia."""
        import tkinter as tk

        if self.economia is None:
            return
        tema = self.tema
        pagina = self._abrir_pagina("Economia de tokens")
        pontos = self.economia()
        meses = por_mes(pontos)
        if not meses:
            tk.Label(
                pagina,
                text="Nenhuma economia registrada ainda.",
                bg=tema.fundo,
                fg="#ffffff",
                font=(tema.fonte, 11),
            ).pack(pady=40)
            return
        escolha = {"mes": max(meses), "dia": ""}
        resumo = tk.Label(pagina, bg=tema.fundo, fg="#ffffff", font=(tema.fonte, 10), anchor="w")
        resumo.pack(fill="x", pady=(10, 4))
        tk.Label(
            pagina,
            text="Meses (clique para ver os dias)",
            bg=tema.fundo,
            fg="#ffffff",
            font=(tema.fonte_titulo, 10, "bold"),
            anchor="w",
        ).pack(fill="x")
        tela_meses = tk.Canvas(pagina, height=150, bg=tema.cartao, highlightthickness=0)
        tela_meses.pack(fill="x", pady=(2, 8))
        titulo_dias = tk.Label(
            pagina, bg=tema.fundo, fg="#ffffff", font=(tema.fonte_titulo, 10, "bold"), anchor="w"
        )
        titulo_dias.pack(fill="x")
        tela_dias = tk.Canvas(pagina, height=170, bg=tema.cartao, highlightthickness=0)
        tela_dias.pack(fill="x", pady=(2, 8))
        titulo_horas = tk.Label(
            pagina, bg=tema.fundo, fg="#ffffff", font=(tema.fonte_titulo, 10, "bold"), anchor="w"
        )
        titulo_horas.pack(fill="x")
        tela_horas = tk.Canvas(pagina, height=150, bg=tema.cartao, highlightthickness=0)
        tela_horas.pack(fill="x", pady=(2, 0))

        def ir_mes(mes: str) -> None:
            escolha.update(mes=mes, dia="")
            desenhar()

        def ir_dia(dia: str) -> None:
            escolha.update(dia=dia)
            desenhar()

        def desenhar() -> None:
            mes, dia = escolha["mes"], escolha["dia"]
            dias = por_dia(pontos, mes)
            if not dia or dia not in dias:
                dia = max(dias) if dias else ""
                escolha["dia"] = dia
            total = sum(meses.values())
            melhor = max(meses, key=lambda m: meses[m])
            resumo.configure(
                text=f"Total poupado: {_milhar(total)} tokens · {nome_mes(mes)}: "
                f"{_milhar(meses[mes])} · melhor mês: {nome_mes(melhor)}"
            )
            barras(
                tela_meses,
                [(nome_mes(m, curto=True), v, m) for m, v in sorted(meses.items())],
                mes,
                ir_mes,
            )
            titulo_dias.configure(
                text=f"Por dia em {nome_mes(mes)} (clique num dia para ver as horas)"
            )
            barras(
                tela_dias,
                [(d[-2:], v, d) for d, v in sorted(dias.items())],
                dia,
                ir_dia,
            )
            horas = por_hora(pontos, dia)
            titulo_horas.configure(
                text=f"Por hora em {dia[8:10]}/{dia[5:7]}/{dia[:4]}" if dia else ""
            )
            barras(tela_horas, [(f"{h}h", v, str(h)) for h, v in enumerate(horas)], "", None)

        def barras(
            tela: Any,
            itens: list[tuple[str, int, str]],
            marcado: str,
            clicar: Callable[[str], object] | None,
        ) -> None:
            tela.update_idletasks()
            largura, altura = max(tela.winfo_width(), 600), int(tela["height"])
            tela.delete("all")
            if not itens:
                return
            maior = max(v for _, v, _ in itens) or 1
            passo = min((largura - 20) / len(itens), 90)  # poucas barras: não viram um bloco
            for i, (rotulo, valor, chave) in enumerate(itens):
                x0 = 10 + i * passo + passo * 0.15
                x1 = 10 + (i + 1) * passo - passo * 0.15
                topo = altura - 22 - (altura - 44) * valor / maior
                cor = tema.cor_ligado if chave != marcado else "#f1c40f"
                barra = tela.create_rectangle(x0, topo, x1, altura - 22, fill=cor, outline="")
                tela.create_text(
                    (x0 + x1) / 2, altura - 11, text=rotulo, fill=tema.texto, font=(tema.fonte, 8)
                )
                if valor and passo > 26:
                    tela.create_text(
                        (x0 + x1) / 2,
                        topo - 8,
                        text=_curto(valor),
                        fill=tema.texto,
                        font=(tema.fonte, 7),
                    )
                if clicar is not None:
                    for alvo in (barra,):
                        tela.tag_bind(alvo, "<Button-1>", lambda _e, c=chave: clicar(c))
                    tela.configure(cursor="hand2")

        pagina.after(50, desenhar)

    def _escrever_resposta(self, texto: str) -> None:
        caixa = self._caixa
        if caixa is None or not caixa.winfo_exists():
            return
        caixa.configure(state="normal")
        caixa.delete("1.0", "end")
        caixa.insert("1.0", texto)
        linhas = min(12, max(4, texto.count("\n") + 1 + len(texto) // 110))
        caixa.configure(state="disabled", height=linhas)

    def _cartao(self, janela: Any, agente: Agente, linha: int, coluna: int) -> tuple[Any, ...]:
        import tkinter as tk

        tema = self.tema
        quadro = tk.Frame(janela, bg=tema.fundo, padx=6, pady=8)
        quadro.grid(row=linha, column=coluna, sticky="nsew")
        quadro.rowconfigure(0, weight=1)
        janela.columnconfigure(coluna, uniform="cartoes")  # placas da mesma largura
        botao = tk.Label(quadro, bg=tema.fundo, cursor="hand2" if agente.ligado else "arrow")
        botao.grid(row=0, column=0, sticky="n")
        botao.bind("<Button-1>", lambda _e: self._clicar(agente))
        placa = self._placa(quadro, padx=8, pady=6)
        placa.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        quadro.columnconfigure(1, weight=1)
        cabeca = tk.Frame(placa, bg=tema.cartao)
        cabeca.pack(anchor="w")
        ponto = tk.Label(cabeca, text="●", bg=tema.cartao, font=(tema.fonte, 9))
        ponto.pack(side="left")
        tk.Label(
            cabeca,
            text=tema.nome_de(agente),
            bg=tema.cartao,
            fg=tema.texto,
            font=(tema.fonte_titulo, 13, "bold" if tema is not PADRAO else "normal"),
        ).pack(side="left", padx=(4, 0))
        opcoes: dict[str, Any] = {
            "bg": tema.cartao,
            "anchor": "w",
            "justify": "left",
            "wraplength": 170,
        }
        estado = tk.Label(placa, font=(tema.fonte, 10), fg=tema.texto, **opcoes)
        estado.pack(anchor="w")
        uso = tk.Label(placa, font=(tema.fonte, 8), fg=tema.apagado, **opcoes)
        uso.pack(anchor="w", pady=(4, 0))
        return agente, botao, ponto, estado, uso

    def _pintar(self, agente: Agente, botao: Any, ponto: Any, estado: Any, uso: Any) -> None:
        tema = self.tema
        if agente.ligado is None:
            ligado, palavra, cor = False, tema.palavras[2], tema.cor_breve
        else:
            try:
                ligado = agente.ligado()
            except Exception:
                logger.exception("estado de %s", agente.nome)
                ligado = False
            palavra = tema.palavras[0] if ligado else tema.palavras[1]
            cor = tema.cor_ligado if ligado else tema.cor_desligado
        botao.configure(image=self._foto(agente, ligado, TAM_ICONE))
        ponto.configure(fg=cor)
        estado.configure(text=f"{palavra} {tema.descricao_de(agente)}")
        uso.configure(text=self._usos.get(agente.nome, ""))

    def _clicar(self, agente: Agente) -> None:
        if agente.ligado is None or agente.alternar is None:
            return
        try:
            agente.alternar(not agente.ligado())
        except Exception:
            logger.exception("alternar %s", agente.nome)

    # --- bolinhas flutuantes ---------------------------------------------------------------

    def _criar_bolinhas(self) -> None:
        import tkinter as tk

        janela = tk.Toplevel(self.raiz, bg=CHAVE_TRANSPARENTE)
        janela.overrideredirect(True)
        janela.attributes("-topmost", True)
        janela.attributes("-transparentcolor", CHAVE_TRANSPARENTE)
        janela.withdraw()
        self._bolinhas = janela
        self._mostrando = ()
        self._rotulos: list[Any] = []
        janela.after(BOLINHAS_MS, self._atualizar_bolinhas)

    def _sem_clique(self) -> None:
        """Deixa os cliques passarem pelas bolinhas e tira a janela do Alt+Tab."""
        import ctypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined,unused-ignore]  # só Windows
        hwnd = user32.GetParent(self._bolinhas.winfo_id())
        gwl_exstyle, ws_ex_transparent, ws_ex_layered, ws_ex_toolwindow = -20, 0x20, 0x80000, 0x80
        estilo = user32.GetWindowLongW(hwnd, gwl_exstyle)
        user32.SetWindowLongW(
            hwnd, gwl_exstyle, estilo | ws_ex_transparent | ws_ex_layered | ws_ex_toolwindow
        )

    def _atualizar_bolinhas(self) -> None:
        import tkinter as tk

        try:
            ativos = self.ativos()
        except Exception:
            logger.exception("ler atividade")
            ativos = set()
        nomes = tuple(a.nome for a in self.agentes if a.nome in ativos)
        if nomes != self._mostrando:
            for rotulo in self._rotulos:
                rotulo.destroy()
            self._rotulos = []
            if nomes:
                for agente in (a for a in self.agentes if a.nome in nomes):
                    rotulo = tk.Label(
                        self._bolinhas,
                        image=self._foto(agente, True, TAM_BOLINHA),
                        bg=CHAVE_TRANSPARENTE,
                    )
                    rotulo.pack(side="left", padx=2)
                    self._rotulos.append(rotulo)
                self._bolinhas.update_idletasks()
                largura = self._bolinhas.winfo_reqwidth()
                # A tela principal começa em (0, 0) no Windows.
                x = self.raiz.winfo_screenwidth() - largura - 16
                self._bolinhas.geometry(f"+{x}+48")
                self._bolinhas.deiconify()
                self._sem_clique()
            else:
                self._bolinhas.withdraw()
            self._mostrando = nomes
        self._bolinhas.after(BOLINHAS_MS, self._atualizar_bolinhas)
