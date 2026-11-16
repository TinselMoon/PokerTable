import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from protocolo import desempacotar, empacotar
from regras_de_negocio import BOT_ID, JogoPoker

MAPA_VALORES = {"10": "T", "A": "A", "J": "J", "Q": "Q", "K": "K"}
MAPA_NAIPES = {"Copas": "h", "Ouros": "d", "Espadas": "s", "Paus": "c"}


def traduzir_carta(valor: str, naipe: str) -> str:
    v = MAPA_VALORES.get(valor, valor)
    n = MAPA_NAIPES.get(naipe, "")
    return f"{v}{n}"


def obter_ip_local() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


class ServidorMesa:
    def __init__(self, porta: int = 5000, on_atualizar_ui=None):
        self.porta = porta
        self.on_atualizar_ui = on_atualizar_ui
        self.jogo = JogoPoker()
        self.lock = threading.Lock()

        self._rodando = False
        self._sock_servidor = None
        self._processo_scanner = None
        self._camera_ligada = False
        self._bot_agendado = False

        self.roteador = {
            "registro": lambda conn, d: self.jogo.registrar_jogador(
                conn, d.get("nome", "Jogador"), d.get("saldo", 1000)
            ),
            "acao": lambda conn, d: self.jogo.processar_acao(
                conn, d.get("acao", ""), float(d.get("valor", 0))
            ),
            "rebuy": lambda conn, d: self.jogo.processar_rebuy(
                conn, float(d.get("valor", 0))
            ),
        }

    # =========================================================================
    # CICLO DE VIDA (INICIAR / ENCERRAR COM SEGURANÇA)
    # =========================================================================
    def iniciar(self) -> None:
        self._rodando = True
        threading.Thread(target=self._loop_sockets, daemon=True).start()
        self._iniciar_scanner()
        self._notificar_ui()

    def encerrar(self) -> None:
        """Desliga LED/IR/câmera no scanner e fecha todos os sockets com segurança."""
        self._rodando = False

        # 1. Encerra o processo do scanner (desliga GPIO LED/IR e fecha câmera)
        if self._processo_scanner is not None:
            try:
                if self._processo_scanner.stdin:
                    self._processo_scanner.stdin.write(b"SAIR\n")
                    self._processo_scanner.stdin.flush()
                self._processo_scanner.wait(timeout=3)
            except Exception:
                try:
                    self._processo_scanner.terminate()
                except Exception:
                    pass
            self._processo_scanner = None

        # 2. Fecha sockets de clientes e servidor
        with self.lock:
            for jid in list(self.jogo.jogadores.keys()):
                if isinstance(jid, socket.socket):
                    try:
                        jid.close()
                    except Exception:
                        pass

        if self._sock_servidor is not None:
            try:
                self._sock_servidor.close()
            except Exception:
                pass
            self._sock_servidor = None

    # =========================================================================
    # COMUNICAÇÃO COM O SUBPROCESSO DO SCANNER
    # =========================================================================
    def _iniciar_scanner(self) -> None:
        script_scanner = Path(__file__).resolve().parent / "scanner_integrado.py"
        try:
            self._processo_scanner = subprocess.Popen(
                [sys.executable, str(script_scanner)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=sys.stderr,
            )
            threading.Thread(target=self._loop_scanner, daemon=True).start()
        except Exception as e:
            print(f"[Servidor] Falha ao iniciar scanner_integrado.py: {e}")

    def _enviar_cmd_scanner(self, cmd: str) -> None:
        proc = self._processo_scanner
        if proc is not None and proc.poll() is None and proc.stdin is not None:
            try:
                proc.stdin.write(f"{cmd}\n".encode("utf-8"))
                proc.stdin.flush()
            except Exception:
                pass

    def _sincronizar_scanner_com_fase(self) -> None:
        """Liga câmera/LED apenas na fase de escaneamento e sincroniza cartas usadas."""
        precisa_scanner = self.jogo.fase in ("DISTRIBUINDO_MAOS", "DISTRIBUINDO_MESA")
        if precisa_scanner and not self._camera_ligada:
            self._camera_ligada = True
            self._enviar_cmd_scanner("LIGAR")
        elif not precisa_scanner and self._camera_ligada:
            self._camera_ligada = False
            self._enviar_cmd_scanner("DESLIGAR")

        lista_usadas = ",".join(sorted(self.jogo.cartas_usadas_rodada))
        self._enviar_cmd_scanner(f"USADAS;{lista_usadas}")

    def _loop_scanner(self) -> None:
        proc = self._processo_scanner
        if proc is None or proc.stdout is None:
            return
        for linha in proc.stdout:
            if not self._rodando:
                break
            evento = linha.decode("utf-8", errors="ignore").strip()
            if not evento:
                continue

            print(f"[Scanner] {evento}")
            if evento.startswith("CARTA;"):
                partes = evento.split(";")
                if len(partes) == 3:
                    carta = traduzir_carta(partes[1], partes[2])
                    with self.lock:
                        msgs = self.jogo.processar_carta_lida(carta)
                        self._sincronizar_scanner_com_fase()
                    self._despachar(msgs)
                    self._notificar_ui()

            elif evento.startswith("DUPLICADA;"):
                with self.lock:
                    self.jogo.registrar_aviso_duplicada()
                self._notificar_ui()

    # =========================================================================
    # REDE TCP (CELULARES ANDROID)
    # =========================================================================
    def _loop_sockets(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", self.porta))
        srv.listen()
        srv.settimeout(1.0)
        self._sock_servidor = srv
        print(f"[Rede] Servidor Poker rodando na porta {self.porta}...")

        while self._rodando:
            try:
                conn, addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(
                target=self._atender_cliente, args=(conn, addr), daemon=True
            ).start()

    def _atender_cliente(self, conn: socket.socket, addr) -> None:
        print(f"[Rede] Celular conectado: {addr}")
        try:
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            pass
        buffer = ""
        try:
            while self._rodando:
                dados_brutos = conn.recv(1024).decode("utf-8")
                if not dados_brutos:
                    break
                buffer += dados_brutos
                while "\n" in buffer:
                    linha, buffer = buffer.split("\n", 1)
                    if not linha.strip():
                        continue
                    tipo, dados = desempacotar(linha)
                    handler = self.roteador.get(tipo)
                    if handler:
                        with self.lock:
                            msgs = handler(conn, dados)
                            self._sincronizar_scanner_com_fase()
                            precisa_bot = self.jogo.jogador_da_vez_eh_bot()
                        self._despachar(msgs)
                        self._notificar_ui()
                        if precisa_bot:
                            self._agendar_jogada_bot()
        except Exception as e:
            print(f"[Rede] Erro com cliente {addr}: {e}")
        finally:
            with self.lock:
                msgs = self.jogo.remover_jogador(conn)
                self._sincronizar_scanner_com_fase()
                precisa_bot = self.jogo.jogador_da_vez_eh_bot()
            self._despachar(msgs)
            self._notificar_ui()
            if precisa_bot:
                self._agendar_jogada_bot()
            try:
                conn.close()
            except Exception:
                pass
            print(f"[Rede] Celular desconectado: {addr}")

    def _despachar(self, mensagens: list[tuple]) -> None:
        if not mensagens:
            return
        with self.lock:
            sockets_humanos = [
                jid
                for jid in self.jogo.jogadores.keys()
                if isinstance(jid, socket.socket)
            ]

        lotes_por_conn: dict[socket.socket, list[bytes]] = {}
        for destino, tipo, dados in mensagens:
            payload = empacotar(tipo, **dados)
            if destino == "TODOS":
                destinatarios = sockets_humanos
            elif isinstance(destino, socket.socket):
                destinatarios = [destino]
            else:
                continue

            for conn in destinatarios:
                lotes_por_conn.setdefault(conn, []).append(payload)

        for conn, pacotes in lotes_por_conn.items():
            try:
                conn.sendall(b"".join(pacotes))
            except Exception:
                pass

    # =========================================================================
    # BOT DE TESTES (AGENDAMENTO ASSÍNCRONO)
    # =========================================================================
    def _agendar_jogada_bot(self) -> None:
        with self.lock:
            if self._bot_agendado or not self._rodando:
                return
            self._bot_agendado = True

        def executar():
            time.sleep(1.1)
            if not self._rodando:
                return
            with self.lock:
                self._bot_agendado = False
                if not self.jogo.jogador_da_vez_eh_bot():
                    return
                acao, valor = self.jogo.escolher_acao_bot()
                msgs = self.jogo.processar_acao(BOT_ID, acao, valor)
                self._sincronizar_scanner_com_fase()
                novo_turno_bot = self.jogo.jogador_da_vez_eh_bot()

            self._despachar(msgs)
            self._notificar_ui()
            if novo_turno_bot:
                self._agendar_jogada_bot()

        threading.Thread(target=executar, daemon=True).start()

    # =========================================================================
    # AÇÕES ACIONADAS PELOS BOTÕES DA INTERFACE LCD
    # =========================================================================
    def obter_snapshot(self) -> dict:
        with self.lock:
            return self.jogo.obter_snapshot_ui()

    def ui_ajustar_blinds(self, delta: int) -> None:
        with self.lock:
            self.jogo.ajustar_blinds(delta)
            msgs = self.jogo._gerar_estado_individualizado(
                f"Blinds ajustados: SB R${self.jogo.small_blind:.0f} / BB R${self.jogo.big_blind:.0f}."
            )
        self._despachar(msgs)
        self._notificar_ui()

    def ui_alternar_bot(self) -> None:
        with self.lock:
            msgs = self.jogo.alternar_bot_testes()
        self._despachar(msgs)
        self._notificar_ui()

    def ui_mover_jogador(self, jid, direcao: int) -> None:
        with self.lock:
            msgs = self.jogo.mover_jogador(jid, direcao)
        self._despachar(msgs)
        self._notificar_ui()

    def ui_iniciar_rodada(self) -> None:
        with self.lock:
            msgs = self.jogo.iniciar_nova_rodada()
            self._sincronizar_scanner_com_fase()
            self._enviar_cmd_scanner("RESET_LEITURA")
        self._despachar(msgs)
        self._notificar_ui()

    def ui_limpar_leitura(self) -> None:
        with self.lock:
            self.jogo.limpar_buffer_atual()
            self._sincronizar_scanner_com_fase()
            self._enviar_cmd_scanner("RESET_LEITURA")
        self._notificar_ui()

    def ui_confirmar_distribuicao(self) -> None:
        with self.lock:
            msgs = self.jogo.confirmar_distribuicao_atual()
            self._sincronizar_scanner_com_fase()
            self._enviar_cmd_scanner("RESET_LEITURA")
            precisa_bot = self.jogo.jogador_da_vez_eh_bot()
        self._despachar(msgs)
        self._notificar_ui()
        if precisa_bot:
            self._agendar_jogada_bot()

    def ui_confirmar_virar_mesa(self) -> None:
        with self.lock:
            msgs = self.jogo.confirmar_virar_cartas_mesa()
            precisa_bot = self.jogo.jogador_da_vez_eh_bot()
        self._despachar(msgs)
        self._notificar_ui()
        if precisa_bot:
            self._agendar_jogada_bot()

    def ui_encerrar_jogo(self) -> None:
        with self.lock:
            msgs = self.jogo.encerrar_jogo()
            self._sincronizar_scanner_com_fase()
        self._despachar(msgs)
        self._notificar_ui()

    def ui_voltar_inicio(self) -> None:
        with self.lock:
            msgs = self.jogo.voltar_ao_inicio()
            self._sincronizar_scanner_com_fase()
        self._despachar(msgs)
        self._notificar_ui()

    def _notificar_ui(self) -> None:
        if self.on_atualizar_ui:
            self.on_atualizar_ui()
