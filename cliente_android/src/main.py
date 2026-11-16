import re
import socket
import threading
from itertools import combinations
import flet as ft
from protocolo import desempacotar, empacotar

SALDO_MIN = 200.0
SALDO_MAX = 10000.0

ICONES_NAIPE = {
    "s": "♠",
    "h": "♥",
    "d": "♦",
    "c": "♣",
}

NOMES_VALORES_TTS = {
    "A": "Ás",
    "2": "Dois",
    "3": "Três",
    "4": "Quatro",
    "5": "Cinco",
    "6": "Seis",
    "7": "Sete",
    "8": "Oito",
    "9": "Nove",
    "T": "Dez",
    "10": "Dez",
    "J": "Valete",
    "Q": "Dama",
    "K": "Rei",
}

NOMES_NAIPES_TTS = {
    "h": "Copas",
    "d": "Ouros",
    "s": "Espadas",
    "c": "Paus",
}

VALORES_MAP = {
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
    "7": 7,
    "8": 8,
    "9": 9,
    "T": 10,
    "J": 11,
    "Q": 12,
    "K": 13,
    "A": 14,
}
NOMES_COMBINACOES = [
    "Carta Alta",
    "Um Par",
    "Dois Pares",
    "Trinca",
    "Sequência",
    "Flush",
    "Full House",
    "Quadra",
    "Straight Flush",
]


class AndroidTTS:
    """Wrapper para o Text-to-Speech nativo do Android via Pyjnius."""

    def __init__(self):
        self.ativo = True
        self._tts = None
        self._idioma_configurado = False
        self._queue_add = 1
        self._queue_flush = 0
        self._utterance_id = 0
        self._lock = threading.Lock()
        self._inicializar_android()

    def _inicializar_android(self):
        try:
            from jnius import autoclass

            ActivityThread = autoclass("android.app.ActivityThread")
            TextToSpeech = autoclass("android.speech.tts.TextToSpeech")

            app = ActivityThread.currentApplication()
            if app is None:
                return
            context = app.getApplicationContext()

            self._queue_add = TextToSpeech.QUEUE_ADD
            self._queue_flush = TextToSpeech.QUEUE_FLUSH
            self._tts = TextToSpeech(context, None)
            self._garantir_idioma()
        except Exception as e:
            print(f"[TTS] Modo desktop/fallback: {e}")
            self._tts = None

    def _garantir_idioma(self):
        if self._tts is not None and not self._idioma_configurado:
            self._idioma_configurado = True
            try:
                from jnius import autoclass

                Locale = autoclass("java.util.Locale")
                res = self._tts.setLanguage(Locale("pt", "BR"))
                if res < 0:
                    self._tts.setLanguage(Locale.getDefault())
            except Exception:
                pass

    def falar(self, texto: str, interromper: bool = False):
        texto = texto.strip()
        if not texto or not self.ativo:
            return

        with self._lock:
            self._utterance_id += 1
            uid = f"poker_tts_{self._utterance_id}"

        if self._tts is not None:
            try:
                self._garantir_idioma()
                modo = self._queue_flush if interromper else self._queue_add
                self._tts.speak(texto, modo, None, uid)
            except Exception as e:
                print(f"[TTS] Erro ao falar: {e}")
        else:
            print(f"[TTS] {texto}")

    def parar(self):
        if self._tts is not None:
            try:
                self._tts.stop()
            except Exception:
                pass


def carta_para_texto_tts(codigo: str) -> str:
    if len(codigo) < 2:
        return codigo
    valor = NOMES_VALORES_TTS.get(codigo[:-1].upper(), codigo[:-1])
    naipe = NOMES_NAIPES_TTS.get(codigo[-1].lower(), "")
    return f"{valor} de {naipe}" if naipe else valor


