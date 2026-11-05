import hashlib
import re

import pytest

from agente import memoria
from agente.executor import ErroExecucao

DIM = 256


class Falso:
    """Embeddings de mentira: saco de palavras com hash. Parecido no texto = parecido no vetor."""

    def __init__(self):
        self.chamadas = 0
        self.textos = 0

    def embutir(self, modelo, textos):
        self.chamadas += 1
        self.textos += len(textos)
        vetores = []
        for texto in textos:
            v = [0.0] * DIM
            for palavra in re.findall(r"[a-zà-ú]{3,}", texto.lower()):
                v[int(hashlib.md5(palavra.encode()).hexdigest(), 16) % DIM] += 1
            vetores.append(v)
        return vetores


@pytest.fixture
def projeto(cfg, tmp_path):
    raiz = tmp_path / "loja"
    (raiz / "src").mkdir(parents=True)
    (raiz / "src" / "pagamento.py").write_text(
        "def cobrar_cartao(valor):\n    # cobra o cartao de credito do cliente\n    return valor\n",
        encoding="utf-8",
    )
    (raiz / "src" / "estoque.py").write_text(
        "def baixar_estoque(produto):\n    # tira o produto do estoque depois da venda\n",
        encoding="utf-8",
    )
    (raiz / "README.md").write_text("# Loja\nSite de vendas.\n", encoding="utf-8")
    (raiz / "node_modules" / "lib").mkdir(parents=True)
    (raiz / "node_modules" / "lib" / "x.js").write_text("cartao cartao", encoding="utf-8")
    (raiz / "logo.png").write_bytes(b"\x89PNG\x00\x00")
    return raiz


def test_quebrar_em_trechos_com_sobreposicao():
    texto = "\n".join(f"linha {i}" for i in range(1, 101))
    trechos = memoria.quebrar(texto)
    assert trechos[0][:2] == (1, 40)
    assert trechos[1][0] == 33  # 8 linhas repetidas
    assert trechos[-1][1] == 100
    assert memoria.quebrar("") == []


def test_ignora_dependencias_e_binarios(projeto):
    nomes = {p.name for p in memoria.arquivos_do_projeto(projeto)}
    assert nomes == {"pagamento.py", "estoque.py", "README.md"}


def test_indexa_so_o_que_mudou(cfg, projeto):
    falso = Falso()
    primeiro = memoria.indexar(cfg, falso, projeto)
    assert (primeiro.arquivos, primeiro.novos, primeiro.trechos) == (3, 3, 3)

    de_novo = memoria.indexar(cfg, falso, projeto)
    assert (de_novo.novos, de_novo.trechos) == (0, 0)

    (projeto / "src" / "estoque.py").write_text("def repor():\n    pass\n", encoding="utf-8")
    (projeto / "README.md").unlink()
    mudou = memoria.indexar(cfg, falso, projeto)
    assert (mudou.novos, mudou.removidos) == (1, 1)


def test_busca_acha_o_arquivo_certo(cfg, projeto):
    falso = Falso()
    memoria.indexar(cfg, falso, projeto)
    trechos = memoria.buscar(cfg, falso, projeto, "erro ao cobrar o cartao de credito", k=1)
    assert trechos[0].caminho == "src/pagamento.py"
    assert trechos[0].inicio == 1


def test_contexto_traz_trechos_e_lembrancas(cfg, projeto):
    falso = Falso()
    memoria.lembrar(
        cfg, falso, projeto, "mudar como cobrar o cartao de credito: usar o gateway novo", "decisao"
    )
    texto = memoria.contexto(cfg, falso, projeto, "mudar como cobrar o cartao de credito", k=2)
    assert "src/pagamento.py:1-3" in texto
    assert "usar o gateway novo" in texto
    assert "node_modules" not in texto


def test_projetos_nao_se_misturam(cfg, projeto, tmp_path):
    outro = tmp_path / "blog"
    outro.mkdir()
    (outro / "post.md").write_text("cartao de credito no blog", encoding="utf-8")
    falso = Falso()
    memoria.indexar(cfg, falso, projeto)
    memoria.indexar(cfg, falso, outro)
    assert {t.caminho for t in memoria.buscar(cfg, falso, outro, "cartao de credito")} == {
        "post.md"
    }


