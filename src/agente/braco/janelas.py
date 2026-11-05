"""Apps do Windows pela árvore de acessibilidade (pywinauto/UIA): lê e clica pelo nome."""

from __future__ import annotations

import logging
import re
import subprocess
import time
from typing import Any

from agente.braco import ThreadUnica
from agente.braco.seguranca import exigir_confirmacao, verificar
from agente.config import Config
from agente.executor import ErroExecucao

logger = logging.getLogger(__name__)

MAX_CONTROLES = 80
TIPOS_UTEIS = {
    "Button": "botão",
    "Edit": "campo",
    "Document": "documento",
    "MenuItem": "menu",
    "CheckBox": "caixa",
    "RadioButton": "opção",
    "ComboBox": "lista",
    "ListItem": "item",
    "TabItem": "aba",
    "Hyperlink": "link",
    "TreeItem": "item",
}

_thread = ThreadUnica("janelas")


def _desktop() -> Any:
    try:
        from pywinauto import Desktop
    except ImportError as exc:
        raise ErroExecucao("pywinauto não instalado (só funciona no Windows)") from exc
    return Desktop(backend="uia")


def _janela(titulo: str) -> Any:
    candidatas = [
        w
        for w in _desktop().windows()
        if w.is_visible() and titulo.lower() in (w.window_text() or "").lower()
    ]
    if not candidatas:
        raise ErroExecucao(f"nenhuma janela com '{titulo}' no título; use janelas_listar")
    return candidatas[0]


def _controles(janela: Any) -> list[tuple[str, str, Any]]:
    achados: list[tuple[str, str, Any]] = []
    for ctrl in janela.descendants():
        tipo = ctrl.element_info.control_type
        nome = (ctrl.window_text() or "").strip()
        if tipo in TIPOS_UTEIS and (nome or tipo in ("Edit", "Document")):
            limite = 400 if tipo in ("Edit", "Document") else 60
            achados.append((TIPOS_UTEIS[tipo], nome[:limite], ctrl))
        if len(achados) >= MAX_CONTROLES:
            break
    return achados


def _rodar(fn: Any) -> str:
    verificar()
    try:
        resultado: str = _thread.rodar(fn)
        return resultado
    except ErroExecucao:
        raise
    except Exception as exc:  # pywinauto levanta muitos tipos próprios e de COM
        raise ErroExecucao(f"janela: {type(exc).__name__}: {exc}") from exc


def listar() -> str:
    def fn() -> str:
        titulos = [
            w.window_text() for w in _desktop().windows() if w.is_visible() and w.window_text()
        ]
        return "\n".join(f"- {t[:90]}" for t in titulos) or "Nenhuma janela visível."

    return _rodar(fn)


def ler(titulo: str) -> str:
    def fn() -> str:
        janela = _janela(titulo)
        linhas = [f"Janela: {janela.window_text()}"]
        for i, (tipo, nome, _) in enumerate(_controles(janela), start=1):
            linhas.append(f'[{i}] {tipo} "{nome}"')
        return "\n".join(linhas)

    return _rodar(fn)


def _achar(janela: Any, alvo: str) -> tuple[str, Any]:
    controles = _controles(janela)
    if alvo.strip().isdigit():
        indice = int(alvo) - 1
        if 0 <= indice < len(controles):
            return controles[indice][1], controles[indice][2]
    padrao = re.compile(re.escape(alvo), re.IGNORECASE)
    for _, nome, ctrl in controles:
        if padrao.search(nome):
            return nome, ctrl
    raise ErroExecucao(f"não achei o controle '{alvo}'; use janela_ler para ver a lista")


def clicar(titulo: str, alvo: str, confirmado: bool = False) -> str:
    def fn() -> str:
        janela = _janela(titulo)
        nome, ctrl = _achar(janela, alvo)
        exigir_confirmacao(nome or alvo, confirmado)
        try:
            ctrl.invoke()
        except Exception:  # nem todo controle aceita invoke; cai para o clique real
            ctrl.click_input()
        return f"Cliquei em '{nome}' na janela '{janela.window_text()[:60]}'."

    return _rodar(fn)


def clicar_em_qualquer(alvo: str, confirmado: bool = False) -> str:
    """Procura o alvo pelo nome em todas as janelas visíveis e na barra de tarefas."""

    def fn() -> str:
        padrao = re.compile(re.escape(alvo), re.IGNORECASE)
        exatos: list[tuple[str, str, Any]] = []
        parciais: list[tuple[str, str, Any]] = []
        # Barra de tarefas primeiro (rápida e comum); para no primeiro nome exato.
        janelas = sorted(
            (w for w in _desktop().windows() if w.is_visible()),
            key=lambda w: w.element_info.class_name != "Shell_TrayWnd",
        )
        for janela in janelas:
            for _, nome, ctrl in _controles(janela):
                if nome.lower() == alvo.lower():
                    exatos.append((nome, janela.window_text(), ctrl))
                elif padrao.search(nome):
                    parciais.append((nome, janela.window_text(), ctrl))
            if exatos:
                break
        achados = exatos or parciais
        if not achados:
            raise ErroExecucao(f"não achei '{alvo}' em nenhuma janela; use janelas_listar")
        nome, janela_nome, ctrl = achados[0]
        exigir_confirmacao(nome, confirmado)
        ctrl.click_input()
        extra = f" (havia {len(achados)} parecidos)" if len(achados) > 1 else ""
        return f"Cliquei em '{nome}' ({janela_nome[:50] or 'área de trabalho'}){extra}."

    return _rodar(fn)


def _colar(ctrl: Any, texto: str) -> None:
    import win32clipboard

    win32clipboard.OpenClipboard()
    try:
        anterior = (
            win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT)
            else None
        )
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, texto)
    finally:
        win32clipboard.CloseClipboard()
    ctrl.type_keys("^v")
    time.sleep(0.3)
    if anterior is not None:
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, anterior)
        finally:
            win32clipboard.CloseClipboard()


def digitar(titulo: str, texto: str, alvo: str = "") -> str:
    def fn() -> str:
        janela = _janela(titulo)
        if alvo:
            nome, ctrl = _achar(janela, alvo)
        else:
            campos = [c for t, _, c in _controles(janela) if t in ("campo", "documento")]
            if not campos:
                raise ErroExecucao("a janela não tem campo de texto visível")
            nome, ctrl = "campo principal", campos[0]
        ctrl.set_focus()
        # Cola no cursor (não apaga o que já existe). Digitar tecla a tecla erra no ABNT2
        # (^ e ~ são acentos) e em editores ricos; a área de transferência volta ao original.
        _colar(ctrl, texto)
        return f"Digitei {len(texto)} caracteres em '{nome}' (na posição do cursor)."

    return _rodar(fn)


def abrir_app(cfg: Config, nome: str) -> str:
    comando = cfg.apps_liberados.get(nome.lower())
    if comando is None:
        liberados = ", ".join(cfg.apps_liberados) or "nenhum"
        raise ErroExecucao(f"app '{nome}' não liberado no config.yaml (liberados: {liberados})")
    verificar()
    try:
        subprocess.Popen(comando, shell=True)  # noqa: S602 - comando vem só do config do usuário
    except OSError as exc:
        raise ErroExecucao(f"não consegui abrir {nome}: {exc}") from exc
    logger.info("app aberto: %s (%s)", nome, comando)
    return f"Abrindo {nome}. Use janelas_listar em alguns segundos para achar a janela."
