"""Modo TDAH: ficha, nomes parecidos, registro de projetos novos e textos para o Claude."""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

import pytest

from agente import projetos_tdah as pt
from agente.config import Config

FICHA = """# Loja

Prioridade: Alta
Concluído: 40%
Próxima ação: terminar o carrinho

## Resumo
Site de vendas do cliente.

## Pronto
- [x] Página inicial

## Falta
- [ ] Carrinho
- Pagamento
"""


def test_ler_ficha() -> None:
    f = pt.ler_ficha(FICHA)
    assert f["prioridade"] == "alta"
    assert f["porcentagem"] == 40
    assert f["proxima"] == "terminar o carrinho"
    assert f["resumo"] == "Site de vendas do cliente."
    assert f["pronto"] == ["Página inicial"]
    assert f["falta"] == ["Carrinho", "Pagamento"]


def test_ficha_sem_porcentagem_conta_caixinhas() -> None:
    f = pt.ler_ficha("## Tarefas\n- [x] a\n- [ ] b\n- [x] c\n- [ ] d\n")
    assert f["porcentagem"] == 50
    assert pt.ler_ficha("")["porcentagem"] is None
    tabela = "| Fase | Situação |\n| --- | --- |\n| 0 | Concluída |\n| 1 | Pendente (x) |\n"
    assert pt.ler_ficha(tabela)["porcentagem"] == 50


def test_nomes_parecidos() -> None:
    nomes = ["Agente de IA", "agente-ia", "loja-api", "Diario", "diario_old"]
    assert pt.parecidos("agente_IA", nomes) == ["Agente de IA", "agente-ia"]
    assert "diario_old" in pt.parecidos("Diario", nomes)
    assert pt.parecidos("sala-de-aula", nomes) == []
    assert pt.normalizar("Código do Sistema") == "codigosistema"


@pytest.fixture
def cfg_tdah(tmp_path: Path, cfg: Config) -> Config:
    raiz = tmp_path / "projetos"
    (raiz / "loja").mkdir(parents=True)
    (raiz / "loja" / "STATUS.md").write_text(FICHA, encoding="utf-8")
    (raiz / "blog").mkdir()
    return replace(cfg, pastas_permitidas=(raiz,), pasta_dados=tmp_path / "dados")


def test_escanear_marca_novos_depois_da_primeira_vez(cfg_tdah: Config) -> None:
    primeira = pt.escanear(cfg_tdah)
    assert [p["nome"] for p in primeira] == ["loja", "blog"]  # prioridade alta no topo
    assert not any(p["novo"] for p in primeira)
    assert primeira[0]["tem_ficha"] and not primeira[1]["tem_ficha"]

    (cfg_tdah.pastas_permitidas[0] / "app").mkdir()
    novos = {p["nome"]: p["novo"] for p in pt.escanear(cfg_tdah)}
    assert novos == {"loja": False, "blog": False, "app": True}

    app = str(cfg_tdah.pastas_permitidas[0] / "app")
    pt.marcar_visto(cfg_tdah, app)
    assert not any(p["novo"] for p in pt.escanear(cfg_tdah))


def test_parado(cfg_tdah: Config) -> None:
    daqui_3h = time.time() + 3 * 3600
    assert all(p["parado"] for p in pt.escanear(cfg_tdah, agora=daqui_3h, parado_horas=2))
    assert not any(p["parado"] for p in pt.escanear(cfg_tdah, parado_horas=2))


def test_criar_ficha_nao_sobrescreve(cfg_tdah: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pt, "_modelo", lambda _c, _p: "Blog pessoal.")
    blog = cfg_tdah.pastas_permitidas[0] / "blog"
    (blog / "README.md").write_text("# Blog", encoding="utf-8")
    arq = pt.criar_ficha(cfg_tdah, str(blog))
    assert "Blog pessoal." in arq.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="já tem"):
        pt.criar_ficha(cfg_tdah, str(blog))
    with pytest.raises(ValueError, match="fora"):
        pt.criar_ficha(cfg_tdah, "/tmp")  # noqa: S108


def test_textos_para_o_claude(cfg_tdah: Config) -> None:
    projetos = pt.escanear(cfg_tdah)
    ctx = pt.contexto(projetos[0])
    assert "Projeto: loja" in ctx and "Próxima ação: terminar o carrinho" in ctx
    semana = pt.resumo_semanal(projetos)
    assert "loja | 40% | alta" in semana
    assert len(semana) < 1000


