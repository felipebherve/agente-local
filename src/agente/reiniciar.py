"""Reinicia o Claude Desktop sozinho (para carregar ferramentas novas do agente).

O comando roda num processo criado pelo WMI (Win32_Process.Create), fora da árvore do
Claude: assim ele continua vivo quando o Claude (e o servidor MCP que ele abriu) fecha.
"""

from __future__ import annotations

import base64
import logging
import subprocess

from agente.executor import ErroExecucao

logger = logging.getLogger(__name__)

APP_ID_PADRAO = "Claude_pzs8sxrjxfjjc!Claude"  # versão da Microsoft Store

SCRIPT = (
    "Start-Sleep -Seconds {atraso}; "
    "Get-Process claude -ErrorAction SilentlyContinue | Stop-Process -Force; "
    "Start-Sleep -Seconds 3; "
    "$app = (Get-StartApps | Where-Object Name -eq 'Claude' | Select-Object -First 1).AppID; "
    "if (-not $app) {{ $app = '{padrao}' }}; "
    "Start-Process ('shell:AppsFolder\\' + $app)"
)


def comando(atraso_s: int = 3) -> str:
    """Linha de comando do processo que fecha e reabre o Claude (script em base64)."""
    script = SCRIPT.format(atraso=atraso_s, padrao=APP_ID_PADRAO)
    codificado = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return f"powershell.exe -NoProfile -WindowStyle Hidden -EncodedCommand {codificado}"


def reiniciar_claude(atraso_s: int = 3) -> str:
    """Agenda o reinício e volta na hora: o Claude fecha em atraso_s segundos e reabre."""
    criar = (
        "(Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
        f"-Arguments @{{CommandLine='{comando(atraso_s)}'}}).ReturnValue"
    )
    try:
        saida = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", criar],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ErroExecucao(f"não consegui agendar o reinício do Claude: {exc}") from exc
    if saida.stdout.strip() != "0":
        detalhe = (saida.stdout + saida.stderr).strip()[:200]
        raise ErroExecucao(f"o Windows recusou o reinício do Claude: {detalhe}")
    logger.info("reinício do Claude agendado em %d s", atraso_s)
    return f"O Claude fecha em {atraso_s} s e abre de novo sozinho (uns 10 s no total)."