def formatar_acao_para_tts(msg: str) -> str | None:
    """Filtra eventos de jogo e adapta o texto para pronúncia natural em português."""
    if not msg:
        return None

    palavras_chave = (
        "correu",
        "passou",
        "pagou",
        "aumentou",
        "ALL-IN",
        "ganhou",
        "SHOWDOWN",
        "Blinds:",
        "Flop virado",
        "Turn virado",
        "River virado",
        "Rebuy",
        "conectou",
        "entrou",
        "saiu",
        "desconectou",
    )
    if not any(k in msg for k in palavras_chave):
        return None

    texto = msg
    for termo in (" (Fold)", " (Check)", " (Call)", " (Raise)"):
        texto = texto.replace(termo, "")
    texto = texto.replace("ALL-IN", "all-in").replace("SHOWDOWN!", "Showdown!")
    texto = texto.replace("(SB ", "(small blind ").replace("(BB ", "(big blind ")
    texto = re.sub(r"R\$\s*(\d+(?:[.,]\d+)?)", r"\1 reais", texto)
    return texto


def fmt_valor(v: float) -> str:
    v = round(float(v), 2)
    return f"{v:.0f}" if v == int(v) else f"{v:.2f}"


def _avaliar_5(cinco: tuple[str, ...]) -> tuple[int, list[int]]:
    valores = sorted([VALORES_MAP[c[0].upper()] for c in cinco], reverse=True)
    naipes = [c[1].lower() for c in cinco]
    eh_flush = len(set(naipes)) == 1
    eh_straight = (valores == list(range(valores[0], valores[0] - 5, -1))) or (
        valores == [14, 5, 4, 3, 2]
    )
    if valores == [14, 5, 4, 3, 2]:
        valores = [5, 4, 3, 2, 1]

    contagem = sorted([(valores.count(v), v) for v in set(valores)], reverse=True)
    freq = [p[0] for p in contagem]
    desempate = [p[1] for p in contagem]

    if eh_straight and eh_flush:
        return (8, desempate)
    if freq == [4, 1]:
        return (7, desempate)
    if freq == [3, 2]:
        return (6, desempate)
    if eh_flush:
        return (5, desempate)
    if eh_straight:
        return (4, desempate)
    if freq == [3, 1, 1]:
        return (3, desempate)
    if freq == [2, 2, 1]:
        return (2, desempate)
    if freq == [2, 1, 1, 1]:
        return (1, desempate)
    return (0, desempate)


def descobrir_combinacao(mao: list[str], mesa: list[str]) -> str:
    todas = [c for c in (mao + mesa) if len(c) >= 2 and c[0].upper() in VALORES_MAP]
    if not todas:
        return "Aguardando cartas..."
    if len(todas) < 5:
        valores = [VALORES_MAP[c[0].upper()] for c in todas]
        cont = sorted([valores.count(v) for v in set(valores)], reverse=True)
        if cont[0] == 4:
            return "Quadra"
        if cont[0] == 3:
            return "Trinca"
        if cont[:2] == [2, 2]:
            return "Dois Pares"
        if cont[0] == 2:
            return "Um Par"
        return "Carta Alta"
    melhor = max(_avaliar_5(comb) for comb in combinations(todas, 5))
    return NOMES_COMBINACOES[melhor[0]]


