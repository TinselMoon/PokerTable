import socket
import threading
import flet as ft
from protocolo import empacotar, desempacotar

SALDO_MIN = 200.0
SALDO_MAX = 10000.0

ICONES_NAIPE = {
    "s": "♠",
    "h": "♥",
    "d": "♦",
    "c": "♣",
}


def main(page: ft.Page):
    page.title = "PokerTable"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 16
    page.scroll = ft.ScrollMode.AUTO

    sock_cliente = None
    conectado = False
    partida_iniciada = False

    # =========================================================================
    # TELA 1: CONEXÃO E CADASTRO DO JOGADOR
    # =========================================================================
    input_ip = ft.TextField(label="IP do servidor", value="192.168.1.100")
    input_porta = ft.TextField(
        label="Porta servidor",
        value="5000",
        keyboard_type=ft.KeyboardType.NUMBER,
    )
    input_nome = ft.TextField(label="Nome", value="Jogador 1")
    input_saldo = ft.TextField(
        label="Saldo Inicial (R$ 200 a R$ 10.000)",
        value="1000",
        keyboard_type=ft.KeyboardType.NUMBER,
    )
    switch_testes = ft.Switch(
        label="Modo Testes (Jogar contra Robô)",
        value=False,
    )

    txt_notificacao = ft.Text("", color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD)
    box_notificacao = ft.Container(
        content=txt_notificacao,
        padding=12,
        bgcolor=ft.Colors.RED_900,
        border_radius=8,
        visible=False,
    )

    def notificar_erro_login(mensagem: str, cor_fundo=ft.Colors.RED_900):
        txt_notificacao.value = mensagem
        box_notificacao.bgcolor = cor_fundo
        box_notificacao.visible = True
        page.update()

    # =========================================================================
    # TELA 2: MESA DE POKER E AÇÕES
    # =========================================================================
    txt_jogador_header = ft.Text("", size=14, color=ft.Colors.GREY_400)
    txt_fase = ft.Text("Fase: AGUARDANDO", weight=ft.FontWeight.BOLD)
    txt_saldo = ft.Text(
        "Saldo: R$ 0", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_300
    )
    txt_pote = ft.Text(
        "Pote: R$ 0", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_300
    )
    txt_turno = ft.Text("Vez de: -", size=15, weight=ft.FontWeight.BOLD)
    txt_info = ft.Text("Clique em 'Iniciar Partida' para começar.", size=14)

    row_mao = ft.Row(spacing=10)
    row_mesa = ft.Row(spacing=8, wrap=True)
    input_raise = ft.TextField(
        label="Valor Raise (R$)",
        value="50",
        width=140,
        keyboard_type=ft.KeyboardType.NUMBER,
    )

    def ir_para_tela_mesa(nome: str, saldo: float, ip: str, porta: int):
        nonlocal partida_iniciada
        partida_iniciada = False
        box_notificacao.visible = False
        tag_teste = " [VS ROBÔ]" if switch_testes.value else ""
        txt_jogador_header.value = f"{nome}{tag_teste} • {ip}:{porta}"
        txt_saldo.value = f"Saldo: R$ {saldo:.0f}"
        atualizar_botao_partida()
        tela_conexao.visible = False
        tela_mesa.visible = True
        page.update()

    def voltar_para_conexao(motivo: str = ""):
        nonlocal conectado, sock_cliente, partida_iniciada
        conectado = False
        partida_iniciada = False
        if sock_cliente:
            try:
                sock_cliente.close()
            except Exception:
                pass
            sock_cliente = None

        row_mao.controls.clear()
        row_mesa.controls.clear()
        btn_conectar.disabled = False
        btn_conectar.content = "Entrar na Mesa"
        tela_mesa.visible = False
        tela_conexao.visible = True
        if motivo:
            notificar_erro_login(motivo)
        else:
            page.update()

    def enviar_comando(tipo: str, **dados):
        if conectado and sock_cliente:
            try:
                sock_cliente.sendall(empacotar(tipo, **dados))
            except Exception as ex:
                voltar_para_conexao(f"Conexão perdida com o servidor: {ex}")

    def criar_carta_ui(codigo: str):
        """Converte '8c' -> '8 ♣' e 'Th' -> '10 ♥'."""
        if len(codigo) >= 2:
            valor_bruto = codigo[:-1]
            letra_naipe = codigo[-1].lower()
            valor_exibido = "10" if valor_bruto == "T" else valor_bruto
            icone = ICONES_NAIPE.get(letra_naipe, letra_naipe)
            texto_carta = f"{valor_exibido} {icone}"
            cor_texto = (
                ft.Colors.RED_700 if letra_naipe in ("h", "d") else ft.Colors.BLACK
            )
        else:
            texto_carta = codigo
            cor_texto = ft.Colors.BLACK

        return ft.Container(
            content=ft.Text(
                texto_carta,
                size=22,
                weight=ft.FontWeight.BOLD,
                color=cor_texto,
            ),
            padding=12,
            bgcolor=ft.Colors.WHITE,
            border_radius=8,
        )

    def atualizar_botao_partida():
        if partida_iniciada:
            btn_controle_partida.content = "Reiniciar Mesa"
            btn_controle_partida.bgcolor = ft.Colors.ORANGE_800
        else:
            btn_controle_partida.content = "Iniciar Partida"
            btn_controle_partida.bgcolor = ft.Colors.GREEN_700

    def on_clique_controle_partida(e):
        if partida_iniciada:
            enviar_comando("reiniciar_mesa")
        else:
            enviar_comando("iniciar_partida", modo_testes=switch_testes.value)

    def on_estado_mesa(dados: dict):
        nonlocal partida_iniciada
        partida_iniciada = dados.get("partida_iniciada", False)
        fase = dados.get("fase", "-")
        atualizar_botao_partida()

        btn_proxima_mao.visible = fase == "SHOWDOWN"

        txt_fase.value = f"Fase: {fase}"
        txt_pote.value = f"Pote: R$ {dados.get('pote', 0):.0f}"
        txt_saldo.value = f"Saldo: R$ {dados.get('seu_saldo', 0):.0f}"
        txt_info.value = dados.get("msg", "")

        sua_vez = dados.get("sua_vez", False)
        a_pagar = dados.get("a_pagar", 0.0)
        txt_turno.value = (
            "SUA VEZ DE AGIR!"
            if sua_vez
            else f"Vez de: {dados.get('jogador_vez', '-')}"
        )
        txt_turno.color = ft.Colors.GREEN_400 if sua_vez else ft.Colors.GREY_400

        btn_fold.disabled = not sua_vez
        btn_check_call.disabled = not sua_vez
        btn_raise.disabled = not sua_vez
        btn_check_call.content = (
            f"Pagar R${a_pagar:.0f}" if a_pagar > 0 else "Passar (Check)"
        )

    def on_limpar_mesa(dados: dict):
        row_mao.controls.clear()
        row_mesa.controls.clear()

    handlers_eventos = {
        "estado_mesa": on_estado_mesa,
        "carta_mao": lambda d: row_mao.controls.append(
            criar_carta_ui(d.get("carta", "?"))
        ),
        "carta_mesa": lambda d: row_mesa.controls.append(
            criar_carta_ui(d.get("carta", "?"))
        ),
        "limpar_mesa": on_limpar_mesa,
        "erro": lambda d: setattr(txt_info, "value", f"Aviso: {d.get('msg', '')}"),
    }

    def escutar_servidor():
        nonlocal conectado
        buffer = ""
        try:
            while conectado and sock_cliente:
                dados_brutos = sock_cliente.recv(1024).decode("utf-8")
                if not dados_brutos:
                    break
                buffer += dados_brutos
                while "\n" in buffer:
                    linha, buffer = buffer.split("\n", 1)
                    if not linha.strip():
                        continue
                    try:
                        tipo, dados = desempacotar(linha)
                        handler = handlers_eventos.get(tipo)
                        if handler:
                            handler(dados)
                            page.update()
                    except Exception as ui_err:
                        txt_info.value = f"Erro de interface: {ui_err}"
                        page.update()
        except Exception as net_err:
            if conectado:
                voltar_para_conexao(f"Desconectado: {net_err}")
                return

        if conectado:
            voltar_para_conexao("Servidor encerrou a conexão.")

    def conectar(e):
        nonlocal sock_cliente, conectado
        if conectado:
            return

        ip = input_ip.value.strip()
        nome = input_nome.value.strip()

        if not ip or not nome:
            notificar_erro_login("Preencha o IP do servidor e o seu Nome.")
            return

        try:
            porta = int(input_porta.value.strip())
            if not (1 <= porta <= 65535):
                raise ValueError
        except ValueError:
            notificar_erro_login("Porta inválida. Digite um número entre 1 e 65535.")
            return

        try:
            saldo_inicial = float(input_saldo.value.strip().replace(",", "."))
        except ValueError:
            notificar_erro_login("Saldo inicial inválido. Digite apenas números.")
            return

        if saldo_inicial < SALDO_MIN or saldo_inicial > SALDO_MAX:
            notificar_erro_login(
                f"Valor fora do limite! O Saldo Inicial deve ser entre R$ {SALDO_MIN:.0f} e R$ {SALDO_MAX:.0f}."
            )
            return

        btn_conectar.disabled = True
        btn_conectar.content = "Conectando..."
        box_notificacao.visible = False
        page.update()

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect((ip, porta))
            sock.settimeout(None)

            sock_cliente = sock
            conectado = True

            enviar_comando(
                "registro",
                nome=nome,
                saldo=saldo_inicial,
                modo_testes=switch_testes.value,
            )
            ir_para_tela_mesa(nome, saldo_inicial, ip, porta)

            threading.Thread(target=escutar_servidor, daemon=True).start()
        except Exception as ex:
            btn_conectar.disabled = False
            btn_conectar.content = "Entrar na Mesa"
            notificar_erro_login(f"Não foi possível conectar em {ip}:{porta} ({ex})")

    def on_raise(e):
        try:
            val = float(input_raise.value.replace(",", "."))
            enviar_comando("acao", acao="raise", valor=val)
        except ValueError:
            txt_info.value = "Digite um número válido para o Raise."
            page.update()

    btn_conectar = ft.Button(
        "Entrar na Mesa",
        bgcolor=ft.Colors.GREEN_700,
        color=ft.Colors.WHITE,
        height=48,
        expand=True,
        on_click=conectar,
    )
    btn_controle_partida = ft.Button(
        "Iniciar Partida",
        bgcolor=ft.Colors.GREEN_700,
        color=ft.Colors.WHITE,
        on_click=on_clique_controle_partida,
    )
    btn_proxima_mao = ft.OutlinedButton(
        "Próxima Mão",
        visible=False,
        on_click=lambda e: enviar_comando(
            "iniciar_partida", modo_testes=switch_testes.value
        ),
    )
    btn_sair = ft.OutlinedButton(
        "Sair",
        on_click=lambda e: voltar_para_conexao(),
    )
    btn_fold = ft.Button(
        "Correr (Fold)",
        bgcolor=ft.Colors.RED_800,
        color=ft.Colors.WHITE,
        disabled=True,
        on_click=lambda e: enviar_comando("acao", acao="fold"),
    )
    btn_check_call = ft.Button(
        "Passar (Check)",
        bgcolor=ft.Colors.BLUE_800,
        color=ft.Colors.WHITE,
        disabled=True,
        on_click=lambda e: enviar_comando(
            "acao", acao="call" if "Pagar" in str(btn_check_call.content) else "check"
        ),
    )
    btn_raise = ft.Button(
        "Apostar (Raise)",
        bgcolor=ft.Colors.GREEN_800,
        color=ft.Colors.WHITE,
        disabled=True,
        on_click=on_raise,
    )

    tela_conexao = ft.Column(
        visible=True,
        spacing=14,
        controls=[
            ft.Text("Conectar à Mesa de Poker", size=22, weight=ft.FontWeight.BOLD),
            input_ip,
            input_porta,
            input_nome,
            input_saldo,
            switch_testes,
            box_notificacao,
            ft.Row([btn_conectar]),
        ],
    )

    tela_mesa = ft.Column(
        visible=False,
        spacing=12,
        controls=[
            ft.Row(
                [txt_jogador_header, btn_sair],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            ft.Row(
                [txt_fase, ft.Row([btn_proxima_mao, btn_controle_partida], spacing=8)],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            ft.Row(
                [txt_pote, txt_saldo],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            txt_turno,
            ft.Container(
                content=txt_info,
                padding=10,
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                border_radius=6,
            ),
            ft.Text("Suas Cartas Privadas:", weight=ft.FontWeight.BOLD),
            row_mao,
            ft.Text("Cartas Comunitárias (Mesa):", weight=ft.FontWeight.BOLD),
            row_mesa,
            ft.Divider(),
            ft.Text("Ações:", weight=ft.FontWeight.BOLD),
            ft.Row([btn_fold, btn_check_call], spacing=10),
            ft.Row([input_raise, btn_raise], spacing=10),
        ],
    )

    page.add(tela_conexao, tela_mesa)


if __name__ == "__main__":
    ft.run(main)
