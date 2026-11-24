"""App de desktop do Agente Local (Windows e Linux): uma janela própria com o painel.

Abre o painel numa janela sem barra de navegador, com a logo do app. O agente começa
desligado; os botões "Acordar Agente" e "Desligar Agente" ficam no topo da janela.

Ordem de tentativa da janela:
1. pywebview (extra opcional [app]; no Windows usa o WebView2 que já vem no sistema);
2. Chrome, Chromium, Edge ou Brave em modo app (--app=...), janela sem abas;
3. o navegador padrão, se nada acima existir.

Se o painel já está no ar (o serviço que deixa o celular acessar), a janela só se
conecta a ele; senão o app sobe o painel e o derruba quando a janela fecha.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

from agente import painel_web
from agente.config import carregar_config

logger = logging.getLogger(__name__)

TITULO = "Agente Local"
ICONE = Path(__file__).resolve().parent / "icones" / "app-512.png"
LARGURA, ALTURA = 1240, 820
NAVEGADORES = (
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
    "microsoft-edge", "microsoft-edge-stable", "brave-browser", "chrome", "msedge",
)
CAMINHOS_WINDOWS = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
)


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
        "--class=agente-local",  # Linux: o atalho .desktop casa a janela com a logo
        "--no-first-run",
        "--no-default-browser-check",
    ]


def _abrir_webview(url: str) -> bool:
    try:
        import webview  # type: ignore[import-not-found]
    except ImportError:
        return False
    try:
        webview.create_window(TITULO, url, width=LARGURA, height=ALTURA, min_size=(380, 560))
        webview.start(icon=str(ICONE))
    except Exception as exc:  # noqa: BLE001 - sem motor de janela: tenta o próximo jeito
        logger.info("pywebview não abriu (%s); tentando o navegador em modo app", exc)
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
    cfg = carregar_config()
    porta = painel_web.PORTA_PADRAO
    url = f"http://127.0.0.1:{porta}"
    servidor = None
    if not painel_web.no_ar(porta):
        servidor = painel_web.criar_servidor(cfg, porta)
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
    try:
        if not _abrir_webview(url) and not _abrir_modo_app(url, cfg.pasta_dados / "janela-app"):
            webbrowser.open(url)
            if servidor:  # sem janela própria: segura o painel até fechar no terminal
                threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        if servidor:
            servidor.shutdown()
            servidor.server_close()


if __name__ == "__main__":
    main()
