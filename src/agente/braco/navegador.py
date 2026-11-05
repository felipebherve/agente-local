"""Navegador controlado pelo agente (Playwright usando o Edge/Chrome já instalado).

A página é lida como uma lista numerada de campos, botões e links: bem mais barato para o
Claude do que um print, e mais confiável que clicar por coordenada.
"""

from __future__ import annotations

import logging
import re
import subprocess
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import quote

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright
from playwright.sync_api import Error as ErroPlaywright

from agente.braco import ThreadUnica
from agente.braco.seguranca import exigir_confirmacao, verificar
from agente.config import Config
from agente.executor import ErroExecucao

logger = logging.getLogger(__name__)
T = TypeVar("T")

MAX_ELEMENTOS = 60
MAX_TEXTO = 1500

# Pega o primeiro vídeo real da busca do YouTube, pulando os anunciados (que usam outras tags).
JS_PRIMEIRO_VIDEO = """
() => {
  const a = document.querySelector(
    'ytd-video-renderer a#video-title, ytd-compact-video-renderer a#video-title'
  );
  return a ? {titulo: (a.textContent || '').trim(), href: a.href} : null;
}
"""

# Marca cada elemento interativo visível com data-agente-ref e devolve a descrição dele.
JS_ELEMENTOS = """
(max) => {
  const sel = 'a[href], button, input, textarea, select, [role=button], [role=link], '
            + '[role=checkbox], [role=tab], [contenteditable=true]';
  const vis = el => { const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const rotulo = el => {
    if (el.labels && el.labels.length) return el.labels[0].innerText;
    return el.getAttribute('aria-label') || el.getAttribute('placeholder')
        || el.innerText || el.value || el.getAttribute('title') || el.getAttribute('name') || '';
  };
  document.querySelectorAll('[data-agente-ref]').forEach(e => e.removeAttribute('data-agente-ref'));
  const saida = [];
  for (const el of document.querySelectorAll(sel)) {
    if (saida.length >= max || !vis(el) || el.disabled) continue;
    const ref = saida.length + 1;
    el.setAttribute('data-agente-ref', String(ref));
    const tag = el.tagName.toLowerCase();
    const tipo = (el.getAttribute('type') || el.getAttribute('role') || '').toLowerCase();
    const editavel = tag === 'input' || tag === 'textarea';
    saida.push({ref, tag, tipo,
      rotulo: rotulo(el).trim().replace(/\\s+/g, ' ').slice(0, 80),
      valor: editavel && el.type !== 'password' ? (el.value || '').slice(0, 40) : ''});
  }
  return saida;
}
"""

NOMES = {"a": "link", "button": "botão", "select": "lista", "textarea": "campo de texto"}


def _descrever(item: dict[str, Any]) -> str:
    tag, tipo = item["tag"], item["tipo"]
    if tag == "input":
        nome = "botão" if tipo in ("submit", "button") else f"campo ({tipo or 'text'})"
    else:
        nome = NOMES.get(tag, tipo or tag)
    valor = f" = '{item['valor']}'" if item["valor"] else ""
    return f'[{item["ref"]}] {nome} "{item["rotulo"]}"{valor}'