def test_modo_no_config(tmp_path: Path) -> None:
    arq = tmp_path / "config.yaml"
    arq.write_text("ollama_url: x\n", encoding="utf-8")
    pt.salvar_modo(arq, True, 3)
    from agente import configuracoes as conf

    assert pt.ler_modo(conf.ler_bloco(arq, "modo_tdah")) == pt.ModoTdah(True, 3.0)
    assert pt.ler_modo(None) == pt.ModoTdah()


# --- revisão V2 ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("valor", "esperado"), [(2, 2.0), ("3.5", 3.5), (0, 0.5), (-4, 0.5), (1000, 168.0)]
)
def test_horas_validas_limita(valor: object, esperado: float) -> None:
    assert pt.horas_validas(valor) == esperado


@pytest.mark.parametrize("valor", [None, "abc", float("nan"), True, [1]])
def test_horas_invalidas_dao_erro_claro(valor: object) -> None:
    with pytest.raises(ValueError, match="número"):
        pt.horas_validas(valor)


def test_ler_modo_com_horas_ruins_volta_ao_padrao() -> None:
    assert pt.ler_modo({"ligado": True, "parado_horas": "nan"}).parado_horas == 2.0


def test_registro_estragado_vira_copia_e_nao_some(cfg_tdah: Config) -> None:
    pt.salvar_registro(cfg_tdah, {"projetos": {"x": {}}})
    arq = cfg_tdah.pasta_dados / "projetos_tdah.json"
    arq.write_text("{meio escrito", encoding="utf-8")
    assert pt.ler_registro(cfg_tdah) == {}
    copias = list(cfg_tdah.pasta_dados.glob("projetos_tdah.estragado-*.json"))
    assert len(copias) == 1 and copias[0].read_text(encoding="utf-8") == "{meio escrito"


def test_gravacoes_em_paralelo_nao_perdem_nada(cfg_tdah: Config) -> None:
    import threading

    pt.escanear(cfg_tdah)
    caminhos = [p["caminho"] for p in pt.escanear(cfg_tdah)]

    def resumir(caminho: str) -> None:
        with pt._TRAVA:
            reg = pt.ler_registro(cfg_tdah)
            reg["projetos"][caminho]["resumo_auto"] = "ok"
            pt.salvar_registro(cfg_tdah, reg)

    threads = [threading.Thread(target=resumir, args=(c,)) for c in caminhos * 10]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    reg = pt.ler_registro(cfg_tdah)
    assert all(reg["projetos"][c]["resumo_auto"] == "ok" for c in caminhos)
    assert not list(cfg_tdah.pasta_dados.glob("*.tmp"))


def test_escanear_rapido_reaproveita_e_limpa(cfg_tdah: Config) -> None:
    pt.limpar_cache()
    primeira = pt.escanear_rapido(cfg_tdah)
    (cfg_tdah.pastas_permitidas[0] / "novo").mkdir()
    assert pt.escanear_rapido(cfg_tdah) is primeira
    pt.limpar_cache()
    assert "novo" in [p["nome"] for p in pt.escanear_rapido(cfg_tdah)]


def test_checar_nome(cfg_tdah: Config) -> None:
    assert "Pode criar" in pt.checar_nome(cfg_tdah, "sala de aula")
    texto = pt.checar_nome(cfg_tdah, "Loja")
    assert "loja" in texto and "40% pronto" in texto and "Site de vendas" in texto
    assert not (cfg_tdah.pasta_dados / "projetos_tdah.json").exists()  # só lê


def test_vigia_roda_uma_vez_so(cfg_tdah: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pt, "_arquivo_trava_vigia", None)
    monkeypatch.setattr(pt, "uma_rodada", lambda _cfg: None)
    assert pt._pegar_trava_vigia(cfg_tdah)
    dono = pt._arquivo_trava_vigia
    # outro processo (simulado: este perde a referência) não consegue a trava
    monkeypatch.setattr(pt, "_arquivo_trava_vigia", None)
    assert not pt._pegar_trava_vigia(cfg_tdah)
    dono.close()
    assert pt._pegar_trava_vigia(cfg_tdah)
    pt._arquivo_trava_vigia.close()


