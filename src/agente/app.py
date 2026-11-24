"""App de desktop do Agente Local (Windows e Linux): uma janela própria com o painel.

Abre o painel numa janela sem barra de navegador, com a logo do app. O agente começa
desligado; os botões "Acordar Agente" e "Desligar Agente" ficam no topo da janela.

Só abre uma janela por vez: se o app já está aberto, clicar no atalho de novo traz a
janela que já existe para a frente (a segunda cópia avisa a primeira e fecha).

Ordem de tentativa da janela:
1. pywebview (extra [app]): WebView2 no Windows, Qt no Linux. No Linux a janela se
   identifica como "agente-local", o mesmo nome do atalho, então a barra de tarefas
   mostra a logo e junta a janela com o ícone fixado;
2. Chrome, Chromium, Edge ou Brave em modo app (--app=...), janela sem abas;
3. o navegador padrão, se nada acima existir.

Se o painel já está no ar (o serviço que deixa o celular acessar), a janela só se
conecta a ele; senão o app sobe o painel e o derruba quando a janela fecha.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import webbrowser
from collections.abc import Callable
from pathlib import Path

from agente import painel_web
from agente.config import carregar_config

logger = logging.getLogger(__name__)

TITULO = "Agente Local"
ID_APP = "agente-local"  # nome do atalho .desktop: a barra de tarefas junta pelos dois
ID_WINDOWS = "AgenteLocal.App"  # AppUserModelID: o mesmo gravado nos atalhos do instalador
ICONE = Path(__file__).resolve().parent / "icones" / "app-512.png"
LARGURA, ALTURA = 1240, 820
PORTA_UNICA = 8897  # só a primeira cópia do app consegue ouvir aqui
NAVEGADORES = (
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
    "microsoft-edge", "microsoft-edge-stable", "brave-browser", "chrome", "msedge",
)
CAMINHOS_WINDOWS = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
)


# --- uma cópia só ----------------------------------------------------------------------


def avisar_aberto(porta: int = PORTA_UNICA) -> bool:
    """True se já tem um app aberto (e pediu para ele mostrar a janela)."""
    try:
        with socket.create_connection(("127.0.0.1", porta), timeout=1) as con:
            con.sendall(b"mostrar\n")
        return True
    except OSError:
        return False


def ouvir_outras_copias(
    ao_abrir_de_novo: Callable[[], None], porta: int = PORTA_UNICA
) -> socket.socket | None:
    """Reserva a porta da cópia única. None se outra cópia já reservou."""
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if sys.platform == "win32":  # no Windows, sem isso duas cópias pegam a mesma porta
        servidor.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)  # type: ignore[attr-defined]
    try:
        servidor.bind(("127.0.0.1", porta))
    except OSError:
        servidor.close()
        return None
    servidor.listen(4)

    def aceitar() -> None:
        while True:
            try:
                con, _ = servidor.accept()
            except OSError:
                return  # fechado no fim do app
            with con:
                with contextlib.suppress(OSError):
                    if con.recv(16).startswith(b"mostrar"):
                        ao_abrir_de_novo()

    threading.Thread(target=aceitar, daemon=True).start()
    return servidor


def parar_de_ouvir(servidor: socket.socket) -> None:
    """Solta a porta da cópia única (o shutdown acorda a thread presa no accept; só o
    close deixaria a porta ouvindo enquanto ela espera)."""
    with contextlib.suppress(OSError):
        servidor.shutdown(socket.SHUT_RDWR)
    servidor.close()


# --- janela ------------------------------------------------------------------------------


def achar_navegador() -> str | None:
    for nome in NAVEGADORES:
        caminho = shutil.which(nome)
        if caminho:
            return caminho
    if sys.platform == "win32":
        for caminho in CAMINHOS_WINDOWS:
            if Path(caminho).exists():
                return caminho
    return None


def comando_modo_app(navegador: str, url: str, perfil: Path) -> list[str]:
    """Janela sem abas e com perfil próprio (não mistura com o navegador do dia a dia)."""
    return [
        navegador,
        f"--app={url}",
        f"--user-data-dir={perfil}",
        f"--window-size={LARGURA},{ALTURA}",
        f"--class={ID_APP}",
        "--no-first-run",
        "--no-default-browser-check",
    ]


def qt_funciona() -> bool:
    """Testa o Qt num processo à parte: se faltar biblioteca do sistema, o Qt derruba o
    processo inteiro (não dá erro tratável), então o app nem tenta e usa o navegador."""
    teste = "import sys; from PyQt6.QtWidgets import QApplication; QApplication(sys.argv)"
    try:
        r = subprocess.run(  # noqa: S603
            [sys.executable, "-c", teste], capture_output=True, timeout=20, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if r.returncode != 0:
        logger.info("Qt não abre neste PC: %s", r.stderr.decode(errors="replace")[-300:])
    return r.returncode == 0


class Janela:
    """Guarda a janela aberta para dar para trazê-la para a frente depois."""

    def __init__(self) -> None:
        self.webview_janela = None  # janela do pywebview, quando é ela que está aberta

    def mostrar(self) -> None:
        janela = self.webview_janela
        if janela is None:
            return
        with contextlib.suppress(Exception):
            janela.restore()
            janela.show()
            janela.on_top = True  # sobe para a frente e solta logo depois
            janela.on_top = False

    def abrir_webview(self, url: str) -> bool:
        try:
            import webview  # type: ignore[import-not-found]
        except ImportError:
            return False
        gui = None
        if sys.platform.startswith("linux"):
            if not qt_funciona():
                return False
            gui = "qt"
            sys.argv[0] = ID_APP  # X11: a classe da janela vem do nome do programa
            os.environ.setdefault("QT_QPA_PLATFORMTHEME", "gtk3")
            with contextlib.suppress(Exception):
                from qtpy.QtGui import QGuiApplication  # type: ignore[import-not-found]

                QGuiApplication.setDesktopFileName(ID_APP)  # Wayland: liga ao atalho
        try:
            self.webview_janela = webview.create_window(
                TITULO, url, width=LARGURA, height=ALTURA, min_size=(380, 560)
            )
            webview.start(gui=gui, icon=str(ICONE))
        except Exception as exc:  # noqa: BLE001 - sem motor de janela: tenta o próximo jeito
            logger.info("pywebview não abriu (%s); tentando o navegador em modo app", exc)
            self.webview_janela = None
            return False
        return True


def _abrir_modo_app(url: str, perfil: Path) -> bool:
    navegador = achar_navegador()
    if not navegador:
        return False
    perfil.mkdir(parents=True, exist_ok=True)
    try:
        processo = subprocess.Popen(comando_modo_app(navegador, url, perfil))  # noqa: S603
    except OSError as exc:
        logger.info("não abriu %s: %s", navegador, exc)
        return False
    processo.wait()  # a janela fechou
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if sys.platform == "win32":  # junta a janela com o atalho fixado na barra de tarefas
        with contextlib.suppress(Exception):
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(ID_WINDOWS)  # type: ignore[attr-defined]
    janela = Janela()
    unica = ouvir_outras_copias(janela.mostrar)
    if unica is None:
        if avisar_aberto():
            logger.info("o app já está aberto: trouxe a janela para a frente")
            return
        logger.info("porta da cópia única ocupada por outro programa; abrindo mesmo assim")
    cfg = carregar_config()
    porta = painel_web.PORTA_PADRAO
    url = f"http://127.0.0.1:{porta}"
    servidor = None
    if not painel_web.no_ar(porta):
        servidor = painel_web.criar_servidor(cfg, porta)
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
    try:
        if not janela.abrir_webview(url) and not _abrir_modo_app(
            url, cfg.pasta_dados / "janela-app"
        ):
            webbrowser.open(url)
            if servidor:  # sem janela própria: segura o painel até fechar no terminal
                threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        if servidor:
            servidor.shutdown()
            servidor.server_close()
        if unica:
            parar_de_ouvir(unica)


if __name__ == "__main__":
    main()
