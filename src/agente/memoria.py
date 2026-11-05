"""Memória dos projetos (Fase 6): índice local com embeddings, para o Claude ler só o que importa.

- indexar: quebra os arquivos de texto do projeto em trechos e guarda o embedding de cada um
  num SQLite em dados/memoria.sqlite. Só reprocessa arquivos que mudaram.
- contexto: acha os trechos mais parecidos com a tarefa e devolve poucos, com arquivo e linhas.
- lembrar: guarda decisões e erros já resolvidos; eles voltam junto no contexto.

Tudo local: os embeddings vêm do nomic-embed-text no Ollama.
"""

from __future__ import annotations

import fnmatch
import hashlib
import logging
import os
import re
import sqlite3
import time
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from agente.config import Config
from agente.executor import ErroExecucao, validar_pasta

logger = logging.getLogger(__name__)

EXTENSOES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte", ".html", ".css",
    ".scss", ".java", ".kt", ".dart", ".go", ".rs", ".c", ".h", ".cpp", ".cs", ".php", ".rb",
    ".sh", ".ps1", ".bat", ".sql", ".md", ".txt", ".rst", ".json", ".yaml", ".yml", ".toml",
    ".ini", ".cfg", ".xml", ".gradle",
}  # fmt: skip
IGNORAR = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "dist", "build", ".next", ".dart_tool", "target",
    "coverage", ".idea", ".vscode", "dados", "logs", "site-packages",
}  # fmt: skip
IGNORAR_ARQUIVOS = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock"}
MAX_BYTES = 300_000  # arquivo maior que isso é gerado ou dado, não código
LINHAS_POR_TRECHO = 40
SOBREPOR = 8  # linhas repetidas entre trechos vizinhos, para não cortar uma função ao meio
MAX_CHARS_TRECHO = 1800
LOTE = 32
# O nomic-embed-text foi treinado com estes prefixos: documento e pergunta ficam comparáveis.
PREFIXO_DOC = "search_document: "
PREFIXO_BUSCA = "search_query: "
PESO_PALAVRAS = 0.15
COMUNS = {
    "como", "onde", "quando", "qual", "quais", "para", "pelo", "pela", "isso", "esse", "essa",
    "este", "esta", "mais", "menos", "muito", "fazer", "faz", "com", "sem", "que", "uma",
    "funciona", "codigo", "arquivo", "projeto", "with", "from", "this", "that", "the",
}  # fmt: skip


