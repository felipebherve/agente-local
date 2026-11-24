from pathlib import Path

import pytest
from PIL import Image

from agente import documentos
from agente.executor import ConfirmacaoNecessaria, ErroExecucao
from agente.llm import Resposta


def _foto(pasta: Path, nome: str, tamanho: tuple[int, int] = (300, 200)) -> Path:
    arq = pasta / nome
    Image.new("RGB", tamanho, (200, 30, 30)).save(arq)
    return arq


class ClienteFalso:
    url = "http://x"
    timeout_s = 5.0
    keep_alive = "1m"
    pensar = None
    max_tokens = 256


def test_juntar_em_pdf_imagens_e_texto(cfg, tmp_path):
    _foto(tmp_path, "rg_frente.jpg")
    _foto(tmp_path, "rg_verso.png", (200, 400))
    (tmp_path / "obs.txt").write_text("Cliente com dependente, 36 meses de CTPS.", "utf-8")
    arquivos = [str(tmp_path / n) for n in ("rg_frente.jpg", "rg_verso.png", "obs.txt")]
    texto = documentos.juntar_em_pdf(cfg, arquivos, str(tmp_path / "RG"))
    pdf = tmp_path / "RG.pdf"
    assert pdf.exists() and pdf.read_bytes().startswith(b"%PDF")
    assert "3 página(s)" in texto


def test_juntar_em_pdf_pasta_inteira_em_ordem(cfg, tmp_path):
    fotos = tmp_path / "fotos"
    fotos.mkdir()
    _foto(fotos, "b.jpg")
    _foto(fotos, "a.jpg")
    (fotos / "planilha.xlsx").write_bytes(b"x")
    listados = documentos._listar(cfg, [str(fotos)], documentos.EXT_IMAGEM)
    assert [p.name for p in listados] == ["a.jpg", "b.jpg"]
    assert "2 página(s)" in documentos.juntar_em_pdf(cfg, [str(fotos)], str(tmp_path / "x.pdf"))


def test_juntar_em_pdf_pede_confirmacao_para_sobrescrever(cfg, tmp_path):
    foto = _foto(tmp_path, "a.jpg")
    (tmp_path / "saida.pdf").write_bytes(b"antigo")
    with pytest.raises(ConfirmacaoNecessaria):
        documentos.juntar_em_pdf(cfg, [str(foto)], str(tmp_path / "saida.pdf"))
    documentos.juntar_em_pdf(cfg, [str(foto)], str(tmp_path / "saida.pdf"), confirmado=True)
    assert (tmp_path / "saida.pdf").read_bytes().startswith(b"%PDF")


def test_fora_das_pastas_permitidas_e_tipo_invalido(cfg, tmp_path):
    fora = Path(__file__)
    with pytest.raises(ErroExecucao, match="fora das pastas"):
        documentos.juntar_em_pdf(cfg, [str(fora)], str(tmp_path / "a.pdf"))
    planilha = tmp_path / "dados.xlsx"
    planilha.write_bytes(b"x")
    with pytest.raises(ErroExecucao, match="não suportado"):
        documentos.juntar_em_pdf(cfg, [str(planilha)], str(tmp_path / "a.pdf"))


def test_transcrever_imagens_usa_modelo_de_visao_e_salva(cfg, tmp_path, monkeypatch):
    _foto(tmp_path, "print1.png")
    _foto(tmp_path, "print2.png")
    chamadas = []

    def conversar(self, modelo, pergunta, sistema=None, temperatura=0.2, imagens=None):
        chamadas.append((modelo, self.max_tokens, len(imagens or [])))
        return Resposta("TEXTO DO PRINT", modelo, 1, 1, 0.1, 10.0)

    monkeypatch.setattr(documentos.ClienteOllama, "conversar", conversar)
    resultado = documentos.transcrever_imagens(
        cfg, ClienteFalso(), [str(tmp_path)], salvar_em=str(tmp_path / "transcricao")
    )
    assert chamadas == [("c", documentos.TOKENS_TRANSCRICAO, 1)] * 2
    assert "## print1.png" in resultado and "## print2.png" in resultado
    salvo = (tmp_path / "transcricao.md").read_text("utf-8")
    assert salvo.count("TEXTO DO PRINT") == 2


def _pdf_texto(pasta: Path, nome: str, texto: str, paginas: int = 1) -> Path:
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.set_font("Helvetica", size=12)
    for i in range(paginas):
        pdf.add_page()
        pdf.cell(0, 10, f"{texto} {i + 1}")
    arq = pasta / nome
    pdf.output(str(arq))
    return arq


def _paginas(arq: Path) -> list[str]:
    from pypdf import PdfReader

    return [p.extract_text() for p in PdfReader(arq).pages]


