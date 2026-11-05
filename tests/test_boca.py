from agente.voz.boca import limpar


def test_limpar_tira_etiqueta_de_origem_no_comeco():
    assert limpar("[Ollama local · qwen3:8b] Canberra.") == "Canberra."
    assert limpar("[OmniRoute · gpt-4o-mini] Tóquio.") == "Tóquio."


def test_limpar_nao_mexe_em_colchete_que_nao_esta_no_comeco():
    assert limpar("A lista tem [1] e [2] itens.") == "A lista tem [1] e [2] itens."


def test_limpar_tira_markdown_e_links():
    assert limpar("**negrito** e `codigo` e # titulo") == "negrito e codigo e titulo"
    assert limpar("veja [aqui](https://exemplo.com)") == "veja aqui"
    assert limpar("acesse https://exemplo.com/pagina") == "acesse link"


def test_limpar_tira_bloco_de_codigo():
    texto = limpar("antes\n```python\nprint(1)\n```\ndepois")
    assert "(trecho de código)" in texto
    assert "print(1)" not in texto