def test_pasta_fora_das_permitidas_e_lembranca_vazia(cfg, projeto):
    with pytest.raises(ErroExecucao):
        memoria.indexar(cfg, Falso(), "C:/Windows")
    with pytest.raises(ErroExecucao):
        memoria.lembrar(cfg, Falso(), projeto, "   ")


def test_ignora_copias_de_backup(cfg, projeto):
    copia = projeto / "skill-antiga-2026"
    copia.mkdir()
    (copia / "pagamento.py").write_text("cobrar cartao", encoding="utf-8")
    (projeto / "notas.bak").write_text("x", encoding="utf-8")
    nomes = {
        p.relative_to(projeto).as_posix()
        for p in memoria.arquivos_do_projeto(projeto, cfg.memoria.ignorar)
    }
    assert "skill-antiga-2026/pagamento.py" not in nomes
    assert "src/pagamento.py" in nomes


def test_texto_repetido_em_dois_arquivos_aparece_uma_vez(cfg, projeto):
    (projeto / "src" / "pagamento_copia.py").write_text(
        (projeto / "src" / "pagamento.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    falso = Falso()
    memoria.indexar(cfg, falso, projeto)
    trechos = memoria.buscar(cfg, falso, projeto, "cobrar o cartao de credito", k=3)
    textos = [t.texto for t in trechos]
    assert len(textos) == len(set(textos))


def test_projetos_sao_as_subpastas(cfg, projeto, tmp_path):
    (tmp_path / "blog").mkdir()
    (tmp_path / "old_site").mkdir()
    nomes = {p.name for p in memoria.projetos(cfg)}
    assert {"loja", "blog"} <= nomes
    assert "old_site" not in nomes


def test_esboco_mostra_funcoes_com_linha():
    texto = "import os\n\nclass Loja:\n    def vender(self):\n        pass\n# comentario\n"
    assert memoria.esboco(texto) == ["3: class Loja:", "4: def vender(self):"]
    assert memoria.esboco("# Loja\ntexto\n## Vendas\n", markdown=True) == [
        "1: # Loja",
        "3: ## Vendas",
    ]


def test_ler_relevante(cfg, projeto):
    grande = projeto / "src" / "grande.py"
    blocos = [f"def funcao_{i}():\n    return 'texto qualquer numero {i}'\n" for i in range(150)]
    blocos[120] = "def cobrar_cartao_credito():\n    # cobra o cartao de credito\n    pass\n"
    grande.write_text("\n".join(blocos), encoding="utf-8")
    falso = Falso()
    texto = memoria.ler_relevante(cfg, falso, grande, "cobrar cartao de credito", k=1)
    assert "def cobrar_cartao_credito" in texto
    assert "Mapa" in texto
    assert len(texto) < len(grande.read_text(encoding="utf-8"))
    pequeno = memoria.ler_relevante(cfg, falso, projeto / "README.md", "loja")
    assert "inteiro" in pequeno


def test_buscar_arquivos_acha_por_nome_parcial(cfg, tmp_path):
    (tmp_path / "relatorio.pdf").write_text("x")
    (tmp_path / "outro.txt").write_text("x")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "Relatorio_Final.pdf").write_text("x")
    achados = memoria.buscar_arquivos(cfg, "relatorio")
    nomes = {p.name for p in achados}
    assert nomes == {"relatorio.pdf", "Relatorio_Final.pdf"}


def test_buscar_arquivos_ignora_acento_caixa_e_pontuacao(cfg, tmp_path):
    (tmp_path / "Currículo.pdf").write_text("x")
    achados = memoria.buscar_arquivos(cfg, "curriculo pdf")
    assert [p.name for p in achados] == ["Currículo.pdf"]


def test_buscar_arquivos_pula_pastas_ignoradas(cfg, tmp_path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "relatorio.pdf").write_text("x")
    assert memoria.buscar_arquivos(cfg, "relatorio") == []


def test_buscar_arquivos_sem_achado(cfg, tmp_path):
    assert memoria.buscar_arquivos(cfg, "nada-disso-existe") == []
