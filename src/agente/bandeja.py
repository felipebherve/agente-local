"""App "Acordar Agente": ícone na bandeja do Windows para acordar, pôr para dormir e ver o status.

O agente funciona no Claude mesmo sem este app (o Ollama carrega o modelo sozinho na primeira
pergunta); a bandeja serve para deixar tudo pronto antes e liberar a placa de vídeo depois.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agente import atalho, atividade, economia, ferramentas, historico, lancador, recursos
from agente.braco import seguranca
from agente.config import Config, ErroConfig, carregar_config
from agente.executor import ErroExecucao
from agente.llm import ClienteOllama, ErroOllama
from agente.logs import configurar_logs
from agente.painel import Agente, Interface, futuros
from agente.voz import ErroVoz
from agente.voz.conversa import SISTEMA_FALADO, Pedido, interpretar

logger = logging.getLogger(__name__)

INTERVALO_S = 5
VRAM_CEREBRO_GB = 6.0  # qwen3:8b na placa de vídeo, com folga
VRAM_WHISPER_GB = 1.5
APP_OLLAMA = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama app.exe"


@dataclass(frozen=True)
class Estado:
    online: bool
    carregados: dict[str, float] = field(default_factory=dict)

    @property
    def nome(self) -> str:
        if not self.online:
            return "fora"
        return "acordado" if self.carregados else "dormindo"

    def texto(self, keep_alive: str = "10m") -> str:
        if not self.online:
            return "Ollama fora do ar. Clique em Acordar para abrir."
        if not self.carregados:
            return "Dormindo: placa de vídeo livre. Acorda sozinho quando o Claude pedir."
        modelos = ", ".join(f"{m} ({gb:.1f} GB)" for m, gb in self.carregados.items())
        return f"Acordado: {modelos}. Dorme sozinho após {keep_alive} sem uso."


def ler_estado(cliente: ClienteOllama) -> Estado:
    try:
        return Estado(True, cliente.modelos_carregados())
    except ErroOllama:
        return Estado(False)


def _ja_aberto() -> bool:
    """Impede dois ícones: um mutex nomeado do Windows marca que o app já está rodando."""
    import ctypes

    ctypes.windll.kernel32.CreateMutexW(None, False, "agente-local-bandeja")
    return bool(ctypes.windll.kernel32.GetLastError() == 183)  # ERROR_ALREADY_EXISTS


class Bandeja:
    def __init__(self, cfg: Config, mostrar_painel: bool = True) -> None:
        self.cfg = cfg
        self.mostrar_painel = mostrar_painel
        # Cliente curto para o monitor (não trava o ícone) e longo para carregar modelos.
        self.rapido = ClienteOllama(cfg.ollama_url, 5, cfg.keep_alive)
        self.cliente = ClienteOllama.de_config(cfg)
        self.estado = Estado(False)
        self.icone: Any = None
        self._ocupado = threading.Lock()
        self._falando = threading.Lock()
        self.voz_ligada = True
        self.pausa_memoria = cfg.pasta_dados / "memoria-pausada"
        self.pausa_porteiro = cfg.pasta_dados / "porteiro-pausado"
        self.pausa_revisor = cfg.pasta_dados / "revisor-pausado"
        self.pausa_maestro = cfg.pasta_dados / "maestro-pausado"
        self.ultimo_maestro = "nenhum pedido ainda"
        self._acordar_memoria = threading.Event()
        self.resolvidos_hoje = 0
        self._passos = self._montar_passos()
        self.interface = Interface(
            self._agentes(),
            ativos=lambda: atividade.ativos(cfg.pasta_dados),
            uso_total=lambda: recursos.medir().texto(),
            arquivo_tema=cfg.pasta_dados / "tema.txt",
            ligar_ferramentas=self.ligar_ferramentas,
            pedir=self.pedir,
            mandar_ao_claude=self.mandar_ao_claude,
            historico=lambda: historico.ler(cfg),
            economia=lambda: economia.pontos(cfg),
            ferramentas_estado=lambda: ferramentas.estados(self._passos),
            ligar_uma=self.ligar_uma,
            desligar_ferramentas=self.desligar_ferramentas,
        )

    def _agentes(self) -> list[Agente]:
        def alternar_cerebro(ligar: bool) -> None:
            self.acordar() if ligar else self.dormir()

        def alternar_braco(ligar: bool) -> None:
            seguranca.liberar() if ligar else seguranca.parar()

        def uso_cerebro() -> str:
            gb = sum(self.estado.carregados.values())
            return f"Placa de vídeo: {gb:.1f} GB" if gb else "Sem uso (dormindo)."

        def uso_braco() -> str:
            gb = recursos.ram_do_navegador_gb(self.cfg)
            return f"Memória: {gb:.1f} GB (navegador)" if gb >= 0.05 else "Sem uso agora."

        def alternar_memoria(ligar: bool) -> None:
            if ligar:
                self.pausa_memoria.unlink(missing_ok=True)
                self._acordar_memoria.set()  # confere os projetos já, sem esperar o intervalo
            else:
                self.pausa_memoria.parent.mkdir(parents=True, exist_ok=True)
                self.pausa_memoria.write_text("pausada", encoding="utf-8")

        def uso_memoria() -> str:
            from agente import memoria

            return memoria.tamanho_indice(self.cfg)

        def alternar_porteiro(ligar: bool) -> None:
            if ligar:
                self.pausa_porteiro.unlink(missing_ok=True)
            else:
                self.pausa_porteiro.parent.mkdir(parents=True, exist_ok=True)
                self.pausa_porteiro.write_text("pausado", encoding="utf-8")

        def alternar_revisor(ligar: bool) -> None:
            if ligar:
                self.pausa_revisor.unlink(missing_ok=True)
            else:
                self.pausa_revisor.parent.mkdir(parents=True, exist_ok=True)
                self.pausa_revisor.write_text("pausado", encoding="utf-8")

        def uso_revisor() -> str:
            try:
                ultima = (self.cfg.pasta_dados / "revisor-ultima.txt").read_text(encoding="utf-8")
            except OSError:
                return "Nenhuma revisão ainda."
            return f"Última revisão: {ultima.strip()}"

        def alternar_maestro(ligar: bool) -> None:
            if ligar:
                self.pausa_maestro.unlink(missing_ok=True)
            else:
                self.pausa_maestro.parent.mkdir(parents=True, exist_ok=True)
                self.pausa_maestro.write_text("pausado", encoding="utf-8")

        def uso_maestro() -> str:
            poupados = f"{economia.total(self.cfg):,}".replace(",", ".")
            return f"Último: {self.ultimo_maestro}. Tokens poupados: {poupados}"

        return [
            Agente(
                "Cérebro",
                "Modelo local na placa de vídeo, pronto para responder.",
                "#b06bff",
                "cerebro",
                lambda: self.estado.nome == "acordado",
                alternar_cerebro,
                uso_cerebro,
            ),
            Agente(
                "Braço",
                "Navegador, apps do Windows e tela (Ctrl+Alt+P desliga).",
                "#3ccf6e",
                "braco",
                lambda: not seguranca.SINAL_PARADA.exists(),
                alternar_braco,
                uso_braco,
            ),
            Agente(
                "Memória",
                "Mantém os projetos indexados e passa ao Claude só os trechos relevantes.",
                "#9b6bff",
                "memoria",
                lambda: self._aceso("Memória", self.pausa_memoria),
                alternar_memoria,
                uso_memoria,
            ),
            Agente(
                "Porteiro",
                "Resolve o simples aqui e manda o resto ao Claude (caixa do painel).",
                "#2fc46b",
                "porteiro",
                lambda: self._aceso("Porteiro", self.pausa_porteiro),
                alternar_porteiro,
                lambda: f"Resolvidos aqui hoje: {self.resolvidos_hoje}",
            ),
            Agente(
                "Revisor",
                "Lint, tipos e testes antes do Claude revisar; trava commit com senha ou conflito.",
                "#e0505a",
                "revisor",
                lambda: self._aceso("Revisor", self.pausa_revisor),
                alternar_revisor,
                uso_revisor,
            ),
            Agente(
                "Maestro",
                "Escolhe o agente de cada pedido da caixa (revisar, testar, achar...).",
                "#3d8bff",
                "maestro",
                lambda: not self.pausa_maestro.exists(),
                alternar_maestro,
                uso_maestro,
            ),
            *futuros(),
        ]

    # --- ações ---------------------------------------------------------------------------

    def _avisar(self, texto: str) -> None:
        logger.info("aviso: %s", texto)
        if self.icone is not None:
            self.icone.notify(texto[:250], "Agente local")

    def _em_segundo_plano(self, nome: str, acao: Callable[[], None]) -> None:
        def rodar() -> None:
            if not self._ocupado.acquire(blocking=False):
                self._avisar("Espere: ainda estou terminando a última ação.")
                return
            try:
                acao()
            except (ErroOllama, ErroExecucao, lancador.ErroLancador, OSError) as exc:
                logger.error("%s falhou: %s", nome, exc)
                self._avisar(f"Não consegui {nome}: {exc}")
            finally:
                self._ocupado.release()
                self.atualizar()

        threading.Thread(target=rodar, name=nome, daemon=True).start()

    def _garantir_ollama(self) -> None:
        if ler_estado(self.rapido).online:
            return
        if not APP_OLLAMA.exists():
            raise ErroOllama("Ollama fora do ar e o app não foi encontrado; abra o Ollama.")
        self._avisar("Abrindo o Ollama...")
        subprocess.Popen([str(APP_OLLAMA)])
        for _ in range(30):
            time.sleep(1)
            if ler_estado(self.rapido).online:
                return
        raise ErroOllama("o Ollama não respondeu em 30 s")

    def _acordar(self) -> None:
        self._garantir_ollama()
        if not ler_estado(self.rapido).carregados:
            recursos.garantir_folga(self.cfg, VRAM_CEREBRO_GB)
        self._avisar("Acordando (carregando o modelo na placa de vídeo)...")
        inicio = time.perf_counter()
        with atividade.trabalhando(self.cfg.pasta_dados, "Cérebro"):
            self.cliente.acordar(self.cfg.modelos.cerebro)
        self._avisar(f"Pronto em {time.perf_counter() - inicio:.0f} s. Pode chamar no Claude.")

    def _dormir(self) -> None:
        carregados = self.rapido.modelos_carregados()
        for modelo in carregados:
            self.cliente.dormir(modelo)
        livres = sum(carregados.values())
        self._avisar(f"Dormindo. {livres:.1f} GB da placa de vídeo liberados.")

    def acordar(self) -> None:
        self._em_segundo_plano("acordar", self._acordar)

    def dormir(self) -> None:
        self._em_segundo_plano("dormir", self._dormir)

    def alternar(self) -> None:
        self.dormir() if self.estado.nome == "acordado" else self.acordar()

    # --- Porteiro -----------------------------------------------------------------------

    def mandar_ao_claude(self, pedido: str) -> str:
        from agente import porteiro

        return porteiro.mandar_ao_claude(self.cfg, pedido)

    def pedir(self, pedido: str) -> tuple[str, str]:
        """Pedido escrito ou falado: o Maestro escolhe o agente (o resto vai ao Porteiro)."""
        from agente import maestro

        if self.pausa_maestro.exists():
            return self._porteiro(pedido)
        with atividade.trabalhando(self.cfg.pasta_dados, "Maestro"):
            r = maestro.conduzir(
                self.cfg, self.cliente, pedido, lambda p: self._porteiro(p, pelo_maestro=True)
            )
        sufixo = {"claude": " (Claude)", "nuvem": " (OmniRoute)"}.get(r.destino, "")
        self.ultimo_maestro = r.agente + sufixo
        return r.destino, r.resposta

    def _aceso(self, agente: str, pausa: Path) -> bool:
        """Ligado no painel, ou ligado agora pelo Maestro para um pedido."""
        return not pausa.exists() or agente in atividade.ativos(self.cfg.pasta_dados)

    def _porteiro(self, pedido: str, pelo_maestro: bool = False) -> tuple[str, str]:
        """O Porteiro resolve aqui ou manda ao Claude."""
        from agente import porteiro

        if self.pausa_porteiro.exists() and not pelo_maestro:  # tudo direto ao Claude
            return "claude", self.mandar_ao_claude(pedido)

        def comando(texto: str) -> str:
            return self.responder(interpretar(texto))

        with atividade.trabalhando(self.cfg.pasta_dados, "Porteiro"):
            r = porteiro.resolver(self.cfg, self.cliente, pedido, executar_comando=comando)
        if r.destino == "local":
            self.resolvidos_hoje += 1
        return r.destino, r.resposta

    # --- voz ---------------------------------------------------------------------------

    def responder(self, pedido: Pedido) -> str:
        """Executa o pedido falado e devolve a frase para falar de volta."""
        dados = self.cfg.pasta_dados
        if pedido.acao == "nada":
            return "Não ouvi nada."
        if pedido.acao == "acordar":
            self._acordar()
            return "Acordado e pronto."
        if pedido.acao == "dormir":
            self._dormir()
            return "Dormindo. A placa de vídeo está livre."
        if pedido.acao == "status":
            return ler_estado(self.rapido).texto(self.cfg.keep_alive)
        if pedido.acao == "economia":
            return economia.relatorio(self.cfg)
        if pedido.acao == "parar":
            seguranca.parar()
            return "Braço parado."
        if pedido.acao == "liberar":
            seguranca.liberar()
            return "Braço liberado."
        if pedido.acao == "abrir":
            from agente.braco import navegador

            with atividade.trabalhando(dados, "Braço"):
                return navegador.resolver_abrir(self.cfg, pedido.alvo)
        if pedido.acao == "tocar":
            from agente.braco.navegador import navegador as navegador_do_processo

            with atividade.trabalhando(dados, "Braço"):
                return navegador_do_processo(self.cfg).tocar(pedido.alvo)
        if pedido.acao == "buscar":
            from agente import memoria

            with atividade.trabalhando(dados, "Memória"):
                achados = memoria.buscar_arquivos(self.cfg, pedido.alvo)
            if not achados:
                return f"Não achei nenhum arquivo com '{pedido.alvo}'."
            return "\n".join(str(p) for p in achados)
        with atividade.trabalhando(dados, "Cérebro"):
            if not ler_estado(self.rapido).carregados:
                recursos.garantir_folga(self.cfg, VRAM_CEREBRO_GB)
            resposta = self.cliente.conversar(
                self.cfg.modelos.cerebro, pedido.alvo, sistema=SISTEMA_FALADO, temperatura=0.4
            )
        return resposta.texto or "Não consegui pensar numa resposta."

    def _conversar(self) -> None:
        from agente.voz import boca, ouvido

        dados = self.cfg.pasta_dados
        with atividade.trabalhando(dados, "Voz"):
            if not ouvido.carregado():
                recursos.garantir_folga(self.cfg, VRAM_WHISPER_GB)
            texto = ouvido.ouvir(self.cfg, aviso=lambda: self._avisar("Pode falar..."))
        logger.info("voz: %r", texto)
        try:
            if not texto:
                resposta = "Não ouvi nada."
            else:
                destino, resposta = self.pedir(texto)
                if destino == "claude":
                    resposta = "Isso é com o Claude. Copiei o pedido e abri o Claude para você."
        except (ErroOllama, ErroExecucao, OSError) as exc:
            resposta = f"Não consegui: {exc}"
        self._avisar(f"Você: {texto or '(silêncio)'}\nAgente: {resposta}")
        if self.cfg.voz.falar_respostas:  # narrador desligado por padrão
            with atividade.trabalhando(dados, "Voz"):
                boca.falar(self.cfg, resposta)

    def conversar_por_voz(self) -> None:
        """Atalho de voz: ouve uma frase, faz o pedido e responde falando."""
        if not self.voz_ligada:
            self._avisar("A voz está desligada no painel.")
            return

        def rodar() -> None:
            if not self._falando.acquire(blocking=False):
                return  # já está ouvindo ou falando
            try:
                self._conversar()
            except (ErroVoz, ErroExecucao, OSError) as exc:
                logger.error("voz falhou: %s", exc)
                self._avisar(f"Voz: {exc}")
            finally:
                self._falando.release()
                self.atualizar()

        threading.Thread(target=rodar, name="voz", daemon=True).start()

    # --- ferramentas -------------------------------------------------------------------

    def _preparar_voz(self) -> None:
        from agente.voz import ouvido

        with atividade.trabalhando(self.cfg.pasta_dados, "Voz"):
            if not ouvido.carregado():
                recursos.garantir_folga(self.cfg, VRAM_WHISPER_GB)
            ouvido.preparar(self.cfg)

    def _montar_passos(self) -> list[ferramentas.Passo]:
        from agente.voz import ouvido

        return ferramentas.passos(
            self.cfg,
            self._acordar,
            self._preparar_voz,
            voz_pronta=ouvido.carregado,
            descarregar_voz=ouvido.descarregar,
        )

    def _ligar_ferramentas(self) -> None:
        relatorio = ferramentas.ligar_tudo(self._passos, progresso=self.interface.mostrar_progresso)
        logger.info("ferramentas:\n%s", "\n".join(relatorio))
        falhas = [linha for linha in relatorio if "FALHOU" in linha]
        if falhas:
            self._avisar("Ferramentas ligadas, menos: " + "; ".join(falhas))
        else:
            self._avisar("Tudo pronto: Ollama, Cérebro, Docker, Ubuntu e VS Code.")

    def ligar_ferramentas(self) -> None:
        """Botão "Ligar ferramentas": tudo que o Claude e os agentes usam num projeto."""
        self._em_segundo_plano("ligar as ferramentas", self._ligar_ferramentas)

    def ligar_uma(self, nome: str) -> None:
        """Check desmarcado no painel: reabre só aquela ferramenta."""
        passo = next((p for p in self._passos if p.nome == nome), None)
        if passo is None:
            return

        def ligar() -> None:
            self.interface.mostrar_progresso(0, 1, nome)
            try:
                passo.ligar()
            finally:
                self.interface.mostrar_progresso(1, 1, "")

        self._em_segundo_plano(f"abrir {nome}", ligar)

    def _desligar_ferramentas(self) -> None:
        relatorio = ferramentas.desligar_tudo(
            self._passos,
            progresso=lambda f, t, n: self.interface.mostrar_progresso(f, t, n, "Fechando"),
        )
        logger.info("desligar:\n%s", "\n".join(relatorio))
        falhas = [linha for linha in relatorio if "FALHOU" in linha]
        if falhas:
            self._avisar("Não fechei: " + "; ".join(falhas))
        else:
            self._avisar("Agentes desligados.")

    def desligar_ferramentas(self) -> None:
        """Botão "Desligar ferramentas": fecha tudo que o "Ligar" abriu."""
        self._em_segundo_plano("desligar as ferramentas", self._desligar_ferramentas)

    def mostrar_status(self) -> None:
        self._avisar(ler_estado(self.rapido).texto(self.cfg.keep_alive))

    def mostrar_economia(self) -> None:
        self._avisar(economia.relatorio(self.cfg))

    def reiniciar_claude(self) -> None:
        from agente import reiniciar
        from agente.executor import ErroExecucao

        try:
            self._avisar(reiniciar.reiniciar_claude())
        except ErroExecucao as exc:
            self._avisar(str(exc))

    def alternar_inicializacao(self) -> None:
        ligar = not lancador.inicia_com_windows()
        self._em_segundo_plano(
            "mudar a inicialização", lambda: lancador.iniciar_com_windows(self.cfg, ligar)
        )

    # --- ícone ---------------------------------------------------------------------------

    def atualizar(self) -> None:
        novo = ler_estado(self.rapido)
        if self.icone is not None and novo != self.estado:
            self.icone.icon = lancador.desenhar_icone(novo.nome)
            self.icone.title = f"Agente local: {novo.texto(self.cfg.keep_alive)}"[:127]
        self.estado = novo

    def _memoria(self) -> None:
        """Agente Memória: confere os projetos de tempos em tempos e reindexa o que mudou."""
        from agente import memoria

        while True:
            if not self.pausa_memoria.exists() and ler_estado(self.rapido).online:
                try:
                    recursos.garantir_folga(self.cfg, 0.5)  # nomic-embed-text é leve
                    mudancas = memoria.manter_atualizado(self.cfg, self.cliente)
                    if mudancas:
                        logger.info("memória: %s", "; ".join(mudancas))
                except (ErroOllama, ErroExecucao, OSError) as exc:
                    logger.warning("memória adiada: %s", exc)
            self._acordar_memoria.wait(self.cfg.memoria.intervalo_min * 60)
            self._acordar_memoria.clear()

    def _monitorar(self) -> None:
        while True:
            self.atualizar()
            time.sleep(INTERVALO_S)

    def _menu(self) -> Any:
        import pystray

        item = pystray.MenuItem
        return pystray.Menu(
            item("Painel dos agentes", lambda: self.interface.abrir_painel(), default=True),
            item("Ligar ferramentas", lambda: self.ligar_ferramentas()),
            item("Desligar ferramentas", lambda: self.desligar_ferramentas()),
            item("Acordar agente", lambda: self.acordar()),
            item("Dormir (liberar placa de vídeo)", lambda: self.dormir()),
            pystray.Menu.SEPARATOR,
            item("Status", lambda: self.mostrar_status()),
            item("Tokens poupados", lambda: self.mostrar_economia()),
            item("Abrir pasta do agente", lambda: lancador.abrir(self.cfg.pasta_dados.parent)),
            item("Abrir log", lambda: lancador.abrir(self.cfg.pasta_logs / "agente.log")),
            item("Reiniciar o Claude", lambda: self.reiniciar_claude()),
            item(
                "Iniciar com o Windows",
                lambda: self.alternar_inicializacao(),
                checked=lambda _item: lancador.inicia_com_windows(),
            ),
            pystray.Menu.SEPARATOR,
            item("Sair", lambda icone: icone.stop()),
        )

    def _ao_abrir(self, icone: Any) -> None:
        icone.visible = True
        self.interface.iniciar()  # as bolinhas aparecem mesmo com o painel fechado
        if self.mostrar_painel:
            self.interface.abrir_painel()
        threading.Thread(target=self._monitorar, name="monitor", daemon=True).start()
        threading.Thread(target=self._memoria, name="memória", daemon=True).start()
        tecla, voz = self.cfg.atalho_acordar, self.cfg.voz.atalho
        avisos = []
        if atalho.registrar(tecla, self.alternar):
            avisos.append(f"{tecla.title()} acorda ou põe para dormir.")
        if voz and atalho.registrar(voz, self.conversar_por_voz):  # atalho vazio: sem voz
            avisos.append(f"{voz.title()} para falar com ele.")
        self._avisar(" ".join(["Agente na bandeja.", *avisos]))

    def rodar(self) -> None:
        import pystray

        self.icone = pystray.Icon(
            "agente-local", lancador.desenhar_icone("dormindo"), "Agente local", self._menu()
        )
        self.icone.run(setup=self._ao_abrir)


def main() -> None:
    try:
        cfg = carregar_config()
        configurar_logs(cfg.pasta_logs)
    except (ErroConfig, RuntimeError) as exc:
        logger.error("config inválida: %s", exc)
        raise SystemExit(1) from exc
    if _ja_aberto():
        # Clicou no atalho com o app já na bandeja: só acorda o modelo e sai.
        logger.info("bandeja já aberta; só acordando o modelo")
        try:
            ClienteOllama.de_config(cfg).acordar(cfg.modelos.cerebro)
        except ErroOllama as exc:
            logger.error("não acordou: %s", exc)
        raise SystemExit(0)
    # Ao iniciar com o Windows o atalho passa --sem-painel: só o ícone, sem janela.
    Bandeja(cfg, mostrar_painel="--sem-painel" not in sys.argv).rodar()


if __name__ == "__main__":
    main()
