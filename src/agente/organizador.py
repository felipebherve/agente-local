"""Levantamento de uma pasta: inventário, duplicados e sugestão de estrutura.

O levantamento (varrer/duplicados/resumir/sugerir_estrutura/gerar_relatorio) é só
leitura — nunca move, renomeia ou apaga nada. Pensado pra pasta grande: duplicata é
achada por tamanho -> pedaço do início/fim -> hash completo (só quando precisa), pra não
ler cada arquivo inteiro sem necessidade. A sugestão de estrutura manda só um resumo pro
OmniRoute (contagens, não o conteúdo dos arquivos), pra gastar pouco.

A limpeza de duplicados (gerar_plano_duplicados_e_salvar/aplicar_plano_lixo) é em duas
etapas de propósito: primeiro só decide e grava o plano em disco (nada se move), depois
de revisado o plano é aplicado. Em nenhuma etapa um arquivo é apagado — o que sobra vira
cópia e vai pra "lixo/duplicados/" dentro da própria pasta, preservando a estrutura de
pastas original, pra quem quiser revisar ou desfazer manualmente.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from agente.config import Config

logger = logging.getLogger(__name__)

PEDACO = 65536  # 64 KB do início e do fim, pra desempatar tamanho igual sem ler tudo

SISTEMA_SUGESTAO = (
    "Você recebeu um resumo (contagens, não o conteúdo) de uma pasta pessoal bagunçada: "
    "fotos, documentos, projetos de programação misturados. Sugira uma estrutura de "
    "pastas para organizar isso, em português do Brasil, curta (até 15 linhas), só com "
    "nomes de pasta e uma frase do que vai em cada uma. Não invente nome de arquivo "
    "específico que não apareça no resumo."
)


@dataclass(frozen=True)
class Arquivo:
    caminho: str
    tamanho: int
    modificado: str
    extensao: str


def varrer(pasta: Path) -> list[Arquivo]:
    """Lista todo arquivo da pasta (recursivo), sem ler o conteúdo."""
    arquivos: list[Arquivo] = []
    for caminho in pasta.rglob("*"):
        if caminho.is_symlink() or not caminho.is_file():
            continue
        try:
            st = caminho.stat()
        except OSError as exc:
            logger.warning("não consegui ler %s: %s", caminho, exc)
            continue
        arquivos.append(
            Arquivo(
                caminho=str(caminho),
                tamanho=st.st_size,
                modificado=datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d"),
                extensao=caminho.suffix.lower() or "(sem extensão)",
            )
        )
    return arquivos


def _pedaco(caminho: str, tamanho: int) -> bytes:
    with open(caminho, "rb") as f:
        inicio = f.read(PEDACO)
        if tamanho <= PEDACO:
            return inicio
        f.seek(max(0, tamanho - PEDACO))
        return inicio + f.read(PEDACO)


def _hash_completo(caminho: str) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def duplicados(arquivos: list[Arquivo]) -> list[list[Arquivo]]:
    """Grupos de arquivo idêntico. Só lê o que precisa pra ter certeza."""
    por_tamanho: dict[int, list[Arquivo]] = defaultdict(list)
    for a in arquivos:
        if a.tamanho > 0:
            por_tamanho[a.tamanho].append(a)

    grupos: list[list[Arquivo]] = []
    for tamanho, candidatos in por_tamanho.items():
        if len(candidatos) < 2:
            continue
        por_pedaco: dict[bytes, list[Arquivo]] = defaultdict(list)
        for a in candidatos:
            try:
                por_pedaco[_pedaco(a.caminho, a.tamanho)].append(a)
            except OSError as exc:
                logger.warning("não consegui ler %s: %s", a.caminho, exc)
        for mesmos in por_pedaco.values():
            if len(mesmos) < 2:
                continue
            if tamanho <= PEDACO * 2:
                grupos.append(mesmos)  # o pedaço já cobriu o arquivo inteiro
                continue
            por_hash: dict[str, list[Arquivo]] = defaultdict(list)
            for a in mesmos:
                try:
                    por_hash[_hash_completo(a.caminho)].append(a)
                except OSError as exc:
                    logger.warning("não consegui ler %s: %s", a.caminho, exc)
            grupos.extend(g for g in por_hash.values() if len(g) > 1)
    return grupos


def resumir(arquivos: list[Arquivo], pasta: Path, grupos: list[list[Arquivo]]) -> dict[str, Any]:
    por_ext: dict[str, int] = defaultdict(int)
    for a in arquivos:
        por_ext[a.extensao] += 1
    try:
        subpastas = sorted(p.name for p in pasta.iterdir() if p.is_dir())
    except OSError:
        subpastas = []
    return {
        "pasta": str(pasta),
        "total_arquivos": len(arquivos),
        "tamanho_total_gb": round(sum(a.tamanho for a in arquivos) / 1e9, 2),
        "subpastas_de_primeiro_nivel": subpastas,
        "por_extensao": sorted(por_ext.items(), key=lambda x: -x[1])[:25],
        "grupos_duplicados": len(grupos),
        "espaco_duplicado_gb": round(
            sum((len(g) - 1) * g[0].tamanho for g in grupos) / 1e9, 2
        ),
    }


def sugerir_estrutura(cfg: Config, resumo: dict[str, Any]) -> str:
    from agente import nuvem

    texto = json.dumps(resumo, ensure_ascii=False, indent=2)
    resposta = nuvem.perguntar(cfg, texto, SISTEMA_SUGESTAO)
    if resposta is None:
        return "(Nenhuma IA grátis respondeu agora — sem sugestão de estrutura por enquanto.)"
    return f"[OmniRoute · {resposta.modelo}] {resposta.texto}"


def _slug(nome: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", nome.lower()).strip("-") or "pasta"


def _quebravel(texto: str) -> str:
    """Caminho de pasta não tem espaço pra quebrar linha; garante um ponto de quebra."""
    return texto.replace("/", "/ ").replace("\\", "\\ ")


def _gerar_pdf(caminho: Path, pasta: Path, resumo: dict[str, Any], sugestao: str) -> None:
    from fpdf import FPDF, XPos, YPos

    def linha(altura: float, texto: str) -> None:
        # sem new_x/new_y, o cursor fica na borda direita e a próxima linha "não cabe".
        # a IA pode escrever caractere fora do cp1252 (emoji etc.): troca por "?" em vez
        # de quebrar o relatório inteiro.
        seguro = texto.encode("cp1252", errors="replace").decode("cp1252")
        pdf.multi_cell(0, altura, seguro, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf = FPDF()
    pdf.core_fonts_encoding = "cp1252"  # a IA costuma usar "–", aspas curvas etc.
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    linha(9, "Levantamento de pasta")
    pdf.set_font("Helvetica", "", 10)
    linha(6, _quebravel(str(pasta)))
    pdf.ln(2)
    pdf.set_font("Helvetica", "", 11)
    linha(7, f"Total de arquivos: {resumo['total_arquivos']}")
    linha(7, f"Tamanho total: {resumo['tamanho_total_gb']} GB")
    linha(7, f"Grupos de arquivo duplicado: {resumo['grupos_duplicados']}")
    linha(7, f"Espaço desperdiçado em duplicatas: {resumo['espaco_duplicado_gb']} GB")
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 13)
    linha(8, "Por tipo de arquivo")
    pdf.set_font("Helvetica", "", 10)
    for ext, qtd in resumo["por_extensao"]:
        linha(6, f"{ext}: {qtd} arquivos")
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 13)
    linha(8, "Sugestão de organização")
    pdf.set_font("Helvetica", "", 10)
    linha(6, _quebravel(sugestao))
    pdf.output(str(caminho))


def gerar_relatorio(cfg: Config, pasta: Path) -> tuple[Path, dict[str, Any]]:
    """Varre, acha duplicados e pede sugestão. Grava tudo em dados/organizador/<pasta>/.

    Devolve a pasta do relatório e o resumo (números), pra responder curto.
    """
    destino = cfg.pasta_dados / "organizador" / _slug(pasta.name)
    destino.mkdir(parents=True, exist_ok=True)

    arquivos = varrer(pasta)
    grupos = duplicados(arquivos)
    resumo = resumir(arquivos, pasta, grupos)
    sugestao = sugerir_estrutura(cfg, resumo)

    (destino / "inventario.json").write_text(
        json.dumps([asdict(a) for a in arquivos], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    linhas = [f"# Arquivos duplicados em {pasta}\n"]
    maiores = sorted(grupos, key=lambda g: -(len(g) - 1) * g[0].tamanho)
    for g in maiores[:200]:
        desperdicio_mb = (len(g) - 1) * g[0].tamanho / 1e6
        linhas.append(f"\n## {len(g)} cópias, {desperdicio_mb:.1f} MB desperdiçados")
        linhas.extend(f"- {a.caminho}" for a in g)
    (destino / "duplicados.md").write_text("\n".join(linhas), encoding="utf-8")

    (destino / "sugestao.md").write_text(
        f"# Sugestão de estrutura para {pasta}\n\n{sugestao}\n", encoding="utf-8"
    )

    (destino / "resumo.json").write_text(
        json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    _gerar_pdf(destino / "relatorio.pdf", pasta, resumo, sugestao)
    return destino, resumo


def _mais_antigo(grupo: list[Arquivo]) -> Arquivo:
    """Escolhe o "original" do grupo: o mais antigo e, empatando, o de caminho mais curto."""
    return min(grupo, key=lambda a: (a.modificado, len(a.caminho), a.caminho))


def gerar_plano_lixo_duplicados(pasta: Path, grupos: list[list[Arquivo]]) -> dict[str, Any]:
    """Decide, por grupo de duplicado, qual arquivo fica e quais vão pro lixo. Não move nada."""
    entradas = []
    for grupo in grupos:
        manter = _mais_antigo(grupo)
        for a in grupo:
            if a.caminho == manter.caminho:
                continue
            entradas.append({"manter": manter.caminho, "mover": a.caminho, "tamanho": a.tamanho})
    return {
        "pasta": str(pasta),
        "total_grupos": len(grupos),
        "total_arquivos_a_mover": len(entradas),
        "total_bytes_a_mover": sum(e["tamanho"] for e in entradas),
        "entradas": entradas,
    }


def _destino_lixo(pasta: Path, caminho_original: str) -> Path:
    rel = Path(caminho_original).relative_to(pasta)
    return pasta / "lixo" / "duplicados" / rel


def executar_plano_lixo(pasta: Path, plano: dict[str, Any]) -> dict[str, Any]:
    """Move de fato os arquivos do plano pra lixo/duplicados, preservando a estrutura de
    pastas original (pra dar pra rastrear de onde veio). Nunca apaga — só move."""
    movidos = 0
    bytes_movidos = 0
    erros: list[str] = []
    for entrada in plano["entradas"]:
        origem = Path(entrada["mover"])
        if not origem.exists():
            erros.append(f"não existe mais: {origem}")
            continue
        destino = _destino_lixo(pasta, entrada["mover"])
        destino.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(origem), str(destino))
            movidos += 1
            bytes_movidos += entrada["tamanho"]
        except OSError as exc:
            erros.append(f"erro movendo {origem}: {exc}")
    return {"movidos": movidos, "bytes_movidos": bytes_movidos, "erros": erros}


def gerar_plano_duplicados_e_salvar(cfg: Config, pasta: Path) -> tuple[Path, dict[str, Any]]:
    """Varre, acha duplicados e grava o plano de limpeza em dados/organizador/<pasta>/.

    Só decide e grava — nenhum arquivo é movido aqui. Revise plano_lixo.md e só então
    chame aplicar_plano_lixo.
    """
    destino = cfg.pasta_dados / "organizador" / _slug(pasta.name)
    destino.mkdir(parents=True, exist_ok=True)

    arquivos = varrer(pasta)
    grupos = duplicados(arquivos)
    plano = gerar_plano_lixo_duplicados(pasta, grupos)

    (destino / "plano_lixo.json").write_text(
        json.dumps(plano, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    linhas = [
        f"# Plano: mover duplicatas para lixo em {pasta}\n",
        f"\nGrupos de duplicado: {plano['total_grupos']}",
        f"\nArquivos a mover: {plano['total_arquivos_a_mover']}",
        f"\nEspaço a liberar: {plano['total_bytes_a_mover'] / 1e9:.2f} GB",
        "\n\nNada foi movido ainda. Revise e só confirme a execução depois.\n",
        "\n## Primeiros 50 exemplos\n",
    ]
    for e in plano["entradas"][:50]:
        linhas.append(f"- mantém `{e['manter']}`, move `{e['mover']}`")
    (destino / "plano_lixo.md").write_text("\n".join(linhas), encoding="utf-8")

    return destino, plano


def aplicar_plano_lixo(cfg: Config, pasta: Path) -> dict[str, Any]:
    """Lê o plano_lixo.json já gravado (de gerar_plano_duplicados_e_salvar) e executa."""
    destino = cfg.pasta_dados / "organizador" / _slug(pasta.name)
    plano = json.loads((destino / "plano_lixo.json").read_text(encoding="utf-8"))
    resultado = executar_plano_lixo(pasta, plano)
    (destino / "resultado_lixo.json").write_text(
        json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return resultado
