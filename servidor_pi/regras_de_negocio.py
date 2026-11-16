import random
from treys import Card, Evaluator

BOT_ID = "BOT_TESTE"
SALDO_MIN_REBUY = 200.0
SALDO_MAX_REBUY = 10000.0

TRADUCAO_MAOS = {
    "Royal Flush": "Royal Flush",
    "Straight Flush": "Straight Flush",
    "Four of a Kind": "Quadra",
    "Full House": "Full House",
    "Flush": "Flush",
    "Straight": "Sequência",
    "Three of a Kind": "Trinca",
    "Two Pair": "Dois Pares",
    "Pair": "Um Par",
    "High Card": "Carta Alta",
}

PASSOS_SMALL_BLIND = [5.0, 10.0, 20.0, 25.0, 50.0, 100.0, 200.0, 500.0]


def fmt_valor(v: float) -> str:
    v = round(v, 2)
    return f"{v:.0f}" if v == int(v) else f"{v:.2f}"


class JogoPoker:
    def __init__(self):
        self.evaluator = Evaluator()

        # Jogadores atualmente conectados (+ Bot se ativo)
        self.jogadores: dict = {}
        self.ordem_jogadores: list = []

        # Histórico financeiro de jogadores que saíram após jogar (para o placar final)
        self.historico_desconectados: list[dict] = []

        # Configurações da mesa
        self.indice_sb_cfg = 1  # Padrão: SB=10 / BB=20
        self.small_blind = PASSOS_SMALL_BLIND[self.indice_sb_cfg]
        self.big_blind = self.small_blind * 2.0
        self.bot_ativo = False

        # Estado da sessão / rodada
        self.fase = "AGUARDANDO"
        self.numero_rodada = 0
        self.indice_dealer_ordem = -1
        self.participantes_mao: list = []
        self.dealer_id = None
        self.sb_id = None
        self.bb_id = None

        # Controle de scanner e cartas
        self.cartas_usadas_rodada: set[str] = set()
        self.buffer_cartas: list[str] = []
        self.indice_distribuicao = 0
        self.cartas_mesa_ocultas: list[str] = []
        self.cartas_mesa_reveladas: list[str] = []
        self.aviso_scanner = ""

        # Controle de apostas e turnos
        self.pote = 0.0
        self.aposta_atual = 0.0
        self.indice_turno_mao = 0
        self.agiram_na_street: set = set()
        self.ultima_acao_msg = "Aguardando jogadores conectarem..."
        self.resultado_rodada: list[dict] = []
        self.placar_final: list[dict] = []

    # =========================================================================
    # CONFIGURAÇÃO NO LOBBY (BLINDS, REORDENAÇÃO, BOT DE TESTES)
    # =========================================================================
    def ajustar_blinds(self, delta: int) -> None:
        if self.fase != "AGUARDANDO":
            return
        novo = max(0, min(len(PASSOS_SMALL_BLIND) - 1, self.indice_sb_cfg + delta))
        self.indice_sb_cfg = novo
        self.small_blind = PASSOS_SMALL_BLIND[novo]
        self.big_blind = self.small_blind * 2.0

    def alternar_bot_testes(self) -> list[tuple]:
        if self.fase != "AGUARDANDO":
            return []
        if self.bot_ativo:
            self.bot_ativo = False
            self.jogadores.pop(BOT_ID, None)
            if BOT_ID in self.ordem_jogadores:
                self.ordem_jogadores.remove(BOT_ID)
            self.ultima_acao_msg = "Modo Testes (Bot) desativado."
        else:
            self.bot_ativo = True
            self.jogadores[BOT_ID] = {
                "id": BOT_ID,
                "nome": "Robô (Bot)",
                "is_bot": True,
                "saldo": 1000.0,
                "saldo_inicial": 1000.0,
                "total_investido": 1000.0,
                "mao": [],
                "aposta_rodada": 0.0,
                "contribuicao_mao": 0.0,
                "ativo": False,
                "all_in": False,
                "na_mao": False,
                "em_espera": False,
                "jogou_sessao": False,
            }
            if BOT_ID not in self.ordem_jogadores:
                self.ordem_jogadores.append(BOT_ID)
            self.ultima_acao_msg = "Modo Testes ativado: Robô (Bot) entrou na mesa."
        return self._gerar_estado_individualizado(self.ultima_acao_msg)

    def mover_jogador(self, jid, direcao: int) -> list[tuple]:
        """direcao = -1 (subir) ou +1 (descer) na ordem física da mesa."""
        if self.fase != "AGUARDANDO" or jid not in self.ordem_jogadores:
            return []
        idx = self.ordem_jogadores.index(jid)
        novo_idx = idx + direcao
        if 0 <= novo_idx < len(self.ordem_jogadores):
            self.ordem_jogadores[idx], self.ordem_jogadores[novo_idx] = (
                self.ordem_jogadores[novo_idx],
                self.ordem_jogadores[idx],
            )
        return self._gerar_estado_individualizado("Ordem da mesa atualizada.")

    # =========================================================================
    # CONEXÃO, DESCONEXÃO E REBUY
    # =========================================================================
    def registrar_jogador(self, conn, nome: str, saldo: float) -> list[tuple]:
        saldo_f = round(float(saldo), 2)
        em_espera = self.fase != "AGUARDANDO"

        self.jogadores[conn] = {
            "id": conn,
            "nome": nome,
            "is_bot": False,
            "saldo": saldo_f,
            "saldo_inicial": saldo_f,
            "total_investido": saldo_f,
            "mao": [],
            "aposta_rodada": 0.0,
            "contribuicao_mao": 0.0,
            "ativo": False,
            "all_in": False,
            "na_mao": False,
            "em_espera": em_espera,
            "jogou_sessao": False,
        }
        if conn not in self.ordem_jogadores:
            self.ordem_jogadores.append(conn)

        mensagens = []
        if em_espera:
            for c in self.cartas_mesa_reveladas:
                mensagens.append((conn, "carta_mesa", {"carta": c}))
            if self.fase == "PLACAR_FINAL":
                mensagens.append((conn, "placar_final", {"ranking": self.placar_final}))
            aviso = f"{nome} entrou em modo de espera (jogará na próxima rodada)."
        else:
            aviso = f"{nome} conectou com R$ {fmt_valor(saldo_f)}."

        self.ultima_acao_msg = aviso
        mensagens.extend(self._gerar_estado_individualizado(aviso))
        return mensagens

    def remover_jogador(self, conn) -> list[tuple]:
        jogador = self.jogadores.pop(conn, None)
        if not jogador:
            return []

        if conn in self.ordem_jogadores:
            self.ordem_jogadores.remove(conn)

        if jogador["jogou_sessao"]:
            self.historico_desconectados.append(
                {
                    "nome": f"{jogador['nome']} (saiu)",
                    "total_investido": jogador["total_investido"],
                    "saldo_final": jogador["saldo"],
                    "lucro": round(jogador["saldo"] - jogador["total_investido"], 2),
                }
            )

        nome = jogador["nome"]
        mensagens = []

        # Se desconectou durante a distribuição de cartas privadas
        if self.fase == "DISTRIBUINDO_MAOS" and conn in self.participantes_mao:
            alvo_atual = self.jogador_alvo_distribuicao()
            if alvo_atual == conn:
                for c in self.buffer_cartas:
                    self.cartas_usadas_rodada.discard(c)
                self.buffer_cartas.clear()
            idx_rem = self.participantes_mao.index(conn)
            self.participantes_mao.remove(conn)
            if idx_rem < self.indice_distribuicao:
                self.indice_distribuicao -= 1

            if len(self.participantes_mao) < 2:
                self.fase = "AGUARDANDO"
                self.ultima_acao_msg = f"{nome} saiu. Jogadores insuficientes; voltando ao lobby."
                mensagens.append(("TODOS", "limpar_mesa", {}))
                mensagens.extend(self._gerar_estado_individualizado(self.ultima_acao_msg))
                return mensagens

            if self.indice_distribuicao >= len(self.participantes_mao):
                self.fase = "DISTRIBUINDO_MESA"
                self.buffer_cartas.clear()

        # Se desconectou durante uma rodada de apostas
        elif self.fase in ("PRE_FLOP", "FLOP", "TURN", "RIVER") and conn in self.participantes_mao:
            jogador["ativo"] = False
            era_vez = (
                self.participantes_mao
                and self.participantes_mao[self.indice_turno_mao] == conn
            )
            self.agiram_na_street.add(conn)
            ativos = self._ativos_na_mao()

            if len(ativos) == 1:
                vencedor_id = ativos[0]
                vencedor = self.jogadores[vencedor_id]
                premio = round(self.pote, 2)
                vencedor["saldo"] = round(vencedor["saldo"] + premio, 2)
                self.resultado_rodada = [
                    {
                        "pote_nome": "Pote Principal",
                        "valor": premio,
                        "vencedores": [vencedor["nome"]],
                        "premio_cada": premio,
                        "combinacao": "Oponente desconectou",
                    }
                ]
                self.fase = "SHOWDOWN"
                self.ultima_acao_msg = (
                    f"{nome} desconectou. {vencedor['nome']} ganhou R$ {fmt_valor(premio)}!"
                )
                return self._gerar_estado_individualizado(self.ultima_acao_msg)

            if self._street_encerrada():
                return self._concluir_street(f"{nome} desconectou.")

            if era_vez:
                self._avancar_turno()

        self.ultima_acao_msg = f"{nome} saiu da mesa."
        mensagens.extend(self._gerar_estado_individualizado(self.ultima_acao_msg))
        return mensagens

    def processar_rebuy(self, conn, valor: float) -> list[tuple]:
        jogador = self.jogadores.get(conn)
        if not jogador:
            return []

        if self.fase not in ("AGUARDANDO", "SHOWDOWN") and jogador["na_mao"]:
            return [
                (
                    conn,
                    "erro",
                    {"msg": "Aguarde o fim da rodada atual para fazer Rebuy."},
                )
            ]

        valor_f = round(float(valor), 2)
        if valor_f < SALDO_MIN_REBUY or valor_f > SALDO_MAX_REBUY:
            return [
                (
                    conn,
                    "erro",
                    {
                        "msg": f"Rebuy deve ser entre R$ {fmt_valor(SALDO_MIN_REBUY)} e R$ {fmt_valor(SALDO_MAX_REBUY)}."
                    },
                )
            ]

        jogador["saldo"] = round(jogador["saldo"] + valor_f, 2)
        jogador["total_investido"] = round(jogador["total_investido"] + valor_f, 2)
        self.ultima_acao_msg = (
            f"{jogador['nome']} fez Rebuy de R$ {fmt_valor(valor_f)} "
            f"(Saldo: R$ {fmt_valor(jogador['saldo'])})."
        )
        return self._gerar_estado_individualizado(self.ultima_acao_msg)

    # =========================================================================
    # INÍCIO DE PARTIDA / NOVA RODADA
    # =========================================================================
    def pode_iniciar_rodada(self) -> tuple[bool, str]:
        aptos = [
            jid
            for jid in self.ordem_jogadores
            if self.jogadores[jid]["saldo"] > 0
            or (self.jogadores[jid]["is_bot"] and self.bot_ativo)
        ]
        if len(aptos) < 2:
            return False, "Necessário pelo menos 2 jogadores com saldo > R$ 0."
        return True, ""

    def iniciar_nova_rodada(self) -> list[tuple]:
        # Rebuy automático do Bot se zerou para não travar os testes
        if self.bot_ativo and BOT_ID in self.jogadores:
            bot = self.jogadores[BOT_ID]
            if bot["saldo"] <= 0:
                bot["saldo"] = 1000.0
                bot["total_investido"] = round(bot["total_investido"] + 1000.0, 2)

        aptos = [
            jid
            for jid in self.ordem_jogadores
            if self.jogadores[jid]["saldo"] > 0
        ]
        if len(aptos) < 2:
            self.ultima_acao_msg = "Mínimo 2 jogadores com saldo > R$ 0 para iniciar."
            return self._gerar_estado_individualizado(self.ultima_acao_msg)

        self.numero_rodada += 1
        self.cartas_usadas_rodada.clear()
        self.buffer_cartas.clear()
        self.cartas_mesa_ocultas.clear()
        self.cartas_mesa_reveladas.clear()
        self.resultado_rodada.clear()
        self.aviso_scanner = ""
        self.pote = 0.0
        self.aposta_atual = 0.0
        self.agiram_na_street.clear()

        for jid in self.ordem_jogadores:
            j = self.jogadores[jid]
            j["mao"].clear()
            j["aposta_rodada"] = 0.0
            j["contribuicao_mao"] = 0.0
            j["all_in"] = False
            if jid in aptos:
                j["na_mao"] = True
                j["ativo"] = True
                j["em_espera"] = False
                j["jogou_sessao"] = True
            else:
                j["na_mao"] = False
                j["ativo"] = False

        # Rotaciona o Dealer entre os participantes aptos
        if self.dealer_id in aptos:
            idx_d = (aptos.index(self.dealer_id) + 1) % len(aptos)
        else:
            idx_d = 0

        self.dealer_id = aptos[idx_d]

        # Reordena a lista da mão começando no Dealer (índice 0 = Dealer)
        self.participantes_mao = aptos[idx_d:] + aptos[:idx_d]

        # Define Small Blind e Big Blind (Heads-Up vs 3+ jogadores)
        n = len(self.participantes_mao)
        if n == 2:
            # Heads-Up: Dealer é SB, outro é BB
            self.sb_id = self.participantes_mao[0]
            self.bb_id = self.participantes_mao[1]
            # Ordem de entrega de cartas: começa pelo BB ou SB (vamos iniciar pelo SB / ordem da mesa)
            self.ordem_distribuicao = [self.sb_id, self.bb_id]
        else:
            self.sb_id = self.participantes_mao[1]
            self.bb_id = self.participantes_mao[2]
            # Começa à esquerda do Dealer (SB, BB, ..., Dealer)
            self.ordem_distribuicao = self.participantes_mao[1:] + [
                self.participantes_mao[0]
            ]

        self.indice_distribuicao = 0
        self.fase = "DISTRIBUINDO_MAOS"
        nome_primeiro = self.jogadores[self.ordem_distribuicao[0]]["nome"]
        self.ultima_acao_msg = f"Rodada #{self.numero_rodada}: escaneie 2 cartas para {nome_primeiro}."

        mensagens = [("TODOS", "limpar_mesa", {})]
        mensagens.extend(self._gerar_estado_individualizado(self.ultima_acao_msg))
        return mensagens

    # =========================================================================
    # LEITURA DO SCANNER E CONFIRMAÇÕES DO DEALER
    # =========================================================================
    def jogador_alvo_distribuicao(self):
        if self.fase != "DISTRIBUINDO_MAOS":
            return None
        if 0 <= self.indice_distribuicao < len(self.ordem_distribuicao):
            return self.ordem_distribuicao[self.indice_distribuicao]
        return None

    def processar_carta_lida(self, carta: str) -> list[tuple]:
        if self.fase not in ("DISTRIBUINDO_MAOS", "DISTRIBUINDO_MESA"):
            return []

        if carta in self.cartas_usadas_rodada:
            self.aviso_scanner = "Carta repetida bloqueada! Passe outra carta."
            return []

        limite = 2 if self.fase == "DISTRIBUINDO_MAOS" else 5
        if len(self.buffer_cartas) >= limite:
            self.aviso_scanner = (
                f"Limite {limite}/{limite} atingido. Clique em Confirmar ou Limpar."
            )
            return []

        self.buffer_cartas.append(carta)
        self.cartas_usadas_rodada.add(carta)
        self.aviso_scanner = f"Carta {len(self.buffer_cartas)}/{limite} registrada."
        return []

    def registrar_aviso_duplicada(self) -> None:
        if self.fase in ("DISTRIBUINDO_MAOS", "DISTRIBUINDO_MESA"):
            self.aviso_scanner = "Carta já usada nesta rodada! Troque a carta."

    def limpar_buffer_atual(self) -> None:
        if self.fase not in ("DISTRIBUINDO_MAOS", "DISTRIBUINDO_MESA"):
            return
        for c in self.buffer_cartas:
            self.cartas_usadas_rodada.discard(c)
        self.buffer_cartas.clear()
        self.aviso_scanner = "Leitura limpa. Escaneie novamente."

    def confirmar_distribuicao_atual(self) -> list[tuple]:
        mensagens = []

        if self.fase == "DISTRIBUINDO_MAOS":
            if len(self.buffer_cartas) != 2:
                self.aviso_scanner = "Escaneie as 2 cartas antes de confirmar."
                return []

            alvo_id = self.jogador_alvo_distribuicao()
            if alvo_id is None or alvo_id not in self.jogadores:
                return []

            jogador = self.jogadores[alvo_id]
            jogador["mao"] = list(self.buffer_cartas)
            self.buffer_cartas.clear()
            self.aviso_scanner = ""

            # Envia cartas privadas apenas ao dono (se humano)
            if not jogador["is_bot"]:
                for c in jogador["mao"]:
                    mensagens.append((alvo_id, "carta_mao", {"carta": c}))

            self.indice_distribuicao += 1
            if self.indice_distribuicao < len(self.ordem_distribuicao):
                prox_nome = self.jogadores[
                    self.ordem_distribuicao[self.indice_distribuicao]
                ]["nome"]
                self.ultima_acao_msg = f"Cartas entregues. Próximo: {prox_nome}."
            else:
                self.fase = "DISTRIBUINDO_MESA"
                self.ultima_acao_msg = (
                    "Mãos entregues! Escaneie as 5 cartas da mesa (viradas para baixo)."
                )

            mensagens.extend(self._gerar_estado_individualizado(self.ultima_acao_msg))
            return mensagens

        if self.fase == "DISTRIBUINDO_MESA":
            if len(self.buffer_cartas) != 5:
                self.aviso_scanner = "Escaneie todas as 5 cartas da mesa antes de confirmar."
                return []

            # Guarda as 5 cartas viradas para baixo (NÃO envia aos celulares)
            self.cartas_mesa_ocultas = list(self.buffer_cartas)
            self.cartas_mesa_reveladas.clear()
            self.buffer_cartas.clear()
            self.aviso_scanner = ""

            return self._iniciar_preflop_com_blinds()

        return []

    def _cobrar_blind(self, jid, valor_blind: float) -> float:
        j = self.jogadores[jid]
        pago = round(min(valor_blind, j["saldo"]), 2)
        j["saldo"] = round(j["saldo"] - pago, 2)
        j["aposta_rodada"] = round(j["aposta_rodada"] + pago, 2)
        j["contribuicao_mao"] = round(j["contribuicao_mao"] + pago, 2)
        self.pote = round(self.pote + pago, 2)
        if j["saldo"] <= 0:
            j["saldo"] = 0.0
            j["all_in"] = True
        return pago

    def _iniciar_preflop_com_blinds(self) -> list[tuple]:
        self.fase = "PRE_FLOP"
        self.agiram_na_street.clear()
        for jid in self.participantes_mao:
            self.jogadores[jid]["aposta_rodada"] = 0.0

        pago_sb = self._cobrar_blind(self.sb_id, self.small_blind)
        pago_bb = self._cobrar_blind(self.bb_id, self.big_blind)
        self.aposta_atual = max(pago_sb, pago_bb)

        sb_nome = self.jogadores[self.sb_id]["nome"]
        bb_nome = self.jogadores[self.bb_id]["nome"]
        msg_blinds = (
            f"Blinds: {sb_nome} (SB R${fmt_valor(pago_sb)}), "
            f"{bb_nome} (BB R${fmt_valor(pago_bb)})."
        )

        # Se menos de 2 jogadores podem apostar (all-in já nos blinds), vai virar o Flop
        if len(self._ativos_que_podem_agir()) <= 1 and self._todos_igualaram_ou_allin():
            return self._concluir_street(msg_blinds)

        n = len(self.participantes_mao)
        if n == 2:
            # Heads-Up Pré-Flop: Dealer/SB (índice 0) age primeiro
            inicio = 0
        else:
            # 3+ jogadores Pré-Flop: UTG (índice 3 % n) age primeiro
            inicio = 3 % n

        self.indice_turno_mao = inicio
        if not self._pode_agir(self.participantes_mao[self.indice_turno_mao]):
            self._avancar_turno()

        self.ultima_acao_msg = msg_blinds
        return self._gerar_estado_individualizado(msg_blinds)

    # =========================================================================
    # VIRAR CARTAS COMUNITÁRIAS (CONFIRMAÇÃO DO DEALER)
    # =========================================================================
    def confirmar_virar_cartas_mesa(self) -> list[tuple]:
        mapa = {
            "AGUARDANDO_VIRAR_FLOP": ("FLOP", 3, "Flop virado!"),
            "AGUARDANDO_VIRAR_TURN": ("TURN", 4, "Turn virado!"),
            "AGUARDANDO_VIRAR_RIVER": ("RIVER", 5, "River virado!"),
        }
        if self.fase not in mapa:
            return []

        proxima_fase, total_reveladas, titulo = mapa[self.fase]
        novas_cartas = self.cartas_mesa_ocultas[
            len(self.cartas_mesa_reveladas) : total_reveladas
        ]
        self.cartas_mesa_reveladas.extend(novas_cartas)

        mensagens = []
        for c in novas_cartas:
            mensagens.append(("TODOS", "carta_mesa", {"carta": c}))

        self.fase = proxima_fase
        self.aposta_atual = 0.0
        self.agiram_na_street.clear()
        for jid in self.participantes_mao:
            if jid in self.jogadores:
                self.jogadores[jid]["aposta_rodada"] = 0.0

        # Em cenário de All-in (menos de 2 jogadores com fichas para apostar),
        # avança para pedir ao dealer virar a próxima fase ou ir ao Showdown
        if len(self._ativos_que_podem_agir()) < 2:
            mensagens.extend(self._concluir_street(f"{titulo} (All-in na mesa)"))
            return mensagens

        # Pós-flop: primeiro jogador ativo à esquerda do Dealer (índice 1 em diante)
        self.indice_turno_mao = 1 % len(self.participantes_mao)
        if not self._pode_agir(self.participantes_mao[self.indice_turno_mao]):
            self._avancar_turno()

        self.ultima_acao_msg = f"{titulo} Rodada de apostas."
        mensagens.extend(self._gerar_estado_individualizado(self.ultima_acao_msg))
        return mensagens

    # =========================================================================
    # PROCESSAMENTO DE AÇÕES (FOLD, CHECK, CALL, RAISE, ALL-IN)
    # =========================================================================
    def _pode_agir(self, jid) -> bool:
        j = self.jogadores.get(jid)
        return bool(j and j["na_mao"] and j["ativo"] and not j["all_in"] and j["saldo"] > 0)

    def _ativos_na_mao(self) -> list:
        return [
            jid
            for jid in self.participantes_mao
            if jid in self.jogadores and self.jogadores[jid]["ativo"]
        ]

    def _ativos_que_podem_agir(self) -> list:
        return [jid for jid in self.participantes_mao if self._pode_agir(jid)]

    def _todos_igualaram_ou_allin(self) -> bool:
        for jid in self._ativos_na_mao():
            j = self.jogadores[jid]
            if not j["all_in"] and j["aposta_rodada"] < self.aposta_atual:
                return False
        return True

    def _street_encerrada(self) -> bool:
        podem_agir = self._ativos_que_podem_agir()
        if not podem_agir:
            return True
        if not self._todos_igualaram_ou_allin():
            return False
        return all(jid in self.agiram_na_street for jid in podem_agir)

    def jogador_da_vez_id(self):
        if self.fase not in ("PRE_FLOP", "FLOP", "TURN", "RIVER"):
            return None
        if not self.participantes_mao:
            return None
        jid = self.participantes_mao[self.indice_turno_mao]
        return jid if self._pode_agir(jid) else None

    def jogador_da_vez_eh_bot(self) -> bool:
        return self.jogador_da_vez_id() == BOT_ID

    def processar_acao(self, conn, acao: str, valor: float = 0.0) -> list[tuple]:
        if self.fase not in ("PRE_FLOP", "FLOP", "TURN", "RIVER"):
            return []
        if conn not in self.jogadores:
            return []
        if self.jogador_da_vez_id() != conn:
            return [(conn, "erro", {"msg": "Não é a sua vez!"})]

        j = self.jogadores[conn]
        nome = j["nome"]
        a_pagar = round(max(0.0, self.aposta_atual - j["aposta_rodada"]), 2)
        aviso = ""

        if acao == "fold":
            j["ativo"] = False
            self.agiram_na_street.add(conn)
            aviso = f"{nome} correu (Fold)."

        elif acao == "check":
            if a_pagar > 0:
                return [
                    (
                        conn,
                        "erro",
                        {"msg": f"Precisa pagar R$ {fmt_valor(a_pagar)} ou correr."},
                    )
                ]
            self.agiram_na_street.add(conn)
            aviso = f"{nome} passou (Check)."

        elif acao == "call":
            pagamento = round(min(a_pagar, j["saldo"]), 2)
            j["saldo"] = round(j["saldo"] - pagamento, 2)
            j["aposta_rodada"] = round(j["aposta_rodada"] + pagamento, 2)
            j["contribuicao_mao"] = round(j["contribuicao_mao"] + pagamento, 2)
            self.pote = round(self.pote + pagamento, 2)
            if j["saldo"] <= 0:
                j["saldo"] = 0.0
                j["all_in"] = True
                aviso = f"{nome} deu ALL-IN pagando R$ {fmt_valor(pagamento)}!"
            else:
                aviso = f"{nome} pagou R$ {fmt_valor(pagamento)} (Call)."
            self.agiram_na_street.add(conn)

        elif acao == "all_in":
            pagamento = round(j["saldo"], 2)
            if pagamento <= 0:
                return [(conn, "erro", {"msg": "Saldo insuficiente."})]
            j["saldo"] = 0.0
            j["aposta_rodada"] = round(j["aposta_rodada"] + pagamento, 2)
            j["contribuicao_mao"] = round(j["contribuicao_mao"] + pagamento, 2)
            self.pote = round(self.pote + pagamento, 2)
            j["all_in"] = True
            if j["aposta_rodada"] > self.aposta_atual:
                self.aposta_atual = j["aposta_rodada"]
                self.agiram_na_street = {conn}
            else:
                self.agiram_na_street.add(conn)
            aviso = f"{nome} foi ALL-IN (R$ {fmt_valor(j['aposta_rodada'])})!"

        elif acao == "raise":
            valor_extra = round(float(valor), 2)
            total_necessario = round(a_pagar + valor_extra, 2)
            if valor_extra <= 0:
                return [(conn, "erro", {"msg": "Digite um valor maior que zero."})]
            if j["saldo"] < total_necessario:
                return [
                    (
                        conn,
                        "erro",
                        {"msg": "Saldo insuficiente para esse Raise. Use All-In."},
                    )
                ]
            j["saldo"] = round(j["saldo"] - total_necessario, 2)
            j["aposta_rodada"] = round(j["aposta_rodada"] + total_necessario, 2)
            j["contribuicao_mao"] = round(j["contribuicao_mao"] + total_necessario, 2)
            self.pote = round(self.pote + total_necessario, 2)
            self.aposta_atual = j["aposta_rodada"]
            self.agiram_na_street = {conn}
            if j["saldo"] <= 0:
                j["saldo"] = 0.0
                j["all_in"] = True
                aviso = f"{nome} aumentou em ALL-IN para R$ {fmt_valor(self.aposta_atual)}!"
            else:
                aviso = f"{nome} aumentou para R$ {fmt_valor(self.aposta_atual)} (Raise)!"
        else:
            return []

        ativos = self._ativos_na_mao()
        if len(ativos) == 1:
            vencedor_id = ativos[0]
            vencedor = self.jogadores[vencedor_id]
            premio = round(self.pote, 2)
            vencedor["saldo"] = round(vencedor["saldo"] + premio, 2)
            self.resultado_rodada = [
                {
                    "pote_nome": "Pote Principal",
                    "valor": premio,
                    "vencedores": [vencedor["nome"]],
                    "premio_cada": premio,
                    "combinacao": "Todos os outros correram",
                }
            ]
            self.fase = "SHOWDOWN"
            self.ultima_acao_msg = (
                f"{aviso} {vencedor['nome']} ganhou R$ {fmt_valor(premio)}!"
            )
            return self._gerar_estado_individualizado(self.ultima_acao_msg)

        if self._street_encerrada():
            return self._concluir_street(aviso)

        self._avancar_turno()
        self.ultima_acao_msg = aviso
        return self._gerar_estado_individualizado(aviso)

    def _avancar_turno(self) -> None:
        total = len(self.participantes_mao)
        for _ in range(total):
            self.indice_turno_mao = (self.indice_turno_mao + 1) % total
            if self._pode_agir(self.participantes_mao[self.indice_turno_mao]):
                break

    def _concluir_street(self, ultimo_aviso: str) -> list[tuple]:
        transicoes = {
            "PRE_FLOP": ("AGUARDANDO_VIRAR_FLOP", "Aguardando dealer virar o Flop (3 cartas)."),
            "FLOP": ("AGUARDANDO_VIRAR_TURN", "Aguardando dealer virar o Turn (4ª carta)."),
            "TURN": ("AGUARDANDO_VIRAR_RIVER", "Aguardando dealer virar o River (5ª carta)."),
            "RIVER": ("SHOWDOWN", ""),
        }
        nova_fase, texto = transicoes[self.fase]
        self.fase = nova_fase

        if nova_fase == "SHOWDOWN":
            return self._avaliar_showdown(ultimo_aviso)

        self.ultima_acao_msg = f"{ultimo_aviso} {texto}"
        return self._gerar_estado_individualizado(self.ultima_acao_msg)

    # =========================================================================
    # SIDE POTS E SHOWDOWN
    # =========================================================================
    def calcular_potes(self) -> list[dict]:
        """Calcula Main Pot e Side Pots considerando contribuições totais na mão."""
        contribuidores_todos = [
            jid
            for jid in self.participantes_mao
            if jid in self.jogadores and self.jogadores[jid]["contribuicao_mao"] > 0
        ]
        niveis = sorted(
            {self.jogadores[jid]["contribuicao_mao"] for jid in contribuidores_todos}
        )

        potes: list[dict] = []
        nivel_ant = 0.0

        for nivel in niveis:
            delta = round(nivel - nivel_ant, 2)
            if delta <= 0:
                continue
            participam_camada = [
                jid
                for jid in contribuidores_todos
                if self.jogadores[jid]["contribuicao_mao"] >= nivel
            ]
            valor_camada = round(delta * len(participam_camada), 2)
            elegiveis = [
                jid for jid in participam_camada if self.jogadores[jid]["ativo"]
            ]

            if not elegiveis:
                if potes:
                    potes[-1]["valor"] = round(potes[-1]["valor"] + valor_camada, 2)
            elif potes and set(potes[-1]["elegiveis"]) == set(elegiveis):
                potes[-1]["valor"] = round(potes[-1]["valor"] + valor_camada, 2)
            else:
                potes.append({"valor": valor_camada, "elegiveis": elegiveis})

            nivel_ant = nivel

        return potes

    def _avaliar_showdown(self, ultimo_aviso: str) -> list[tuple]:
        board_treys = [Card.new(c) for c in self.cartas_mesa_reveladas]
        scores: dict = {}
        classes_pt: dict = {}

        for jid in self._ativos_na_mao():
            j = self.jogadores[jid]
            if len(j["mao"]) < 2:
                continue
            mao_treys = [Card.new(c) for c in j["mao"]]
            score = self.evaluator.evaluate(board_treys, mao_treys)
            classe_en = self.evaluator.class_to_string(
                self.evaluator.get_rank_class(score)
            )
            scores[jid] = score
            classes_pt[jid] = TRADUCAO_MAOS.get(classe_en, classe_en)

        potes = self.calcular_potes()
        self.resultado_rodada = []
        resumo_msgs = []
        idx_side = 0

        for i, pote_info in enumerate(potes):
            valor_pote = pote_info["valor"]
            elegiveis = [jid for jid in pote_info["elegiveis"] if jid in scores]
            if not elegiveis:
                continue

            # Excesso não pago (apenas 1 jogador contribuiu nesse nível)
            if len(elegiveis) == 1:
                jid_unico = elegiveis[0]
                self.jogadores[jid_unico]["saldo"] = round(
                    self.jogadores[jid_unico]["saldo"] + valor_pote, 2
                )
                self.resultado_rodada.append(
                    {
                        "pote_nome": "Excesso devolvido",
                        "valor": valor_pote,
                        "vencedores": [self.jogadores[jid_unico]["nome"]],
                        "premio_cada": valor_pote,
                        "combinacao": "Aposta não coberta",
                    }
                )
                continue

            melhor_score = min(scores[jid] for jid in elegiveis)
            vencedores_ids = [
                jid for jid in elegiveis if scores[jid] == melhor_score
            ]
            premio_cada = round(valor_pote / len(vencedores_ids), 2)

            # Ajuste fino de eventual centavo residual para o primeiro vencedor
            resto = round(valor_pote - premio_cada * len(vencedores_ids), 2)
            for k, vid in enumerate(vencedores_ids):
                bonus = resto if k == 0 else 0.0
                self.jogadores[vid]["saldo"] = round(
                    self.jogadores[vid]["saldo"] + premio_cada + bonus, 2
                )

            nome_pote = "Pote Principal" if i == 0 else f"Side Pot {idx_side + 1}"
            if i > 0:
                idx_side += 1

            nomes_v = [self.jogadores[vid]["nome"] for vid in vencedores_ids]
            comb = classes_pt[vencedores_ids[0]]

            self.resultado_rodada.append(
                {
                    "pote_nome": nome_pote,
                    "valor": valor_pote,
                    "vencedores": nomes_v,
                    "premio_cada": premio_cada,
                    "combinacao": comb,
                }
            )
            resumo_msgs.append(
                f"{nome_pote}: {', '.join(nomes_v)} levou R$ {fmt_valor(premio_cada)} ({comb})"
            )

        resumo_str = " | ".join(resumo_msgs) if resumo_msgs else "Rodada finalizada."
        self.ultima_acao_msg = f"SHOWDOWN! {resumo_str}"
        return self._gerar_estado_individualizado(self.ultima_acao_msg)

    # =========================================================================
    # ENCERRAR JOGO (PLACAR FINAL) E VOLTAR AO INÍCIO
    # =========================================================================
    def encerrar_jogo(self) -> list[tuple]:
        ranking = []
        for jid in self.ordem_jogadores:
            j = self.jogadores[jid]
            ranking.append(
                {
                    "nome": j["nome"],
                    "total_investido": round(j["total_investido"], 2),
                    "saldo_final": round(j["saldo"], 2),
                    "lucro": round(j["saldo"] - j["total_investido"], 2),
                }
            )
        ranking.extend(self.historico_desconectados)
        ranking.sort(key=lambda item: (item["lucro"], item["saldo_final"]), reverse=True)

        self.placar_final = ranking
        self.fase = "PLACAR_FINAL"
        self.ultima_acao_msg = "Partida encerrada! Veja o placar final."

        mensagens = [("TODOS", "placar_final", {"ranking": ranking})]
        mensagens.extend(self._gerar_estado_individualizado(self.ultima_acao_msg))
        return mensagens

    def voltar_ao_inicio(self) -> list[tuple]:
        self.fase = "AGUARDANDO"
        self.numero_rodada = 0
        self.dealer_id = None
        self.sb_id = None
        self.bb_id = None
        self.participantes_mao.clear()
        self.cartas_usadas_rodada.clear()
        self.buffer_cartas.clear()
        self.cartas_mesa_ocultas.clear()
        self.cartas_mesa_reveladas.clear()
        self.resultado_rodada.clear()
        self.placar_final.clear()
        self.historico_desconectados.clear()
        self.pote = 0.0
        self.aposta_atual = 0.0
        self.agiram_na_street.clear()
        self.aviso_scanner = ""

        # Reinicia o ponto de referência financeiro para uma nova sessão
        for jid in self.ordem_jogadores:
            j = self.jogadores[jid]
            if j["is_bot"] and j["saldo"] <= 0:
                j["saldo"] = 1000.0
            j["saldo_inicial"] = j["saldo"]
            j["total_investido"] = j["saldo"]
            j["mao"].clear()
            j["aposta_rodada"] = 0.0
            j["contribuicao_mao"] = 0.0
            j["ativo"] = False
            j["all_in"] = False
            j["na_mao"] = False
            j["em_espera"] = False
            j["jogou_sessao"] = False

        self.ultima_acao_msg = "Nova mesa aberta! Aguardando jogadores..."
        mensagens = [("TODOS", "mesa_reiniciada", {})]
        mensagens.extend(self._gerar_estado_individualizado(self.ultima_acao_msg))
        return mensagens

    # =========================================================================
    # IA DO BOT DE TESTES
    # =========================================================================
    def escolher_acao_bot(self) -> tuple[str, float]:
        bot = self.jogadores.get(BOT_ID)
        if not bot:
            return "fold", 0.0

        a_pagar = round(max(0.0, self.aposta_atual - bot["aposta_rodada"]), 2)
        saldo = bot["saldo"]

        # Avalia força da mão (0.0 fraca -> 1.0 muito forte)
        forca = 0.45
        if len(bot["mao"]) == 2:
            if len(self.cartas_mesa_reveladas) >= 3:
                board = [Card.new(c) for c in self.cartas_mesa_reveladas]
                mao = [Card.new(c) for c in bot["mao"]]
                score = self.evaluator.evaluate(board, mao)
                forca = max(0.05, min(1.0, 1.0 - (score / 7462.0)))
            else:
                mapa_v = {"2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8,
                          "9": 9, "T": 10, "J": 11, "Q": 12, "K": 13, "A": 14}
                v1 = mapa_v.get(bot["mao"][0][0], 7)
                v2 = mapa_v.get(bot["mao"][1][0], 7)
                mesmo_naipe = bot["mao"][0][1] == bot["mao"][1][1]
                if v1 == v2:
                    forca = 0.68 + (v1 / 50.0)
                else:
                    forca = ((v1 + v2) / 36.0) + (0.08 if mesmo_naipe else 0.0)

        sorteio = random.random()

        if a_pagar == 0:
            if forca > 0.72 and saldo >= self.big_blind and sorteio < 0.65:
                aumento = min(self.big_blind * 2, saldo)
                return "raise", aumento
            return "check", 0.0

        # Há aposta a cobrir
        if forca < 0.32 and a_pagar > self.big_blind * 2 and sorteio < 0.70:
            return "fold", 0.0

        if forca > 0.80 and saldo > a_pagar + self.big_blind and sorteio < 0.45:
            aumento = min(self.big_blind * 2, saldo - a_pagar)
            return "raise", aumento

        return "call", 0.0

    # =========================================================================
    # SNAPSHOTS PARA INTERFACE LCD E CELULARES
    # =========================================================================
    def montante_total_mesa(self) -> float:
        return round(
            sum(self.jogadores[jid]["saldo"] for jid in self.ordem_jogadores)
            + self.pote,
            2,
        )

    def obter_snapshot_ui(self) -> dict:
        alvo_id = self.jogador_alvo_distribuicao()
        jogadores_lista = []
        for idx, jid in enumerate(self.ordem_jogadores):
            j = self.jogadores[jid]
            tags = []
            if jid == self.dealer_id:
                tags.append("D")
            if jid == self.sb_id:
                tags.append("SB")
            if jid == self.bb_id:
                tags.append("BB")

            if j["em_espera"]:
                status = "ESPERA"
            elif not j["na_mao"] and self.fase != "AGUARDANDO":
                status = "FORA (R$0)" if j["saldo"] <= 0 else "FORA"
            elif j["all_in"]:
                status = "ALL-IN"
            elif j["ativo"]:
                status = "ATIVO"
            elif self.fase == "AGUARDANDO":
                status = "PRONTO"
            else:
                status = "FOLD"

            jogadores_lista.append(
                {
                    "id": jid,
                    "pos": idx + 1,
                    "nome": j["nome"],
                    "is_bot": j["is_bot"],
                    "saldo": j["saldo"],
                    "aposta_rodada": j["aposta_rodada"],
                    "tags": "/".join(tags),
                    "status": status,
                    "eh_vez": (jid == self.jogador_da_vez_id()),
                }
            )

        potes = self.calcular_potes() if self.pote > 0 else []
        pode_iniciar, motivo_bloqueio = self.pode_iniciar_rodada()

        return {
            "fase": self.fase,
            "numero_rodada": self.numero_rodada,
            "small_blind": self.small_blind,
            "big_blind": self.big_blind,
            "bot_ativo": self.bot_ativo,
            "pote": self.pote,
            "qtd_side_pots": max(0, len(potes) - 1),
            "aposta_atual": self.aposta_atual,
            "montante_total": self.montante_total_mesa(),
            "jogadores": jogadores_lista,
            "pode_iniciar": pode_iniciar,
            "motivo_bloqueio": motivo_bloqueio,
            "alvo_nome": self.jogadores[alvo_id]["nome"] if alvo_id in self.jogadores else "",
            "alvo_idx": self.indice_distribuicao + 1,
            "alvo_total": len(getattr(self, "ordem_distribuicao", [])),
            "buffer_qtd": len(self.buffer_cartas),
            "aviso_scanner": self.aviso_scanner,
            "cartas_mesa_reveladas": list(self.cartas_mesa_reveladas),
            "jogador_vez_nome": (
                self.jogadores[self.jogador_da_vez_id()]["nome"]
                if self.jogador_da_vez_id() in self.jogadores
                else "-"
            ),
            "ultima_acao_msg": self.ultima_acao_msg,
            "resultado_rodada": list(self.resultado_rodada),
            "placar_final": list(self.placar_final),
        }

    def _gerar_estado_individualizado(self, msg: str) -> list[tuple]:
        vez_id = self.jogador_da_vez_id()
        nome_vez = self.jogadores[vez_id]["nome"] if vez_id in self.jogadores else "-"
        potes = self.calcular_potes() if self.pote > 0 else []
        qtd_side_pots = max(0, len(potes) - 1)

        mensagens = []
        for jid in self.ordem_jogadores:
            j = self.jogadores[jid]
            if j["is_bot"]:
                continue

            a_pagar = (
                round(max(0.0, self.aposta_atual - j["aposta_rodada"]), 2)
                if j["na_mao"] and j["ativo"]
                else 0.0
            )
            tags = []
            if jid == self.dealer_id:
                tags.append("D")
            if jid == self.sb_id:
                tags.append("SB")
            if jid == self.bb_id:
                tags.append("BB")

            pode_rebuy = (
                self.fase in ("AGUARDANDO", "SHOWDOWN") or not j["na_mao"]
            ) and self.fase != "PLACAR_FINAL"

            dados = {
                "fase": self.fase,
                "pote": self.pote,
                "qtd_side_pots": qtd_side_pots,
                "seu_saldo": j["saldo"],
                "a_pagar": a_pagar,
                "min_raise": self.big_blind,
                "sua_vez": (jid == vez_id),
                "jogador_vez": nome_vez,
                "papel": "/".join(tags),
                "em_espera": j["em_espera"],
                "pode_rebuy": pode_rebuy,
                "small_blind": self.small_blind,
                "big_blind": self.big_blind,
                "msg": msg,
            }
            mensagens.append((jid, "estado_mesa", dados))
        return mensagens
