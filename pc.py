import socket
import threading
import json

clientes = {}  # {nome: conn}

def escutar_celular(conn, addr):
    nome_jogador = None
    buffer = ""
    try:
        while True:
            dados = conn.recv(1024).decode('utf-8')
            if not dados:
                break
            buffer += dados
            while "\n" in buffer:
                linha, buffer = buffer.split("\n", 1)
                if not linha.strip():
                    continue
                pacote = json.loads(linha)
                tipo = pacote.get("tipo")

                if tipo == "registro":
                    nome_jogador = pacote.get("nome")
                    saldo = pacote.get("saldo")
                    clientes[nome_jogador] = conn
                    print(f"\n[+] Celular conectado: '{nome_jogador}' com saldo inicial R$ {saldo} ({addr[0]})")
                    print("Comando > ", end="", flush=True)

                elif tipo == "acao":
                    print(f"\n[AÇÃO DO CELULAR] {nome_jogador} escolheu: {pacote.get('acao')} (Valor: {pacote.get('valor')})")
                    print("Comando > ", end="", flush=True)

                elif tipo == "desconectar":
                    print(f"\n[-] '{nome_jogador}' clicou em Desconectar.")
                    break
    except Exception as e:
        print(f"\n[!] Erro na conexão com {nome_jogador or addr}: {e}")
    finally:
        if nome_jogador and nome_jogador in clientes:
            del clientes[nome_jogador]
            print(f"\n[-] '{nome_jogador}' saiu da mesa.")
            print("Comando > ", end="", flush=True)
        conn.close()

def enviar_json_todos(dicionario):
    if not clientes:
        print("[!] Nenhum celular conectado no momento.")
        return
    msg = (json.dumps(dicionario) + "\n").encode('utf-8')
    for nome, conn in list(clientes.items()):
        try:
            conn.sendall(msg)
            print(f" -> Enviado para '{nome}': {dicionario}")
        except Exception as e:
            print(f"Erro ao enviar para {nome}: {e}")

def servidor_accept():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('0.0.0.0', 5000))
        s.listen()
        while True:
            conn, addr = s.accept()
            threading.Thread(target=escutar_celular, args=(conn, addr), daemon=True).start()

if __name__ == "__main__":
    # Descobre e exibe o IP local do PC automaticamente
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s_ip:
        try:
            s_ip.connect(("8.8.8.8", 80))
            meu_ip = s_ip.getsockname()[0]
        except Exception:
            meu_ip = "127.0.0.1"

    threading.Thread(target=servidor_accept, daemon=True).start()

    print("=" * 55)
    print(f" SERVIDOR DE TESTE ATIVO - IP DO PC: {meu_ip} | PORTA: 5000")
    print("=" * 55)
    print("Comandos disponíveis para digitar:")
    print("  As, Kd, 9h ... -> Envia carta para a MÃO do celular")
    print("  mesa Td        -> Envia carta para a MESA comunitária")
    print("  vez 20         -> Libera os botões no celular (Call = 20)")
    print("  vez 0          -> Libera os botões no celular (Check livre)")
    print("  limpar         -> Limpa todas as cartas no celular")
    print("  sair           -> Fecha este servidor de teste")
    print("=" * 55)

    while True:
        entrada = input("Comando > ").strip()
        if not entrada:
            continue

        partes = entrada.split()
        cmd = partes[0].lower()

        if cmd == "sair":
            break
        elif cmd == "limpar":
            enviar_json_todos({"tipo": "nova_rodada"})
        elif cmd == "mesa" and len(partes) > 1:
            carta = partes[1]
            enviar_json_todos({"tipo": "carta_mesa", "carta": carta})
        elif cmd == "vez":
            valor_call = int(partes[1]) if len(partes) > 1 else 0
            enviar_json_todos({"tipo": "sua_vez", "valor_call": valor_call, "min_raise": valor_call + 20})
        else:
            # Qualquer outra string de 2 caracteres (ex: "As", "Kh") vai como carta da mão
            enviar_json_todos({"tipo": "carta_mao", "carta": partes[0]})
