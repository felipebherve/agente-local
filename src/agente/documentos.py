"""Documentos: transcreve imagens com o modelo de visão local e junta arquivos num PDF.

Pensado para o dia a dia de quem monta pastas de documentos (RG, holerite, extrato):
as fotos do celular viram um PDF só, em páginas A4, e prints viram texto sem gastar
tokens do Claude (a imagem nunca sai do PC).
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

logger = logging.getLogger(__name__)

EXT_IMAGEM = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
EXT_TEXTO = {".txt", ".md"}
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
            arquivos.extend(
                sorted(f for f in p.iterdir() if f.is_file() and f.suffix.lower() in extensoes)
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
    try:
        imagem = ImageOps.exif_transpose(Image.open(arquivo))
    except OSError as exc:
        raise ErroExecucao(f"não consegui abrir a imagem {arquivo.name}: {exc}") from exc
    imagem = imagem.convert("RGB")
    imagem.thumbnail((lado_max, lado_max))
    return imagem


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
) -> str:
    """Transcreve uma ou mais imagens (ou pastas de imagens) com o modelo de visão local."""
    arquivos = _listar(cfg, caminhos, EXT_IMAGEM)
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
    if salvar_em:
        destino = _destino(cfg, salvar_em, ".md", confirmado=True)
        destino.write_text(resultado + "\n", encoding="utf-8")
        resultado += f"\n\n(Transcrição salva em {destino})"
    return resultado


def _texto_latin1(texto: str) -> str:
    """As fontes padrão do PDF só têm Latin-1 (acentos ok); o resto vira '?'."""
    return texto.encode("latin-1", "replace").decode("latin-1")


def juntar_em_pdf(
    cfg: Config, caminhos: list[str], destino: str, confirmado: bool = False
) -> str:
    """Junta imagens e textos (.txt, .md) num PDF A4, um arquivo por página, na ordem dada."""
    try:
        from fpdf import FPDF
    except ImportError as exc:
        raise ErroExecucao(f"falta a biblioteca fpdf2: {exc}") from exc
    arquivos = _listar(cfg, caminhos, EXT_IMAGEM | EXT_TEXTO)
    saida = _destino(cfg, destino, ".pdf", confirmado)
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
    pdf.output(str(saida))
    tamanho_mb = saida.stat().st_size / 1024**2
    logger.info("PDF %s: %d páginas, %.1f MB", saida, len(arquivos), tamanho_mb)
    return f"PDF criado: {saida} ({len(arquivos)} página(s), {tamanho_mb:.1f} MB)."
