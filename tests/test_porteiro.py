from dataclasses import dataclass

import pytest

from agente import porteiro
from agente.porteiro import calcular, triar


@dataclass
class Resposta:
    texto: str


class Cerebro:
    def __init__(self, *respostas):
        self.respostas = list(respostas)
        self.perguntas = []

    def conversar(self, modelo, pergunta, sistema=None, temperatura=0.2):
        self.perguntas.append((sistema, pergunta))
        return Resposta(self.respostas.pop(0))


@pytest.mark.parametrize(
    ("pedido", "destino"),
    [
        ("Qual a capital da Austrália?", "local"),
        ("o que é uma API?", "local"),
        ("traduz 'good morning' para português", "local"),
        ("12 * (3 + 4)", "conta"),
        ("acorda", "comando"),
        ("implementa login com Google no site loja", "claude"),
        ("corrija o bug do botão de exportar", "claude"),
        ("por que o meu projeto falavado não abre a página de narração", "claude"),
        ("```py\nprint(1)\n```\nexplica", "claude"),
    ],
)
def test_triagem_por_regras(pedido, destino):
    assert triar(pedido).destino == destino


def test_texto_longo_colado_para_resumir_fica_local():
    texto = "resuma isto:\n" + "\n".join(f"linha {i} de um relatório" for i in range(30))
    assert triar(texto).destino == "local"


def test_cerebro_so_desempata_quando_as_regras_nao_bastam():
    chamadas = []
    pedido = "me conta umas ideias de presente de aniversário para minha mãe que gosta de plantas"
    decisao = triar(pedido, lambda p: chamadas.append(p) or "LOCAL")
    assert decisao.destino == "local" and chamadas == [pedido]
    assert triar("Qual a capital da Austrália?", lambda p: chamadas.append(p) or "CLAUDE")
    assert len(chamadas) == 1  # pergunta curta nem chega no modelo


def test_calcular_sem_eval():
    assert calcular("2 + 3 x 4") == 14
    assert calcular("10 / 4") == 2.5
    assert calcular("2^10") == 1024
    with pytest.raises(ValueError):
        calcular("__import__('os')")
    with pytest.raises(ValueError):
        calcular("9 ^ 999999")


def test_resolve_local_e_registra_economia(cfg):
    r = porteiro.resolver(cfg, Cerebro("Camberra."), "Qual a capital da Austrália?")
    assert r.destino == "local"
    assert r.resposta == f"[Ollama local · {cfg.modelos.cerebro}] Camberra."
    assert (cfg.pasta_logs / "economia.jsonl").exists()


def test_quando_o_cerebro_nao_sabe_e_nuvem_tambem_nao_vai_ao_claude(cfg):
    enviados = []
    r = porteiro.resolver(
        cfg,
        Cerebro("PRECISA DO CLAUDE"),
        "Qual o horário do meu dentista?",
        encaminhar=lambda p: enviados.append(p) or "mandei",
        perguntar_nuvem=lambda p: None,
    )
    assert r == porteiro.Resultado("claude", "mandei")
    assert enviados == ["Qual o horário do meu dentista?"]


def test_quando_o_cerebro_nao_sabe_tenta_a_nuvem_antes_do_claude(cfg):
    from agente.nuvem import Resposta as NuvemResposta

    enviados = []
    perguntas_nuvem = []
    r = porteiro.resolver(
        cfg,
        Cerebro("PRECISA DO CLAUDE"),
        "O que é fotossíntese?",
        encaminhar=lambda p: enviados.append(p) or "mandei",
        perguntar_nuvem=lambda p: perguntas_nuvem.append(p)
        or NuvemResposta("gpt-4o-mini", "É o processo que as plantas usam pra..."),
    )
    assert r == porteiro.Resultado(
        "nuvem", "[OmniRoute · gpt-4o-mini] É o processo que as plantas usam pra..."
    )
    assert perguntas_nuvem == ["O que é fotossíntese?"]
    assert enviados == []  # não precisou do Claude


def test_conta_e_comando_nao_usam_o_modelo(cfg):
    cerebro = Cerebro()
    assert porteiro.resolver(cfg, cerebro, "2+2").resposta == "2+2 = 4"
    r = porteiro.resolver(cfg, cerebro, "dorme", executar_comando=lambda p: "Dormindo.")
    assert r.resposta == "Dormindo."
    assert cerebro.perguntas == []


def test_mandar_ao_claude_com_dica_do_projeto(cfg, tmp_path):
    (tmp_path / "falavado").mkdir()
    copiado, abertos = [], []
    aviso = porteiro.mandar_ao_claude(
        cfg, "melhora a narração do falavado", copiado.append, lambda: abertos.append(1)
    )
    assert "Ctrl+V" in aviso and abertos == [1]
    assert copiado[0].startswith("melhora a narração do falavado")
    assert str(tmp_path / "falavado") in copiado[0]


@pytest.mark.parametrize(
    "pedido",
    [
        "O que você pode fazer por mim?",
        "o que vc sabe fazer",
        "Oi, quem é você?",
        "ajuda",
        "Como você pode me ajudar?",
        "pra que você serve?",
    ],
)
def test_pergunta_sobre_o_agente_tem_resposta_fixa_sem_modelo(cfg, pedido):
    cerebro = Cerebro()
    r = porteiro.resolver(cfg, cerebro, pedido)
    assert r.destino == "local"
    assert r.resposta.startswith("Sou o Agente Local")
    assert "testes" in r.resposta and "fotos" in r.resposta
    assert cerebro.perguntas == []  # nenhum modelo inventa uma profissão


def test_o_que_e_algo_continua_indo_ao_modelo():
    assert triar("o que é uma API?").destino == "local"
    assert triar("o que você acha de python?").destino != "ajuda"


def test_prompts_dizem_quem_e_o_agente(cfg):
    local = porteiro.sistema(porteiro.SISTEMA_LOCAL, cfg)
    assert "Agente Local" in local and "NÃO tem outra especialidade" in local
    assert "Agente Local" in porteiro.sistema(porteiro.SISTEMA_NUVEM, cfg)
