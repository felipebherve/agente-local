"""Documentos: transcreve imagens com o modelo de visão local e junta arquivos num PDF.

Pensado para o dia a dia de quem monta pastas de documentos (RG, holerite, extrato):
as fotos do celular (inclusive HEIC do iPhone) e PDFs que já existem viram um PDF só,
em páginas A4, e prints viram texto sem gastar tokens do Claude (a imagem nunca sai do PC).
"""

from __future__ import annotations

import base64
import io
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from agente.config import Config
from agente.economia import registrar
from agente.executor import ConfirmacaoNecessaria, ErroExecucao, validar_pasta
from agente.llm import ClienteOllama

if TYPE_CHECKING:
    from PIL.Image import Image as ImagemPIL
    from pypdf import PdfReader as PdfReaderT

logger = logging.getLogger(__name__)

EXT_HEIC = {".heic", ".heif"}  # fotos de iPhone
EXT_IMAGEM = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"} | EXT_HEIC
EXT_TEXTO = {".txt", ".md"}
EXT_PDF = {".pdf"}
MAX_ARQUIVOS = 50
LADO_VISAO = 1600  # maior lado enviado ao modelo de visão
LADO_PDF = 2000  # maior lado da imagem dentro do PDF (deixa o arquivo leve)
TOKENS_TRANSCRICAO = 4096

PEDIDO_TRANSCRICAO = (
    "Transcreva fielmente TODO o texto visível nesta imagem, em português, na ordem de "
    "leitura (de cima para baixo, da esquerda para a direita). Mantenha títulos, listas e "
    "tabelas (use Markdown). Não resuma, não traduza e não invente: onde não der para ler, "
    "escreva [ilegível]. Se houver partes que não são texto (botões, fotos, gráficos), "
    "descreva em uma linha entre parênteses."
)


def _listar(cfg: Config, caminhos: list[str], extensoes: set[str]) -> list[Path]:
    """Expande pastas (só o primeiro nível, em ordem alfabética) e checa as permissões."""
    arquivos: list[Path] = []
    for bruto in caminhos:
        p = validar_pasta(cfg, bruto)
        if p.is_dir():
            # cada arquivo da pasta é validado de novo: um atalho dentro de uma pasta
            # permitida não pode levar para fora dela
            arquivos.extend(
                sorted(
                    validar_pasta(cfg, f)
                    for f in p.iterdir()
                    if f.is_file() and f.suffix.lower() in extensoes
                )
            )
        elif p.suffix.lower() in extensoes:
            arquivos.append(p)
        else:
            raise ErroExecucao(f"tipo de arquivo não suportado: {p.name}")
    if not arquivos:
        raise ErroExecucao("nenhum arquivo suportado encontrado")
    if len(arquivos) > MAX_ARQUIVOS:
        raise ErroExecucao(f"{len(arquivos)} arquivos; o limite por vez é {MAX_ARQUIVOS}")
    return arquivos


def _abrir_imagem(arquivo: Path, lado_max: int) -> ImagemPIL:
    """Abre a imagem já virada do jeito certo (EXIF do celular), em RGB e reduzida."""
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise ErroExecucao(f"falta a biblioteca Pillow: {exc}") from exc
    if arquivo.suffix.lower() in EXT_HEIC:
        _ativar_heic()
    try:
        imagem = ImageOps.exif_transpose(Image.open(arquivo))
    except OSError as exc:
        raise ErroExecucao(f"não consegui abrir a imagem {arquivo.name}: {exc}") from exc
    if imagem.mode in ("RGBA", "LA", "P"):
        # fundo branco no lugar da transparência (senão ela vira preto)
        fundo = Image.new("RGB", imagem.size, (255, 255, 255))
        rgba = imagem.convert("RGBA")
        fundo.paste(rgba, mask=rgba.getchannel("A"))
        imagem = fundo
    imagem = imagem.convert("RGB")
    imagem.thumbnail((lado_max, lado_max))
    return imagem


