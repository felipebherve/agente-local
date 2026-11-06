"""Modo TDAH: todos os projetos num lugar só, com ficha, progresso e lembretes.

Liga em Configurações > Modo TDAH. Desligado, nada aqui roda.

- Cada subpasta das pastas liberadas é um projeto. A ficha dele é o STATUS.md da pasta.
- Do STATUS.md saem: resumo, prioridade, porcentagem, o que falta e a próxima ação.
- Projeto novo aparece sozinho e é marcado como "novo".
- Nome parecido com outro projeto gera aviso (para não criar um por cima do outro).
- Projeto parado há mais de `parado_horas`: o modelo local resume os últimos commits.
- Uma vez por semana: um resumo curto de todas as fichas, para colar no Claude.

Tudo roda no PC. O Claude só recebe o texto que você copiar.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import subprocess
import threading
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from agente.config import Config
from agente.textos_tdah import t

logger = logging.getLogger(__name__)

FICHA = "STATUS.md"
SEMANA_S = 7 * 24 * 3600
PARECIDO = 0.82
IGNORAR = {"node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
PRIORIDADES = {"alta": 0, "media": 1, "baixa": 2}
HORAS_MIN, HORAS_MAX = 0.5, 168.0
CACHE_S = 30.0  # o painel reaproveita a última varredura por este tempo
RESUMOS_POR_RODADA = 2  # o vigia resume no máximo isto por rodada (não ocupa a placa)
ATRASO_INICIAL_S = 300.0  # o vigia espera isto antes da primeira rodada

# Uma trava para todo ler-mudar-gravar do registro (painel atende pedidos em paralelo
# e o vigia roda em outra thread).
_TRAVA = threading.RLock()
_cache: dict[float, tuple[float, list[dict[str, Any]]]] = {}
_arquivo_trava_vigia: Any = None  # fica aberto enquanto este processo é o dono do vigia

MODELO_FICHA = """# {nome}

Prioridade: média
Concluído: 0%
Próxima ação: escrever a próxima ação aqui

## Resumo
{resumo}

## Onde fica
- Pasta: `{caminho}`
- GitHub: {github}

## Pronto
- 

