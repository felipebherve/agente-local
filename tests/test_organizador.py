import os
import time
from datetime import datetime

from agente import organizador


def _criar(caminho, conteudo: bytes, modificado: str | None = None):
    caminho.write_bytes(conteudo)
    if modificado is not None:
        t = time.mktime(datetime.strptime(modificado, "%Y-%m-%d").timetuple())
        os.utime(caminho, (t, t))


def test_varrer_ignora_pastas_e_pega_tamanho_e_extensao(tmp_path):
    (tmp_path / "sub").mkdir()
    _criar(tmp_path / "foto.jpg", b"abc")
    _criar(tmp_path / "sub" / "doc.txt", b"abcdef")

    arquivos = organizador.varrer(tmp_path)
    nomes = {a.caminho.split("/")[-1]: a for a in arquivos}
    assert set(nomes) == {"foto.jpg", "doc.txt"}
    assert nomes["foto.jpg"].tamanho == 3
    assert nomes["foto.jpg"].extensao == ".jpg"
    assert nomes["doc.txt"].tamanho == 6


def test_duplicados_por_conteudo_identico(tmp_path):
    _criar(tmp_path / "a.txt", b"mesmo conteudo")
    _criar(tmp_path / "b.txt", b"mesmo conteudo")
    _criar(tmp_path / "c.txt", b"outro conteudo")

    arquivos = organizador.varrer(tmp_path)
    grupos = organizador.duplicados(arquivos)
    assert len(grupos) == 1
    assert {a.caminho.split("/")[-1] for a in grupos[0]} == {"a.txt", "b.txt"}


def test_tamanho_igual_mas_conteudo_diferente_nao_e_duplicado(tmp_path):
    _criar(tmp_path / "a.txt", b"xxxxxxxxxx")
    _criar(tmp_path / "b.txt", b"yyyyyyyyyy")

    arquivos = organizador.varrer(tmp_path)
    assert organizador.duplicados(arquivos) == []


def test_duplicado_em_arquivo_maior_que_o_pedaco_usa_hash_completo(tmp_path, monkeypatch):
    monkeypatch.setattr(organizador, "PEDACO", 4)  # força precisar do hash completo
    _criar(tmp_path / "a.txt", b"0123456789")
    _criar(tmp_path / "b.txt", b"0123456789")
    _criar(tmp_path / "c.txt", b"0123998769")  # início e fim iguais, meio diferente

    arquivos = organizador.varrer(tmp_path)
    grupos = organizador.duplicados(arquivos)
    assert len(grupos) == 1
    assert {a.caminho.split("/")[-1] for a in grupos[0]} == {"a.txt", "b.txt"}


def test_resumir_conta_extensoes_e_subpastas(tmp_path):
    (tmp_path / "Fotos").mkdir()
    _criar(tmp_path / "x.jpg", b"a")
    _criar(tmp_path / "y.jpg", b"ab")
    _criar(tmp_path / "z.txt", b"abc")

    arquivos = organizador.varrer(tmp_path)
    resumo = organizador.resumir(arquivos, tmp_path, grupos=[])
    assert resumo["total_arquivos"] == 3
    assert resumo["subpastas_de_primeiro_nivel"] == ["Fotos"]
    assert dict(resumo["por_extensao"])[".jpg"] == 2


def test_sugerir_estrutura_usa_omniroute_e_rotula(cfg, monkeypatch):
    from agente import nuvem

    monkeypatch.setattr(
        nuvem, "perguntar", lambda _cfg, _p, _s: nuvem.Resposta("modelo-x", "crie pasta Fotos")
    )
    assert organizador.sugerir_estrutura(cfg, {"total_arquivos": 1}) == (
        "[OmniRoute · modelo-x] crie pasta Fotos"
    )


def test_sugerir_estrutura_sem_omniroute_nao_quebra(cfg, monkeypatch):
    from agente import nuvem

    monkeypatch.setattr(nuvem, "perguntar", lambda *_a: None)
    assert "Nenhuma IA" in organizador.sugerir_estrutura(cfg, {"total_arquivos": 1})


