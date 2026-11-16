#!/usr/bin/env python3
import queue
import subprocess
import sys
import tkinter as tk

from regras_de_negocio import fmt_valor
from servidor_mesa import ServidorMesa, obter_ip_local

LARGURA = 480
ALTURA = 320
ALTURA_HEADER = 36
ALTURA_CORPO = ALTURA - ALTURA_HEADER

COR_BG = "#121212"
COR_CARD = "#1E1E1E"
COR_CARD_ALT = "#262626"
COR_TEXTO = "#FFFFFF"
COR_SUB = "#B0BEC5"

NAIPES_ICONE = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}


def formatar_carta(codigo: str) -> tuple[str, str]:
    if len(codigo) < 2:
        return codigo, "#111111"
    valor = "10" if codigo[:-1].upper() == "T" else codigo[:-1].upper()
    naipe = codigo[-1].lower()
    icone = NAIPES_ICONE.get(naipe, naipe)
    cor = "#C62828" if naipe in ("h", "d") else "#111111"
    return f"{valor}{icone}", cor


class ScrollableTouchFrame(tk.Frame):
    """Container com rolagem vertical por arrasto de dedo (touch) para LCD 480x320."""

    def __init__(self, master, bg=COR_BG, **kwargs):
        super().__init__(master, bg=bg, **kwargs)
        self.canvas = tk.Canvas(self, bg=bg, bd=0, highlightthickness=0)
        self.scrollbar = tk.Scrollbar(
            self, orient="vertical", command=self.canvas.yview, width=10
        )
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.win_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        self._drag_y = 0
        self.vincular_touch(self.canvas)
        self.vincular_touch(self.inner)

    def _on_inner_configure(self, _e=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self.win_id, width=event.width)

    def vincular_touch(self, widget):
        widget.bind("<ButtonPress-1>", self._inicio_arrasto, add="+")
        widget.bind("<B1-Motion>", self._movimento_arrasto, add="+")

    def vincular_filhos_recursivo(self, widget):
        if not isinstance(widget, tk.Button):
            self.vincular_touch(widget)
        for filho in widget.winfo_children():
            self.vincular_filhos_recursivo(filho)

    def _inicio_arrasto(self, event):
        self._drag_y = event.y_root

    def _movimento_arrasto(self, event):
        dy = self._drag_y - event.y_root
        if abs(dy) >= 6:
            unidades = int(dy / 12)
            if unidades != 0:
                self.canvas.yview_scroll(unidades, "units")
                self._drag_y = event.y_root

    def limpar(self):
        for w in self.inner.winfo_children():
            w.destroy()
        self.canvas.yview_moveto(0)


