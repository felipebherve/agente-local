from agente.compactar import compactar


def test_repeticoes_viram_contagem():
    texto = "\n".join(["PASSED test_a"] * 200 + ["FAILED test_login - 401"])
    saida = compactar(texto)
    assert saida.splitlines() == ["PASSED test_a  (x200)", "FAILED test_login - 401"]


def test_texto_grande_mantem_erros_e_final():
    linhas = [f"ok linha {i}" for i in range(5000)]
    linhas.insert(10, "Traceback: ValueError no parser")
    saida = compactar("\n".join(linhas), limite=3000)
    assert "Traceback: ValueError no parser" in saida
    assert "ok linha 4999" in saida
    assert "omitidas" in saida
    assert len(saida) <= 3000


def test_texto_curto_nao_muda():
    assert compactar("a\nb") == "a\nb"