def _ativar_heic() -> None:
    """Ensina o Pillow a abrir HEIC/HEIF (pi-heif: só leitura, sem codec GPL)."""
    try:
        from pi_heif import register_heif_opener
    except ImportError as exc:
        raise ErroExecucao(
            f"falta a biblioteca pi-heif para abrir fotos HEIC do iPhone: {exc}"
        ) from exc
    register_heif_opener()


def _base64_png(imagem: ImagemPIL) -> str:
    buffer = io.BytesIO()
    imagem.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _destino(cfg: Config, caminho: str, extensao: str, confirmado: bool) -> Path:
    """Valida onde gravar: pasta-mãe permitida, extensão certa e sem sobrescrever sem OK."""
    destino = Path(caminho).expanduser()
    if destino.suffix.lower() != extensao:
        destino = destino.with_suffix(extensao)
    pasta = validar_pasta(cfg, destino.parent)
    destino = pasta / destino.name
    if destino.exists() and not confirmado:
        raise ConfirmacaoNecessaria(f"{destino} já existe e seria substituído")
    return destino


def transcrever_imagens(
    cfg: Config,
    cliente: ClienteOllama,
    caminhos: list[str],
    foco: str = "",
    salvar_em: str = "",
    confirmado: bool = False,
) -> str:
    """Transcreve uma ou mais imagens (ou pastas de imagens) com o modelo de visão local."""
    arquivos = _listar(cfg, caminhos, EXT_IMAGEM)
    # checa o destino antes de gastar minutos no modelo de visão
    destino_md = _destino(cfg, salvar_em, ".md", confirmado) if salvar_em else None
    resultado = transcrever_arquivos(cfg, cliente, arquivos, foco)
    if destino_md is not None:
        destino_md.write_text(resultado + "\n", encoding="utf-8")
        resultado += f"\n\n(Transcrição salva em {destino_md})"
    return resultado