## Falta
- 
"""


@dataclass(frozen=True)
class ModoTdah:
    """Bloco `modo_tdah` do config.yaml."""

    ligado: bool = False
    parado_horas: float = 2.0


def horas_validas(valor: Any) -> float:  # noqa: ANN401 - vem do JSON ou do YAML
    """Horas para considerar um projeto parado, entre 0,5 e 168. Erro se não for número."""
    if isinstance(valor, bool):
        raise ValueError("parado_horas precisa ser um número")
    try:
        horas = float(valor)
    except (TypeError, ValueError):
        raise ValueError(t("erro_horas")) from None
    if math.isnan(horas):
        raise ValueError("parado_horas precisa ser um número")
    return min(max(horas, HORAS_MIN), HORAS_MAX)


def ler_modo(bruto: Any) -> ModoTdah:  # noqa: ANN401 - YAML de qualquer formato
    bruto = bruto if isinstance(bruto, dict) else {}
    try:
        horas = horas_validas(bruto.get("parado_horas", 2.0))
    except ValueError:
        horas = 2.0
    return ModoTdah(ligado=bool(bruto.get("ligado", False)), parado_horas=horas)


def modo_atual(cfg: Config) -> ModoTdah:
    from agente import configuracoes as conf
    from agente.config import caminho_config

    try:
        return ler_modo(conf.ler_bloco(caminho_config(), "modo_tdah"))
    except OSError:
        return ModoTdah()


def salvar_modo(caminho: Path, ligado: bool, parado_horas: float = 2.0) -> None:
    from agente import configuracoes as conf

    horas = horas_validas(parado_horas)
    conf.trocar_bloco(caminho, "modo_tdah", {"ligado": bool(ligado), "parado_horas": horas})
    limpar_cache()


# --- nomes ---------------------------------------------------------------------------------


def normalizar(nome: str) -> str:
    """'Agente de IA' e 'agente-ia' ficam iguais: minúsculo, sem acento, sem símbolo."""
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    palavras = re.findall(r"[a-z0-9]+", sem_acento.lower())
    uteis = [p for p in palavras if p not in {"de", "da", "do", "e", "o", "a"}]
    return "".join(uteis or palavras)


def parecidos(nome: str, outros: list[str]) -> list[str]:
    """Nomes da lista que parecem o mesmo projeto que `nome`."""
    alvo = normalizar(nome)
    achados = []
    for outro in outros:
        o = normalizar(outro)
        if not alvo or not o or outro == nome:
            continue
        if alvo == o or (min(len(alvo), len(o)) >= 4 and (alvo in o or o in alvo)):
            achados.append(outro)
        elif SequenceMatcher(None, alvo, o).ratio() >= PARECIDO:
            achados.append(outro)
    return achados


# --- ficha (STATUS.md) ---------------------------------------------------------------------


def _secao(texto: str, titulos: tuple[str, ...]) -> list[str]:
    """Itens (linhas com '-') da seção cujo título começa com um dos `titulos`."""
    itens: list[str] = []
    dentro = False
    for linha in texto.splitlines():
        if linha.startswith("#"):
            t = normalizar(linha.lstrip("# "))
            dentro = any(t.startswith(normalizar(x)) for x in titulos)
            continue
        if dentro:
            item = linha.strip().lstrip("-*").strip()
            item = re.sub(r"^\[[ xX/]\]\s*", "", item)
            if item:
                itens.append(item)
    return itens[:8]


def _campo(texto: str, nomes: tuple[str, ...]) -> str:
    for linha in texto.splitlines():
        if ":" not in linha:
            continue
        chave, valor = linha.split(":", 1)
        if normalizar(chave.strip("-*# ")) in {normalizar(n) for n in nomes}:
            return valor.strip().strip("*").strip()
    return ""


def ler_ficha(texto: str) -> dict[str, Any]:
    """Tira do STATUS.md o que o cartão mostra. Campos que faltam ficam vazios."""
    pct_txt = _campo(texto, ("Concluído", "Concluido", "Progresso", "Porcentagem"))
    pct_m = re.search(r"(\d{1,3})\s*%", pct_txt) or re.search(
        r"(\d{1,3})\s*%\s*conclu", texto, re.I
    )
    if pct_m:
        pct: int | None = min(100, int(pct_m.group(1)))
    else:
        feitos = len(re.findall(r"^\s*[-*]\s*\[[xX]\]", texto, re.M))
        todos = len(re.findall(r"^\s*[-*]\s*\[[ xX/]\]", texto, re.M))
        if not todos:  # tabela de fases: | Fase | Concluída | ... | Pendente |
            feitos = len(re.findall(r"^\|.*\|\s*Conclu[ií]d[ao]", texto, re.M | re.I))
            todos = feitos + len(
                re.findall(r"^\|.*\|\s*(Pendente|Em andamento|A fazer)", texto, re.M | re.I)
            )
        pct = round(100 * feitos / todos) if todos else None
    prio = normalizar(_campo(texto, ("Prioridade",)))
    resumo = _secao(texto, ("Resumo",))
    if not resumo:
        resumo = [p for p in (x.strip() for x in texto.split("\n\n")) if _e_frase(p)][:1]
    return {
        "resumo": re.sub(r"\*\*|__|`", "", " ".join(" ".join(resumo).split()))[:400],
        "prioridade": prio if prio in PRIORIDADES else "",
        "porcentagem": pct,
        "proxima": _campo(texto, ("Próxima ação", "Proxima acao", "Próximo passo")),
        "pronto": _secao(texto, ("Pronto", "Feito", "Concluído")),
        "falta": _secao(texto, FALTA) or _caixas(texto, marcadas=False),
        "claude": _link_claude(texto),
    }


def _caixas(texto: str, marcadas: bool) -> list[str]:
    """Itens de lista com caixinha ([x] feitos, [ ] por fazer), em qualquer seção."""
    marca = r"[xX]" if marcadas else r" "
    return re.findall(rf"^\s*[-*]\s*\[{marca}\]\s*(.+?)\s*$", texto, re.M)[:8]


def _link_claude(texto: str) -> str:
    """Linha 'Claude: https://claude.ai/...' da ficha: o projeto ou conversa no Claude."""
    m = re.search(r"https://claude\.ai/\S+", _campo(texto, ("Claude", "Projeto no Claude")))
    return m.group(0).rstrip(").,") if m else ""


FALTA = ("Falta", "Pendente", "A fazer", "Próximos passos", "Next steps", "To do", "TODO")
LEIAME = ("README.pt-BR.md", "README.md", "readme.md", "LEIAME.md")


def _e_frase(paragrafo: str) -> bool:
    """Parágrafo que explica algo (não é título, lista, tabela, selo, link solto ou data)."""
    if not paragrafo or paragrafo[0] in "#-*|>!<[`🇺🇧🔗":
        return False
    return not re.match(r"(Atualizado|Updated|Última atualização)\b", paragrafo, re.I)


def ficha_do_leiame(pasta: Path) -> dict[str, Any]:
    """Sem STATUS.md: resumo e o que falta tirados do README (a porcentagem fica vazia)."""
    for nome in LEIAME:
        try:
            texto = (pasta / nome).read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        f = ler_ficha(texto)
        return {**ler_ficha(""), "resumo": f["resumo"], "falta": f["falta"]}
    return {**ler_ficha(""), "resumo": _o_que_tem(pasta)}


def _o_que_tem(pasta: Path) -> str:
    """Sem README nem ficha: o título do primeiro .md e o que há na pasta, para lembrar."""
    try:
        itens = sorted(p for p in pasta.iterdir() if not p.name.startswith("."))
    except OSError:
        return ""
    if not itens:
        return t("pasta_vazia")
    titulo = ""
    for md in (p for p in itens if p.suffix.lower() == ".md"):
        try:
            primeira = md.read_text(encoding="utf-8-sig", errors="replace").lstrip().splitlines()[0]
        except (OSError, IndexError):
            continue
        titulo = primeira.lstrip("# ").strip()
        break
    nomes = ", ".join(p.name + ("/" if p.is_dir() else "") for p in itens[:5])
    return t("sem_leiame", titulo=f"{titulo}. " if titulo else "", nomes=nomes)


# --- git -----------------------------------------------------------------------------------


def _git(pasta: Path, *args: str) -> str:
    try:
        r = subprocess.run(  # noqa: S603 - comando fixo, sem shell
            ["git", "-C", str(pasta), *args],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def link_github(pasta: Path) -> str:
    url = _git(pasta, "remote", "get-url", "origin")
    m = re.match(r"git@github\.com:(.+?)(\.git)?$", url)
    if m:
        return f"https://github.com/{m.group(1)}"
    return url.removesuffix(".git")


def ultima_mudanca(pasta: Path) -> float:
    """Hora da última mudança: último commit ou arquivo alterado no topo da pasta."""
    tempos = [pasta.stat().st_mtime]
    commit = _git(pasta, "log", "-1", "--format=%ct")
    if commit.isdigit():
        tempos.append(float(commit))
    try:
        for p in pasta.iterdir():
            if p.name not in IGNORAR and not p.name.startswith("."):
                tempos.append(p.stat().st_mtime)
    except OSError:
        pass
    return max(tempos)


# --- registro ------------------------------------------------------------------------------


def _arquivo(cfg: Config) -> Path:
    return cfg.pasta_dados / "projetos_tdah.json"


def ler_registro(cfg: Config) -> dict[str, Any]:
    """Lê o registro. Se o arquivo estiver estragado, guarda uma cópia antes de começar do zero."""
    arq = _arquivo(cfg)
    with _TRAVA:
        try:
            texto = arq.read_text(encoding="utf-8")
        except OSError:
            return {}
        try:
            dados = json.loads(texto)
        except json.JSONDecodeError:
            copia = arq.with_suffix(f".estragado-{int(time.time())}.json")
            logger.error("registro do Modo TDAH estragado; cópia em %s", copia)
            try:
                arq.replace(copia)
            except OSError:
                pass
            return {}
        return dados if isinstance(dados, dict) else {}


def salvar_registro(cfg: Config, dados: dict[str, Any]) -> None:
    """Grava num arquivo temporário e troca de uma vez: nunca fica meio escrito."""
    arq = _arquivo(cfg)
    with _TRAVA:
        arq.parent.mkdir(parents=True, exist_ok=True)
        tmp = arq.with_name(f"{arq.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, arq)


def limpar_cache() -> None:
    _cache.clear()


def _pastas(cfg: Config) -> list[Path]:
    achadas: list[Path] = []
    for raiz in cfg.pastas_permitidas:
        try:
            for p in sorted(raiz.iterdir()):
                if p.is_dir() and not p.name.startswith(".") and p.name not in IGNORAR:
                    achadas.append(p)
        except OSError:
            continue
    return achadas


def escanear(
    cfg: Config, agora: float | None = None, parado_horas: float = 2.0
) -> list[dict[str, Any]]:
    """Lista os projetos com a ficha de cada um. Atualiza o registro (novos, vistos)."""
    with _TRAVA:
        saida = _escanear(cfg, agora or time.time(), parado_horas)
    _cache[parado_horas] = (time.monotonic(), saida)
    return saida


def escanear_rapido(cfg: Config, parado_horas: float = 2.0) -> list[dict[str, Any]]:
    """Igual a `escanear`, mas reaproveita a varredura dos últimos CACHE_S segundos."""
    guardado = _cache.get(parado_horas)
    if guardado and time.monotonic() - guardado[0] < CACHE_S:
        return guardado[1]
    return escanear(cfg, parado_horas=parado_horas)


def _escanear(cfg: Config, agora: float, parado_horas: float) -> list[dict[str, Any]]:
    reg = ler_registro(cfg)
    projetos_reg: dict[str, Any] = reg.setdefault("projetos", {})
    primeira_vez = not projetos_reg
    pastas = _pastas(cfg)
    nomes = [p.name for p in pastas]
    saida: list[dict[str, Any]] = []
    for pasta in pastas:
        chave = str(pasta)
        info = projetos_reg.setdefault(chave, {"visto_em": agora, "novo": not primeira_vez})
        ficha_arq = pasta / FICHA
        try:
            texto_ficha = ficha_arq.read_text(encoding="utf-8-sig", errors="replace")
            ficha = ler_ficha(texto_ficha)
            tem_ficha = True
            if not _secao(texto_ficha, ("Resumo",)):  # sem "## Resumo": o README explica melhor
                ficha["resumo"] = ficha_do_leiame(pasta)["resumo"] or ficha["resumo"]
        except OSError:
            ficha = ficha_do_leiame(pasta)
            tem_ficha = False
        mudou = ultima_mudanca(pasta)
        parado_h = (agora - mudou) / 3600
        saida.append(
            {
                "nome": pasta.name,
                "caminho": chave,
                "git": (pasta / ".git").exists(),
                "github": link_github(pasta) if (pasta / ".git").exists() else "",
                "tem_ficha": tem_ficha,
                **ficha,
                "alterado": datetime.fromtimestamp(mudou).strftime("%d/%m/%Y %H:%M"),
                "parado_horas": round(parado_h, 1),
                "parado": parado_h >= parado_horas,
                "novo": bool(info.get("novo")),
                "parecido_com": parecidos(pasta.name, nomes),
                "resumo_auto": str(info.get("resumo_auto", "")),
                "serve": str((info.get("explicacao") or {}).get("serve", ""))
                if isinstance(info.get("explicacao"), dict)
                else "",
                "resumo_auto_em": str(info.get("resumo_auto_em", "")),
            }
        )
    salvar_registro(cfg, reg)
    saida.sort(
        key=lambda p: (
            PRIORIDADES.get(p["prioridade"], 3),
            -(p["porcentagem"] or 0),
            p["parado_horas"],
        )
    )
    return saida


def marcar_visto(cfg: Config, caminho: str) -> None:
    with _TRAVA:
        reg = ler_registro(cfg)
        info = reg.setdefault("projetos", {}).get(caminho)
        if info is not None:
            info["novo"] = False
            salvar_registro(cfg, reg)
    limpar_cache()


# --- textos para o Claude ------------------------------------------------------------------


def checar_nome(cfg: Config, nome: str) -> str:
    """Antes de criar um projeto: diz se já existe um com nome parecido. Só lê, não grava."""
    nome = nome.strip()
    if not nome:
        return t("nome_vazio")
    pastas = {p.name: p for p in _pastas(cfg)}
    achados = parecidos(nome, list(pastas))
    if nome in pastas:
        achados.insert(0, nome)
    if not achados:
        return t("nome_livre", nome=nome)
    linhas = [t("nome_parecido", nome=nome)]
    for n in achados[:5]:
        pasta = pastas[n]
        try:
            ficha = ler_ficha((pasta / FICHA).read_text(encoding="utf-8-sig", errors="replace"))
        except OSError:
            ficha = ler_ficha("")
        extra = f", {ficha['porcentagem']}% pronto" if ficha.get("porcentagem") is not None else ""
        resumo = f": {ficha['resumo'][:120]}" if ficha.get("resumo") else ""
        linhas.append(f"- {n} ({pasta}{extra}){resumo}")
    return "\n".join(linhas)


def contexto(p: dict[str, Any]) -> str:
    """Texto curto para colar no Claude ao retomar um projeto."""
    linhas = [t("ctx_projeto", v=p["nome"]), t("ctx_pasta", v=p["caminho"])]
    if p.get("github"):
        linhas.append(t("ctx_github", v=p["github"]))
    if p.get("porcentagem") is not None:
        linhas.append(t("ctx_concluido", v=p["porcentagem"]))
    if p.get("resumo"):
        linhas.append(t("ctx_resumo", v=p["resumo"]))
    if p.get("resumo_auto"):
        linhas.append(t("ctx_mudancas", v=p["resumo_auto"]))
    if p.get("falta"):
        linhas.append(t("ctx_falta", v="; ".join(p["falta"][:5])))
    if p.get("proxima"):
        linhas.append(t("ctx_proxima", v=p["proxima"]))
    return "\n".join(linhas)


def resumo_semanal(projetos: list[dict[str, Any]]) -> str:
    """Todas as fichas em poucas linhas, para o Claude sugerir prioridades."""
    linhas = [t("semanal_titulo")]
    for p in projetos:
        pct = f"{p['porcentagem']}%" if p.get("porcentagem") is not None else "?%"
        prio = p.get("prioridade") or t("sem_prioridade")
        prox = p.get("proxima") or (p.get("falta") or [t("sem_proxima")])[0]
        linhas.append(
            f"- {p['nome']} | {pct} | {prio} | {t('parado', h=p['parado_horas'])} | {prox}"[:220]
        )
    return "\n".join(linhas)


# --- modelo local --------------------------------------------------------------------------


def _modelo(
    cfg: Config, pergunta: str, modelo: str = "", sistema: str = "", pensar: bool = False
) -> str:
    """Pergunta ao modelo local. pensar=True: raciocina antes (mais lento, responde melhor)."""
    from agente.llm import ClienteOllama, ErroOllama

    if pensar:
        cliente = ClienteOllama(cfg.ollama_url, max(cfg.timeout_s, 180), cfg.keep_alive, True, 4096)
    else:
        cliente = ClienteOllama.de_config(cfg)
    try:
        r = cliente.conversar(
            modelo or cfg.modelos.codigo,
            pergunta,
            sistema=sistema or "Responda em português do Brasil, curto e simples.",
        )
    except ErroOllama as exc:
        logger.warning("modelo local falhou: %s", exc)
        return ""
    return r.texto


def resumir_commits(cfg: Config, caminho: str) -> str:
    """Resume os últimos commits com o modelo local e guarda no registro."""
    pasta = Path(caminho)
    log = _git(pasta, "log", "-15", "--format=%ad %s", "--date=short")
    if not log:
        return ""
    texto = _modelo(
        cfg,
        "Em UMA frase curta (até 25 palavras), sem introdução, diga o que mudou por "
        f"último neste projeto. Fale do que a pessoa ganhou, não de arquivos:\n{log}",
    )
    if texto:
        with _TRAVA:
            reg = ler_registro(cfg)
            info = reg.setdefault("projetos", {}).setdefault(caminho, {})
            info["resumo_auto"] = texto[:600]
            info["resumo_auto_em"] = datetime.now().strftime("%d/%m/%Y %H:%M")
            info["resumo_auto_ts"] = time.time()
            salvar_registro(cfg, reg)
        limpar_cache()
    return texto


def criar_ficha(cfg: Config, caminho: str) -> Path:
    """Cria o STATUS.md (rascunho feito pelo modelo local). Nunca sobrescreve um que exista."""
    pasta = Path(caminho)
    if not any(pasta.resolve().is_relative_to(r.resolve()) for r in cfg.pastas_permitidas):
        raise ValueError(t("erro_fora"))
    arq = pasta / FICHA
    if arq.exists():
        raise ValueError(t("erro_ja_tem_ficha"))
    base = ""
    for nome in ("README.md", "README.pt-BR.md", "readme.md"):
        try:
            base = (pasta / nome).read_text(encoding="utf-8-sig", errors="replace")[:3000]
            break
        except OSError:
            continue
    log = _git(pasta, "log", "-10", "--format=%s")
    resumo = ""
    if base or log:
        resumo = _modelo(
            cfg,
            f"Em até 3 linhas curtas, diga o que é este projeto.\nREADME:\n{base}\nCommits:\n{log}",
        )
    arq.write_text(
        MODELO_FICHA.format(
            nome=pasta.name,
            resumo=resumo or t("ficha_resumo_vazio"),
            caminho=pasta,
            github=link_github(pasta) or "(sem link)",
        ),
        encoding="utf-8",
    )
    limpar_cache()
    return arq


# --- vigia em segundo plano ----------------------------------------------------------------


def uma_rodada(cfg: Config, agora: float | None = None) -> None:
    """Resume projetos parados com mudança nova e faz o resumo da semana se venceu."""
    agora = agora or time.time()
    modo = modo_atual(cfg)
    if not modo.ligado:
        return
    projetos = escanear(cfg, agora, modo.parado_horas)
    reg = ler_registro(cfg)
    feitos = 0
    for p in projetos:
        if feitos >= RESUMOS_POR_RODADA:
            break  # o resto fica para a próxima rodada
        info = reg.get("projetos", {}).get(p["caminho"], {})
        ultimo = float(info.get("resumo_auto_ts", 0))
        mudou = agora - p["parado_horas"] * 3600
        if p["git"] and p["parado"] and mudou > ultimo:
            resumir_commits(cfg, p["caminho"])
            feitos += 1
    for p in projetos:  # quem ainda não tem "para que serve" ganha um, aos poucos
        if feitos >= RESUMOS_POR_RODADA:
            break
        if not p.get("serve"):
            detalhes(cfg, p["caminho"])
            feitos += 1
    with _TRAVA:
        reg = ler_registro(cfg)
        if agora - float(reg.get("semanal_ts", 0)) < SEMANA_S:
            return
        reg["semanal_ts"] = agora
        salvar_registro(cfg, reg)
    texto = resumo_semanal(escanear(cfg, agora, modo.parado_horas))
    (cfg.pasta_dados / "resumo_semanal.md").write_text(texto, encoding="utf-8")


def _pegar_trava_vigia(cfg: Config) -> bool:
    """Só um processo no PC roda o vigia (bandeja ou painel, quem abrir primeiro).

    A trava é do sistema operacional: se o processo morrer, ela some junto.
    """
    global _arquivo_trava_vigia
    if _arquivo_trava_vigia is not None:
        return True
    cfg.pasta_dados.mkdir(parents=True, exist_ok=True)
    arq = open(cfg.pasta_dados / "vigia_tdah.lock", "a+b")  # noqa: SIM115 - fica aberto de propósito
    try:
        if os.name == "nt":
            import msvcrt

            arq.seek(0)
            msvcrt.locking(arq.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined,unused-ignore]
        else:
            import fcntl

            fcntl.flock(arq.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        arq.close()
        return False
    _arquivo_trava_vigia = arq
    return True


def vigiar(
    cfg: Config, intervalo_s: float = 1800, atraso_s: float = ATRASO_INICIAL_S
) -> threading.Thread | None:
    """Roda `uma_rodada` de tempos em tempos numa thread que morre com o processo.

    Devolve None se outro processo (a bandeja ou outro painel) já é o dono do vigia.
    """
    if not _pegar_trava_vigia(cfg):
        logger.info("vigia do Modo TDAH já roda em outro processo")
        return None

    def laco() -> None:
        time.sleep(atraso_s)  # não disputa a placa com o que está abrindo agora
        while True:
            try:
                uma_rodada(cfg)
            except Exception:  # noqa: BLE001 - o vigia nunca pode derrubar o painel
                logger.exception("vigia do modo TDAH falhou")
            time.sleep(intervalo_s)

    t = threading.Thread(target=laco, name="vigia-tdah", daemon=True)
    t.start()
    return t


# --- mais informações ------------------------------------------------------------------------

PULAR = IGNORAR | {".git", ".idea", ".vscode", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def _tamanho(n: float) -> str:
    for unidade in ("B", "KB", "MB", "GB"):
        if n < 1024 or unidade == "GB":
            return f"{n:.0f} {unidade}" if unidade == "B" else f"{n:.1f} {unidade}"
        n /= 1024
    return ""


def _contar(pasta: Path, limite: int = 5000) -> tuple[int, int, dict[str, int]]:
    """Arquivos, bytes e extensões dentro de `pasta` (para no `limite` de arquivos)."""
    arquivos = tamanho = 0
    tipos: dict[str, int] = {}
    pilha = [pasta]
    while pilha and arquivos < limite:
        atual = pilha.pop()
        try:
            itens = list(atual.iterdir())
        except OSError:
            continue
        for item in itens:
            if item.name in PULAR or item.name.startswith("."):
                continue
            try:
                if item.is_symlink():
                    continue
                if item.is_dir():
                    pilha.append(item)
                else:
                    arquivos += 1
                    tamanho += item.stat().st_size
                    ext = item.suffix.lower() or "(sem extensão)"
                    tipos[ext] = tipos.get(ext, 0) + 1
            except OSError:
                continue
    return arquivos, tamanho, tipos


def mapa_pasta(pasta: Path) -> dict[str, Any]:
    """O que tem na pasta: cada item do topo com tamanho, e os tipos de arquivo mais comuns."""
    itens: list[dict[str, Any]] = []
    total_arq = total_bytes = 0
    tipos: dict[str, int] = {}
    try:
        topo = sorted(pasta.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    except OSError:
        topo = []
    for item in topo:
        if item.name in PULAR or item.name.startswith("."):
            continue
        if item.is_dir():
            n, b, t_ = _contar(item)
            for k, v in t_.items():
                tipos[k] = tipos.get(k, 0) + v
            itens.append(
                {"nome": item.name + "/", "pasta": True, "arquivos": n, "tamanho": _tamanho(b)}
            )
        else:
            try:
                n, b = 1, item.stat().st_size
            except OSError:
                continue
            ext = item.suffix.lower() or "(sem extensão)"
            tipos[ext] = tipos.get(ext, 0) + 1
            itens.append({"nome": item.name, "pasta": False, "arquivos": 1, "tamanho": _tamanho(b)})
        total_arq += n
        total_bytes += b
    comuns = sorted(tipos.items(), key=lambda kv: -kv[1])[:8]
    return {
        "itens": itens[:40],
        "mais_itens": max(0, len(itens) - 40),
        "arquivos": total_arq,
        "tamanho": _tamanho(total_bytes),
        "tipos": [{"tipo": k, "quantos": v} for k, v in comuns],
    }


def info_git(pasta: Path) -> dict[str, Any]:
    if not (pasta / ".git").exists():
        return {}
    commits = _git(pasta, "log", "-6", "--format=%ad|%s", "--date=format:%d/%m/%Y")
    return {
        "branch": _git(pasta, "branch", "--show-current"),
        "total": _git(pasta, "rev-list", "--count", "HEAD"),
        "primeiro": _git(
            pasta, "log", "--reverse", "--format=%ad", "--date=format:%d/%m/%Y"
        ).splitlines()[:1],
        "ultimos": [
            dict(zip(("data", "msg"), c.split("|", 1), strict=False)) for c in commits.splitlines()
        ],
        "pendentes": len(_git(pasta, "status", "--porcelain").splitlines()),
        "github": link_github(pasta),
    }


def _leiame(pasta: Path) -> str:
    """O README; sem ele, o primeiro .md do topo da pasta (ex.: requisitos.md)."""
    try:
        outros = sorted(p.name for p in pasta.iterdir() if p.suffix.lower() == ".md")
    except OSError:
        outros = []
    for nome in (*LEIAME, *outros):
        try:
            return (pasta / nome).read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
    return ""


VERSAO_EXPLICA = "2"  # mude para refazer todas as explicações guardadas


def _assinatura(pasta: Path) -> str:
    """Muda quando o projeto muda de verdade (README, ficha, último commit ou itens do topo)."""
    partes = [VERSAO_EXPLICA, _git(pasta, "rev-parse", "HEAD")]
    for nome in (*LEIAME, FICHA):
        try:
            partes.append(str((pasta / nome).stat().st_mtime))
        except OSError:
            continue
    try:
        partes.append(",".join(sorted(p.name for p in pasta.iterdir())))
    except OSError:
        pass
    return hashlib.sha1("|".join(partes).encode()).hexdigest()[:16]  # noqa: S324 - não é senha


SISTEMA_EXPLICA = (
    "Você ajuda uma pessoa com TDAH a lembrar do que é cada pasta de projetos do PC dela. "
    "Escreva em português do Brasil como um amigo explicando, de um jeito natural e atual: "
    "frases curtas, palavras do dia a dia, sem jargão, sem markdown, sem enrolação e sem "
    "frases genéricas como 'projeto para desenvolvimento de soluções'. Diga coisas concretas "
    "(o que faz, para quem, com o quê). Não invente: use só o que está nos arquivos. Se a pasta "
    "for cópia de um projeto de outra pessoa (driver, biblioteca, repositório baixado), diga isso."
)

EXEMPLO_EXPLICA = (
    "Exemplo de resposta boa (para outra pasta):\n"
    "SERVE: Site da loja de bolos da Ana, com cardápio e pedidos pelo WhatsApp.\n"
    "EXPLICA: É um site simples em HTML e JavaScript. Mostra os bolos com foto e preço e monta "
    "a mensagem do pedido. Fica publicado no GitHub Pages.\n"
    "ESTADO: Já funciona; falta a página de encomendas para festas (está no README)."
)


def _amostra_arquivos(pasta: Path, limite: int = 40) -> list[str]:
    """Caminhos de até `limite` arquivos, dois níveis abaixo, para o modelo ter uma ideia."""
    saida: list[str] = []
    for item in sorted(pasta.iterdir()) if pasta.is_dir() else []:
        if item.name in PULAR or item.name.startswith("."):
            continue
        if item.is_dir():
            try:
                filhos = sorted(x.name for x in item.iterdir() if not x.name.startswith("."))
            except OSError:
                filhos = []
            saida.append(f"{item.name}/ ({len(filhos)} itens: {', '.join(filhos[:8])})")
        else:
            saida.append(item.name)
        if len(saida) >= limite:
            break
    return saida


def _textos_da_pasta(pasta: Path) -> str:
    """README e STATUS.md da pasta; se só houver uma subpasta, o README dela também."""
    partes = []
    leiame = _leiame(pasta)
    if leiame:
        partes.append(f"README:\n{leiame[:2500]}")
    try:
        partes.append(f"STATUS.md:\n{(pasta / FICHA).read_text(encoding='utf-8-sig')[:1200]}")
    except OSError:
        pass
    try:
        subpastas = [
            p
            for p in pasta.iterdir()
            if p.is_dir() and p.name not in PULAR and not p.name.startswith(".")
        ]
    except OSError:
        subpastas = []
    if not leiame and len(subpastas) == 1:
        dentro = _leiame(subpastas[0])
        if dentro:
            partes.append(f"README de {subpastas[0].name}/:\n{dentro[:2500]}")
    return "\n\n".join(partes) or "(sem README nem STATUS.md)"


def explicar(cfg: Config, pasta: Path, mapa: dict[str, Any], git: dict[str, Any]) -> dict[str, str]:
    """Pede ao modelo local: para que serve (1 frase) e uma explicação um pouco maior."""
    commits = "; ".join(f"{c.get('data', '')} {c.get('msg', '')}" for c in git.get("ultimos", []))
    tipos = ", ".join(f"{x['tipo']} ({x['quantos']})" for x in mapa["tipos"])
    pergunta = (
        f"Pasta: {pasta.name}\n"
        f"Arquivos: {'; '.join(_amostra_arquivos(pasta))}\n"
        f"Tipos mais comuns: {tipos}\n"
        f"Últimos commits: {commits or 'sem Git'}\n\n"
        f"{_textos_da_pasta(pasta)}\n\n"
        f"{EXEMPLO_EXPLICA}\n\n"
        "Agora responda sobre a pasta acima, exatamente em 3 linhas com estes rótulos:\n"
        "SERVE: para que serve, em UMA frase concreta de até 20 palavras.\n"
        "EXPLICA: o que é e como funciona, em 2 ou 3 frases curtas.\n"
        "ESTADO: em que pé está e o próximo passo, em UMA frase (se não der para saber, diga isso)."
    )
    texto = _modelo(cfg, pergunta, cfg.modelos.cerebro, SISTEMA_EXPLICA, pensar=True)
    texto = re.sub(r"<think>.*?</think>", "", texto, flags=re.S)
    saida = {"serve": "", "explica": "", "estado": ""}
    for rotulo, chave in (("SERVE", "serve"), ("EXPLICA", "explica"), ("ESTADO", "estado")):
        m = re.search(
            rf"{rotulo}\s*:\s*(.+?)(?=\n\s*(SERVE|EXPLICA|ESTADO)\s*:|\Z)", texto, re.S | re.I
        )
        if m:
            saida[chave] = re.sub(r"\*\*|`", "", " ".join(m.group(1).split()))[:500]
    return saida


def detalhes(cfg: Config, caminho: str, refazer: bool = False) -> dict[str, Any]:
    """Tudo sobre um projeto para o botão "Mais informações". A explicação fica guardada e
    só é refeita quando o projeto muda (ou se pedir `refazer`)."""
    pasta = Path(caminho)
    if not any(pasta.resolve().is_relative_to(r.resolve()) for r in cfg.pastas_permitidas):
        raise ValueError(t("erro_fora"))
    mapa = mapa_pasta(pasta)
    git = info_git(pasta)
    assinatura = _assinatura(pasta)
    info = ler_registro(cfg).get("projetos", {}).get(caminho, {})
    expl = info.get("explicacao") if isinstance(info.get("explicacao"), dict) else None
    if refazer or not expl or info.get("explicacao_assinatura") != assinatura:
        novo = explicar(cfg, pasta, mapa, git)
        if novo["serve"]:
            expl = novo
            with _TRAVA:
                reg = ler_registro(cfg)
                guardado = reg.setdefault("projetos", {}).setdefault(caminho, {})
                guardado["explicacao"] = expl
                guardado["explicacao_assinatura"] = assinatura
                salvar_registro(cfg, reg)
            limpar_cache()
    leiame = _leiame(pasta)
    return {
        "nome": pasta.name,
        "caminho": caminho,
        "explicacao": expl or {"serve": "", "explica": "", "estado": ""},
        "mapa": mapa,
        "git": git,
        "leiame": leiame[:3000],
        "tem_leiame": bool(leiame),
    }