def main(page: ft.Page):
    page.title = "PokerTable"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 16
    page.scroll = ft.ScrollMode.AUTO

    tts = AndroidTTS()
    sock_cliente = None
    conectado = False
    ultima_msg_falada = ""
    cartas_mao_codigos: list[str] = []
    cartas_mesa_codigos: list[str] = []

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
    # TELA 2: MESA DE POKER E AÇÕES DO JOGADOR
    # =========================================================================
    txt_jogador_header = ft.Text("", size=14, color=ft.Colors.GREY_400)
    txt_papel = ft.Text(
        "", size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN_300
    )
    txt_fase = ft.Text("Fase: AGUARDANDO", weight=ft.FontWeight.BOLD)
    txt_saldo = ft.Text(
        "Saldo: R$ 0", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_300
    )
    txt_pote = ft.Text(
        "Pote: R$ 0", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_300
    )
    txt_turno = ft.Text("Vez de: -", size=16, weight=ft.FontWeight.BOLD)
    txt_combinacao = ft.Text(
        "Jogo Atual: Aguardando cartas...",
        size=15,
        weight=ft.FontWeight.BOLD,
        color=ft.Colors.CYAN_300,
    )
    txt_info = ft.Text("Aguardando o servidor iniciar a partida...", size=14)

    def alternar_audio(_e):
        tts.ativo = not tts.ativo
        if not tts.ativo:
            tts.parar()
        btn_audio.text = "Áudio: ON" if tts.ativo else "Áudio: OFF"
        page.update()

    btn_audio = ft.OutlinedButton("Áudio: ON", on_click=alternar_audio)

    row_mao = ft.Row(spacing=10)
    row_mesa = ft.Row(spacing=8, wrap=True)
    input_raise = ft.TextField(
        label="Valor Raise (R$)",
        value="20",
        width=140,
        keyboard_type=ft.KeyboardType.NUMBER,
    )

    input_rebuy = ft.TextField(
        label="Valor Rebuy (R$)",
        value="500",
        width=150,
        keyboard_type=ft.KeyboardType.NUMBER,
    )
    box_rebuy = ft.Container(
        visible=False,
        padding=10,
        bgcolor=ft.Colors.BLUE_GREY_900,
        border_radius=8,
        content=ft.Column(
            spacing=8,
            controls=[
                ft.Text("Adicionar Fichas (Rebuy)", weight=ft.FontWeight.BOLD),
                ft.Row(
                    spacing=10,
                    controls=[
                        input_rebuy,
                        ft.Button(
                            "Fazer Rebuy",
                            bgcolor=ft.Colors.AMBER_700,
                            color=ft.Colors.WHITE,
                            on_click=lambda e: on_rebuy(),
                        ),
                    ],
                ),
            ],
        ),
    )

    # =========================================================================
    # TELA 3: PLACAR FINAL DA SESSÃO
    # =========================================================================
    col_placar_lista = ft.Column(spacing=8)

    def mostrar_tela(qual: str):
        tela_conexao.visible = qual == "CONEXAO"
        tela_mesa.visible = qual == "MESA"
        tela_placar.visible = qual == "PLACAR"
        page.update()

    def ir_para_tela_mesa(nome: str, saldo: float, ip: str, porta: int):
        box_notificacao.visible = False
        txt_jogador_header.value = f"{nome} • {ip}:{porta}"
        txt_saldo.value = f"Saldo: R$ {fmt_valor(saldo)}"
        mostrar_tela("MESA")

    def voltar_para_conexao(motivo: str = ""):
        nonlocal conectado, sock_cliente, ultima_msg_falada
        conectado = False
        ultima_msg_falada = ""
        tts.parar()
        if sock_cliente:
            try:
                sock_cliente.close()
            except Exception:
                pass
            sock_cliente = None

        cartas_mao_codigos.clear()
        cartas_mesa_codigos.clear()
        row_mao.controls.clear()
        row_mesa.controls.clear()
        col_placar_lista.controls.clear()
        btn_conectar.disabled = False
        btn_conectar.content = "Entrar na Mesa"
        mostrar_tela("CONEXAO")
        if motivo:
            notificar_erro_login(motivo)

    def enviar_comando(tipo: str, **dados):
        if conectado and sock_cliente:
            try:
                sock_cliente.sendall(empacotar(tipo, **dados))
            except Exception as ex:
                voltar_para_conexao(f"Conexão perdida com o servidor: {ex}")

    def criar_carta_ui(codigo: str):
        if len(codigo) >= 2:
            valor_bruto = codigo[:-1]
            letra_naipe = codigo[-1].lower()
            valor_exibido = "10" if valor_bruto.upper() == "T" else valor_bruto.upper()
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

    def atualizar_combinacao():
        txt_combinacao.value = f"Jogo Atual: {descobrir_combinacao(cartas_mao_codigos, cartas_mesa_codigos)}"

    def on_estado_mesa(dados: dict):
        nonlocal ultima_msg_falada
        fase = dados.get("fase", "-")
        if fase != "PLACAR_FINAL" and tela_placar.visible:
            tela_placar.visible = False
            tela_mesa.visible = True

        txt_fase.value = f"Fase: {fase}"
        pote = dados.get("pote", 0.0)
        qtd_side = dados.get("qtd_side_pots", 0)
        txt_pote.value = (
            f"Pote: R$ {fmt_valor(pote)} (+{qtd_side} Side)"
            if qtd_side > 0
            else f"Pote: R$ {fmt_valor(pote)}"
        )
        saldo = dados.get("seu_saldo", 0.0)
        txt_saldo.value = f"Saldo: R$ {fmt_valor(saldo)}"

        msg = dados.get("msg", "")
        txt_info.value = msg
        if msg and msg != ultima_msg_falada:
            ultima_msg_falada = msg
            fala = formatar_acao_para_tts(msg)
            if fala:
                tts.falar(fala)

        papel = dados.get("papel", "")
        em_espera = dados.get("em_espera", False)
        if em_espera:
            txt_papel.value = "MODO DE ESPERA (entra na próxima rodada)"
            txt_papel.color = ft.Colors.ORANGE_300
        elif papel:
            txt_papel.value = f"Posição: {papel}"
            txt_papel.color = ft.Colors.CYAN_300
        else:
            txt_papel.value = ""

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
        btn_all_in.disabled = not sua_vez or saldo <= 0
        btn_check_call.content = (
            f"Pagar R${fmt_valor(a_pagar)}" if a_pagar > 0 else "Passar (Check)"
        )

        box_rebuy.visible = bool(dados.get("pode_rebuy", False))

    def on_limpar_mesa(_dados: dict):
        nonlocal ultima_msg_falada
        ultima_msg_falada = ""
        cartas_mao_codigos.clear()
        cartas_mesa_codigos.clear()
        row_mao.controls.clear()
        row_mesa.controls.clear()
        atualizar_combinacao()

    def on_carta_mao(dados: dict):
        codigo = dados.get("carta", "?")
        cartas_mao_codigos.append(codigo)
        row_mao.controls.append(criar_carta_ui(codigo))
        atualizar_combinacao()
        tts.falar(f"Sua carta: {carta_para_texto_tts(codigo)}")

    def on_carta_mesa(dados: dict):
        codigo = dados.get("carta", "?")
        cartas_mesa_codigos.append(codigo)
        row_mesa.controls.append(criar_carta_ui(codigo))
        atualizar_combinacao()
        tts.falar(f"Carta na mesa: {carta_para_texto_tts(codigo)}")

    def on_placar_final(dados: dict):
        ranking = dados.get("ranking", [])
        col_placar_lista.controls.clear()

        for idx, item in enumerate(ranking):
            lucro = float(item.get("lucro", 0))
            if lucro > 0:
                txt_l = f"+R$ {fmt_valor(lucro)}"
                cor_l = ft.Colors.GREEN_400
            elif lucro < 0:
                txt_l = f"-R$ {fmt_valor(abs(lucro))}"
                cor_l = ft.Colors.RED_400
            else:
                txt_l = "R$ 0"
                cor_l = ft.Colors.GREY_400

            col_placar_lista.controls.append(
                ft.Container(
                    padding=12,
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                    border_radius=8,
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Column(
                                spacing=2,
                                controls=[
                                    ft.Text(
                                        f"{idx + 1}º  {item.get('nome', '-')}",
                                        size=16,
                                        weight=ft.FontWeight.BOLD,
                                    ),
                                    ft.Text(
                                        f"Investido: R$ {fmt_valor(item.get('total_investido', 0))} • Saldo: R$ {fmt_valor(item.get('saldo_final', 0))}",
                                        size=12,
                                        color=ft.Colors.GREY_400,
                                    ),
                                ],
                            ),
                            ft.Text(
                                txt_l,
                                size=16,
                                weight=ft.FontWeight.BOLD,
                                color=cor_l,
                            ),
                        ],
                    ),
                )
            )
        mostrar_tela("PLACAR")

    def on_mesa_reiniciada(_dados: dict):
        on_limpar_mesa({})
        mostrar_tela("MESA")

    handlers_eventos = {
        "estado_mesa": on_estado_mesa,
        "carta_mao": on_carta_mao,
        "carta_mesa": on_carta_mesa,
        "limpar_mesa": on_limpar_mesa,
        "placar_final": on_placar_final,
        "mesa_reiniciada": on_mesa_reiniciada,
        "erro": lambda d: setattr(txt_info, "value", f"Aviso: {d.get('msg', '')}"),
    }

    def escutar_servidor():
        nonlocal conectado
        buffer = ""
        try:
            while conectado and sock_cliente:
                dados_brutos = sock_cliente.recv(4096).decode("utf-8")
                if not dados_brutos:
                    break
                buffer += dados_brutos
                atualizou = False
                while "\n" in buffer:
                    linha, buffer = buffer.split("\n", 1)
                    if not linha.strip():
                        continue
                    try:
                        tipo, dados = desempacotar(linha)
                        handler = handlers_eventos.get(tipo)
                        if handler:
                            handler(dados)
                            atualizou = True
                    except Exception as ui_err:
                        txt_info.value = f"Erro de interface: {ui_err}"
                        atualizou = True
                if atualizou:
                    page.update()
        except Exception as net_err:
            if conectado:
                voltar_para_conexao(f"Desconectado: {net_err}")
                return

        if conectado:
            voltar_para_conexao("Servidor encerrou a conexão.")

    def conectar(_e):
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
                f"Saldo Inicial deve ser entre R$ {fmt_valor(SALDO_MIN)} e R$ {fmt_valor(SALDO_MAX)}."
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

            enviar_comando("registro", nome=nome, saldo=saldo_inicial)
            ir_para_tela_mesa(nome, saldo_inicial, ip, porta)

            threading.Thread(target=escutar_servidor, daemon=True).start()
        except Exception as ex:
            btn_conectar.disabled = False
            btn_conectar.content = "Entrar na Mesa"
            notificar_erro_login(f"Não foi possível conectar em {ip}:{porta} ({ex})")

    def on_raise(_e):
        try:
            val = float(input_raise.value.replace(",", "."))
            enviar_comando("acao", acao="raise", valor=val)
        except ValueError:
            txt_info.value = "Digite um número válido para o Raise."
            page.update()

    def on_rebuy():
        try:
            val = float(input_rebuy.value.replace(",", "."))
            if val < SALDO_MIN or val > SALDO_MAX:
                txt_info.value = f"Rebuy deve ser entre R$ {fmt_valor(SALDO_MIN)} e R$ {fmt_valor(SALDO_MAX)}."
                page.update()
                return
            enviar_comando("rebuy", valor=val)
        except ValueError:
            txt_info.value = "Digite um valor numérico válido para o Rebuy."
            page.update()

    btn_conectar = ft.Button(
        "Entrar na Mesa",
        bgcolor=ft.Colors.GREEN_700,
        color=ft.Colors.WHITE,
        height=48,
        expand=True,
        on_click=conectar,
    )
    btn_sair = ft.OutlinedButton("Sair", on_click=lambda e: voltar_para_conexao())
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
    btn_all_in = ft.Button(
        "All-In",
        bgcolor=ft.Colors.ORANGE_800,
        color=ft.Colors.WHITE,
        disabled=True,
        on_click=lambda e: enviar_comando("acao", acao="all_in"),
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
            box_notificacao,
            ft.Row([btn_conectar]),
        ],
    )

    tela_mesa = ft.Column(
        visible=False,
        spacing=10,
        controls=[
            ft.Row(
                [txt_jogador_header, ft.Row([btn_audio, btn_sair], spacing=6)],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            txt_papel,
            txt_fase,
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
            txt_combinacao,
            ft.Text("Cartas Comunitárias (Mesa):", weight=ft.FontWeight.BOLD),
            row_mesa,
            ft.Divider(),
            ft.Text("Ações:", weight=ft.FontWeight.BOLD),
            ft.Row([btn_fold, btn_check_call, btn_all_in], spacing=8, wrap=True),
            ft.Row([input_raise, btn_raise], spacing=10),
            box_rebuy,
        ],
    )

    tela_placar = ft.Column(
        visible=False,
        spacing=12,
        controls=[
            ft.Row(
                [
                    ft.Text("Placar Final da Mesa", size=22, weight=ft.FontWeight.BOLD),
                    ft.OutlinedButton("Sair", on_click=lambda e: voltar_para_conexao()),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            ft.Text(
                "Aguardando o dealer iniciar uma nova mesa ou desconectar.",
                size=13,
                color=ft.Colors.GREY_400,
            ),
            col_placar_lista,
        ],
    )

    page.add(tela_conexao, tela_mesa, tela_placar)


if __name__ == "__main__":
    ft.run(main)