def transcrever_arquivos(
    cfg: Config, cliente: ClienteOllama, arquivos: list[Path], foco: str = ""
) -> str:
    """Transcreve imagens já conferidas (o painel usa para as fotos mandadas pelo app)."""
    leitor = ClienteOllama(
        cliente.url,
        cliente.timeout_s,
        cliente.keep_alive,
        cliente.pensar,
        max(cliente.max_tokens, TOKENS_TRANSCRICAO),
    )
    pedido = PEDIDO_TRANSCRICAO + (f" Atenção especial a: {foco}." if foco else "")
    partes: list[str] = []
    bytes_imagens = 0
    for arquivo in arquivos:
        imagem_b64 = _base64_png(_abrir_imagem(arquivo, LADO_VISAO))
        bytes_imagens += len(imagem_b64)
        texto = leitor.conversar(cfg.modelos.visao, pedido, imagens=[imagem_b64]).texto
        partes.append(f"## {arquivo.name}\n\n{texto}" if len(arquivos) > 1 else texto)
        logger.info("transcrito %s (%d caracteres)", arquivo.name, len(texto))
    resultado = "\n\n".join(partes)
    registrar(cfg, "transcrever imagem", bytes_imagens // 3, len(resultado))
    return resultado


# Caracteres comuns em textos (e nas transcrições do modelo) que não existem em Latin-1
TROCAS_LATIN1 = str.maketrans(
    {
        "\u2014": "-",  # travessão
        "\u2013": "-",  # meia-risca
        "\u2212": "-",  # sinal de menos
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u2026": "...",
        "\u2022": "-",  # marcador de lista
        "\u25cf": "-",
        "\u2192": "->",
        "\u20ac": "EUR",
        "\u00a0": " ",
        "\u200b": "",
    }
)


def _texto_latin1(texto: str) -> str:
    """As fontes padrão do PDF só têm Latin-1 (acentos ok): troca o que dá e o resto vira '?'."""
    return texto.translate(TROCAS_LATIN1).encode("latin-1", "replace").decode("latin-1")


def _pdf_de_paginas(arquivos: list[Path]) -> bytes:
    """Monta um PDF A4 com imagens (uma por página) e textos (quantas páginas precisarem)."""
    try:
        from fpdf import FPDF
    except ImportError as exc:
        raise ErroExecucao(f"falta a biblioteca fpdf2: {exc}") from exc
    pdf = FPDF(format="A4")
    pdf.set_image_filter("DCTDecode")  # imagens em JPEG: PDF bem menor
    pdf.set_auto_page_break(auto=True, margin=12)
    margem = 10.0
    largura_util = pdf.w - 2 * margem
    altura_util = pdf.h - 2 * margem
    for arquivo in arquivos:
        pdf.add_page()
        if arquivo.suffix.lower() in EXT_IMAGEM:
            imagem = _abrir_imagem(arquivo, LADO_PDF)
            escala = min(largura_util / imagem.width, altura_util / imagem.height)
            w, h = imagem.width * escala, imagem.height * escala
            pdf.image(imagem, x=(pdf.w - w) / 2, y=(pdf.h - h) / 2, w=w, h=h)
        else:
            pdf.set_font("Helvetica", size=11)
            texto = arquivo.read_text(encoding="utf-8", errors="replace")
            pdf.multi_cell(0, 6, _texto_latin1(texto))
    return bytes(pdf.output())


def _ler_pdf(arquivo: Path) -> PdfReaderT:
    """Abre um PDF existente (lido para a memória, para poder sobrescrever o próprio destino)."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        leitor = PdfReader(io.BytesIO(arquivo.read_bytes()))
        if leitor.is_encrypted and not leitor.decrypt(""):
            raise ErroExecucao(
                f"{arquivo.name} tem senha: abra, salve uma cópia sem senha e tente de novo"
            )
        len(leitor.pages)  # força a leitura agora, para o erro sair com o nome do arquivo
    except ErroExecucao:
        raise
    except (PdfReadError, OSError, ValueError, NotImplementedError) as exc:
        raise ErroExecucao(f"não consegui ler o PDF {arquivo.name}: {exc}") from exc
    return leitor


def juntar_em_pdf(cfg: Config, caminhos: list[str], destino: str, confirmado: bool = False) -> str:
    """Junta imagens, textos (.txt, .md) e PDFs num PDF só, na ordem dada.

    Cada imagem vira uma página A4; textos ocupam as páginas que precisarem; PDFs entram
    com todas as páginas deles.
    """
    saida = _destino(cfg, destino, ".pdf", confirmado)
    # o próprio destino (de uma rodada anterior) nunca entra como parte dele mesmo
    arquivos = [a for a in _listar(cfg, caminhos, EXT_IMAGEM | EXT_TEXTO | EXT_PDF) if a != saida]
    if not arquivos:
        raise ErroExecucao("nenhum arquivo para juntar além do próprio destino")
    if not any(a.suffix.lower() in EXT_PDF for a in arquivos):
        conteudo = _pdf_de_paginas(arquivos)
    else:
        try:
            from pypdf import PdfReader, PdfWriter
        except ImportError as exc:
            raise ErroExecucao(f"falta a biblioteca pypdf para juntar PDFs: {exc}") from exc
        escritor = PdfWriter()
        grupo: list[Path] = []  # imagens/textos seguidos viram um bloco só

        def _fechar_grupo() -> None:
            if grupo:
                escritor.append(PdfReader(io.BytesIO(_pdf_de_paginas(grupo))))
                grupo.clear()

        for arquivo in arquivos:
            if arquivo.suffix.lower() in EXT_PDF:
                _fechar_grupo()
                escritor.append(_ler_pdf(arquivo))
            else:
                grupo.append(arquivo)
        _fechar_grupo()
        buffer = io.BytesIO()
        escritor.write(buffer)
        conteudo = buffer.getvalue()
    saida.write_bytes(conteudo)
    paginas = _contar_paginas(conteudo)
    tamanho_mb = len(conteudo) / 1024**2
    logger.info(
        "PDF %s: %d arquivos, %d páginas, %.1f MB", saida, len(arquivos), paginas, tamanho_mb
    )
    return (
        f"PDF criado: {saida} ({len(arquivos)} arquivo(s), {paginas} página(s), "
        f"{tamanho_mb:.1f} MB)."
    )


def _contar_paginas(conteudo: bytes) -> int:
    from pypdf import PdfReader

    return len(PdfReader(io.BytesIO(conteudo)).pages)