class InterfacePokerLCD:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("PokerTable Central")

        # Detecta a resolução real do display (evita cortar o rodapé em telas 320x240)
        global LARGURA, ALTURA, ALTURA_CORPO
        larg_tela = self.root.winfo_screenwidth()
        alt_tela = self.root.winfo_screenheight()
        if larg_tela > 0 and alt_tela > 0:
            LARGURA = min(480, larg_tela)
            ALTURA = min(320, alt_tela)
            ALTURA_CORPO = ALTURA - ALTURA_HEADER

        self.root.title("PokerTable Central")
        self.root.geometry(f"{LARGURA}x{ALTURA}+0+0")
        self.root.configure(bg=COR_BG, cursor="none")
        self.root.resizable(False, False)
        self.root.bind("<Escape>", lambda _e: self._sair_app())

        self.ip_local = obter_ip_local()
        self.fila_ui: queue.SimpleQueue = queue.SimpleQueue()
        self.tela_ativa = ""

        self._criar_header_global()
        self._criar_tela_lobby()
        self._criar_tela_distribuir_mao()
        self._criar_tela_distribuir_mesa()
        self._criar_tela_jogo()
        self._criar_tela_virar_mesa()
        self._criar_tela_showdown()
        self._criar_tela_placar()
        self._criar_overlay_desligamento()

        self.servidor = ServidorMesa(
            porta=5000, on_atualizar_ui=lambda: self.fila_ui.put("ATUALIZAR")
        )
        self.servidor.iniciar()

        self._renderizar_estado()
        self._processar_fila_ui()

        modo_mouse = "--mouse" in sys.argv
        self.root.title("PokerTable Central")
        if modo_mouse:
            self.root.geometry(f"{LARGURA}x{ALTURA}+80+80")
            self.root.configure(bg=COR_BG, cursor="arrow")
        else:
            self.root.geometry(f"{LARGURA}x{ALTURA}+0+0")
            self.root.configure(bg=COR_BG, cursor="none")

    # =========================================================================
    # HEADER GLOBAL (PRESENTE EM TODAS AS TELAS COM BOTÃO DE DESLIGAR)
    # =========================================================================
    def _criar_header_global(self):
        self.header = tk.Frame(self.root, bg="#1A1A1A", height=ALTURA_HEADER)
        self.header.place(x=0, y=0, width=LARGURA, height=ALTURA_HEADER)

        self.lbl_header_titulo = tk.Label(
            self.header,
            text=f"POKER • {self.ip_local}:5000",
            fg="#E0E0E0",
            bg="#1A1A1A",
            font=("DejaVu Sans", 11, "bold"),
            anchor="w",
        )
        self.lbl_header_titulo.place(x=10, y=0, width=420, height=ALTURA_HEADER)

        tk.Button(
            self.header,
            text="⏻",
            command=self._mostrar_confirmacao_desligar,
            bg="#C62828",
            fg="#FFFFFF",
            activebackground="#8E0000",
            activeforeground="#FFFFFF",
            font=("DejaVu Sans", 13, "bold"),
            bd=0,
            highlightthickness=0,
        ).place(x=LARGURA - 42, y=3, width=38, height=30)

    # =========================================================================
    # TELA 1: LOBBY / AGUARDANDO JOGADORES
    # =========================================================================
    def _criar_tela_lobby(self):
        f = tk.Frame(self.root, bg=COR_BG)
        self.frame_lobby = f

        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(0, weight=0)  # Topo (Total e Blinds)
        f.grid_rowconfigure(1, weight=1)  # Lista de jogadores (expande/encolhe)
        f.grid_rowconfigure(2, weight=0)  # Rodapé (Bot e Iniciar Partida - fixo)

        topo = tk.Frame(f, bg="#181818", height=34)
        topo.grid(row=0, column=0, sticky="ew", padx=6, pady=(4, 2))
        topo.pack_propagate(False)

        self.lbl_lobby_total = tk.Label(
            topo,
            text="Total: R$ 0",
            fg="#69F0AE",
            bg="#181818",
            font=("DejaVu Sans", 11, "bold"),
        )
        self.lbl_lobby_total.pack(side="left", padx=8)

        ctrl_blinds = tk.Frame(topo, bg="#181818")
        ctrl_blinds.pack(side="right", padx=6)

        tk.Button(
            ctrl_blinds,
            text="-",
            command=lambda: self.servidor.ui_ajustar_blinds(-1),
            bg="#37474F",
            fg="#FFFFFF",
            activebackground="#546E7A",
            font=("DejaVu Sans", 12, "bold"),
            width=2,
            bd=0,
            highlightthickness=0,
        ).pack(side="left", padx=2, pady=2)

        self.lbl_blinds = tk.Label(
            ctrl_blinds,
            text="SB/BB: 10/20",
            fg="#FFD54F",
            bg="#181818",
            font=("DejaVu Sans", 10, "bold"),
            width=13,
        )
        self.lbl_blinds.pack(side="left", padx=2)

        tk.Button(
            ctrl_blinds,
            text="+",
            command=lambda: self.servidor.ui_ajustar_blinds(1),
            bg="#37474F",
            fg="#FFFFFF",
            activebackground="#546E7A",
            font=("DejaVu Sans", 12, "bold"),
            width=2,
            bd=0,
            highlightthickness=0,
        ).pack(side="left", padx=2, pady=2)

        self.scroll_lobby = ScrollableTouchFrame(f, bg=COR_BG)
        self.scroll_lobby.grid(row=1, column=0, sticky="nsew", padx=6, pady=2)

        rodape = tk.Frame(f, bg=COR_BG, height=44)
        rodape.grid(row=2, column=0, sticky="ew", padx=6, pady=(2, 4))
        rodape.pack_propagate(False)

        self.btn_bot = tk.Button(
            rodape,
            text="Modo Teste: OFF",
            command=lambda: self.servidor.ui_alternar_bot(),
            bg="#455A64",
            fg="#FFFFFF",
            activebackground="#607D8B",
            font=("DejaVu Sans", 10, "bold"),
            bd=0,
            highlightthickness=0,
        )
        self.btn_bot.pack(side="left", fill="both", expand=True, padx=(0, 4))

        self.btn_iniciar = tk.Button(
            rodape,
            text="INICIAR PARTIDA",
            command=lambda: self.servidor.ui_iniciar_rodada(),
            bg="#2E7D32",
            fg="#FFFFFF",
            activebackground="#1B5E20",
            disabledforeground="#9E9E9E",
            font=("DejaVu Sans", 11, "bold"),
            bd=0,
            highlightthickness=0,
        )
        self.btn_iniciar.pack(side="right", fill="both", expand=True, padx=(4, 0))

    # =========================================================================
    # TELA 2: DISTRIBUIÇÃO DAS 2 CARTAS POR JOGADOR (OCULTAS NO LCD)
    # =========================================================================
    def _criar_tela_distribuir_mao(self):
        f = tk.Frame(self.root, bg=COR_BG)
        self.frame_distribuir_mao = f

        self.lbl_dist_progresso = tk.Label(
            f,
            text="DISTRIBUINDO CARTAS PRIVADAS",
            fg="#90CAF9",
            bg=COR_BG,
            font=("DejaVu Sans", 11, "bold"),
        )
        self.lbl_dist_progresso.pack(pady=(10, 4))

        tk.Label(
            f,
            text="Escaneie e entregue 2 cartas para:",
            fg=COR_SUB,
            bg=COR_BG,
            font=("DejaVu Sans", 11),
        ).pack()

        self.lbl_dist_nome = tk.Label(
            f,
            text="-",
            fg="#FFFFFF",
            bg=COR_BG,
            font=("DejaVu Sans", 22, "bold"),
        )
        self.lbl_dist_nome.pack(pady=(4, 6))

        self.lbl_dist_contador = tk.Label(
            f,
            text="0 / 2 cartas lidas",
            fg="#FFD54F",
            bg="#1E1E1E",
            font=("DejaVu Sans", 16, "bold"),
            padx=20,
            pady=8,
        )
        self.lbl_dist_contador.pack(pady=4)

        self.lbl_dist_aviso = tk.Label(
            f,
            text="",
            fg="#FF8A65",
            bg=COR_BG,
            font=("DejaVu Sans", 10, "bold"),
            wraplength=450,
        )
        self.lbl_dist_aviso.pack(pady=(6, 4))

        rodape = tk.Frame(f, bg=COR_BG, height=52)
        rodape.pack(side="bottom", fill="x", padx=10, pady=8)
        rodape.pack_propagate(False)

        tk.Button(
            rodape,
            text="Limpar / Re-escanear",
            command=lambda: self.servidor.ui_limpar_leitura(),
            bg="#E65100",
            fg="#FFFFFF",
            activebackground="#BF360C",
            font=("DejaVu Sans", 11, "bold"),
            bd=0,
            highlightthickness=0,
        ).pack(side="left", fill="both", expand=True, padx=(0, 6))

        self.btn_confirmar_mao = tk.Button(
            rodape,
            text="Confirmar Entrega",
            command=lambda: self.servidor.ui_confirmar_distribuicao(),
            bg="#2E7D32",
            fg="#FFFFFF",
            activebackground="#1B5E20",
            disabledforeground="#888888",
            font=("DejaVu Sans", 12, "bold"),
            bd=0,
            highlightthickness=0,
        )
        self.btn_confirmar_mao.pack(side="right", fill="both", expand=True, padx=(6, 0))

    # =========================================================================
    # TELA 3: DISTRIBUIÇÃO DAS 5 CARTAS DA MESA (VIRADAS PARA BAIXO)
    # =========================================================================
    def _criar_tela_distribuir_mesa(self):
        f = tk.Frame(self.root, bg=COR_BG)
        self.frame_distribuir_mesa = f

        tk.Label(
            f,
            text="CARTAS DA MESA (VIRADAS PARA BAIXO)",
            fg="#80CBC4",
            bg=COR_BG,
            font=("DejaVu Sans", 12, "bold"),
        ).pack(pady=(10, 4))

        tk.Label(
            f,
            text="Escaneie as 5 cartas comunitárias e disponha viradas para baixo:",
            fg=COR_SUB,
            bg=COR_BG,
            font=("DejaVu Sans", 10),
        ).pack()

        self.row_slots_ocultos = tk.Frame(f, bg=COR_BG)
        self.row_slots_ocultos.pack(pady=10)
        self.slots_ocultos_lbls = []
        for _ in range(5):
            lbl = tk.Label(
                self.row_slots_ocultos,
                text="?",
                fg="#78909C",
                bg="#263238",
                font=("DejaVu Sans", 16, "bold"),
                width=4,
                height=2,
            )
            lbl.pack(side="left", padx=5)
            self.slots_ocultos_lbls.append(lbl)

        self.lbl_mesa_contador = tk.Label(
            f,
            text="0 / 5 cartas lidas",
            fg="#FFD54F",
            bg=COR_BG,
            font=("DejaVu Sans", 14, "bold"),
        )
        self.lbl_mesa_contador.pack(pady=2)

        self.lbl_mesa_aviso = tk.Label(
            f,
            text="",
            fg="#FF8A65",
            bg=COR_BG,
            font=("DejaVu Sans", 10, "bold"),
            wraplength=450,
        )
        self.lbl_mesa_aviso.pack(pady=4)

        rodape = tk.Frame(f, bg=COR_BG, height=52)
        rodape.pack(side="bottom", fill="x", padx=10, pady=8)
        rodape.pack_propagate(False)

        tk.Button(
            rodape,
            text="Limpar / Re-escanear",
            command=lambda: self.servidor.ui_limpar_leitura(),
            bg="#E65100",
            fg="#FFFFFF",
            activebackground="#BF360C",
            font=("DejaVu Sans", 11, "bold"),
            bd=0,
            highlightthickness=0,
        ).pack(side="left", fill="both", expand=True, padx=(0, 6))

        self.btn_confirmar_mesa = tk.Button(
            rodape,
            text="Confirmar 5 Cartas",
            command=lambda: self.servidor.ui_confirmar_distribuicao(),
            bg="#2E7D32",
            fg="#FFFFFF",
            activebackground="#1B5E20",
            disabledforeground="#888888",
            font=("DejaVu Sans", 12, "bold"),
            bd=0,
            highlightthickness=0,
        )
        self.btn_confirmar_mesa.pack(
            side="right", fill="both", expand=True, padx=(6, 0)
        )

    # =========================================================================
    # TELA 4: APOSTAS EM ANDAMENTO (PRÉ-FLOP, FLOP, TURN, RIVER)
    # =========================================================================
    def _criar_tela_jogo(self):
        f = tk.Frame(self.root, bg=COR_BG)
        self.frame_jogo = f

        painel_topo = tk.Frame(f, bg=COR_CARD, height=54)
        painel_topo.pack(fill="x", padx=6, pady=(4, 3))
        painel_topo.pack_propagate(False)

        esq = tk.Frame(painel_topo, bg=COR_CARD)
        esq.pack(side="left", fill="both", expand=True, padx=8, pady=4)

        tk.Label(
            esq,
            text="VEZ DE:",
            fg=COR_SUB,
            bg=COR_CARD,
            font=("DejaVu Sans", 8, "bold"),
        ).pack(anchor="w")
        self.lbl_jogo_vez = tk.Label(
            esq, text="-", fg="#69F0AE", bg=COR_CARD, font=("DejaVu Sans", 15, "bold")
        )
        self.lbl_jogo_vez.pack(anchor="w")

        dir_box = tk.Frame(painel_topo, bg=COR_CARD)
        dir_box.pack(side="right", fill="y", padx=8, pady=4)

        self.lbl_jogo_pote = tk.Label(
            dir_box,
            text="POTE: R$ 0",
            fg="#FFD54F",
            bg=COR_CARD,
            font=("DejaVu Sans", 13, "bold"),
            anchor="e",
        )
        self.lbl_jogo_pote.pack(anchor="e")

        self.lbl_jogo_aposta = tk.Label(
            dir_box,
            text="Aposta: R$ 0",
            fg=COR_SUB,
            bg=COR_CARD,
            font=("DejaVu Sans", 9),
            anchor="e",
        )
        self.lbl_jogo_aposta.pack(anchor="e")

        # Faixa das 5 cartas da mesa (reveladas ou ocultas)
        self.row_cartas_jogo = tk.Frame(f, bg=COR_BG, height=40)
        self.row_cartas_jogo.pack(fill="x", padx=6, pady=2)
        self.slots_cartas_jogo = []
        holder = tk.Frame(self.row_cartas_jogo, bg=COR_BG)
        holder.pack()
        for _ in range(5):
            lbl = tk.Label(
                holder,
                text="?",
                fg="#78909C",
                bg="#263238",
                font=("DejaVu Sans", 13, "bold"),
                width=5,
                height=1,
                pady=4,
            )
            lbl.pack(side="left", padx=4)
            self.slots_cartas_jogo.append(lbl)

        self.lbl_jogo_msg = tk.Label(
            f,
            text="",
            fg="#81D4FA",
            bg="#181818",
            font=("DejaVu Sans", 9),
            anchor="w",
            padx=8,
            pady=3,
        )
        self.lbl_jogo_msg.pack(fill="x", padx=6, pady=(2, 3))

        self.scroll_jogo = ScrollableTouchFrame(f, bg=COR_BG)
        self.scroll_jogo.pack(fill="both", expand=True, padx=6, pady=(0, 4))

    # =========================================================================
    # TELA 5: AVISO PARA VIRAR CARTAS DA MESA
    # =========================================================================
    def _criar_tela_virar_mesa(self):
        f = tk.Frame(self.root, bg=COR_BG)
        self.frame_virar_mesa = f

        self.lbl_virar_titulo = tk.Label(
            f,
            text="VIRE AS CARTAS",
            fg="#FFD54F",
            bg=COR_BG,
            font=("DejaVu Sans", 20, "bold"),
            justify="center",
        )
        self.lbl_virar_titulo.pack(pady=(28, 8))

        self.lbl_virar_sub = tk.Label(
            f,
            text="Vire as cartas correspondentes na mesa física\ne confirme abaixo para revelar nos celulares.",
            fg=COR_SUB,
            bg=COR_BG,
            font=("DejaVu Sans", 11),
            justify="center",
        )
        self.lbl_virar_sub.pack(pady=6)

        self.lbl_virar_pote = tk.Label(
            f,
            text="Pote atual: R$ 0",
            fg="#69F0AE",
            bg=COR_BG,
            font=("DejaVu Sans", 13, "bold"),
        )
        self.lbl_virar_pote.pack(pady=10)

        tk.Button(
            f,
            text="CONFIRMAR CARTAS VIRADAS",
            command=lambda: self.servidor.ui_confirmar_virar_mesa(),
            bg="#2E7D32",
            fg="#FFFFFF",
            activebackground="#1B5E20",
            font=("DejaVu Sans", 14, "bold"),
            bd=0,
            highlightthickness=0,
            height=3,
        ).pack(side="bottom", fill="x", padx=20, pady=18)

    # =========================================================================
    # TELA 6: RESULTADO DA RODADA (SHOWDOWN)
    # =========================================================================
    def _criar_tela_showdown(self):
        f = tk.Frame(self.root, bg=COR_BG)
        self.frame_showdown = f

        self.lbl_show_titulo = tk.Label(
            f,
            text="RESULTADO DA RODADA",
            fg="#FFD54F",
            bg=COR_BG,
            font=("DejaVu Sans", 12, "bold"),
        )
        self.lbl_show_titulo.pack(pady=(5, 2))

        self.row_cartas_show = tk.Frame(f, bg=COR_BG)
        self.row_cartas_show.pack(pady=2)

        self.scroll_showdown = ScrollableTouchFrame(f, bg=COR_BG)
        self.scroll_showdown.pack(fill="both", expand=True, padx=6, pady=3)

        rodape = tk.Frame(f, bg=COR_BG, height=48)
        rodape.pack(fill="x", padx=8, pady=(2, 6))
        rodape.pack_propagate(False)

        tk.Button(
            rodape,
            text="Encerrar Jogo",
            command=lambda: self.servidor.ui_encerrar_jogo(),
            bg="#C62828",
            fg="#FFFFFF",
            activebackground="#8E0000",
            font=("DejaVu Sans", 11, "bold"),
            bd=0,
            highlightthickness=0,
        ).pack(side="left", fill="both", expand=True, padx=(0, 6))

        self.btn_nova_rodada = tk.Button(
            rodape,
            text="Nova Rodada",
            command=lambda: self.servidor.ui_iniciar_rodada(),
            bg="#2E7D32",
            fg="#FFFFFF",
            activebackground="#1B5E20",
            disabledforeground="#888888",
            font=("DejaVu Sans", 12, "bold"),
            bd=0,
            highlightthickness=0,
        )
        self.btn_nova_rodada.pack(side="right", fill="both", expand=True, padx=(6, 0))

    # =========================================================================
    # TELA 7: PLACAR FINAL DA SESSÃO
    # =========================================================================
    def _criar_tela_placar(self):
        f = tk.Frame(self.root, bg=COR_BG)
        self.frame_placar = f

        tk.Label(
            f,
            text="PLACAR FINAL DA MESA",
            fg="#FFD54F",
            bg=COR_BG,
            font=("DejaVu Sans", 13, "bold"),
        ).pack(pady=(6, 4))

        self.scroll_placar = ScrollableTouchFrame(f, bg=COR_BG)
        self.scroll_placar.pack(fill="both", expand=True, padx=6, pady=2)

        tk.Button(
            f,
            text="Voltar ao Início (Nova Mesa)",
            command=lambda: self.servidor.ui_voltar_inicio(),
            bg="#1565C0",
            fg="#FFFFFF",
            activebackground="#0D47A1",
            font=("DejaVu Sans", 12, "bold"),
            bd=0,
            highlightthickness=0,
            height=2,
        ).pack(fill="x", padx=12, pady=8)

    # =========================================================================
    # OVERLAY GLOBAL DE CONFIRMAÇÃO DE DESLIGAMENTO
    # =========================================================================
    def _criar_overlay_desligamento(self):
        self.frame_desligar = tk.Frame(self.root, bg="#1A1A1A")

        self.lbl_desligar_msg = tk.Label(
            self.frame_desligar,
            text="Deseja realmente desligar\no Raspberry Pi?",
            fg="#FFFFFF",
            bg="#1A1A1A",
            font=("DejaVu Sans", 16, "bold"),
            justify="center",
        )
        self.lbl_desligar_msg.pack(expand=True, pady=(35, 10))

        self.box_btns_desligar = tk.Frame(self.frame_desligar, bg="#1A1A1A")
        self.box_btns_desligar.pack(fill="x", padx=24, pady=(0, 35))

        tk.Button(
            self.box_btns_desligar,
            text="Cancelar",
            command=self._ocultar_confirmacao_desligar,
            bg="#424242",
            fg="#FFFFFF",
            activebackground="#616161",
            font=("DejaVu Sans", 14, "bold"),
            bd=0,
            highlightthickness=0,
            height=3,
        ).pack(side="left", expand=True, fill="x", padx=(0, 10))

        tk.Button(
            self.box_btns_desligar,
            text="Confirmar",
            command=self._executar_desligamento,
            bg="#C62828",
            fg="#FFFFFF",
            activebackground="#8E0000",
            font=("DejaVu Sans", 14, "bold"),
            bd=0,
            highlightthickness=0,
            height=3,
        ).pack(side="right", expand=True, fill="x", padx=(10, 0))

    # =========================================================================
    # CONTROLE DE TELAS E RENDERIZAÇÃO DO ESTADO
    # =========================================================================
    def _mostrar_tela(self, nome: str, frame: tk.Frame):
        if self.tela_ativa == nome:
            return
        for f in (
            self.frame_lobby,
            self.frame_distribuir_mao,
            self.frame_distribuir_mesa,
            self.frame_jogo,
            self.frame_virar_mesa,
            self.frame_showdown,
            self.frame_placar,
        ):
            f.place_forget()
        frame.place(x=0, y=ALTURA_HEADER, width=LARGURA, height=ALTURA_CORPO)
        frame.tkraise()
        self.header.tkraise()
        self.tela_ativa = nome

    def _processar_fila_ui(self):
        atualizar = False
        while not self.fila_ui.empty():
            try:
                self.fila_ui.get_nowait()
                atualizar = True
            except queue.Empty:
                break
        if atualizar:
            self._renderizar_estado()
        self.root.after(60, self._processar_fila_ui)

    def _renderizar_estado(self):
        s = self.servidor.obter_snapshot()
        fase = s["fase"]

        if fase == "AGUARDANDO":
            self.lbl_header_titulo.config(text=f"LOBBY • {self.ip_local}:5000")
            self._mostrar_tela("LOBBY", self.frame_lobby)
            self._atualizar_lobby(s)

        elif fase == "DISTRIBUINDO_MAOS":
            self.lbl_header_titulo.config(
                text=f"RODADA #{s['numero_rodada']} • DISTRIBUIR MÃOS"
            )
            self._mostrar_tela("DIST_MAO", self.frame_distribuir_mao)
            self._atualizar_distribuir_mao(s)

        elif fase == "DISTRIBUINDO_MESA":
            self.lbl_header_titulo.config(
                text=f"RODADA #{s['numero_rodada']} • CARTAS DA MESA"
            )
            self._mostrar_tela("DIST_MESA", self.frame_distribuir_mesa)
            self._atualizar_distribuir_mesa(s)

        elif fase in ("PRE_FLOP", "FLOP", "TURN", "RIVER"):
            nomes_fase = {
                "PRE_FLOP": "PRÉ-FLOP",
                "FLOP": "FLOP",
                "TURN": "TURN",
                "RIVER": "RIVER",
            }
            self.lbl_header_titulo.config(
                text=f"RODADA #{s['numero_rodada']} • {nomes_fase[fase]} • Mesa R${fmt_valor(s['montante_total'])}"
            )
            self._mostrar_tela("JOGO", self.frame_jogo)
            self._atualizar_jogo(s)

        elif fase in (
            "AGUARDANDO_VIRAR_FLOP",
            "AGUARDANDO_VIRAR_TURN",
            "AGUARDANDO_VIRAR_RIVER",
        ):
            self.lbl_header_titulo.config(
                text=f"RODADA #{s['numero_rodada']} • AÇÃO DO DEALER"
            )
            self._mostrar_tela("VIRAR", self.frame_virar_mesa)
            self._atualizar_virar_mesa(s)

        elif fase == "SHOWDOWN":
            self.lbl_header_titulo.config(
                text=f"RODADA #{s['numero_rodada']} • FINALIZADA"
            )
            self._mostrar_tela("SHOWDOWN", self.frame_showdown)
            self._atualizar_showdown(s)

        elif fase == "PLACAR_FINAL":
            self.lbl_header_titulo.config(text="SESSÃO ENCERRADA • PLACAR")
            self._mostrar_tela("PLACAR", self.frame_placar)
            self._atualizar_placar(s)

    def _atualizar_lobby(self, s: dict):
        self.lbl_lobby_total.config(text=f"Mesa: R$ {fmt_valor(s['montante_total'])}")
        self.lbl_blinds.config(
            text=f"SB/BB: {fmt_valor(s['small_blind'])}/{fmt_valor(s['big_blind'])}"
        )

        if s["bot_ativo"]:
            self.btn_bot.config(text="Bot Teste: ON", bg="#1976D2")
        else:
            self.btn_bot.config(text="Bot Teste: OFF", bg="#455A64")

        self.btn_iniciar.config(
            state="normal" if s["pode_iniciar"] else "disabled",
            bg="#2E7D32" if s["pode_iniciar"] else "#333333",
        )

        self.scroll_lobby.limpar()
        jogadores = s["jogadores"]
        if not jogadores:
            lbl = tk.Label(
                self.scroll_lobby.inner,
                text="Aguardando jogadores conectarem\npelo aplicativo Android...",
                fg=COR_SUB,
                bg=COR_BG,
                font=("DejaVu Sans", 12),
                justify="center",
                pady=45,
            )
            lbl.pack(fill="x")
            self.scroll_lobby.vincular_filhos_recursivo(lbl)
            return

        total = len(jogadores)
        for idx, j in enumerate(jogadores):
            cor = COR_CARD if idx % 2 == 0 else COR_CARD_ALT
            linha = tk.Frame(self.scroll_lobby.inner, bg=cor, height=40)
            linha.pack(fill="x", pady=2, padx=2)
            linha.pack_propagate(False)

            tk.Label(
                linha,
                text=f"{j['pos']}. {j['nome']}",
                fg="#81D4FA" if j["is_bot"] else COR_TEXTO,
                bg=cor,
                font=("DejaVu Sans", 11, "bold"),
                anchor="w",
            ).pack(side="left", padx=8, fill="x", expand=True)

            tk.Label(
                linha,
                text=f"R$ {fmt_valor(j['saldo'])}",
                fg="#69F0AE",
                bg=cor,
                font=("DejaVu Sans", 11, "bold"),
            ).pack(side="left", padx=6)

            jid = j["id"]
            tk.Button(
                linha,
                text="▲",
                command=lambda target=jid: self.servidor.ui_mover_jogador(target, -1),
                state="normal" if idx > 0 else "disabled",
                bg="#37474F" if idx > 0 else "#222222",
                fg="#FFFFFF",
                disabledforeground="#555555",
                font=("DejaVu Sans", 10, "bold"),
                width=3,
                bd=0,
                highlightthickness=0,
            ).pack(side="left", padx=2, pady=4, fill="y")

            tk.Button(
                linha,
                text="▼",
                command=lambda target=jid: self.servidor.ui_mover_jogador(target, 1),
                state="normal" if idx < total - 1 else "disabled",
                bg="#37474F" if idx < total - 1 else "#222222",
                fg="#FFFFFF",
                disabledforeground="#555555",
                font=("DejaVu Sans", 10, "bold"),
                width=3,
                bd=0,
                highlightthickness=0,
            ).pack(side="left", padx=(2, 6), pady=4, fill="y")

            self.scroll_lobby.vincular_filhos_recursivo(linha)

    def _atualizar_distribuir_mao(self, s: dict):
        qtd = s["buffer_qtd"]
        self.lbl_dist_progresso.config(
            text=f"CARTAS PRIVADAS • Jogador {s['alvo_idx']} de {s['alvo_total']}"
        )
        self.lbl_dist_nome.config(text=s["alvo_nome"])
        self.lbl_dist_contador.config(
            text=f"{qtd} / 2 cartas lidas",
            fg="#69F0AE" if qtd == 2 else "#FFD54F",
        )
        self.lbl_dist_aviso.config(text=s["aviso_scanner"])
        pronto = qtd == 2
        self.btn_confirmar_mao.config(
            state="normal" if pronto else "disabled",
            bg="#2E7D32" if pronto else "#333333",
        )

    def _atualizar_distribuir_mesa(self, s: dict):
        qtd = s["buffer_qtd"]
        for i, lbl in enumerate(self.slots_ocultos_lbls):
            if i < qtd:
                lbl.config(text="✓", fg="#FFFFFF", bg="#2E7D32")
            else:
                lbl.config(text="?", fg="#78909C", bg="#263238")

        self.lbl_mesa_contador.config(
            text=f"{qtd} / 5 cartas lidas",
            fg="#69F0AE" if qtd == 5 else "#FFD54F",
        )
        self.lbl_mesa_aviso.config(text=s["aviso_scanner"])
        pronto = qtd == 5
        self.btn_confirmar_mesa.config(
            state="normal" if pronto else "disabled",
            bg="#2E7D32" if pronto else "#333333",
        )

    def _atualizar_jogo(self, s: dict):
        self.lbl_jogo_vez.config(text=s["jogador_vez_nome"])
        extra_side = f" (+{s['qtd_side_pots']} Side)" if s["qtd_side_pots"] > 0 else ""
        self.lbl_jogo_pote.config(text=f"POTE: R$ {fmt_valor(s['pote'])}{extra_side}")
        self.lbl_jogo_aposta.config(
            text=f"Aposta atual: R$ {fmt_valor(s['aposta_atual'])}"
        )
        self.lbl_jogo_msg.config(text=s["ultima_acao_msg"])

        reveladas = s["cartas_mesa_reveladas"]
        for i, lbl in enumerate(self.slots_cartas_jogo):
            if i < len(reveladas):
                txt, cor = formatar_carta(reveladas[i])
                lbl.config(text=txt, fg=cor, bg="#FFFFFF")
            else:
                lbl.config(text="?", fg="#78909C", bg="#263238")

        self.scroll_jogo.limpar()
        for idx, j in enumerate(s["jogadores"]):
            cor = (
                "#1B3B2B"
                if j["eh_vez"]
                else (COR_CARD if idx % 2 == 0 else COR_CARD_ALT)
            )
            linha = tk.Frame(self.scroll_jogo.inner, bg=cor, height=32)
            linha.pack(fill="x", pady=1, padx=2)
            linha.pack_propagate(False)

            tag = f"[{j['tags']}] " if j["tags"] else ""
            seta = "▶ " if j["eh_vez"] else ""
            tk.Label(
                linha,
                text=f"{seta}{tag}{j['nome']}",
                fg="#69F0AE" if j["eh_vez"] else COR_TEXTO,
                bg=cor,
                font=("DejaVu Sans", 10, "bold"),
                anchor="w",
            ).pack(side="left", padx=6, fill="x", expand=True)

            tk.Label(
                linha,
                text=f"R${fmt_valor(j['saldo'])} (Ap:{fmt_valor(j['aposta_rodada'])})",
                fg="#FFD54F",
                bg=cor,
                font=("DejaVu Sans", 9),
            ).pack(side="left", padx=4)

            cor_st = {
                "ATIVO": "#81C784",
                "ALL-IN": "#FFAB40",
                "FOLD": "#EF5350",
                "ESPERA": "#90CAF9",
            }.get(j["status"], COR_SUB)
            tk.Label(
                linha,
                text=j["status"],
                fg=cor_st,
                bg=cor,
                font=("DejaVu Sans", 9, "bold"),
                width=8,
                anchor="e",
            ).pack(side="right", padx=6)

            self.scroll_jogo.vincular_filhos_recursivo(linha)

    def _atualizar_virar_mesa(self, s: dict):
        titulos = {
            "AGUARDANDO_VIRAR_FLOP": "VIRE AS 3 CARTAS\nDO FLOP",
            "AGUARDANDO_VIRAR_TURN": "VIRE A 4ª CARTA\n(TURN)",
            "AGUARDANDO_VIRAR_RIVER": "VIRE A 5ª CARTA\n(RIVER)",
        }
        self.lbl_virar_titulo.config(text=titulos.get(s["fase"], "VIRE AS CARTAS"))
        self.lbl_virar_pote.config(text=f"Pote atual: R$ {fmt_valor(s['pote'])}")

    def _atualizar_showdown(self, s: dict):
        for w in self.row_cartas_show.winfo_children():
            w.destroy()
        for c in s["cartas_mesa_reveladas"]:
            txt, cor = formatar_carta(c)
            tk.Label(
                self.row_cartas_show,
                text=txt,
                fg=cor,
                bg="#FFFFFF",
                font=("DejaVu Sans", 11, "bold"),
                padx=6,
                pady=2,
            ).pack(side="left", padx=3)

        self.scroll_showdown.limpar()
        for item in s["resultado_rodada"]:
            box = tk.Frame(self.scroll_showdown.inner, bg=COR_CARD, pady=6, padx=8)
            box.pack(fill="x", pady=3, padx=2)

            vencedores = ", ".join(item["vencedores"])
            tk.Label(
                box,
                text=f"{item['pote_nome']} — {vencedores}",
                fg="#69F0AE",
                bg=COR_CARD,
                font=("DejaVu Sans", 11, "bold"),
                anchor="w",
            ).pack(fill="x")

            tk.Label(
                box,
                text=f"Recebeu R$ {fmt_valor(item['premio_cada'])} cada • {item['combinacao']}",
                fg=COR_TEXTO,
                bg=COR_CARD,
                font=("DejaVu Sans", 10),
                anchor="w",
            ).pack(fill="x")
            self.scroll_showdown.vincular_filhos_recursivo(box)

        # Lista rápida de saldos atualizados e jogadores aguardando rebuy/espera
        sep = tk.Label(
            self.scroll_showdown.inner,
            text="Saldos atuais (jogadores podem fazer Rebuy no celular):",
            fg=COR_SUB,
            bg=COR_BG,
            font=("DejaVu Sans", 9),
            anchor="w",
            pady=4,
        )
        sep.pack(fill="x", padx=4)
        self.scroll_showdown.vincular_touch(sep)

        for j in s["jogadores"]:
            linha = tk.Frame(self.scroll_showdown.inner, bg="#1A1A1A", height=26)
            linha.pack(fill="x", pady=1, padx=2)
            linha.pack_propagate(False)
            extra = " [ESPERA]" if j["status"] == "ESPERA" else ""
            tk.Label(
                linha,
                text=f"{j['nome']}{extra}",
                fg=COR_TEXTO,
                bg="#1A1A1A",
                font=("DejaVu Sans", 9, "bold"),
                anchor="w",
            ).pack(side="left", padx=8)
            tk.Label(
                linha,
                text=f"R$ {fmt_valor(j['saldo'])}",
                fg="#EF5350" if j["saldo"] <= 0 else "#FFD54F",
                bg="#1A1A1A",
                font=("DejaVu Sans", 9, "bold"),
            ).pack(side="right", padx=8)
            self.scroll_showdown.vincular_filhos_recursivo(linha)

        self.btn_nova_rodada.config(
            state="normal" if s["pode_iniciar"] else "disabled",
            bg="#2E7D32" if s["pode_iniciar"] else "#333333",
        )

    def _atualizar_placar(self, s: dict):
        self.scroll_placar.limpar()
        for idx, item in enumerate(s["placar_final"]):
            cor = COR_CARD if idx % 2 == 0 else COR_CARD_ALT
            linha = tk.Frame(self.scroll_placar.inner, bg=cor, height=42)
            linha.pack(fill="x", pady=2, padx=2)
            linha.pack_propagate(False)

            lucro = item["lucro"]
            if lucro > 0:
                txt_lucro = f"+R$ {fmt_valor(lucro)}"
                cor_lucro = "#69F0AE"
            elif lucro < 0:
                txt_lucro = f"-R$ {fmt_valor(abs(lucro))}"
                cor_lucro = "#EF5350"
            else:
                txt_lucro = "R$ 0"
                cor_lucro = COR_SUB

            tk.Label(
                linha,
                text=f"{idx + 1}º  {item['nome']}",
                fg=COR_TEXTO,
                bg=cor,
                font=("DejaVu Sans", 11, "bold"),
                anchor="w",
            ).pack(side="left", padx=8, fill="x", expand=True)

            tk.Label(
                linha,
                text=f"Saldo: R$ {fmt_valor(item['saldo_final'])}",
                fg="#FFD54F",
                bg=cor,
                font=("DejaVu Sans", 10),
            ).pack(side="left", padx=6)

            tk.Label(
                linha,
                text=txt_lucro,
                fg=cor_lucro,
                bg=cor,
                font=("DejaVu Sans", 11, "bold"),
                width=10,
                anchor="e",
            ).pack(side="right", padx=8)

            self.scroll_placar.vincular_filhos_recursivo(linha)

    # =========================================================================
    # DESLIGAMENTO SEGURO DO RASPBERRY PI
    # =========================================================================
    def _mostrar_confirmacao_desligar(self):
        self.frame_desligar.place(x=0, y=0, width=LARGURA, height=ALTURA)
        self.frame_desligar.tkraise()

    def _ocultar_confirmacao_desligar(self):
        self.frame_desligar.place_forget()

    def _executar_desligamento(self):
        self.box_btns_desligar.pack_forget()
        self.lbl_desligar_msg.config(
            text="Encerrando scanner, servidor\ne desligando o Raspberry Pi...\nAguarde o LED verde apagar.",
            fg="#FFB74D",
            font=("DejaVu Sans", 13, "bold"),
        )
        self.root.update()
        self.servidor.encerrar()
        self.root.after(
            300,
            lambda: subprocess.run(
                ["sudo", "/usr/sbin/shutdown", "-h", "now"], check=False
            ),
        )

    def _sair_app(self):
        self.servidor.encerrar()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    InterfacePokerLCD(root)
    root.mainloop()