class Navegador:
    """Uma janela de navegador por processo, com perfil próprio (logins ficam salvos)."""

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._thread = ThreadUnica("navegador")
        self._pw: Playwright | None = None
        self._contexto: BrowserContext | None = None
        self._pagina: Page | None = None

    def _garantir(self) -> Page:
        if self._pagina is not None and not self._pagina.is_closed():
            return self._pagina
        if self._pw is None:
            self._pw = sync_playwright().start()
        if self._contexto is None:
            perfil = self._cfg.pasta_dados / "navegador"
            perfil.mkdir(parents=True, exist_ok=True)
            self._contexto = self._pw.chromium.launch_persistent_context(
                str(perfil), channel=self._cfg.navegador, headless=False, no_viewport=True
            )
            self._contexto.on("close", lambda _c: self._esquecer())
        paginas = self._contexto.pages
        self._pagina = paginas[-1] if paginas else self._contexto.new_page()
        return self._pagina

    def _esquecer(self) -> None:
        self._contexto = None
        self._pagina = None

    def _executar(self, acao: str, fn: Callable[[], str]) -> str:
        verificar()
        try:
            resultado: str = self._thread.rodar(fn)
            return resultado
        except ErroPlaywright as exc:
            raise ErroExecucao(f"navegador ({acao}): {str(exc).splitlines()[0]}") from exc

    def _elemento(self, pagina: Page, alvo: str, campo: bool = False) -> tuple[Any, str]:
        """Acha um elemento pelo número da leitura ou pelo rótulo (exato antes de parcial).

        campo=True procura só entre campos (input, textarea, select).
        """
        itens: list[dict[str, Any]] = pagina.evaluate(JS_ELEMENTOS, MAX_ELEMENTOS)
        if alvo.strip().isdigit():
            escolhidos = [i for i in itens if str(i["ref"]) == alvo.strip()]
        else:
            chave = alvo.strip().lower()
            tags = ("input", "textarea", "select")
            candidatos = [i for i in itens if not campo or i["tag"] in tags]
            escolhidos = [i for i in candidatos if i["rotulo"].lower() == chave] or [
                i for i in candidatos if chave in i["rotulo"].lower()
            ]
        if escolhidos:
            item = escolhidos[0]
            loc = pagina.locator(f'[data-agente-ref="{item["ref"]}"]')
            return loc, f"{item['rotulo']} ({item['tipo'] or item['tag']})"
        loc = pagina.get_by_text(alvo, exact=False).first
        if loc.count() == 0:
            raise ErroExecucao(f"não achei '{alvo}' na página; use navegador_ler para ver a lista")
        return loc, alvo

    def _resumo(self, pagina: Page) -> str:
        return f"{pagina.title()[:100]} ({pagina.url})"

    def abrir(self, url: str) -> str:
        if "://" not in url:
            url = "https://" + url

        def fn() -> str:
            pagina = self._garantir()
            pagina.goto(url, wait_until="domcontentloaded", timeout=45_000)
            return f"Aberto: {self._resumo(pagina)}\n{self._ler(pagina)}"

        return self._executar("abrir", fn)

    def _ler(self, pagina: Page) -> str:
        itens = pagina.evaluate(JS_ELEMENTOS, MAX_ELEMENTOS)
        texto = " ".join(pagina.inner_text("body").split())
        sobra = len(texto) - MAX_TEXTO
        corpo = texto[:MAX_TEXTO] + (f" [...+{sobra} caracteres]" if sobra > 0 else "")
        linhas = [f"Página: {self._resumo(pagina)}", f"Texto: {corpo}", "Elementos:"]
        linhas += [_descrever(i) for i in itens] or ["(nenhum elemento interativo visível)"]
        return "\n".join(linhas)

    def ler(self) -> str:
        return self._executar("ler", lambda: self._ler(self._garantir()))

    def clicar(self, alvo: str, confirmado: bool = False) -> str:
        def fn() -> str:
            pagina = self._garantir()
            loc, info = self._elemento(pagina, alvo)
            exigir_confirmacao(info, confirmado)
            loc.click(timeout=10_000)
            try:
                pagina.wait_for_load_state("domcontentloaded", timeout=5_000)
            except ErroPlaywright:
                pass
            return f"Cliquei em {info[:60]}. Agora: {self._resumo(pagina)}"

        return self._executar("clicar", fn)

    def preencher(self, alvo: str, valor: str, confirmado: bool = False) -> str:
        def fn() -> str:
            pagina = self._garantir()
            loc, info = self._elemento(pagina, alvo, campo=True)
            senha = loc.get_attribute("type") == "password"
            exigir_confirmacao(info, confirmado, "é um campo de senha" if senha else "")
            if loc.evaluate("el => el.tagName.toLowerCase()") == "select":
                loc.select_option(label=valor, timeout=10_000)
            else:
                loc.fill(valor, timeout=10_000)
            return f"Preenchi {info[:60]}."

        return self._executar("preencher", fn)

    def tecla(self, tecla: str, confirmado: bool = False) -> str:
        def fn() -> str:
            pagina = self._garantir()
            if tecla.lower() == "enter":
                tem_senha = pagina.evaluate("!!document.querySelector('input[type=password]')")
                motivo = "pode enviar um formulário de login" if tem_senha else ""
                exigir_confirmacao("Enter", confirmado, motivo)
            pagina.keyboard.press(tecla)
            return f"Tecla {tecla} enviada. Agora: {self._resumo(pagina)}"

        return self._executar("tecla", fn)

    def print(self) -> str:
        def fn() -> str:
            pagina = self._garantir()
            pasta = self._cfg.pasta_dados / "prints"
            pasta.mkdir(parents=True, exist_ok=True)
            destino = pasta / f"pagina-{datetime.now():%Y%m%d-%H%M%S}.png"
            pagina.screenshot(path=str(destino))
            return str(destino)

        return self._executar("print", fn)

    def _ir(self, url: str) -> Page:
        if "://" not in url:
            url = "https://" + url
        pagina = self._garantir()
        pagina.goto(url, wait_until="domcontentloaded", timeout=45_000)
        try:  # sites de vaga montam a página depois (JavaScript)
            pagina.wait_for_load_state("networkidle", timeout=8_000)
        except ErroPlaywright:
            pass
        return pagina

    def texto_da_pagina(self, url: str) -> tuple[str, str, str]:
        """(título, url final, texto inteiro) sem devolver a lista de elementos."""

        def fn() -> tuple[str, str, str]:
            pagina = self._ir(url)
            texto = " ".join(pagina.inner_text("body").split())
            return pagina.title(), pagina.url, texto

        return self._rodar_dados("ler vaga", fn)

    def links_da_pagina(self, url: str) -> tuple[str, str, list[tuple[str, str]]]:
        """(título, url final, [(texto do link, endereço)])."""

        def fn() -> tuple[str, str, list[tuple[str, str]]]:
            pagina = self._ir(url)
            js = (
                "() => Array.from(document.querySelectorAll('a[href]'))"
                ".map(a => [(a.innerText || a.getAttribute('aria-label') || '').trim(), a.href])"
            )
            brutos = pagina.evaluate(js)
            if len(brutos) < 20 or not pagina.title():  # ainda montando: espera e lê de novo
                pagina.wait_for_timeout(4_000)
                brutos = pagina.evaluate(js)
            return pagina.title(), pagina.url, [(str(t), str(h)) for t, h in brutos]

        return self._rodar_dados("buscar vagas", fn)

    def _rodar_dados(self, acao: str, fn: Callable[[], T]) -> T:
        """Como _executar, mas para funções que devolvem dados em vez de texto."""
        verificar()
        try:
            return self._thread.rodar(fn)
        except ErroPlaywright as exc:
            raise ErroExecucao(f"navegador ({acao}): {str(exc).splitlines()[0]}") from exc

    def tocar(self, busca: str) -> str:
        """Busca no YouTube e abre o primeiro vídeo real do resultado (pula anúncios)."""

        def fn() -> str:
            pagina = self._garantir()
            url = "https://www.youtube.com/results?search_query=" + quote(busca)
            pagina.goto(url, wait_until="domcontentloaded", timeout=45_000)
            try:
                pagina.wait_for_selector("ytd-video-renderer a#video-title", timeout=10_000)
            except ErroPlaywright:
                pass
            item = pagina.evaluate(JS_PRIMEIRO_VIDEO)
            if not item:
                return f"Não achei nenhum vídeo para '{busca}' no YouTube."
            pagina.goto(item["href"], wait_until="domcontentloaded", timeout=45_000)
            return f"Tocando no YouTube: {item['titulo']}"

        return self._executar("tocar", fn)

    def fechar(self) -> str:
        def fn() -> str:
            if self._contexto is not None:
                self._contexto.close()
            self._esquecer()
            return "Navegador fechado."

        return self._executar("fechar", fn)