class Embutidor(Protocol):
    def embutir(self, modelo: str, textos: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class Trecho:
    caminho: str  # relativo ao projeto
    inicio: int  # linhas, começando em 1
    fim: int
    texto: str
    nota: float = 0.0

    def formatar(self) -> str:
        return f"### {self.caminho}:{self.inicio}-{self.fim}\n```\n{self.texto.rstrip()}\n```"


@dataclass(frozen=True)
class Lembranca:
    tipo: str
    texto: str
    quando: str
    nota: float = 0.0


@dataclass(frozen=True)
class ResultadoIndice:
    arquivos: int  # arquivos de texto vistos
    novos: int  # arquivos (re)indexados agora
    removidos: int
    trechos: int  # trechos novos
    segundos: float

    def texto(self) -> str:
        return (
            f"Índice atualizado em {self.segundos:.1f} s: {self.arquivos} arquivos, "
            f"{self.novos} (re)indexados, {self.removidos} removidos, {self.trechos} trechos novos."
        )


# --- banco ---------------------------------------------------------------------------------


def _banco(cfg: Config) -> sqlite3.Connection:
    cfg.pasta_dados.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(cfg.pasta_dados / "memoria.sqlite", timeout=30)
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS arquivos (
            projeto TEXT, caminho TEXT, mtime REAL, tamanho INTEGER,
            PRIMARY KEY (projeto, caminho));
        CREATE TABLE IF NOT EXISTS trechos (
            projeto TEXT, caminho TEXT, inicio INTEGER, fim INTEGER, texto TEXT, vetor BLOB);
        CREATE INDEX IF NOT EXISTS trechos_arquivo ON trechos (projeto, caminho);
        CREATE TABLE IF NOT EXISTS lembrancas (
            projeto TEXT, tipo TEXT, texto TEXT, vetor BLOB, quando TEXT);
        """
    )
    return con


def _vetor_bytes(vetor: list[float]) -> bytes:
    import numpy as np

    v = np.asarray(vetor, dtype="float32")
    norma = float(np.linalg.norm(v)) or 1.0
    return (v / norma).tobytes()


def _matriz(blobs: list[bytes]) -> Any:
    import numpy as np

    return np.vstack([np.frombuffer(b, dtype="float32") for b in blobs])


# --- arquivos e trechos --------------------------------------------------------------------


def _ignorado(nome: str, padroes: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(nome.lower(), p.lower()) for p in padroes)


def arquivos_do_projeto(raiz: Path, ignorar: tuple[str, ...] = ()) -> Iterator[Path]:
    """Arquivos de texto do projeto, pulando dependências, builds, backups e coisas grandes."""
    for pasta, subpastas, nomes in os.walk(raiz):
        subpastas[:] = sorted(
            s
            for s in subpastas
            if s not in IGNORAR and not s.startswith(".") and s != "~" and not _ignorado(s, ignorar)
        )
        for nome in sorted(nomes):
            caminho = Path(pasta) / nome
            if caminho.suffix.lower() not in EXTENSOES or nome in IGNORAR_ARQUIVOS:
                continue
            if _ignorado(nome, ignorar):
                continue
            if nome.endswith((".min.js", ".min.css", ".map")):
                continue
            try:
                if caminho.stat().st_size > MAX_BYTES:
                    continue
            except OSError:
                continue
            yield caminho


def _chave_arquivo(texto: str) -> str:
    """minúsculas, sem acento e sem espaço: compara nome de arquivo ignorando pontuação.

    Quem chama normalmente já normalizou o pedido (voz.conversa.normalizar), que tira o
    ponto da extensão ("relatorio.pdf" -> "relatorio pdf"); tirar o espaço aqui de novo
    junta os dois lados de volta.
    """
    from agente.voz.conversa import normalizar

    return normalizar(texto).replace(" ", "")


def buscar_arquivos(cfg: Config, nome: str, maximo: int = 15) -> list[Path]:
    """Procura, nas pastas permitidas, arquivos cujo nome contenha `nome` (sem distinguir caixa).

    Não lê o conteúdo nem respeita MAX_BYTES: é uma busca pelo nome, não pelo texto.
    """
    chave = _chave_arquivo(nome)
    achados: list[Path] = []
    for raiz in cfg.pastas_permitidas:
        raiz = raiz.expanduser()
        if not raiz.exists():
            continue
        for pasta, subpastas, nomes in os.walk(raiz):
            subpastas[:] = sorted(
                s for s in subpastas if s not in IGNORAR and not s.startswith(".")
            )
            for arquivo in sorted(nomes):
                if chave in _chave_arquivo(arquivo):
                    achados.append(Path(pasta) / arquivo)
                    if len(achados) >= maximo:
                        return achados
    return achados


def quebrar(texto: str) -> list[tuple[int, int, str]]:
    """Trechos de ~40 linhas com sobreposição: (linha inicial, linha final, texto)."""
    linhas = texto.splitlines()
    trechos = []
    passo = LINHAS_POR_TRECHO - SOBREPOR
    for inicio in range(0, max(len(linhas), 1), passo):
        bloco = linhas[inicio : inicio + LINHAS_POR_TRECHO]
        conteudo = "\n".join(bloco)[:MAX_CHARS_TRECHO]
        if conteudo.strip():
            trechos.append((inicio + 1, inicio + len(bloco), conteudo))
        if inicio + LINHAS_POR_TRECHO >= len(linhas):
            break
    return trechos


def _ler(caminho: Path) -> str | None:
    try:
        dados = caminho.read_bytes()
    except OSError:
        return None
    if b"\x00" in dados[:4096]:
        return None  # binário com extensão de texto
    return dados.decode("utf-8", errors="replace")


def indexar(cfg: Config, cliente: Embutidor, pasta: str | Path) -> ResultadoIndice:
    """Atualiza o índice do projeto: só arquivos novos ou alterados vão ao modelo."""
    raiz = validar_pasta(cfg, pasta)
    projeto = str(raiz)
    inicio = time.perf_counter()
    con = _banco(cfg)
    try:
        conhecidos = {
            c: (m, t)
            for c, m, t in con.execute(
                "SELECT caminho, mtime, tamanho FROM arquivos WHERE projeto = ?", (projeto,)
            )
        }
        vistos: set[str] = set()
        pendentes: list[tuple[str, float, int, list[tuple[int, int, str]]]] = []
        for caminho in arquivos_do_projeto(raiz, cfg.memoria.ignorar):
            relativo = caminho.relative_to(raiz).as_posix()
            vistos.add(relativo)
            info = caminho.stat()
            if conhecidos.get(relativo) == (info.st_mtime, info.st_size):
                continue
            texto = _ler(caminho)
            if texto is None:
                continue
            pendentes.append((relativo, info.st_mtime, info.st_size, quebrar(texto)))

        removidos = [c for c in conhecidos if c not in vistos]
        for relativo in removidos:
            con.execute(
                "DELETE FROM trechos WHERE projeto = ? AND caminho = ?", (projeto, relativo)
            )
            con.execute(
                "DELETE FROM arquivos WHERE projeto = ? AND caminho = ?", (projeto, relativo)
            )

        fila = [
            (rel, ini, fim, txt) for rel, _m, _t, partes in pendentes for ini, fim, txt in partes
        ]
        vetores: list[list[float]] = []
        for i in range(0, len(fila), LOTE):
            lote = fila[i : i + LOTE]
            entradas = [f"{PREFIXO_DOC}{rel}\n{txt}" for rel, _ini, _fim, txt in lote]
            vetores.extend(cliente.embutir(cfg.modelos.embeddings, entradas))
        if len(vetores) != len(fila):
            raise ErroExecucao("o modelo de embeddings devolveu menos vetores que trechos")

        for relativo, mtime, tamanho, _partes in pendentes:
            con.execute(
                "DELETE FROM trechos WHERE projeto = ? AND caminho = ?", (projeto, relativo)
            )
            con.execute(
                "INSERT OR REPLACE INTO arquivos VALUES (?, ?, ?, ?)",
                (projeto, relativo, mtime, tamanho),
            )
        con.executemany(
            "INSERT INTO trechos VALUES (?, ?, ?, ?, ?, ?)",
            [
                (projeto, rel, ini, fim, txt, _vetor_bytes(v))
                for (rel, ini, fim, txt), v in zip(fila, vetores, strict=True)
            ],
        )
        con.commit()
    finally:
        con.close()
    resultado = ResultadoIndice(
        len(vistos), len(pendentes), len(removidos), len(fila), time.perf_counter() - inicio
    )
    logger.info("índice %s: %s", projeto, resultado.texto())
    return resultado


# --- busca ---------------------------------------------------------------------------------


def _palavras(texto: str) -> set[str]:
    """Palavras de 4+ letras, minúsculas e sem acento ('Acordar' e 'acordar' contam igual)."""
    sem_acento = unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()
    return {p for p in re.findall(r"[a-z_][a-z0-9_]{3,}", sem_acento) if p not in COMUNS}


def _busca(cfg: Config, cliente: Embutidor, consulta: str) -> Any:
    import numpy as np

    vetor = cliente.embutir(cfg.modelos.embeddings, [f"{PREFIXO_BUSCA}{consulta}"])[0]
    return np.frombuffer(_vetor_bytes(vetor), dtype="float32")


def buscar(
    cfg: Config,
    cliente: Embutidor,
    pasta: str | Path,
    consulta: str,
    k: int = 5,
    por_arquivo: int = 2,
    caminho: str | None = None,
) -> list[Trecho]:
    """Os k trechos mais parecidos com a consulta (no máximo `por_arquivo` do mesmo arquivo)."""
    projeto = str(validar_pasta(cfg, pasta))
    con = _banco(cfg)
    try:
        if caminho is None:
            linhas = con.execute(
                "SELECT caminho, inicio, fim, texto, vetor FROM trechos WHERE projeto = ?",
                (projeto,),
            ).fetchall()
        else:
            linhas = con.execute(
                "SELECT caminho, inicio, fim, texto, vetor FROM trechos "
                "WHERE projeto = ? AND caminho = ?",
                (projeto, caminho),
            ).fetchall()
    finally:
        con.close()
    if not linhas:
        return []
    notas = _matriz([linha[4] for linha in linhas]) @ _busca(cfg, cliente, consulta)
    # Busca híbrida: o embedding acha o assunto; as palavras exatas da tarefa desempatam
    # (nomes de função e termos do projeto que o modelo pequeno não liga ao sentido).
    palavras = _palavras(consulta)
    if palavras:
        for i, linha in enumerate(linhas):
            presentes = palavras & _palavras(f"{linha[0]} {linha[3]}")
            notas[i] += PESO_PALAVRAS * len(presentes) / len(palavras)
    escolhidos: list[Trecho] = []
    contagem: dict[str, int] = {}
    vistos: set[str] = set()  # o mesmo texto em dois arquivos (cópias) entra uma vez só
    for i in notas.argsort()[::-1]:
        arquivo, inicio, fim, texto, _v = linhas[int(i)]
        if contagem.get(arquivo, 0) >= por_arquivo:
            continue
        if any(t.caminho == arquivo and t.inicio <= fim and inicio <= t.fim for t in escolhidos):
            continue  # pedaço sobreposto a um já escolhido
        assinatura = hashlib.sha1(" ".join(texto.split()).encode("utf-8")).hexdigest()
        if assinatura in vistos:
            continue
        vistos.add(assinatura)
        contagem[arquivo] = contagem.get(arquivo, 0) + 1
        escolhidos.append(Trecho(arquivo, inicio, fim, texto, float(notas[int(i)])))
        if len(escolhidos) >= k:
            break
    return escolhidos


def lembrar(
    cfg: Config, cliente: Embutidor, pasta: str | Path, texto: str, tipo: str = "decisao"
) -> str:
    """Guarda uma decisão ou um erro resolvido para voltar em tarefas parecidas."""
    if tipo not in ("decisao", "erro"):
        raise ErroExecucao("tipo deve ser 'decisao' ou 'erro'")
    texto = texto.strip()
    if not texto:
        raise ErroExecucao("nada para lembrar")
    projeto = str(validar_pasta(cfg, pasta))
    vetor = cliente.embutir(cfg.modelos.embeddings, [f"{PREFIXO_DOC}{texto}"])[0]
    con = _banco(cfg)
    try:
        con.execute(
            "INSERT INTO lembrancas VALUES (?, ?, ?, ?, ?)",
            (projeto, tipo, texto, _vetor_bytes(vetor), time.strftime("%Y-%m-%d")),
        )
        con.commit()
    finally:
        con.close()
    return f"Guardado ({'decisão' if tipo == 'decisao' else 'erro resolvido'}): {texto[:80]}"


def lembrancas(
    cfg: Config,
    cliente: Embutidor,
    pasta: str | Path,
    consulta: str,
    k: int = 3,
    minimo: float = 0.55,
) -> list[Lembranca]:
    """Decisões e erros já resolvidos parecidos com a consulta."""
    projeto = str(validar_pasta(cfg, pasta))
    con = _banco(cfg)
    try:
        linhas = con.execute(
            "SELECT tipo, texto, quando, vetor FROM lembrancas WHERE projeto = ?", (projeto,)
        ).fetchall()
    finally:
        con.close()
    if not linhas:
        return []
    notas = _matriz([linha[3] for linha in linhas]) @ _busca(cfg, cliente, consulta)
    ordem = [int(i) for i in notas.argsort()[::-1] if notas[int(i)] >= minimo][:k]
    return [Lembranca(linhas[i][0], linhas[i][1], linhas[i][2], float(notas[i])) for i in ordem]


def contexto(
    cfg: Config,
    cliente: Embutidor,
    pasta: str | Path,
    tarefa: str,
    k: int = 5,
    max_chars: int = 8000,
) -> str:
    """Atualiza o índice e devolve só os trechos e lembranças relevantes para a tarefa."""
    from agente import economia

    raiz = validar_pasta(cfg, pasta)
    indice = indexar(cfg, cliente, raiz)
    trechos = buscar(cfg, cliente, raiz, tarefa, k)
    memorias = lembrancas(cfg, cliente, raiz, tarefa)
    partes = [f"Contexto de {raiz.name} para: {tarefa}"]
    if memorias:
        partes.append("Já decidido ou resolvido antes:")
        partes += [f"- [{m.quando}] ({m.tipo}) {m.texto}" for m in memorias]
    if trechos:
        partes.append(f"Trechos mais relevantes ({len(trechos)} de {indice.arquivos} arquivos):")
        usados = sum(len(p) for p in partes)
        for t in trechos:
            bloco = t.formatar()
            if usados + len(bloco) > max_chars:
                break
            partes.append(bloco)
            usados += len(bloco)
    else:
        partes.append("Nenhum trecho indexado neste projeto (pasta sem arquivos de texto?).")
    resposta = "\n\n".join(partes)
    # o que o Claude teria lido sem o agente: os arquivos inteiros de onde vieram os trechos
    brutos = sum(
        (raiz / c).stat().st_size for c in {t.caminho for t in trechos} if (raiz / c).exists()
    )
    economia.registrar(cfg, "contexto", brutos, len(resposta))
    return resposta


# --- agente Memória (Fase 7) -----------------------------------------------------------------


def projetos(cfg: Config) -> list[Path]:
    """Projetos que a Memória mantém indexados: as subpastas das pastas do config."""
    encontrados = []
    for pasta in cfg.memoria.projetos:
        try:
            filhas = sorted(p for p in pasta.iterdir() if p.is_dir())
        except OSError:
            continue
        encontrados += [
            p
            for p in filhas
            if not p.name.startswith(".") and not _ignorado(p.name, cfg.memoria.ignorar)
        ]
    return encontrados


def manter_atualizado(cfg: Config, cliente: Embutidor) -> list[str]:
    """Uma rodada da Memória: atualiza o índice de cada projeto; devolve o que mudou."""
    mudancas = []
    for projeto in projetos(cfg):
        try:
            r = indexar(cfg, cliente, projeto)
        except ErroExecucao as exc:
            logger.warning("memória: %s ficou de fora: %s", projeto.name, exc)
            continue
        if r.novos or r.removidos:
            mudancas.append(
                f"{projeto.name}: {r.novos} arquivos atualizados, {r.removidos} removidos"
            )
    return mudancas


def tamanho_indice(cfg: Config) -> str:
    """Resumo curto do índice para o painel."""
    arquivo = cfg.pasta_dados / "memoria.sqlite"
    if not arquivo.exists():
        return "Índice vazio."
    con = _banco(cfg)
    try:
        n_projetos, n_trechos = con.execute(
            "SELECT COUNT(DISTINCT projeto), COUNT(*) FROM trechos"
        ).fetchone()
    finally:
        con.close()
    mb = arquivo.stat().st_size / 1024**2
    return f"Disco: {mb:.0f} MB · {n_projetos} projetos, {n_trechos} trechos"


ESBOCO = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?(?:def|class|function|interface|type|enum|struct|fn|func|"
    r"public|private|protected|static|const\s+\w+\s*=\s*(?:async\s*)?\()"
)
TITULO = re.compile(r"^#{1,4}\s")  # títulos de Markdown (em código, # é comentário)


def esboco(texto: str, maximo: int = 80, markdown: bool = False) -> list[str]:
    """Mapa do arquivo: linhas que abrem funções, classes e títulos, com o número da linha."""
    padrao = TITULO if markdown else ESBOCO
    linhas = [
        f"{n}: {linha.strip()[:110]}"
        for n, linha in enumerate(texto.splitlines(), 1)
        if padrao.match(linha)
    ]
    if len(linhas) > maximo:
        linhas = linhas[:maximo] + [f"... (+{len(linhas) - maximo} itens)"]
    return linhas


def _projeto_de(cfg: Config, arquivo: Path) -> Path:
    for projeto in projetos(cfg):
        if arquivo.is_relative_to(projeto):
            return projeto
    return arquivo.parent


def ler_relevante(
    cfg: Config, cliente: Embutidor, caminho: str | Path, tarefa: str, k: int = 3
) -> str:
    """Em vez do arquivo inteiro: o mapa das funções e só os trechos ligados à tarefa."""
    from agente import economia

    arquivo = Path(caminho).resolve()
    validar_pasta(cfg, arquivo.parent)
    texto = _ler(arquivo) if arquivo.is_file() else None
    if texto is None:
        raise ErroExecucao(f"não consegui ler {arquivo} como texto")
    if len(texto) <= 6000:
        return f"### {arquivo.name} (inteiro, é pequeno)\n```\n{texto.rstrip()}\n```"
    raiz = _projeto_de(cfg, arquivo)
    relativo = arquivo.relative_to(raiz).as_posix()
    indexar(cfg, cliente, raiz)
    trechos = buscar(cfg, cliente, raiz, tarefa, k=k, por_arquivo=k, caminho=relativo)
    if not trechos:  # fora do índice (ignorado ou grande demais): avisa em vez de inventar
        raise ErroExecucao(f"{relativo} não está no índice (ignorado ou acima de 300 KB)")
    total = len(texto.splitlines())
    partes = [
        f"{relativo}: {total} linhas. Mapa (linha: definição):",
        *esboco(texto, markdown=arquivo.suffix.lower() in (".md", ".rst")),
    ]
    partes.append(f"Trechos ligados a '{tarefa}':")
    partes += [t.formatar() for t in sorted(trechos, key=lambda t: t.inicio)]
    partes.append("Para ver outra parte, peça as linhas pelo mapa acima.")
    resposta = "\n".join(partes)
    economia.registrar(cfg, "ler relevante", len(texto), len(resposta))
    return resposta