def test_gerar_relatorio_grava_json_md_e_pdf(cfg, tmp_path, monkeypatch):
    from agente import nuvem

    # em-dash e emoji: a IA usa e o Helvetica puro não suporta (já quebrou o relatório antes)
    monkeypatch.setattr(
        nuvem, "perguntar", lambda *_a: nuvem.Resposta("x", "sugestão – curta 📁")
    )
    origem = tmp_path / "Pasta Teste"
    origem.mkdir()
    _criar(origem / "a.txt", b"dup")
    _criar(origem / "b.txt", b"dup")

    destino, resumo = organizador.gerar_relatorio(cfg, origem)
    assert destino == cfg.pasta_dados / "organizador" / "pasta-teste"
    assert resumo["grupos_duplicados"] == 1
    assert (destino / "inventario.json").exists()
    assert (destino / "duplicados.md").exists()
    assert (destino / "sugestao.md").exists()
    assert (destino / "resumo.json").exists()
    assert (destino / "relatorio.pdf").exists()
    assert (destino / "relatorio.pdf").stat().st_size > 0


def test_gerar_plano_lixo_mantem_o_mais_antigo_e_marca_o_resto(tmp_path):
    _criar(tmp_path / "antigo.txt", b"dup", modificado="2020-01-01")
    _criar(tmp_path / "novo.txt", b"dup", modificado="2024-01-01")

    arquivos = organizador.varrer(tmp_path)
    grupos = organizador.duplicados(arquivos)
    plano = organizador.gerar_plano_lixo_duplicados(tmp_path, grupos)

    assert plano["total_grupos"] == 1
    assert plano["total_arquivos_a_mover"] == 1
    entrada = plano["entradas"][0]
    assert entrada["manter"].endswith("antigo.txt")
    assert entrada["mover"].endswith("novo.txt")


def test_executar_plano_lixo_move_preservando_estrutura_e_nao_apaga_nada(tmp_path):
    (tmp_path / "Fotos" / "sub").mkdir(parents=True)
    _criar(tmp_path / "Fotos" / "a.jpg", b"dup", modificado="2020-01-01")
    _criar(tmp_path / "Fotos" / "sub" / "b.jpg", b"dup", modificado="2024-01-01")

    arquivos = organizador.varrer(tmp_path)
    grupos = organizador.duplicados(arquivos)
    plano = organizador.gerar_plano_lixo_duplicados(tmp_path, grupos)

    resultado = organizador.executar_plano_lixo(tmp_path, plano)

    assert resultado == {"movidos": 1, "bytes_movidos": 3, "erros": []}
    assert (tmp_path / "Fotos" / "a.jpg").exists()  # o mais antigo fica no lugar
    assert not (tmp_path / "Fotos" / "sub" / "b.jpg").exists()  # o duplicado saiu de lá
    esperado = tmp_path / "lixo" / "duplicados" / "Fotos" / "sub" / "b.jpg"
    assert esperado.exists()  # mas não foi apagado, só movido preservando o caminho
    assert esperado.read_bytes() == b"dup"


def test_gerar_plano_duplicados_e_salvar_grava_json_e_md_sem_mover_nada(cfg, tmp_path):
    origem = tmp_path / "Pasta Teste"
    origem.mkdir()
    _criar(origem / "a.txt", b"dup", modificado="2020-01-01")
    _criar(origem / "b.txt", b"dup", modificado="2024-01-01")

    destino, plano = organizador.gerar_plano_duplicados_e_salvar(cfg, origem)

    assert destino == cfg.pasta_dados / "organizador" / "pasta-teste"
    assert plano["total_arquivos_a_mover"] == 1
    assert (destino / "plano_lixo.json").exists()
    assert (destino / "plano_lixo.md").exists()
    assert (origem / "a.txt").exists()
    assert (origem / "b.txt").exists()  # nada se move nessa etapa


def test_aplicar_plano_lixo_le_o_plano_gravado_e_executa(cfg, tmp_path):
    origem = tmp_path / "Pasta Teste"
    origem.mkdir()
    _criar(origem / "a.txt", b"dup", modificado="2020-01-01")
    _criar(origem / "b.txt", b"dup", modificado="2024-01-01")

    destino, _ = organizador.gerar_plano_duplicados_e_salvar(cfg, origem)
    resultado = organizador.aplicar_plano_lixo(cfg, origem)

    assert resultado["movidos"] == 1
    assert resultado["erros"] == []
    assert (destino / "resultado_lixo.json").exists()
    assert (origem / "a.txt").exists()
    assert (origem / "lixo" / "duplicados" / "b.txt").exists()
