"""Painel do agente: uma página no navegador que mostra e controla tudo num lugar só.

- Estado: placa de vídeo, memória e processador; Ollama e OmniRoute no ar; agentes
  ligados e quem está trabalhando agora.
- Conversa: o pedido passa pelo Maestro, igual ao Claude e à voz, e a resposta volta com
  a rota (comando direto, Ollama local, OmniRoute ou "precisa do Claude").
- Microfone: o mesmo liga/desliga do atalho Ctrl+Alt+F.
- Histórico, economia de tokens e projetos.

Só biblioteca padrão (http.server), igual ao resto do agente, e só escuta em 127.0.0.1.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import urllib.error
import urllib.request
import webbrowser
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from agente import atividade, economia, historico
from agente.config import Config, carregar_config

logger = logging.getLogger(__name__)

PORTA_PADRAO = 8899
PASTA_WEB = Path(__file__).resolve().parent / "web_painel"
TIMEOUT_SONDA_S = 1.5

# Agentes que dá pra ligar e desligar no painel e o arquivo de pausa de cada um
# (o mesmo que a bandeja e o Maestro já usam).
AGENTES: list[dict[str, str]] = [
    {
        "nome": "Maestro",
        "descricao": "Recebe cada pedido e escolhe quem resolve.",
        "pausa": "maestro-pausado",
    },
    {
        "nome": "Porteiro",
        "descricao": "Resolve o simples no PC ou na IA grátis; o resto vai ao Claude.",
        "pausa": "porteiro-pausado",
    },
    {
        "nome": "Memória",
        "descricao": "Indexa os projetos e entrega só os trechos que importam.",
        "pausa": "memoria-pausada",
    },
    {
        "nome": "Revisor",
        "descricao": "Lint, tipos e testes; trava commit com senha ou conflito.",
        "pausa": "revisor-pausado",
    },
    {
        "nome": "Braço",
        "descricao": "Navegador e tela. Pede confirmação antes de enviar ou pagar.",
        "pausa": "",  # usa a parada de emergência do Braço
    },
]


# --- uso do OmniRoute pelo painel ----------------------------------------------------------


def _arquivo_uso(cfg: Config) -> Path:
    return cfg.pasta_dados / "painel_uso.json"


def ler_uso(cfg: Config) -> dict[str, int]:
    """Tokens somados por provedor desde sempre (só o que passou por este painel)."""
    try:
        return dict(json.loads(_arquivo_uso(cfg).read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return {}


def registrar_uso(cfg: Config, provedor: str, tokens: int) -> None:
    if not provedor or tokens <= 0:
        return
    uso = ler_uso(cfg)
    uso[provedor] = uso.get(provedor, 0) + tokens
    try:
        cfg.pasta_dados.mkdir(parents=True, exist_ok=True)
        _arquivo_uso(cfg).write_text(json.dumps(uso), encoding="utf-8")
    except OSError as exc:
        logger.warning("não consegui gravar o uso do painel: %s", exc)


def provedores_configurados(cfg: Config) -> list[str]:
    """Provedores na fila do OmniRoute (cfg.omniroute.modelos), sem repetir, na ordem."""
    vistos: list[str] = []
    for modelo in cfg.omniroute.modelos:
        provedor = modelo.split("/", 1)[0]
        if provedor not in vistos:
            vistos.append(provedor)
    return vistos


# --- estado ---------------------------------------------------------------------------------


def _get_json(url: str) -> Any:  # noqa: ANN401 - JSON de qualquer formato
    with urllib.request.urlopen(url, timeout=TIMEOUT_SONDA_S) as r:  # noqa: S310 - só localhost
        return json.loads(r.read().decode("utf-8"))


def servicos(cfg: Config) -> dict[str, Any]:
    """Ollama e OmniRoute no ar, e quais modelos estão carregados na placa agora."""
    ollama, carregados = False, []
    try:
        dados = _get_json(f"{cfg.ollama_url}/api/ps")
        ollama = True
        carregados = [m.get("name", "") for m in dados.get("models", [])]
    except (OSError, ValueError):
        pass
    omniroute = False
    if cfg.omniroute.ligado:
        try:
            _get_json(f"{cfg.omniroute.url.rstrip('/')}/models")
            omniroute = True
        except urllib.error.HTTPError:  # respondeu (ex.: 401 sem chave): está no ar
            omniroute = True
        except (OSError, ValueError):
            pass
    return {
        "ollama": ollama,
        "modelos_carregados": carregados,
        "omniroute": omniroute,
        "omniroute_configurado": cfg.omniroute.ligado,
    }


def _pausa_braco() -> Path:
    from agente.braco import seguranca

    return seguranca.SINAL_PARADA


def agente_ligado(cfg: Config, nome: str) -> bool:
    for a in AGENTES:
        if a["nome"] == nome:
            arquivo = cfg.pasta_dados / a["pausa"] if a["pausa"] else _pausa_braco()
            return not arquivo.exists()
    raise KeyError(nome)


def alternar_agente(cfg: Config, nome: str, ligar: bool) -> None:
    for a in AGENTES:
        if a["nome"] == nome:
            arquivo = cfg.pasta_dados / a["pausa"] if a["pausa"] else _pausa_braco()
            if ligar:
                arquivo.unlink(missing_ok=True)
            else:
                arquivo.parent.mkdir(parents=True, exist_ok=True)
                arquivo.write_text("pausado", encoding="utf-8")
            return
    raise KeyError(nome)


def estado_agentes(cfg: Config) -> list[dict[str, Any]]:
    trabalhando = atividade.ativos(cfg.pasta_dados)
    return [
        {
            "nome": a["nome"],
            "descricao": a["descricao"],
            "ligado": agente_ligado(cfg, a["nome"]),
            "trabalhando": a["nome"] in trabalhando,
        }
        for a in AGENTES
    ]


def recursos_agora() -> dict[str, float]:
    from agente import recursos

    u = recursos.medir()
    return {
        "vram_usada_gb": round(u.vram_usada_gb, 1),
        "vram_total_gb": round(u.vram_total_gb, 1),
        "ram_usada_gb": round(u.ram_usada_gb, 1),
        "ram_total_gb": round(u.ram_total_gb, 1),
        "cpu_pct": round(u.cpu_pct),
    }


# --- economia e projetos --------------------------------------------------------------------


def resumo_economia(cfg: Config, hoje: datetime | None = None) -> dict[str, Any]:
    """Total, últimos 30 dias (um valor por dia) e por tipo de tarefa."""
    hoje = hoje or datetime.now()
    por_dia: dict[str, int] = defaultdict(int)
    por_tipo: Counter[str] = Counter()
    try:
        linhas = (cfg.pasta_logs / "economia.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        linhas = []
    for bruto in linhas:
        try:
            item = json.loads(bruto)
            tokens = int(item["tokens_poupados"])
            por_dia[str(item["quando"])[:10]] += tokens
            por_tipo[str(item.get("tarefa", "outros"))] += tokens
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    dias = [(hoje - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(29, -1, -1)]
    return {
        "total": economia.total(cfg),
        "dias": [{"dia": d, "tokens": por_dia.get(d, 0)} for d in dias],
        "por_tipo": [{"tipo": t, "tokens": n} for t, n in por_tipo.most_common(8)],
    }


def listar_projetos(cfg: Config) -> list[dict[str, str]]:
    """Pastas dentro das pastas liberadas (cada uma é um projeto), mais recentes primeiro."""
    achados: list[tuple[float, Path]] = []
    for raiz in cfg.pastas_permitidas:
        try:
            for p in raiz.iterdir():
                if p.is_dir() and not p.name.startswith("."):
                    achados.append((p.stat().st_mtime, p))
        except OSError:
            continue
    achados.sort(reverse=True)
    return [
        {
            "nome": p.name,
            "caminho": str(p),
            "git": "sim" if (p / ".git").exists() else "não",
            "alterado": datetime.fromtimestamp(t).strftime("%d/%m/%Y"),
        }
        for t, p in achados[:40]
    ]


# --- voz ------------------------------------------------------------------------------------


def voz_gravando() -> bool:
    try:
        from agente.voz import atalho_voz
    except ImportError:  # voz não instalada (extra opcional)
        return False
    return atalho_voz.gravando_agora() is not None


def alternar_voz() -> bool:
    """Mesmo efeito do Ctrl+Alt+F. Devolve True se começou a gravar, False se mandou parar."""
    from agente.voz import atalho_voz

    pid = atalho_voz.gravando_agora()
    if pid is not None:
        atalho_voz.pedir_para_parar(pid)
        return False
    subprocess.Popen(  # noqa: S603 - o próprio Python do agente
        [sys.executable, "-m", "agente.voz.atalho_voz"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return True


# --- servidor -------------------------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    cfg: Config

    def log_message(self, formato: str, *args: object) -> None:
        logger.debug("painel_web: " + formato, *args)

    def _enviar_json(self, corpo: Any, codigo: int = 200) -> None:  # noqa: ANN401
        dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(dados)

    def _enviar_arquivo(self, caminho: Path, tipo: str) -> None:
        dados = caminho.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def _ler_corpo(self) -> dict[str, Any]:
        tamanho = int(self.headers.get("Content-Length", "0"))
        corpo = json.loads(self.rfile.read(tamanho).decode("utf-8") or "{}")
        if not isinstance(corpo, dict):
            raise ValueError("corpo não é um objeto")
        return corpo

    def do_GET(self) -> None:  # noqa: N802 - nome exigido pelo http.server
        cfg = self.cfg
        if self.path in ("/", "/index.html"):
            self._enviar_arquivo(PASTA_WEB / "index.html", "text/html; charset=utf-8")
        elif self.path == "/api/estado":
            uso = ler_uso(cfg)
            self._enviar_json(
                {
                    "recursos": recursos_agora(),
                    "servicos": servicos(cfg),
                    "agentes": estado_agentes(cfg),
                    "voz_gravando": voz_gravando(),
                    "tokens_poupados": economia.total(cfg),
                    "omniroute_uso": [
                        {"nome": p, "tokens": uso.get(p, 0)} for p in provedores_configurados(cfg)
                    ],
                }
            )
        elif self.path == "/api/historico":
            registros = [
                {
                    "quando": r.quando,
                    "pedido": r.pedido,
                    "agente": r.agente,
                    "destino": r.destino,
                    "resposta": r.resposta_completa or r.resumo,
                    "segundos": r.segundos,
                    "tokens_poupados": r.tokens_poupados,
                }
                for r in historico.ler(cfg, limite=200)
            ]
            self._enviar_json({"registros": registros})
        elif self.path == "/api/economia":
            self._enviar_json(resumo_economia(cfg))
        elif self.path == "/api/projetos":
            self._enviar_json({"projetos": listar_projetos(cfg)})
        elif self.path == "/api/config":
            self._enviar_json(estado_config(cfg))
        else:
            self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        try:
            corpo = self._ler_corpo()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            self._enviar_json({"erro": "pedido inválido"}, 400)
            return
        if self.path == "/api/perguntar":
            mensagem = str(corpo.get("mensagem", "")).strip()
            if not mensagem:
                self._enviar_json({"erro": "mensagem vazia"}, 400)
                return
            from agente import maestro
            from agente.llm import ClienteOllama

            r = maestro.perguntar(
                self.cfg,
                ClienteOllama.de_config(self.cfg),
                mensagem,
                encaminhar=lambda _p: "Isso precisa do Claude: peça no Claude Code.",
            )
            self._enviar_json({"agente": r.agente, "destino": r.destino, "resposta": r.resposta})
        elif self.path == "/api/agente":
            try:
                alternar_agente(self.cfg, str(corpo["nome"]), bool(corpo["ligado"]))
            except KeyError:
                self._enviar_json({"erro": "agente desconhecido"}, 400)
                return
            self._enviar_json({"agentes": estado_agentes(self.cfg)})
        elif self.path == "/api/voz":
            self._enviar_json({"gravando": alternar_voz()})
        elif self.path.startswith("/api/config/"):
            _config_post(self, self.path.removeprefix("/api/config/"), corpo)
        else:
            self.send_error(404)


def _recarregar(handler: type[_Handler]) -> Config:
    """Lê o config.yaml de novo depois de uma mudança feita pelo painel."""
    handler.cfg = carregar_config()
    return handler.cfg


def _config_post(self: _Handler, acao: str, corpo: dict[str, Any]) -> None:
    from agente import configuracoes as conf
    from agente.config import caminho_config

    try:
        if acao == "entrar":
            ok = conf.entrar(str(corpo.get("servico", "")))
            aviso = "" if ok else "Não achei um terminal para abrir."
            self._enviar_json({"ok": ok, "aviso": aviso})
        elif acao == "registrar-claude":
            self._enviar_json({"ok": True, "linhas": conf.registrar_no_claude()})
        elif acao == "omniroute":
            modelos = corpo.get("modelos") or []
            if not isinstance(modelos, list):
                raise ValueError("modelos precisa ser uma lista")
            lista = [str(m) for m in modelos]
            conf.salvar_omniroute(caminho_config(), bool(corpo.get("ligado")), lista)
            _recarregar(type(self))
            self._enviar_json(estado_config(self.cfg))
        elif acao == "omniroute-testar":
            from agente import nuvem

            r = nuvem.perguntar(self.cfg, "Responda só com a palavra: ok", "Responda curto.")
            self._enviar_json({"ok": r is not None, "modelo": r.modelo if r else ""})
        elif acao == "pastas":
            pastas = corpo.get("pastas") or []
            if not isinstance(pastas, list):
                raise ValueError("pastas precisa ser uma lista")
            conf.salvar_pastas(caminho_config(), [str(p) for p in pastas])
            _recarregar(type(self))
            self._enviar_json(estado_config(self.cfg))
        elif acao == "escolher-pasta":
            self._enviar_json({"pasta": conf.escolher_pasta()})
        elif acao == "atalho":
            atalho = conf.aplicar_atalho(str(corpo.get("atalho", "")))
            self._enviar_json({"ok": True, "atalho": atalho})
        else:
            self.send_error(404)
    except (KeyError, ValueError, RuntimeError, OSError) as exc:
        self._enviar_json({"erro": str(exc)}, 400)



def estado_config(cfg: Config) -> dict[str, Any]:
    from agente import configuracoes as conf

    return {
        "claude": conf.status_claude(),
        "github": conf.status_github(),
        "omniroute": {
            "no_ar": _omniroute_no_ar(cfg),
            "ligado": cfg.omniroute.ligado,
            "modelos": list(cfg.omniroute.modelos),
            "painel": cfg.omniroute.url.rsplit("/v1", 1)[0],
        },
        "atalho": {**conf.atalho_atual(), "sugerido": conf.ATALHO_SUGERIDO},
        "pastas": [str(p) for p in cfg.pastas_permitidas],
    }


def _omniroute_no_ar(cfg: Config) -> bool:
    try:
        _get_json(f"{cfg.omniroute.url.rstrip('/')}/models")
        return True
    except urllib.error.HTTPError:
        return True
    except (OSError, ValueError):
        return False


def no_ar(porta: int = PORTA_PADRAO) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{porta}/api/projetos", timeout=1):  # noqa: S310
            return True
    except OSError:
        return False


def servir(cfg: Config | None = None, porta: int = PORTA_PADRAO, abrir: bool = True) -> None:
    """Sobe o painel e (opcional) já abre o navegador padrão. Bloqueia a thread atual."""
    cfg = cfg or carregar_config()
    handler = type("Handler", (_Handler,), {"cfg": cfg})
    servidor = ThreadingHTTPServer(("127.0.0.1", porta), handler)
    if abrir:
        webbrowser.open(f"http://127.0.0.1:{porta}")
    logger.info("painel web em http://127.0.0.1:%d", porta)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()


def abrir() -> None:
    """O que o atalho "Agente local" faz: sobe o painel (se não estiver no ar) e abre o
    navegador padrão nele. Funciona igual no Linux e no Windows."""
    if no_ar():
        webbrowser.open(f"http://127.0.0.1:{PORTA_PADRAO}")
        return
    servir(abrir=True)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    abrir()


if __name__ == "__main__":
    main()
