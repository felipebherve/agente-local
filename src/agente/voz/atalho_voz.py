"""Atalho de voz (Ctrl+Alt+F): aperta uma vez para começar, aperta de novo para mandar.

O atalho do sistema só avisa quando a tecla é apertada, então cada aperto roda este script:
- se ninguém está gravando, começa a gravar (e guarda o PID num arquivo);
- se já tem uma gravação, cria o arquivo de parada (ela vê e para) e sai.
Funciona igual no Linux e no Windows (sem sinais do sistema).
A gravação também para sozinha no teto de tempo (MAX_S). Depois transcreve e manda pro
Maestro (comando direto, Ollama local, depois OmniRoute), igual texto e painel, e fica
registrado em dados/historico.jsonl — o painel web lê de lá. O botão do microfone do
painel chama este mesmo script, então os dois funcionam do mesmo jeito.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import wave
from pathlib import Path

import numpy as np

from agente.config import Config, carregar_config
from agente.llm import ClienteOllama

TAXA_PREFERIDA = 16000  # o Whisper trabalha em 16 kHz; se o microfone recusar, usa a dele
BLOCO_S = 0.1
MAX_S = 120.0  # teto absoluto: se esquecer de apertar de novo, manda sozinho
LIMIAR_RMS = 200  # abaixo disso é silêncio (int16: fala normal passa de 500)
PASTA_TMP = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir())
ARQUIVO_PID = PASTA_TMP / "agente-voz.pid"
ARQUIVO_PARAR = PASTA_TMP / "agente-voz.parar"
AUDIO_TMP = PASTA_TMP / "agente-voz.wav"
LIMITE_NOTIFICACAO = 220
ID_NOTIFICACAO = "4242"  # mesma notificação é trocada no lugar, em vez de empilhar

_parar = threading.Event()  # para testes e para quem usa gravar() no mesmo processo


def notificar(titulo: str, texto: str, segundos: int = 15) -> None:
    curto = texto
    if len(texto) > LIMITE_NOTIFICACAO:
        curto = texto[:LIMITE_NOTIFICACAO] + "… (veja tudo no painel)"
    try:
        subprocess.run(
            ["notify-send", "-a", "Agente local", "-r", ID_NOTIFICACAO, "-t", str(segundos * 1000),
             titulo, curto],
            check=False,
        )
    except FileNotFoundError:  # sem notify-send (ex.: Windows): só imprime
        print(f"{titulo}: {curto}")


def gravando_agora() -> int | None:
    """PID da gravação em andamento, ou None (limpa arquivo velho de gravação que morreu)."""
    try:
        pid = int(ARQUIVO_PID.read_text().strip())
    except (OSError, ValueError):
        return None
    import psutil

    if not psutil.pid_exists(pid):
        ARQUIVO_PID.unlink(missing_ok=True)
        return None
    return pid


def pedir_para_parar(_pid: int) -> None:
    ARQUIVO_PARAR.write_text("parar", encoding="utf-8")


def _deve_parar() -> bool:
    return _parar.is_set() or ARQUIVO_PARAR.exists()


def _dispositivo_entrada(cfg: Config) -> int | None:
    """Microfone escolhido na config (trecho do nome) ou o padrão do sistema."""
    import sounddevice as sd

    nome = (cfg.voz.microfone or "").lower()
    if not nome:
        return None
    for i, d in enumerate(sd.query_devices()):
        if nome in d["name"].lower() and d["max_input_channels"] > 0:
            return i
    return None  # não achou: usa o padrão em vez de falhar


def _taxa(dispositivo: int | None) -> int:
    import sounddevice as sd

    try:
        sd.check_input_settings(device=dispositivo, samplerate=TAXA_PREFERIDA, channels=1)
        return TAXA_PREFERIDA
    except Exception:  # noqa: BLE001 - cada driver levanta um erro diferente
        return int(sd.query_devices(dispositivo, "input")["default_samplerate"])


def gravar(cfg: Config) -> bool:
    """Grava até apertarem o atalho de novo ou chegar no teto. False = só silêncio."""
    import sounddevice as sd

    dispositivo = _dispositivo_entrada(cfg)
    taxa = _taxa(dispositivo)
    tamanho_bloco = int(taxa * BLOCO_S)
    blocos: list[np.ndarray] = []
    ouviu_fala = False
    tempo_total = 0.0

    with sd.InputStream(
        device=dispositivo, samplerate=taxa, channels=1, dtype="int16", blocksize=tamanho_bloco
    ) as stream:
        while tempo_total < MAX_S and not _deve_parar():
            bloco, _ = stream.read(tamanho_bloco)
            blocos.append(bloco.copy())
            tempo_total += BLOCO_S
            rms = float(np.sqrt(np.mean(bloco.astype(np.float64) ** 2)))
            if rms >= LIMIAR_RMS:
                ouviu_fala = True

    audio = np.concatenate(blocos) if blocos else np.zeros((0, 1), dtype=np.int16)
    with wave.open(str(AUDIO_TMP), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes(audio.tobytes())
    return ouviu_fala


def transcrever(cfg: Config) -> str:
    from faster_whisper import WhisperModel

    modelo = WhisperModel(cfg.voz.stt_cpu, device="cpu", compute_type="int8")
    segmentos, _ = modelo.transcribe(str(AUDIO_TMP), language="pt")
    return " ".join(s.text for s in segmentos).strip()


def responder(cfg: Config, pergunta: str) -> str:
    cliente = ClienteOllama.de_config(cfg)
    from agente import maestro

    r = maestro.perguntar(
        cfg,
        cliente,
        pergunta,
        encaminhar=lambda _p: "Isso aqui precisa do Claude — abra o Claude Code pra continuar.",
    )
    return r.resposta


def main() -> None:
    pid = gravando_agora()
    if pid is not None:  # segundo aperto: manda a gravação que está rodando parar
        pedir_para_parar(pid)
        return

    ARQUIVO_PARAR.unlink(missing_ok=True)
    ARQUIVO_PID.write_text(str(os.getpid()))
    cfg = carregar_config()
    from agente.braco import navegador as braco_navegador

    braco_navegador.NAVEGADOR_PROPRIO = True  # este processo termina logo após responder
    notificar("Ouvindo...", "Fale à vontade. Aperte Ctrl+Alt+F de novo para mandar.", int(MAX_S))
    try:
        try:
            ouviu = gravar(cfg)
        finally:
            ARQUIVO_PID.unlink(missing_ok=True)
            ARQUIVO_PARAR.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001 - microfone ocupado, não encontrado, etc.
        notificar("Erro na voz", f"Não consegui gravar: {exc}")
        sys.exit(1)

    if not ouviu:
        notificar("Agente local", "Não ouvi nada (só silêncio).")
        return

    notificar("Entendendo...", "Transcrevendo o que você disse.")
    pergunta = transcrever(cfg)
    if not pergunta:
        notificar("Agente local", "Não entendi o que foi dito.")
        return

    notificar(f"Você: {pergunta}", "Pensando...")
    notificar(f"Você: {pergunta}", responder(cfg, pergunta))


if __name__ == "__main__":
    main()
