import socket
import threading
import subprocess
import sys
import time
from regras_de_negocio import JogoPoker
from protocolo import empacotar, desempacotar

MAPA_VALORES = {"10": "T", "A": "A", "J": "J", "Q": "Q", "K": "K"}
MAPA_NAIPES = {"Copas": "h", "Ouros": "d", "Espadas": "s", "Paus": "c"}

jogo = JogoPoker()
lock_jogo = threading.Lock()


def traduzir_carta(valor, naipe):
    v = MAPA_VALORES.get(valor, valor)
    n = MAPA_NAIPES.get(naipe, "")
    return f"{v}{n}"


def despachar_mensagens(mensagens: list[tuple]):
    """Envia envelopes padronizados para TODOS ou para o socket específico."""
    for destino, tipo, dados in mensagens:
        payload = empacotar(tipo, **dados)
        destinatarios = list(jogo.jogadores.keys()) if destino == "TODOS" else [destino]
        for conn in destinatarios:
            try:
                conn.sendall(payload)
            except Exception:
                pass


# Tabela de despacho de comandos recebidos dos celulares
ROTEADOR_COMANDOS = {
    "registro": lambda conn, d: jogo.registrar_jogador(
        conn, d.get("nome", "Jogador"), d.get("saldo", 1000)
    ),
    "iniciar_rodada": lambda conn, d: jogo.iniciar_nova_rodada(),
    "acao": lambda conn, d: jogo.processar_acao(
        conn, d.get("acao", ""), float(d.get("valor", 0))
    ),
}


def gerenciar_leitura_scanner(processo_scanner):
    for linha in processo_scanner.stdout:
        evento = linha.decode("utf-8").strip()
        if not evento:
            continue

        print(f"[Scanner] {evento}")
        if evento.startswith("CARTA;"):
            _, valor, naipe = evento.split(";")
            carta = traduzir_carta(valor, naipe)
            with lock_jogo:
                msgs = jogo.processar_carta_lida(carta)
            despachar_mensagens(msgs)


def atender_cliente(conn, addr):
    print(f"[Rede] Celular conectado: {addr}")
    buffer = ""
    try:
        while True:
            dados_brutos = conn.recv(1024).decode("utf-8")
            if not dados_brutos:
                break
            buffer += dados_brutos
            while "\n" in buffer:
                linha, buffer = buffer.split("\n", 1)
                if not linha.strip():
                    continue
                tipo, dados = desempacotar(linha)
                handler = ROTEADOR_COMANDOS.get(tipo)
                if handler:
                    with lock_jogo:
                        msgs = handler(conn, dados)
                    despachar_mensagens(msgs)
    except Exception as e:
        print(f"[Rede] Erro com cliente {addr}: {e}")
    finally:
        with lock_jogo:
            msgs = jogo.remover_jogador(conn)
        despachar_mensagens(msgs)
        conn.close()
        print(f"[Rede] Celular desconectado: {addr}")


def iniciar_servidor_sockets():
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    servidor.bind(("0.0.0.0", 5000))
    servidor.listen()
    print("[Rede] Servidor Poker rodando na porta 5000...")

    while True:
        conn, addr = servidor.accept()
        threading.Thread(target=atender_cliente, args=(conn, addr), daemon=True).start()


def main():
    threading.Thread(target=iniciar_servidor_sockets, daemon=True).start()

    scanner = subprocess.Popen(
        [sys.executable, "scanner_integrado.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
    )
    threading.Thread(
        target=gerenciar_leitura_scanner, args=(scanner,), daemon=True
    ).start()

    time.sleep(2)
    scanner.stdin.write(b"LIGAR\n")
    scanner.stdin.flush()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        scanner.stdin.write(b"SAIR\n")
        scanner.stdin.flush()


if __name__ == "__main__":
    main()
