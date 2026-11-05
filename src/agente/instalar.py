"""Registra o agente no Claude de forma global (Desktop e Code), para todos os projetos."""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

NOME_SERVIDOR = "agente-local"
INICIO = "<!-- agente-local:inicio -->"
FIM = "<!-- agente-local:fim -->"
# Só entra quando o módulo de vagas existe (ele não vai na versão pública).
LINHA_VAGAS = (
    """- Vagas de emprego: `buscar_vagas` (url da busca) lista títulos e links; `ler_vaga` (url)
  devolve só a ficha da vaga. Nunca leia a página de vaga inteira.
"""
    if importlib.util.find_spec("agente.vagas")
    else ""
)
INSTRUCOES = f"""{INICIO}
## Agente local (economia de tokens)

Existe um servidor MCP `agente-local` rodando de graça no PC do usuário (Ollama na placa de vídeo).

**Em toda conversa, comece chamando `pedir_ao_agente`** com o pedido do usuário (e `pasta`
quando for sobre um projeto). O Maestro liga o agente certo (Revisor, testes, git, Memória
ou Cérebro), desliga depois e devolve a resposta curta. Só faça você mesmo o que voltar
"PRECISA DO CLAUDE". Ao terminar uma tarefa, diga quanto o agente poupou
(`relatorio_economia`).

Delegue a ele o trabalho mecânico e leia só o resumo que ele devolve:
- Testes: `rodar_testes` em vez de rodar e ler a saída inteira no terminal.
- Git: `git_status`, `git_pull`, `git_criar_branch`, `git_commit` (sem mensagem, ele
  escreve uma), `git_merge`, `git_push`.
- PR: `abrir_pr` abre em rascunho com título e descrição gerados localmente.
- Arquivos e saídas longas: `resumir_arquivo` e `resumir_texto`.
- Antes de explorar um projeto: `contexto_projeto` (pasta + tarefa) devolve só os trechos
  relevantes e as decisões já tomadas. Ao decidir algo ou resolver um erro difícil, guarde
  com `lembrar` para não repetir a conversa depois.
- Arquivo grande (mais de ~150 linhas): `ler_relevante` (arquivo + tarefa) devolve o mapa
  das funções com linhas e só os trechos ligados à tarefa, em vez do arquivo inteiro.
- Antes de revisar código ou dar uma tarefa como pronta: `revisar_projeto` (pasta) roda
  lint, tipos, testes e procura senhas e conflitos nas alterações; leia só os problemas.
  Com o Revisor ligado, `git_commit` se recusa a commitar senha ou marca de conflito.
{LINHA_VAGAS}- Rascunhos simples e dúvidas rápidas: `perguntar_local`, revisando o resultado.
- Segunda opinião antes de seguir com uma decisão, código ou plano: `segunda_opiniao`
  (é um modelo pequeno, confira antes de agir).
- Sites: `navegador_abrir`, `navegador_ler`, `navegador_clicar`, `navegador_preencher`,
  `navegador_tecla` (a página vem como lista numerada em texto, sem print).
- Apps do Windows: `abrir_app`, `janelas_listar`, `janela_ler`, `janela_clicar`,
  `janela_digitar`; `tela_clicar` acha um botão pelo nome em qualquer janela.
- Ver a tela sem receber imagem: `tela_descrever`.
- Carregar ferramentas novas do agente: `reiniciar_claude` (com o OK do usuário).
- Voz: `falar` lê a resposta em voz alta no PC quando o usuário pedir para ouvir.
- "PRECISA DE CONFIRMAÇÃO": pergunte ao usuário antes de repetir com confirmado=true.
- "ERRO no agente local": siga normalmente sem ele.
{FIM}
"""


def _executavel_mcp() -> str:
    pasta = Path(sys.executable).parent
    exe = pasta / ("agente-mcp.exe" if os.name == "nt" else "agente-mcp")
    if not exe.exists():
        raise FileNotFoundError(f"{exe} não existe; rode 'pip install -e .' no venv do agente")
    return str(exe)


def _configs_desktop() -> list[Path]:
    """Caminhos do Claude Desktop: instalação comum e versão da Microsoft Store."""
    caminhos: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        caminhos.append(Path(appdata) / "Claude" / "claude_desktop_config.json")
    local = os.environ.get("LOCALAPPDATA")
    if local:
        for pacote in (Path(local) / "Packages").glob("Claude_*"):
            caminhos.append(
                pacote / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json"
            )
        # Versões novas da Store guardam os dados do usuário fora do pacote
        caminhos.extend((Path(local) / "Claude-Data").glob("claude_*/claude_desktop_config.json"))
    return caminhos


def _backup(arquivo: Path) -> None:
    if arquivo.exists():
        carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(arquivo, arquivo.with_name(f"{arquivo.name}.bak-{carimbo}"))


def registrar_servidor(arquivo: Path, comando: str) -> bool:
    """Adiciona o servidor em mcpServers sem tocar no resto. Devolve True se mudou algo."""
    dados: dict[str, Any] = {}
    if arquivo.exists():
        try:
            dados = json.loads(arquivo.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"{arquivo} não é um JSON válido; não mexi nele: {exc}") from exc
    entrada = {"type": "stdio", "command": comando, "args": []}
    servidores = dados.setdefault("mcpServers", {})
    if servidores.get(NOME_SERVIDOR) == entrada:
        return False
    _backup(arquivo)
    servidores[NOME_SERVIDOR] = entrada
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8")
    return True


def registrar_instrucoes(arquivo: Path) -> bool:
    """Coloca (ou atualiza) o bloco de instruções no CLAUDE.md global."""
    atual = arquivo.read_text(encoding="utf-8") if arquivo.exists() else ""
    if INICIO in atual and FIM in atual:
        antes, resto = atual.split(INICIO, 1)
        novo = antes + INSTRUCOES.rstrip("\n") + resto.split(FIM, 1)[1]
    else:
        novo = (atual.rstrip("\n") + "\n\n" if atual else "") + INSTRUCOES
    if novo == atual:
        return False
    _backup(arquivo)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(novo, encoding="utf-8")
    return True


def instalar_no_claude() -> list[str]:
    """Registra o MCP no Claude Desktop e no Claude Code (escopo de usuário) e as instruções."""
    comando = _executavel_mcp()
    casa = Path.home()
    relatorio: list[str] = []
    alvos = [*_configs_desktop(), casa / ".claude.json"]
    for alvo in alvos:
        try:
            mudou = registrar_servidor(alvo, comando)
            relatorio.append(f"{'registrado' if mudou else 'já estava'}: {alvo}")
        except (OSError, ValueError) as exc:
            logger.error("falha ao registrar em %s: %s", alvo, exc)
            relatorio.append(f"FALHOU: {alvo} ({exc})")
    claude_md = casa / ".claude" / "CLAUDE.md"
    try:
        mudou = registrar_instrucoes(claude_md)
        relatorio.append(
            f"{'instruções gravadas' if mudou else 'instruções já estavam'}: {claude_md}"
        )
    except OSError as exc:
        logger.error("falha ao gravar %s: %s", claude_md, exc)
        relatorio.append(f"FALHOU: {claude_md} ({exc})")
    return relatorio