_instancia: Navegador | None = None


def navegador(cfg: Config) -> Navegador:
    """O navegador do processo (criado na primeira vez que for usado)."""
    global _instancia
    if _instancia is None:
        _instancia = Navegador(cfg)
    return _instancia


GIT_PALAVRAS = ("git", "github", "gitlab", "repositorio", "repositório")


BUSCA = "https://duckduckgo.com/?q="

# Processos curtos (o atalho de voz Ctrl+Alt+F) ligam isto: o Chrome do Playwright morre
# junto com o processo, então a janela abria e fechava na hora. Nesses casos o site abre
# no navegador normal do usuário, que continua aberto depois que o atalho termina.
NAVEGADOR_PROPRIO = False


def abrir_no_navegador_proprio(endereco: str) -> str:
    """Abre o endereço no navegador padrão do sistema, solto do processo do agente."""
    if "://" not in endereco:
        endereco = f"https://{endereco}"
    subprocess.Popen(
        ["xdg-open", endereco],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return f"Aberto no seu navegador: {endereco}"


def site_conhecido(cfg: Config, alvo: str) -> str | None:
    """Endereço do site conhecido citado no pedido ("o YouTube e deixe aberto" -> YouTube)."""
    chave = alvo.strip().lower()
    if chave in cfg.sites_liberados:
        return cfg.sites_liberados[chave]
    # Nomes mais longos primeiro: "chat gpt" ganha de "gpt", "google gemini" de "google".
    for nome in sorted(cfg.sites_liberados, key=len, reverse=True):
        if re.search(rf"(?<![\w.-]){re.escape(nome.lower())}(?![\w.-])", chave):
            return cfg.sites_liberados[nome]
    return None


def abrir_endereco(cfg: Config, alvo: str) -> str:
    """Abre o alvo no navegador: site conhecido, domínio direto ou uma busca.

    A busca vai para o DuckDuckGo: o Google não aceita buscas vindas de navegador
    automatizado e responde com a página de verificação (google.com/sorry).
    """
    endereco = site_conhecido(cfg, alvo)
    if endereco is None:
        tem_dominio = "." in alvo.strip() and " " not in alvo.strip()
        endereco = alvo if tem_dominio else f"{BUSCA}{quote(alvo)}"
    if NAVEGADOR_PROPRIO:
        return abrir_no_navegador_proprio(endereco)
    return navegador(cfg).abrir(endereco)


def resolver_abrir(cfg: Config, alvo: str) -> str:
    """Resolve o comando "abrir <alvo>": projeto no git, app liberado, arquivo local ou site.

    Nessa ordem: se o pedido citar git/github e um projeto conhecido pelo nome, abre o
    repositório remoto; senão tenta um app liberado no config.yaml; senão um arquivo ou
    pasta existente dentro das pastas permitidas (abre com o programa padrão do sistema);
    por fim, um site conhecido, um domínio direto ou uma busca no Google.
    """
    from agente import git_ops
    from agente.braco import janelas
    from agente.maestro import achar_projeto
    from agente.voz.conversa import normalizar

    if any(palavra in alvo.lower() for palavra in GIT_PALAVRAS):
        projeto = achar_projeto(cfg, normalizar(alvo))
        if projeto is None:
            raise ErroExecucao(f"não achei um projeto conhecido em '{alvo}'")
        return abrir_endereco(cfg, git_ops.remoto_web(cfg, projeto))
    try:
        return janelas.abrir_app(cfg, alvo)
    except ErroExecucao:
        pass
    caminho = Path(alvo).expanduser()
    if not caminho.is_absolute():
        for permitida in cfg.pastas_permitidas:
            candidata = permitida.expanduser() / alvo
            if candidata.exists():
                caminho = candidata
                break
    if caminho.exists():
        subprocess.Popen(["xdg-open", str(caminho)])
        return f"Abrindo {caminho}."
    return abrir_endereco(cfg, alvo)