def test_uma_rodada_resume_no_maximo_dois(
    cfg_tdah: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    feitos: list[str] = []
    projetos = [
        {"nome": f"p{i}", "caminho": f"/p{i}", "git": True, "parado": True, "parado_horas": 5.0}
        for i in range(5)
    ]
    monkeypatch.setattr(pt, "modo_atual", lambda _c: pt.ModoTdah(ligado=True))
    monkeypatch.setattr(pt, "escanear", lambda *_a, **_k: projetos)
    monkeypatch.setattr(pt, "resumir_commits", lambda _c, cam: feitos.append(cam) or "")
    pt.uma_rodada(cfg_tdah, agora=time.time())
    assert feitos == ["/p0", "/p1"]


def test_sem_ficha_usa_readme_e_lista_o_que_tem(tmp_path: Path) -> None:
    api = tmp_path / "api"
    api.mkdir()
    (api / "README.md").write_text(
        "﻿# API\n\n🔗 site\n\nUma API de tarefas.\n\n## Próximos passos\n\n- Paginação\n",
        encoding="utf-8",
    )
    f = pt.ficha_do_leiame(api)
    assert f["resumo"] == "Uma API de tarefas." and f["falta"] == ["Paginação"]
    drv = tmp_path / "drivers"
    (drv / "8821cu").mkdir(parents=True)
    assert "8821cu/" in pt.ficha_do_leiame(drv)["resumo"]
    (tmp_path / "vazia").mkdir()
    assert pt.ficha_do_leiame(tmp_path / "vazia")["resumo"] == "Pasta vazia."


def test_status_sem_resumo_prefere_readme(cfg_tdah: Config) -> None:
    loja = cfg_tdah.pastas_permitidas[0] / "loja"
    (loja / "STATUS.md").write_text("# Loja\n\nAtualizado em 2026-10-26.\n\nConcluído: 50%\n")
    (loja / "README.md").write_text("# Loja\n\nSite de vendas.\n", encoding="utf-8")
    p = next(x for x in pt.escanear(cfg_tdah) if x["nome"] == "loja")
    assert p["resumo"] == "Site de vendas." and p["porcentagem"] == 50


def test_detalhes_guarda_explicacao_e_so_refaz_se_mudar(
    cfg_tdah: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    chamadas: list[str] = []

    def modelo(_cfg: Config, pergunta: str, *_a: object, **_k: object) -> str:
        chamadas.append(pergunta)
        return "<think>hm</think>SERVE: Vende **coisas**.\nEXPLICA: Um site.\nESTADO: Quase pronto."

    monkeypatch.setattr(pt, "_modelo", modelo)
    loja = str(cfg_tdah.pastas_permitidas[0] / "loja")
    d = pt.detalhes(cfg_tdah, loja)
    assert d["explicacao"] == {
        "serve": "Vende coisas.",
        "explica": "Um site.",
        "estado": "Quase pronto.",
    }
    assert d["mapa"]["arquivos"] == 1 and d["mapa"]["itens"][0]["nome"] == "STATUS.md"
    assert "Site de vendas" in d["leiame"]  # sem README, usa o primeiro .md
    pt.detalhes(cfg_tdah, loja)
    assert len(chamadas) == 1  # guardada
    (cfg_tdah.pastas_permitidas[0] / "loja" / "novo.py").write_text("x")
    pt.detalhes(cfg_tdah, loja)
    assert len(chamadas) == 2  # a pasta mudou
    pt.limpar_cache()
    card = next(p for p in pt.escanear(cfg_tdah) if p["nome"] == "loja")
    assert card["serve"] == "Vende coisas."
    with pytest.raises(ValueError):
        pt.detalhes(cfg_tdah, "/etc")


def test_falta_das_caixinhas_e_link_do_claude() -> None:
    f = pt.ler_ficha(
        "# X\n\nClaude: https://claude.ai/project/abc123\n\n## Tarefas\n- [x] a\n- [ ] b\n- [ ] c\n"
    )
    assert f["porcentagem"] == 33 and f["falta"] == ["b", "c"]
    assert f["claude"] == "https://claude.ai/project/abc123"
    assert pt.ler_ficha("Claude: site falso https://evil.com")["claude"] == ""