def test_texto_longo_conta_paginas_de_verdade_e_troca_aspas(cfg, tmp_path):
    (tmp_path / "longo.txt").write_text("linha — “aspas” …\n" * 200, "utf-8")
    texto = documentos.juntar_em_pdf(cfg, [str(tmp_path / "longo.txt")], str(tmp_path / "o"))
    paginas = _paginas(tmp_path / "o.pdf")
    assert len(paginas) > 1 and f"{len(paginas)} página(s)" in texto
    assert 'linha - "aspas" ...' in paginas[0] and "?" not in paginas[0]


def test_juntar_pdfs_existentes_com_fotos_na_ordem(cfg, tmp_path):
    holerite = _pdf_texto(tmp_path, "holerite.pdf", "HOLERITE", paginas=2)
    foto = _foto(tmp_path, "rg.jpg")
    extrato = _pdf_texto(tmp_path, "extrato.pdf", "EXTRATO")
    texto = documentos.juntar_em_pdf(
        cfg, [str(holerite), str(foto), str(extrato)], str(tmp_path / "renda.pdf")
    )
    paginas = _paginas(tmp_path / "renda.pdf")
    assert len(paginas) == 4 and "3 arquivo(s), 4 página(s)" in texto
    assert "HOLERITE 1" in paginas[0] and "HOLERITE 2" in paginas[1]
    assert "EXTRATO 1" in paginas[3]


def test_juntar_pasta_nao_inclui_o_proprio_destino(cfg, tmp_path):
    pasta = tmp_path / "docs"
    pasta.mkdir()
    _pdf_texto(pasta, "a.pdf", "A")
    _foto(pasta, "b.jpg")
    destino = str(pasta / "tudo.pdf")
    documentos.juntar_em_pdf(cfg, [str(pasta)], destino)
    texto = documentos.juntar_em_pdf(cfg, [str(pasta)], destino, confirmado=True)
    assert "2 arquivo(s), 2 página(s)" in texto


def test_pdf_com_senha_da_erro_claro(cfg, tmp_path):
    from pypdf import PdfReader, PdfWriter

    aberto = _pdf_texto(tmp_path, "aberto.pdf", "X")
    escritor = PdfWriter()
    escritor.append(PdfReader(aberto))
    escritor.encrypt("segredo", algorithm="RC4-128")
    with (tmp_path / "senha.pdf").open("wb") as f:
        escritor.write(f)
    with pytest.raises(ErroExecucao, match="tem senha"):
        documentos.juntar_em_pdf(cfg, [str(tmp_path / "senha.pdf")], str(tmp_path / "o.pdf"))


def test_atalho_para_fora_das_pastas_permitidas_e_barrado(cfg, tmp_path):
    pasta = tmp_path / "docs"
    pasta.mkdir()
    _foto(pasta, "a.jpg")
    try:
        (pasta / "fora.md").symlink_to(Path(__file__).parent.parent / "README.md")
    except OSError:
        pytest.skip("sem permissão para criar atalhos")
    with pytest.raises(ErroExecucao, match="fora das pastas"):
        documentos.juntar_em_pdf(cfg, [str(pasta)], str(tmp_path / "o.pdf"))


def test_png_transparente_fica_com_fundo_branco(tmp_path):
    arq = tmp_path / "t.png"
    Image.new("RGBA", (20, 20), (0, 0, 0, 0)).save(arq)
    assert documentos._abrir_imagem(arq, 100).getpixel((1, 1)) == (255, 255, 255)


def test_heic_usa_pi_heif(tmp_path, monkeypatch):
    chamadas = []
    monkeypatch.setattr(documentos, "_ativar_heic", lambda: chamadas.append(1))
    arq = tmp_path / "foto.heic"
    Image.new("RGB", (30, 20)).save(arq, format="PNG")  # conteúdo PNG: só testa o caminho
    assert documentos._abrir_imagem(arq, 100).size == (30, 20)
    assert chamadas == [1]


def test_heic_sem_pi_heif_explica_o_que_falta(monkeypatch):
    import builtins

    original = builtins.__import__

    def sem_pi_heif(nome, *args, **kwargs):
        if nome == "pi_heif":
            raise ImportError("No module named 'pi_heif'")
        return original(nome, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", sem_pi_heif)
    with pytest.raises(ErroExecucao, match="pi-heif"):
        documentos._ativar_heic()


def test_pi_heif_ensina_o_pillow_a_abrir_heic():
    pytest.importorskip("pi_heif")
    documentos._ativar_heic()
    assert Image.registered_extensions().get(".heic") == "HEIF"


def test_transcricao_pede_confirmacao_antes_de_sobrescrever(cfg, tmp_path, monkeypatch):
    _foto(tmp_path, "print.png")
    (tmp_path / "t.md").write_text("antigo", "utf-8")

    def conversar(self, *a, **k):
        raise AssertionError("não devia chamar o modelo antes de confirmar")

    monkeypatch.setattr(documentos.ClienteOllama, "conversar", conversar)
    with pytest.raises(ConfirmacaoNecessaria):
        documentos.transcrever_imagens(
            cfg, ClienteFalso(), [str(tmp_path / "print.png")], salvar_em=str(tmp_path / "t.md")
        )
